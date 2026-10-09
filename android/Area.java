package scrcpyf;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;

/**
 * (08/out/2026, pedido dele) AREA DE TRANSFERENCIA ENTRE O PC E O CELULAR,
 * sem depender de uma janela do scrcpy aberta (o scrcpy so sincroniza com
 * ele de pe, e o texto do PC so no Ctrl+V dentro dele). Faz o mesmo que o
 * servidor do scrcpy: chama o servico "clipboard" com a identidade do shell.
 *
 *   app_process / scrcpyf.Area <texto base64>   poe o texto e sai ("ok")
 *   app_process / scrcpyf.Area vigiar           fica de pe:
 *       escreve "C <base64>" quando o texto do celular muda (a cada 0,5 s);
 *       le "S <base64>" na entrada e poe no celular (sem eco: o texto posto
 *       aqui nao volta como "C").
 *
 * So reflexao (nada de cascas): ClipData e IClipboard mudam de assinatura a
 * cada Android -- os parametros sao preenchidos pelo tipo (ClipData = o
 * texto, a 1a String = o pacote do shell, outras String = null, int = 0).
 */
public final class Area {
    private static Object sCb;
    private static volatile String sUltimo;

    public static void main(String[] args) {
        try {
            if (args.length > 0 && "vigiar".equals(args[0])) {
                vigiar();
                return;
            }
            definir(decodificar(args.length > 0 ? args[0] : ""));
            System.out.println("ok");
        } catch (Throwable e) {
            System.out.println("erro " + causa(e));
        }
    }

    static String causa(Throwable e) {
        while (e.getCause() != null) {
            e = e.getCause();
        }
        return e.toString();
    }

    static String decodificar(String b64) throws Exception {
        return new String(java.util.Base64.getDecoder().decode(b64.trim()),
                "UTF-8");
    }

    static Object cb() throws Exception {
        if (sCb == null) {
            Object binder = Class.forName("android.os.ServiceManager")
                    .getMethod("getService", String.class)
                    .invoke(null, "clipboard");
            sCb = Class.forName("android.content.IClipboard$Stub")
                    .getMethod("asInterface",
                            Class.forName("android.os.IBinder"))
                    .invoke(null, binder);
        }
        return sCb;
    }

    /** O metodo de nome `nome` com mais parametros (o do Android de agora). */
    static Method metodo(Object alvo, String nome) {
        Method certo = null;
        for (Method m : alvo.getClass().getMethods()) {
            if (m.getName().equals(nome) && (certo == null
                    || m.getParameterTypes().length
                    > certo.getParameterTypes().length)) {
                certo = m;
            }
        }
        return certo;
    }

    static Object[] valores(Class<?>[] tipos, Object clip) throws Exception {
        Class<?> cd = Class.forName("android.content.ClipData");
        Object[] v = new Object[tipos.length];
        boolean pacote = false;
        for (int i = 0; i < tipos.length; i++) {
            if (tipos[i] == cd) {
                v[i] = clip;
            } else if (tipos[i] == String.class) {
                v[i] = pacote ? null : "com.android.shell";
                pacote = true;
            } else if (tipos[i] == int.class) {
                v[i] = 0;
            } else {
                v[i] = null;
            }
        }
        return v;
    }

    static void definir(String texto) throws Exception {
        Class<?> cd = Class.forName("android.content.ClipData");
        Object clip = cd.getMethod("newPlainText", CharSequence.class,
                CharSequence.class).invoke(null, "scrcpy-f", texto);
        Object c = cb();
        Method m = metodo(c, "setPrimaryClip");
        if (m == null) {
            throw new Exception("sem setPrimaryClip");
        }
        sUltimo = texto;
        m.invoke(c, valores(m.getParameterTypes(), clip));
    }

    static String ler() throws Exception {
        Object c = cb();
        Method m = metodo(c, "getPrimaryClip");
        if (m == null) {
            return null;
        }
        Object clip = m.invoke(c, valores(m.getParameterTypes(), null));
        if (clip == null) {
            return null;
        }
        int n = (Integer) clip.getClass().getMethod("getItemCount")
                .invoke(clip);
        if (n < 1) {
            return null;
        }
        Object item = clip.getClass().getMethod("getItemAt", int.class)
                .invoke(clip, 0);
        Object t = item.getClass().getMethod("getText").invoke(item);
        return t == null ? null : t.toString();
    }

    static synchronized void escrever(String s) {
        System.out.println(s);
        System.out.flush();
    }

    static void vigiar() throws Exception {
        sUltimo = ler();               // o que ja estava nao vai ao PC
        Thread entrada = new Thread(new Runnable() {
            public void run() {
                try {
                    BufferedReader r = new BufferedReader(
                            new InputStreamReader(System.in));
                    String l;
                    while ((l = r.readLine()) != null) {
                        if (l.startsWith("S ")) {
                            try {
                                definir(decodificar(l.substring(2)));
                                escrever("ok");
                            } catch (Throwable e) {
                                escrever("erro " + causa(e));
                            }
                        }
                    }
                } catch (Throwable e) {
                    escrever("erro entrada " + causa(e));
                }
                System.exit(0);        // o PC fechou: sai junto
            }
        }, "scrcpyf-area-entrada");
        entrada.setDaemon(true);
        entrada.start();
        escrever("vigiando");
        while (true) {
            try {
                String t = ler();
                if (t != null && !t.equals(sUltimo)) {
                    sUltimo = t;
                    escrever("C " + java.util.Base64.getEncoder()
                            .encodeToString(t.getBytes("UTF-8")));
                }
            } catch (Throwable e) {
                escrever("erro ler " + causa(e));
                Thread.sleep(3000);
            }
            Thread.sleep(500);
        }
    }
}
