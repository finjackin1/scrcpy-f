package scrcpyf;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * scrcpy-f: REMOVE notificacoes do celular, sem app instalado (roda como o
 * scrcpy-server: shell, por app_process). Tudo por reflexao, sem SDK.
 *
 *   app_process / scrcpyf.Notif remover <chave> [<chave> ...]
 *
 * A chave e a do `cmd notification list`: "usuario|pacote|id|tag|uid".
 * Escreve uma linha por chave: "removido via=<jeito>" ou
 * "nao removido: <motivos>".
 *
 * Sonda de 01/out/2026 (Android 16): a LISTA pela API pede
 * ACCESS_NOTIFICATIONS (o shell nao tem) -- quem le e o PC, pelo
 * `cmd notification`. Remover pela barra (IStatusBarService
 * .onNotificationClear, o mesmo que arrastar a notificacao para o lado) o
 * shell pode. Montado com javac + dx (ver LEIA-ME.txt).
 */
public final class Notif {

    private static Object sNm;
    private static String sJeito = "";       // o jeito que serviu

    public static void main(String[] args) throws Exception {
        if (args.length < 2 || !"remover".equals(args[0])) {
            escrever("erro uso: remover <chave> [<chave> ...]");
            System.exit(0);
        }
        for (int i = 1; i < args.length; i++) {
            try {
                remover(args[i]);
            } catch (Throwable t) {
                escrever("nao removido: " + causa(t));
            }
        }
        System.exit(0);
    }

    static void escrever(String s) {
        System.out.println(s);
        System.out.flush();
    }

    static String causa(Throwable t) {
        while (t.getCause() != null) {
            t = t.getCause();
        }
        String m = t.getMessage();
        String s = t.getClass().getSimpleName() + (m == null ? "" : " " + m);
        return s.replace('\n', ' ').replace('\t', ' ');
    }

    static Object servico(String nome, String iface) throws Exception {
        Class<?> sm = Class.forName("android.os.ServiceManager");
        Object b = sm.getMethod("getService", String.class).invoke(null, nome);
        Class<?> stub = Class.forName(iface + "$Stub");
        return stub.getMethod("asInterface", Class.forName("android.os.IBinder"))
                .invoke(null, b);
    }

    static Method metodo(Object o, String nome) {
        for (Method m : o.getClass().getMethods()) {
            if (m.getName().equals(nome)) {
                return m;
            }
        }
        return null;
    }

    static boolean ativa(String chave) throws Exception {
        Process p = Runtime.getRuntime().exec(
                new String[]{"cmd", "notification", "list"});
        BufferedReader r = new BufferedReader(
                new InputStreamReader(p.getInputStream()));
        String l;
        boolean achou = false;
        while ((l = r.readLine()) != null) {
            if (l.trim().equals(chave)) {
                achou = true;
            }
        }
        p.waitFor();
        return achou;
    }

    static boolean saiu(String chave) throws Exception {
        for (int i = 0; i < 8; i++) {
            if (!ativa(chave)) {
                return true;
            }
            Thread.sleep(100);
        }
        return false;
    }

