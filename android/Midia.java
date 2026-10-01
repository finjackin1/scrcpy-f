package scrcpyf;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * scrcpy-f: o PLAYER do celular (01/out/2026), sem app instalado -- roda
 * como o scrcpy-server (shell), por app_process; tudo por reflexao.
 *
 * O shell PODE listar as sessoes de midia (ISessionManager.getSessions;
 * sonda de 01/out no S22) e falar com cada uma pelo ISessionController.
 *
 *   app_process / scrcpyf.Midia ler         -> uma foto e sai
 *   app_process / scrcpyf.Midia vigiar      -> de pe: escreve a foto quando
 *       algo muda (e a cada 5 s, para acertar a posicao) e obedece a
 *       entrada: "c <pacote> play|pause|next|previous|seek <ms>"
 *
 * Foto: uma linha por sessao e "fim":
 *   M <pacote> <estado> <posicao_ms_agora> <duracao_ms> <velocidade>
 *     <acoes> <titulo> <artista> <album>      (TAB; \t \n \\ escapados)
 * estado = o PlaybackState (3 tocando, 2 pausado, 6 carregando...).
 * Comando: "ok <acao>" ou "erro <acao>: <causa>".
 */
public final class Midia {

    private static Object sGerente;
    private static final Object TRAVA = new Object();

    public static void main(String[] args) throws Exception {
        String modo = args.length > 0 ? args[0] : "ler";
        try {
            if ("vigiar".equals(modo)) {
                vigiar();
            } else {
                escrever(foto());
            }
        } catch (Throwable t) {
            escrever("erro " + modo + ": " + causa(t));
        }
        System.exit(0);
    }

    static void escrever(String s) {
        synchronized (System.out) {
            System.out.println(s);
            System.out.flush();
        }
    }

    static String causa(Throwable t) {
        while (t.getCause() != null) {
            t = t.getCause();
        }
        String m = t.getMessage();
        return (t.getClass().getSimpleName() + (m == null ? "" : " " + m))
                .replace('\n', ' ').replace('\t', ' ');
    }

