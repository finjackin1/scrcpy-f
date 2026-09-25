package scrcpyf;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * scrcpy-f: liga/desliga o PAINEL da tela do celular (o mesmo que o scrcpy
 * faz no --turn-screen-off), sem mexer no estado do Android.
 *
 *   app_process / scrcpyf.Tela on|off   -> uma vez e sai
 *   app_process / scrcpyf.Tela          -> de pe, lendo "on"/"off" da entrada
 *   app_process / scrcpyf.Tela vigia    -> de pe E vigiando o botao (r156):
 *       le o logcat de eventos; a cada pedido de dormir (o botao ou o tempo)
 *       acorda o celular NA HORA (chamada direta ao sistema, sem abrir
 *       processo) e alterna o painel sozinho. Escreve
 *       "botao <acesa|apagada> logcat=<ms> acordar=<ms> total=<ms> via=<jeito>"
 *       para o PC so saber o que houve.
 *
 * Tudo por reflexao: roda como o scrcpy-server (shell), sem SDK.
 * Montado com javac + dx (dex-tools 2.4). Fonte: android\Tela.java.
 */
public final class Tela {

    private static Class<?> sControle;          // DisplayControl, 1x so
    private static volatile boolean sApagada;   // o painel esta desligado?
    private static final Object TRAVA = new Object();
    private static int sJeito = -1;             // como acordar (ver acordar)
    private static Object sPower, sInput;
    private static Method sWake, sInject;

    public static void main(String[] args) throws Exception {
        if (args.length > 0 && !"vigia".equals(args[0])) {
            ordem(args[0].trim());
            return;
        }
        if (args.length > 0) {
            iniciarVigia();
        }
        BufferedReader r = new BufferedReader(new InputStreamReader(System.in));
        String l;
        while ((l = r.readLine()) != null) {
            l = l.trim();
            if (l.isEmpty()) {
                continue;
            }
            if ("sair".equals(l)) {
                break;
            }
            ordem(l);
        }
        System.exit(0);
    }

    static void escrever(String s) {
        synchronized (System.out) {
            System.out.println(s);
            System.out.flush();
        }
    }

    static void ordem(String o) {
        int modo = "off".equals(o) ? 0 : 2;
        try {
            int n;
            synchronized (TRAVA) {
                n = aplicar(modo);
                sApagada = modo == 0;
            }
            escrever("ok " + modo + " " + n);
        } catch (Throwable t) {
            escrever("erro " + causa(t));
        }
    }

    static String causa(Throwable t) {
        while (t.getCause() != null) {
            t = t.getCause();
        }
        return t.toString();
    }

    // ---------------------------------------------------------------- painel

    static int sdk() throws Exception {
        return Class.forName("android.os.Build$VERSION")
                .getField("SDK_INT").getInt(null);
    }

    /** Quantas telas fisicas receberam o modo (2 = normal, 0 = desligado). */
    static int aplicar(int modo) throws Exception {
        Class<?> sc = Class.forName("android.view.SurfaceControl");
        Method power = sc.getMethod("setDisplayPowerMode",
                Class.forName("android.os.IBinder"), int.class);
        int sdk = sdk();
        List<Object> tokens = new ArrayList<>();
        if (sdk < 29) {
            tokens.add(sc.getMethod("getBuiltInDisplay", int.class)
                    .invoke(null, 0));
        } else {
            Class<?> dono = sc;
            if (sdk >= 34) {
                if (sControle == null) {
                    Class<?> f = Class.forName(
                            "com.android.internal.os.ClassLoaderFactory");
                    Method m = f.getDeclaredMethod("createClassLoader",
                            String.class, String.class, String.class,
                            ClassLoader.class, int.class, boolean.class,
                            String.class);
                    ClassLoader cl = (ClassLoader) m.invoke(null,
                            "/system/framework/services.jar", null, null,
                            ClassLoader.getSystemClassLoader(), 0, true, null);
                    Class<?> dc = cl.loadClass(
                            "com.android.server.display.DisplayControl");
                    Method load = Runtime.class.getDeclaredMethod(
                            "loadLibrary0", Class.class, String.class);
                    load.setAccessible(true);
                    load.invoke(Runtime.getRuntime(), dc, "android_servers");
                    sControle = dc;
                }
                dono = sControle;
            }
            long[] ids = (long[]) dono.getMethod("getPhysicalDisplayIds")
                    .invoke(null);
            Method tok = dono.getMethod("getPhysicalDisplayToken", long.class);
            for (long id : ids) {
                tokens.add(tok.invoke(null, id));
            }
        }
        int n = 0;
        for (Object t : tokens) {
            if (t != null) {
                power.invoke(null, t, modo);
                n++;
            }
        }
        return n;
    }

    // ---------------------------------------------------------------- acordar

    static long uptime() throws Exception {
        return (Long) Class.forName("android.os.SystemClock")
                .getMethod("uptimeMillis").invoke(null);
    }