    /** Tenta, em ordem, os jeitos que o Android pode aceitar do shell; o que
     *  servir vale para as chaves seguintes. */
    static void remover(String chave) throws Exception {
        if (!ativa(chave)) {
            escrever("removido via=ja-saiu");
            return;
        }
        String[] p = chave.split("\\|", 5);
        int u = Integer.parseInt(p[0]);
        String pkg = p[1];
        int id = Integer.parseInt(p[2]);
        String tag = "null".equals(p[3]) ? null : p[3];
        StringBuilder motivos = new StringBuilder();
        List<String> jeitos = new ArrayList<String>();
        if (!sJeito.isEmpty()) {
            jeitos.add(sJeito);
        }
        for (String j : new String[]{"barra", "cancelar-pkg", "cancelar-shell"}) {
            if (!jeitos.contains(j)) {
                jeitos.add(j);
            }
        }
        for (String j : jeitos) {
            try {
                if ("barra".equals(j)) {
                    limparPelaBarra(pkg, tag, id, u, chave);
                } else {
                    if (sNm == null) {
                        sNm = servico("notification", "android.app.INotificationManager");
                    }
                    Method m = metodo(sNm, "cancelNotificationWithTag");
                    if (m == null) {
                        throw new RuntimeException("sem metodo");
                    }
                    String op = "cancelar-pkg".equals(j) ? pkg : "com.android.shell";
                    if (m.getParameterTypes().length == 5) {
                        m.invoke(sNm, pkg, op, tag, id, u);
                    } else {
                        m.invoke(sNm, pkg, tag, id, u);
                    }
                }
                if (saiu(chave)) {
                    sJeito = j;
                    escrever("removido via=" + j);
                    return;
                }
                motivos.append(j).append(": chamou mas ficou; ");
            } catch (Throwable t) {
                motivos.append(j).append(": ").append(causa(t)).append("; ");
            }
        }
        escrever("nao removido: " + motivos);
    }

    /** O mesmo que arrastar a notificacao para o lado na barra do celular:
     *  IStatusBarService.onNotificationClear (a assinatura muda por versao:
     *  3 textos = pkg, tag, key + id, user; 2 textos = pkg, key + user). */
    static void limparPelaBarra(String pkg, String tag, int id, int u,
                                String chave) throws Exception {
        Object sb = servico("statusbar",
                "com.android.internal.statusbar.IStatusBarService");
        Method m = metodo(sb, "onNotificationClear");
        if (m == null) {
            throw new RuntimeException("sem onNotificationClear");
        }
        Class<?>[] tipos = m.getParameterTypes();
        int strings = 0;
        int ints = 0;
        for (Class<?> c : tipos) {
            if (c == String.class) {
                strings++;
            } else if (c == int.class) {
                ints++;
            }
        }
        List<Object> textos = new ArrayList<Object>();
        List<Object> numeros = new ArrayList<Object>();
        textos.add(pkg);
        if (strings >= 3) {
            textos.add(tag);
            numeros.add(id);
        }
        textos.add(chave);
        numeros.add(u);
        numeros.add(1);                  // superficie: a barra
        while (numeros.size() < ints) {
            numeros.add(0);              // sentimento neutro e o resto
        }
        Object[] a = new Object[tipos.length];
        int ti = 0;
        int ni = 0;
        for (int i = 0; i < tipos.length; i++) {
            Class<?> c = tipos[i];
            if (c == String.class) {
                a[i] = ti < textos.size() ? textos.get(ti++) : null;
            } else if (c == int.class) {
                a[i] = numeros.get(ni++);
            } else if (c == boolean.class) {
                a[i] = Boolean.FALSE;
            } else if (c.getName().endsWith("NotificationVisibility")) {
                a[i] = visibilidade(c, chave);
            } else {
                a[i] = null;
            }
        }
        m.invoke(sb, a);
    }

    static Object visibilidade(Class<?> c, String chave) {
        for (Method m : c.getMethods()) {
            if (!m.getName().equals("obtain")) {
                continue;
            }
            Class<?>[] t = m.getParameterTypes();
            Object[] a = new Object[t.length];
            int ints = 0;
            for (int i = 0; i < t.length; i++) {
                if (t[i] == String.class) {
                    a[i] = chave;
                } else if (t[i] == int.class) {
                    a[i] = ints++ == 1 ? 1 : 0;   // rank 0, count 1, local 0
                } else if (t[i] == boolean.class) {
                    a[i] = Boolean.TRUE;
                } else {
                    a[i] = null;
                }
            }
            try {
                return m.invoke(null, a);
            } catch (Throwable t2) {
                // tenta a proxima assinatura
            }
        }
        return null;
    }
}