    static String esc(Object o) {
        if (o == null) {
            return "";
        }
        String s = o.toString();
        StringBuilder b = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\\') {
                b.append("\\\\");
            } else if (c == '\t') {
                b.append("\\t");
            } else if (c == '\n') {
                b.append("\\n");
            } else if (c != '\r') {
                b.append(c);
            }
        }
        return b.toString();
    }

    static Method metodo(Object o, String nome) {
        for (Method m : o.getClass().getMethods()) {
            if (m.getName().equals(nome)) {
                return m;
            }
        }
        return null;
    }

    /** Chama `nome` preenchendo os argumentos pelo tipo: texto = o pacote
     *  de quem chama ("com.android.shell"), long = `numero`. */
    static Object chamar(Object o, String nome, long numero) throws Exception {
        Method m = metodo(o, nome);
        if (m == null) {
            throw new RuntimeException("sem " + nome);
        }
        Class<?>[] t = m.getParameterTypes();
        Object[] a = new Object[t.length];
        for (int i = 0; i < t.length; i++) {
            if (t[i] == String.class) {
                a[i] = "com.android.shell";
            } else if (t[i] == long.class) {
                a[i] = numero;
            } else if (t[i] == int.class) {
                a[i] = 0;
            } else if (t[i] == boolean.class) {
                a[i] = Boolean.FALSE;
            } else {
                a[i] = null;
            }
        }
        return m.invoke(o, a);
    }

    static Object gerente() throws Exception {
        if (sGerente == null) {
            Class<?> sm = Class.forName("android.os.ServiceManager");
            Object b = sm.getMethod("getService", String.class)
                    .invoke(null, "media_session");
            sGerente = Class.forName("android.media.session.ISessionManager$Stub")
                    .getMethod("asInterface", Class.forName("android.os.IBinder"))
                    .invoke(null, b);
        }
        return sGerente;
    }

    /** Os ISessionController das sessoes ativas (a mais recente primeiro). */
    static List<Object> controles() throws Exception {
        Object g = gerente();
        Method gs = metodo(g, "getSessions");
        Object[] a = new Object[gs.getParameterTypes().length];
        for (int i = 0; i < a.length; i++) {
            a[i] = gs.getParameterTypes()[i] == int.class ? 0 : null;
        }
        Object r = gs.invoke(g, a);
        if (r != null && !(r instanceof List)) {
            r = r.getClass().getMethod("getList").invoke(r);
        }
        List<Object> saida = new ArrayList<Object>();
        if (r == null) {
            return saida;
        }
        for (Object token : (List<?>) r) {
            Object c = controleDo(token);
            if (c != null) {
                saida.add(c);
            }
        }
        return saida;
    }

    static Object controleDo(Object token) throws Exception {
        for (Field f : token.getClass().getDeclaredFields()) {
            if (f.getType().getName().endsWith("ISessionController")) {
                f.setAccessible(true);
                return f.get(token);
            }
        }
        Method gb = metodo(token, "getBinder");
        if (gb != null) {
            Object b = gb.invoke(token);
            return Class.forName("android.media.session.ISessionController$Stub")
                    .getMethod("asInterface", Class.forName("android.os.IBinder"))
                    .invoke(null, b);
        }
        return null;
    }

    static Object semArg(Object o, String nome) {
        try {
            Method m = metodo(o, nome);
            return m == null ? null : m.invoke(o);
        } catch (Throwable t) {
            return null;
        }
    }

    static String texto(Object meta, String chave) {
        try {
            Object v = meta.getClass().getMethod("getString", String.class)
                    .invoke(meta, chave);
            return v == null ? "" : v.toString();
        } catch (Throwable t) {
            return "";
        }
    }

    static long numero(Object meta, String chave) {
        try {
            return (Long) meta.getClass().getMethod("getLong", String.class)
                    .invoke(meta, chave);
        } catch (Throwable t) {
            return 0;
        }
    }

    static String linha(Object c) throws Exception {
        String pkg = String.valueOf(semArg(c, "getPackageName"));
        Object est = semArg(c, "getPlaybackState");
        int estado = 0;
        long pos = 0;
        float vel = 0;
        long acoes = 0;
        if (est != null) {
            estado = (Integer) est.getClass().getMethod("getState").invoke(est);
            pos = (Long) est.getClass().getMethod("getPosition").invoke(est);
            vel = (Float) est.getClass().getMethod("getPlaybackSpeed").invoke(est);
            acoes = (Long) est.getClass().getMethod("getActions").invoke(est);
            long quando = (Long) est.getClass()
                    .getMethod("getLastPositionUpdateTime").invoke(est);
            if (estado == 3 && quando > 0) {
                Class<?> sc = Class.forName("android.os.SystemClock");
                long agora = (Long) sc.getMethod("elapsedRealtime").invoke(null);
                pos += (long) ((agora - quando) * vel);
            }
        }
        Object meta = semArg(c, "getMetadata");
        String titulo = "";
        String artista = "";
        String album = "";
        long dur = 0;
        if (meta != null) {
            titulo = texto(meta, "android.media.metadata.TITLE");
            if (titulo.isEmpty()) {
                titulo = texto(meta, "android.media.metadata.DISPLAY_TITLE");
            }
            artista = texto(meta, "android.media.metadata.ARTIST");
            if (artista.isEmpty()) {
                artista = texto(meta, "android.media.metadata.DISPLAY_SUBTITLE");
            }
            album = texto(meta, "android.media.metadata.ALBUM");
            dur = numero(meta, "android.media.metadata.DURATION");
        }
        return "M\t" + esc(pkg) + "\t" + estado + "\t" + Math.max(0, pos) + "\t"
                + dur + "\t" + vel + "\t" + acoes + "\t" + esc(titulo) + "\t"
                + esc(artista) + "\t" + esc(album);
    }

    static String foto() throws Exception {
        StringBuilder b = new StringBuilder();
        for (Object c : controles()) {
            try {
                b.append(linha(c)).append('\n');
            } catch (Throwable t) {
                // sessao que caiu no meio: fica de fora
            }
        }
        return b.append("fim").toString();
    }

    /** Sem a posicao (que anda sozinha): o que, se mudar, vale escrever. */
    static String semPosicao(String foto) {
        StringBuilder b = new StringBuilder();
        for (String l : foto.split("\n")) {
            String[] p = l.split("\t", -1);
            if (p.length > 3) {
                p[3] = "";
            }
            b.append(String.join("\t", p)).append('\n');
        }
        return b.toString();
    }

    static void comando(String linha) {
        String[] p = linha.trim().split(" ");
        if (p.length < 3 || !"c".equals(p[0])) {
            escrever("erro comando: " + linha);
            return;
        }
        String acao = p[2];
        try {
            Object alvo = null;
            for (Object c : controles()) {
                if (p[1].equals(String.valueOf(semArg(c, "getPackageName")))) {
                    alvo = c;
                    break;
                }
            }
            if (alvo == null) {
                throw new RuntimeException("sem sessao de " + p[1]);
            }
            if ("seek".equals(acao)) {
                chamar(alvo, "seekTo", Long.parseLong(p[3]));
            } else {
                chamar(alvo, acao, 0);
            }
            escrever("ok " + acao);
        } catch (Throwable t) {
            escrever("erro " + acao + ": " + causa(t));
        }
    }

    static void vigiar() throws Exception {
        Thread entrada = new Thread(new Runnable() {
            public void run() {
                try {
                    BufferedReader r = new BufferedReader(
                            new InputStreamReader(System.in));
                    String l;
                    while ((l = r.readLine()) != null) {
                        synchronized (TRAVA) {
                            comando(l);
                        }
                        synchronized (TRAVA) {
                            TRAVA.notifyAll();      // foto ja, sem esperar
                        }
                    }
                } catch (Throwable t) {
                    // fechou
                }
                System.exit(0);                       // o PC saiu
            }
        });
        entrada.setDaemon(true);
        entrada.start();
        escrever("vigia ok");
        String antes = null;
        long ultima = 0;
        while (true) {
            String f;
            try {
                f = foto();
            } catch (Throwable t) {
                f = "erro foto: " + causa(t) + "\nfim";
            }
            String chave = semPosicao(f);
            long agora = System.currentTimeMillis();
            if (!chave.equals(antes) || agora - ultima > 5000) {
                escrever(f);
                antes = chave;
                ultima = agora;
            }
            synchronized (TRAVA) {
                TRAVA.wait(300);
            }
        }
    }
}