    /** Acorda o celular. Devolve o jeito que serviu (para o registro). */
    static String acordar() {
        // 1) PowerManager direto (precisa de DEVICE_POWER: o shell pode nao
        //    ter); 2) tecla WAKEUP injetada (INJECT_EVENTS, o shell tem --
        //    o mesmo que o `input` faz, sem abrir processo); 3) `cmd input`.
        if (sJeito <= 1) {
            try {
                if (sWake == null) {
                    Object b = Class.forName("android.os.ServiceManager")
                            .getMethod("getService", String.class)
                            .invoke(null, "power");
                    sPower = Class.forName("android.os.IPowerManager$Stub")
                            .getMethod("asInterface",
                                    Class.forName("android.os.IBinder"))
                            .invoke(null, b);
                    for (Method m : sPower.getClass().getMethods()) {
                        if ("wakeUp".equals(m.getName())) {
                            sWake = m;
                            break;
                        }
                    }
                }
                Class<?>[] p = sWake.getParameterTypes();
                Object[] a = new Object[p.length];
                a[0] = uptime();
                for (int i = 1; i < p.length; i++) {
                    if (p[i] == int.class) {
                        a[i] = 0;
                    } else if (p[i] == String.class) {
                        a[i] = i == p.length - 1 ? "com.android.shell"
                                : "scrcpy-f";
                    } else {
                        a[i] = null;
                    }
                }
                sWake.invoke(sPower, a);
                sJeito = 1;
                return "power";
            } catch (Throwable t) {
                sJeito = 2;
            }
        }
        if (sJeito <= 2) {
            try {
                if (sInject == null) {
                    Object im;
                    try {
                        Class<?> g = Class.forName(
                                "android.hardware.input.InputManagerGlobal");
                        im = g.getMethod("getInstance").invoke(null);
                    } catch (ClassNotFoundException e) {
                        Class<?> g = Class.forName(
                                "android.hardware.input.InputManager");
                        Method gi = g.getDeclaredMethod("getInstance");
                        gi.setAccessible(true);
                        im = gi.invoke(null);
                    }
                    sInput = im;
                    sInject = im.getClass().getMethod("injectInputEvent",
                            Class.forName("android.view.InputEvent"),
                            int.class);
                }
                Class<?> ke = Class.forName("android.view.KeyEvent");
                long agora = uptime();
                for (int acao = 0; acao <= 1; acao++) {
                    Object ev = ke.getConstructor(long.class, long.class,
                            int.class, int.class, int.class)
                            .newInstance(agora, agora, acao, 224, 0);
                    ke.getMethod("setSource", int.class).invoke(ev, 0x101);
                    sInject.invoke(sInput, ev, 0);
                }
                sJeito = 2;
                return "tecla";
            } catch (Throwable t) {
                sJeito = 3;
            }
        }
        try {
            Runtime.getRuntime().exec(new String[] {"cmd", "input",
                "keyevent", "KEYCODE_WAKEUP"});
            return "cmd";
        } catch (Throwable t) {
            return "nenhum(" + causa(t) + ")";
        }
    }

    // ----------------------------------------------------------------- vigia

    static void iniciarVigia() {
        Thread t = new Thread(new Runnable() {
            public void run() {
                vigiar();
            }
        }, "scrcpyf-vigia");
        t.setDaemon(true);
        t.start();
    }

    static void vigiar() {
        try {
            long ms = System.currentTimeMillis();
            // So eventos de AGORA em diante (pedido velho = toque fantasma).
            String desde = (ms / 1000) + "." + String.format("%03d", ms % 1000);
            Process p = new ProcessBuilder("logcat", "-b", "events", "-v",
                    "epoch", "-T", desde, "-s", "power_sleep_requested",
                    "scrcpyf_sono:S").redirectErrorStream(true).start();
            escrever("vigia ok");
            BufferedReader r = new BufferedReader(
                    new InputStreamReader(p.getInputStream()));
            String l;
            while ((l = r.readLine()) != null) {
                if (!l.contains("power_sleep_requested")) {
                    continue;
                }
                long recebido = System.currentTimeMillis();
                long t0 = System.nanoTime();
                String via = acordar();
                long tAcordar = (System.nanoTime() - t0) / 1000000;
                String acao;
                try {
                    synchronized (TRAVA) {
                        if (sApagada) {
                            aplicar(2);
                            sApagada = false;
                            acao = "acesa";
                        } else {
                            aplicar(0);
                            sApagada = true;
                            acao = "apagada";
                        }
                    }
                } catch (Throwable t) {
                    acao = "erro(" + causa(t) + ")";
                }
                long evento = -1;
                try {
                    evento = (long) (Double.parseDouble(
                            l.trim().split("\\s+")[0]) * 1000);
                } catch (Throwable t) {
                    evento = -1;
                }
                long fim = System.currentTimeMillis();
                escrever("botao " + acao
                        + " logcat=" + (evento > 0 ? recebido - evento : -1)
                        + " acordar=" + tAcordar
                        + " total=" + (evento > 0 ? fim - evento : -1)
                        + " via=" + via);
            }
        } catch (Throwable t) {
            escrever("erro vigia " + causa(t));
        }
        escrever("semlog");
    }
}
