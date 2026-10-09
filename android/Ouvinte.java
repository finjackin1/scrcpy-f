package scrcpyf;

import android.app.ActivityOptions;
import android.app.Notification;
import android.app.PendingIntent;
import android.app.Person;
import android.app.RemoteInput;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.BitmapDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.Icon;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStreamReader;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * scrcpy-f: OUVINTE de notificacoes (03/out/2026), sem app instalado -- roda
 * como o shell, por app_process, e se registra como a barra do Android se
 * registra (NotificationListenerService.registerAsSystemService; o shell tem
 * STATUS_BAR_SERVICE). Recebe o objeto inteiro de cada notificacao: as
 * ACOES (com o PendingIntent e o campo de texto) e as IMAGENS.
 *
 *   app_process / scrcpyf.Ouvinte
 *
 * O que escreve (TAB entre campos; \t \n \\ escapados):
 *   pronto                                  registrou e leu as de agora
 *   N <chave> <conteudo> <n> (<titulo> <tipo>)*n <icone> <foto>
 *       conteudo/tipo: "a" abre tela (activity), "o" outro, "-" sem;
 *       no tipo da acao, "t" na frente = tem campo de texto ("ta", "to").
 *       icone (PNG) / foto (JPEG) em base64; "-" nenhuma; "=" a mesma de antes.
 *   P <chave> <nome> <png>                  foto de quem fala na conversa
 *   M <chave> <titulo> <grupo> <eu> <n> (<quem> <texto> <quando>)*n
 *                                           a conversa (quem vazio = eu)
 *   X <chave>                               saiu
 *   r <id> ok|erro <detalhe>                resposta de um pedido
 *   erro <detalhe>                          nao deu para ser ouvinte (sai)
 *
 * Pedidos (uma linha cada):
 *   <id> a <chave> <indice> <tela> <texto>  aperta a acao (texto = resposta)
 *   <id> c <chave> <tela>                   o toque no corpo (contentIntent)
 * <tela> = a tela (display) onde abrir uma tela do app; -1 = a do celular.
 * Montado com javac (cascas em android\stubs, so para compilar) + dx.
 */
public final class Ouvinte extends NotificationListenerService {

    static final int LADO_ICONE = 96;
    static final int LADO_FOTO = 480;

    static Context sCtx;
    static final Map<String, StatusBarNotification> ATIVAS =
            new ConcurrentHashMap<String, StatusBarNotification>();
    static final Map<String, String> ASSINATURA = new HashMap<String, String>();

    public static void main(String[] args) throws Exception {
        Class<?> looper = Class.forName("android.os.Looper");
        looper.getMethod("prepareMainLooper").invoke(null);
        try {
            sCtx = contextoDoSistema();
            Ouvinte eu = new Ouvinte();
            Class<?> cn = Class.forName("android.content.ComponentName");
            Object comp = cn.getConstructor(String.class, String.class)
                    .newInstance("com.android.shell", "scrcpyf.Ouvinte");
            Method r = null;
            for (Method m : NotificationListenerService.class.getMethods()) {
                if (m.getName().equals("registerAsSystemService")) {
                    r = m;
                }
            }
            if (r == null) {
                throw new RuntimeException("sem registerAsSystemService");
            }
            r.invoke(eu, sCtx, comp, -1);            // USER_ALL
        } catch (Throwable t) {
            escrever("erro " + causa(t));
            System.exit(0);
        }
        Thread entrada = new Thread(new Runnable() {
            public void run() {
                ouvirPedidos();
            }
        });
        entrada.setDaemon(true);
        entrada.start();
        looper.getMethod("loop").invoke(null);
    }

    /** O mesmo preparo do scrcpy (Workarounds): um ActivityThread de sistema. */
    static Context contextoDoSistema() throws Exception {
        Class<?> at = Class.forName("android.app.ActivityThread");
        Constructor<?> c = at.getDeclaredConstructor();
        c.setAccessible(true);
        Object thread = c.newInstance();
        Field f = at.getDeclaredField("sCurrentActivityThread");
        f.setAccessible(true);
        f.set(null, thread);
        Field s = at.getDeclaredField("mSystemThread");
        s.setAccessible(true);
        s.setBoolean(thread, true);
        try {                                    // Android 12+
            Class<?> cc = Class.forName("android.app.ConfigurationController");
            Class<?> ati = Class.forName("android.app.ActivityThreadInternal");
            Constructor<?> k = cc.getDeclaredConstructor(ati);
            k.setAccessible(true);
            Field fc = at.getDeclaredField("mConfigurationController");
            fc.setAccessible(true);
            fc.set(thread, k.newInstance(thread));
        } catch (ClassNotFoundException e) {
            // Android antigo: nao precisa
        }
        Method g = at.getDeclaredMethod("getSystemContext");
        g.setAccessible(true);
        return (Context) g.invoke(thread);
    }

    // -- saida -----------------------------------------------------------------

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

    static String desesc(String s) {
        StringBuilder b = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\\' && i + 1 < s.length()) {
                char d = s.charAt(++i);
                b.append(d == 't' ? '\t' : d == 'n' ? '\n' : d);
            } else {
                b.append(c);
            }
        }
        return b.toString();
    }

    // -- o que chega do Android (na thread principal) ----------------------------

    @Override
    public void onListenerConnected() {
        try {
            StatusBarNotification[] todas = getActiveNotifications();
            if (todas != null) {
                for (StatusBarNotification sbn : todas) {
                    chegou(sbn);
                }
            }
            escrever("pronto");
        } catch (Throwable t) {
            escrever("erro listar: " + causa(t));
            System.exit(0);
        }
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            chegou(sbn);
        } catch (Throwable t) {
            // uma notificacao estranha nao derruba o ouvinte
        }
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
        try {
            String k = sbn.getKey();
            ATIVAS.remove(k);
            PROPRIAS.remove(k);
            synchronized (ASSINATURA) {
                ASSINATURA.remove(k);
                java.util.Iterator<String> it = ASSINATURA.keySet().iterator();
                while (it.hasNext()) {
                    if (it.next().startsWith(k + "#")) {
                        it.remove();
                    }
                }
            }
            escrever("X\t" + esc(k));
        } catch (Throwable t) {
            // idem
        }
    }

    static String tipo(PendingIntent pi) {
        if (pi == null) {
            return "-";
        }
        try {
            return pi.isActivity() ? "a" : "o";
        } catch (Throwable t) {
            return "o";                          // Android < 12: nao sabe
        }
    }

    static void chegou(StatusBarNotification sbn) {
        String k = sbn.getKey();
        ATIVAS.put(k, sbn);
        Notification n = sbn.getNotification();
        StringBuilder b = new StringBuilder();
        b.append(tipo(n.contentIntent));
        Notification.Action[] acoes = n.actions;
        int total = acoes == null ? 0 : acoes.length;
        // (07/out) layout PROPRIO do app (o "excluida · desfazer" do Gmail):
        // os botoes de dentro dele entram depois dos do app.
        Proprio prop = proprio(n, sbn.getPackageName());
        if (prop.cliques.isEmpty()) {
            PROPRIAS.remove(k);
        } else {
            PROPRIAS.put(k, prop.cliques);
        }
        b.append('\t').append(total + prop.cliques.size());
        for (int i = 0; i < total; i++) {
            Notification.Action a = acoes[i];
            RemoteInput[] ri = null;
            try {
                ri = a.getRemoteInputs();
            } catch (Throwable t) {
                // sem campo
            }
            b.append('\t').append(esc(a.title)).append('\t')
                    .append(temTexto(ri) ? "t" : "").append(tipo(a.actionIntent));
        }
        for (int i = 0; i < prop.cliques.size(); i++) {
            b.append('\t').append(esc(prop.rotulos.get(i))).append('\t')
                    .append(tipo(prop.cliques.get(i)));
        }
        String icone = imagem(k + "#i", icone(n), LADO_ICONE, true);
        String foto = imagem(k + "#f", foto(n), LADO_FOTO, false);
        String corpo = b.toString();
        boolean igual;
        synchronized (ASSINATURA) {
            igual = corpo.equals(ASSINATURA.get(k)) && "=".equals(icone)
                    && "=".equals(foto);
            ASSINATURA.put(k, corpo);
        }
        if (!igual) {
            escrever("N\t" + esc(k) + "\t" + corpo + "\t" + icone + "\t" + foto);
        }
        rostos(k, n);                            // a conversa pode ter andado
        conversa(k, n);
        textosProprios(k, prop);
    }

    /** "V <chave> <n> <texto>*n": os textos do layout proprio (depois do N,
     *  que cria a ficha no PC); n = 0 apaga os de antes. */
    static void textosProprios(String k, Proprio prop) {
        StringBuilder s = new StringBuilder().append(prop.textos.size());
        for (String t : prop.textos) {
            s.append('\t').append(esc(t));
        }
        String corpo = s.toString();
        synchronized (ASSINATURA) {
            String antes = ASSINATURA.get(k + "#v");
            if (corpo.equals(antes) || (antes == null && prop.textos.isEmpty())) {
                return;
            }
            ASSINATURA.put(k + "#v", corpo);
        }
        escrever("V\t" + esc(k) + "\t" + corpo);
    }

    // -- layout proprio (RemoteViews) ----------------------------------------------
    // (07/out, pedido dele) Notificacao com layout do app (contentView): o
    // Android so desenha, nao da titulo/texto/botoes. Os textos vem das
    // acoes "setText" guardadas no RemoteViews, e os botoes das acoes de
    // clique (PendingIntent), com o rotulo = o texto da mesma view.

    static final Map<String, java.util.List<PendingIntent>> PROPRIAS =
            new ConcurrentHashMap<String, java.util.List<PendingIntent>>();

    static final class Proprio {
        final java.util.List<String> textos = new java.util.ArrayList<String>();
        final java.util.List<String> rotulos = new java.util.ArrayList<String>();
        final java.util.List<PendingIntent> cliques =
                new java.util.ArrayList<PendingIntent>();
    }

    static Proprio proprio(Notification n, String pacote) {
        Proprio p = new Proprio();
        Object rv = null;
        try {
            rv = Notification.class.getField("contentView").get(n);
            if (rv == null) {
                rv = Notification.class.getField("bigContentView").get(n);
            }
        } catch (Throwable t) {
            rv = null;
        }
        if (rv == null || !doApp(rv)) {
            return p;
        }
        java.util.LinkedHashMap<Integer, String> textos =
                new java.util.LinkedHashMap<Integer, String>();
        java.util.LinkedHashMap<Integer, PendingIntent> cliques =
                new java.util.LinkedHashMap<Integer, PendingIntent>();
        try {
            varrer(rv, textos, cliques, 0);
        } catch (Throwable t) {
            // tenta montar, abaixo
        }
        if (textos.isEmpty() && cliques.isEmpty() && pacote != null) {
            // (07/out, achado no Gmail) o layout nao guarda setText nem
            // cliques: os textos estao no DESENHO do app -- monta e le
            try {
                java.util.List<Object[]> vistos = new java.util.ArrayList<Object[]>();
                inflar(rv, pacote, textos, vistos);
                for (Object[] v : vistos) {
                    if (v[2] instanceof PendingIntent) {
                        int id = v[3] instanceof Integer ? (Integer) v[3] : 0;
                        if (id == -1 || cliques.containsKey(id)) {
                            id = 2000000 + cliques.size();
                        }
                        cliques.put(id, (PendingIntent) v[2]);
                        String rotulo = v[1] == null ? "" : v[1].toString();
                        if (!rotulo.isEmpty()) {
                            textos.put(id, rotulo);
                            // o rotulo nao repete como texto solto
                            java.util.Iterator<Map.Entry<Integer, String>> it =
                                    textos.entrySet().iterator();
                            while (it.hasNext()) {
                                Map.Entry<Integer, String> e = it.next();
                                if (e.getKey() != id && rotulo.equals(e.getValue())) {
                                    it.remove();
                                }
                            }
                        }
                    }
                }
            } catch (Throwable t) {
                // sem montar: fica como estava
            }
        }
        for (Map.Entry<Integer, PendingIntent> c : cliques.entrySet()) {
            String r = textos.get(c.getKey());
            p.rotulos.add(r == null || r.trim().isEmpty() ? "abrir" : r.trim());
            p.cliques.add(c.getValue());
        }
        for (Map.Entry<Integer, String> t : textos.entrySet()) {
            String v = t.getValue().trim();
            if (!v.isEmpty() && !cliques.containsKey(t.getKey())
                    && !p.textos.contains(v)) {
                p.textos.add(v);
            }
        }
        return p;
    }

    /** (07/out, teste no celular dele: o X e as do sistema viravam "layout
     *  proprio") O Android tambem guarda o layout PADRAO num RemoteViews;
     *  ele e do pacote "android". So o layout do proprio app conta. */
    static boolean doApp(Object rv) {
        // O ouvinte (sem app de verdade) recebe o layout padrao ja montado,
        // com o pacote DO APP: o que diferencia e o DESENHO -- o do Android
        // tem id 0x01xxxxxx; o do app, 0x7fxxxxxx.
        try {
            Object em = campo(rv, "mPortrait");
            if (em != null) {
                rv = em;
            }
            int id = (Integer) rv.getClass().getMethod("getLayoutId").invoke(rv);
            return id != 0 && (id >>> 24) != 0x01;
        } catch (Throwable t) {
            return false;
        }
    }

    static void varrer(Object rv, Map<Integer, String> textos,
                       Map<Integer, PendingIntent> cliques, int fundo) throws Exception {
        if (rv == null || fundo > 6) {
            return;
        }
        // layout com versao deitada/em pe ou por tamanho: a "em pe"
        Object outra = campo(rv, "mPortrait");
        if (outra != null) {
            varrer(outra, textos, cliques, fundo + 1);
            return;
        }
        Object lista = campo(rv, "mActions");
        if (!(lista instanceof java.util.List)) {
            return;
        }
        for (Object a : (java.util.List<?>) lista) {
            if (a == null) {
                continue;
            }
            int id = inteiro(campo(a, "mViewId", "viewId"));
            Object metodo = campo(a, "mMethodName", "methodName");
            if (metodo != null && "setText".equals(metodo.toString())) {
                Object v = campo(a, "mValue", "value");
                if (v instanceof CharSequence) {
                    textos.put(id, v.toString());
                }
                continue;
            }
            Object pi = campo(a, "mPendingIntent", "pendingIntent");
            if (pi == null) {
                Object resp = campo(a, "mResponse");
                if (resp != null) {
                    pi = campo(resp, "mPendingIntent");
                }
            }
            if (pi instanceof PendingIntent) {
                cliques.put(id, (PendingIntent) pi);
                continue;
            }
            Object filho = campo(a, "mNestedViews", "nestedViews");
            if (filho != null) {
                varrer(filho, textos, cliques, fundo + 1);
            }
        }
    }

    /** O primeiro campo que existir (procura na classe e nas de cima). */
    static Object campo(Object o, String... nomes) {
        for (String nome : nomes) {
            for (Class<?> c = o.getClass(); c != null; c = c.getSuperclass()) {
                try {
                    Field f = c.getDeclaredField(nome);
                    f.setAccessible(true);
                    return f.get(o);
                } catch (NoSuchFieldException e) {
                    // a de cima
                } catch (Throwable t) {
                    break;
                }
            }
        }
        return null;
    }

    static int inteiro(Object o) {
        return o instanceof Integer ? (Integer) o : 0;
    }

    /** (03/out) A CONVERSA (MessagingStyle) lida do objeto: o `cmd
     *  notification` nao diz quem mandou quando o app so poe a Person (o
     *  WhatsApp). Linha "M <chave> <titulo> <grupo 0|1> <eu> <n>
     *  (<quem> <texto> <quando>)*n"; quem vazio = a propria pessoa. */
    static void conversa(String k, Notification n) {
        try {
            Bundle ex = n.extras;
            Object msgs = ex == null ? null : ex.get("android.messages");
            if (!(msgs instanceof Object[])) {
                return;
            }
            String eu = nome(ex.get("android.messagingUser"));
            if (eu.isEmpty()) {
                Object s = ex.get("android.selfDisplayName");
                eu = s == null ? "" : s.toString();
            }
            Object titulo = ex.get("android.conversationTitle");
            boolean grupo = Boolean.TRUE.equals(ex.get("android.isGroupConversation"));
            StringBuilder itens = new StringBuilder();
            int total = 0;
            for (Object m : (Object[]) msgs) {
                if (!(m instanceof Bundle)) {
                    continue;
                }
                Bundle mb = (Bundle) m;
                Object texto = mb.get("text");
                if (texto == null) {
                    continue;
                }
                String quem = nome(mb.get("sender_person"));
                if (quem.isEmpty()) {
                    Object s = mb.get("sender");
                    quem = s == null ? "" : s.toString();
                }
                Object t = mb.get("time");
                long quando = t instanceof Long ? (Long) t : 0L;
                itens.append('\t').append(esc(quem)).append('\t').append(esc(texto))
                        .append('\t').append(quando);
                total++;
            }
            String corpo = esc(titulo) + "\t" + (grupo ? "1" : "0") + "\t" + esc(eu)
                    + "\t" + total + itens;
            synchronized (ASSINATURA) {
                if (corpo.equals(ASSINATURA.get(k + "#m"))) {
                    return;
                }
                ASSINATURA.put(k + "#m", corpo);
            }
            escrever("M\t" + esc(k) + "\t" + corpo);
        } catch (Throwable t) {
            // conversa estranha: fica o que o cmd notification deu
        }
    }

    static String nome(Object p) {
        if (p instanceof Person) {
            CharSequence c = ((Person) p).getName();
            return c == null ? "" : c.toString();
        }
        return "";
    }

    /** Conversa a dois sem foto grande (o Android poe a do contato): a foto
     *  de quem mandou a ultima mensagem que nao e da propria pessoa. */
    static Bitmap rostoDaConversa(Notification n) {
        try {
            Bundle ex = n.extras;
            if (ex == null || Boolean.TRUE.equals(ex.get("android.isGroupConversation"))) {
                return null;
            }
            Object msgs = ex.get("android.messages");
            if (!(msgs instanceof Object[])) {
                return null;
            }
            Object[] lista = (Object[]) msgs;
            for (int i = lista.length - 1; i >= 0; i--) {
                if (!(lista[i] instanceof Bundle)) {
                    continue;
                }
                Object p = ((Bundle) lista[i]).get("sender_person");
                if (p instanceof Person) {
                    Bitmap b = deIcone(((Person) p).getIcon());
                    if (b != null) {
                        return b;
                    }
                }
            }
        } catch (Throwable t) {
            // sem foto
        }
        return null;
    }

    /** (03/out) Conversa (MessagingStyle): a foto de cada pessoa, uma linha
     *  "P <chave> <nome> <png>" so quando a foto daquela pessoa muda. */
    static void rostos(String k, Notification n) {
        try {
            Object msgs = n.extras == null ? null : n.extras.get("android.messages");
            if (!(msgs instanceof Object[])) {
                return;
            }
            java.util.Set<String> vistos = new java.util.HashSet<String>();
            for (Object m : (Object[]) msgs) {
                if (!(m instanceof Bundle)) {
                    continue;
                }
                Object p = ((Bundle) m).get("sender_person");
                if (!(p instanceof Person)) {
                    continue;
                }
                CharSequence nome = ((Person) p).getName();
                if (nome == null || !vistos.add(nome.toString())) {
                    continue;
                }
                Bitmap b = null;
                try {
                    b = deIcone(((Person) p).getIcon());
                } catch (Throwable t) {
                    // sem foto
                }
                String png = imagem(k + "#p:" + nome, b, LADO_ICONE, true);
                if (!"=".equals(png)) {
                    escrever("P\t" + esc(k) + "\t" + esc(nome) + "\t" + png);
                }
            }
        } catch (Throwable t) {
            // conversa estranha: fica sem os rostos
        }
    }

    static boolean temTexto(RemoteInput[] ri) {
        if (ri == null) {
            return false;
        }
        for (RemoteInput r : ri) {
            if (r != null && r.getAllowFreeFormInput()) {
                return true;
            }
        }
        return false;
    }

    // -- imagens -------------------------------------------------------------------

    static Bitmap icone(Notification n) {
        try {
            Bitmap b = deIcone(n.getLargeIcon());
            if (b != null) {
                return b;
            }
        } catch (Throwable t) {
            // tenta o extra
        }
        Bitmap b = doExtra(n, "android.largeIcon");
        return b != null ? b : rostoDaConversa(n);
    }

    static Bitmap foto(Notification n) {
        Bitmap b = doExtra(n, "android.picture");
        return b != null ? b : doExtra(n, "android.pictureIcon");
    }

    static Bitmap doExtra(Notification n, String chave) {
        try {
            Object o = n.extras == null ? null : n.extras.get(chave);
            if (o instanceof Bitmap) {
                return (Bitmap) o;
            }
            if (o instanceof Icon) {
                return deIcone((Icon) o);
            }
        } catch (Throwable t) {
            // sem imagem
        }
        return null;
    }

    static Bitmap deIcone(Icon ic) {
        if (ic == null) {
            return null;
        }
        Drawable d = ic.loadDrawable(sCtx);
        if (d == null) {
            return null;
        }
        if (d instanceof BitmapDrawable) {
            Bitmap b = ((BitmapDrawable) d).getBitmap();
            if (b != null) {
                return b;
            }
        }
        int w = Math.max(1, Math.min(LADO_FOTO, d.getIntrinsicWidth()));
        int h = Math.max(1, Math.min(LADO_FOTO, d.getIntrinsicHeight()));
        Bitmap b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
        d.setBounds(0, 0, w, h);
        d.draw(new Canvas(b));
        return b;
    }

    /** Base64 da imagem, "-" sem, "=" igual a ultima mandada desta chave. A
     *  comparacao e por amostra de pixels: a mesma foto chega como objeto
     *  novo a cada atualizacao da notificacao. */
    static String imagem(String chave, Bitmap bmp, int lado, boolean png) {
        String sig = "-";
        try {
            if (bmp != null) {
                try {
                    bmp = bmp.copy(Bitmap.Config.ARGB_8888, false);
                } catch (Throwable t) {
                    // fica a original
                }
                int w = bmp.getWidth();
                int h = bmp.getHeight();
                StringBuilder s = new StringBuilder().append(w).append('x').append(h);
                for (int i = 1; i < 8; i++) {
                    s.append(':').append(bmp.getPixel(w * i / 8, h * i / 8))
                            .append(':').append(bmp.getPixel(w * i / 8, h * (8 - i) / 8));
                }
                sig = s.toString();
            }
        } catch (Throwable t) {
            bmp = null;
            sig = "-";
        }
        synchronized (ASSINATURA) {
            if (sig.equals(ASSINATURA.get(chave))) {
                return "=";
            }
            ASSINATURA.put(chave, sig);
        }
        if (bmp == null) {
            return "-";
        }
        try {
            int w = bmp.getWidth();
            int h = bmp.getHeight();
            if (w > lado || h > lado) {
                float f = Math.min(lado / (float) w, lado / (float) h);
                bmp = Bitmap.createScaledBitmap(bmp, Math.max(1, (int) (w * f)),
                        Math.max(1, (int) (h * f)), true);
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            bmp.compress(png ? Bitmap.CompressFormat.PNG : Bitmap.CompressFormat.JPEG,
                    85, out);
            return Base64.getEncoder().encodeToString(out.toByteArray());
        } catch (Throwable t) {
            return "-";
        }
    }

    // -- pedidos do PC ---------------------------------------------------------------

    static void ouvirPedidos() {
        try {
            BufferedReader r = new BufferedReader(new InputStreamReader(System.in));
            String linha;
            while ((linha = r.readLine()) != null) {
                String[] p = linha.split("\t", -1);
                if (p.length < 2) {
                    continue;
                }
                String id = p[0];
                try {
                    escrever("r\t" + id + "\tok\t" + esc(pedido(p)));
                } catch (Throwable t) {
                    escrever("r\t" + id + "\terro\t" + esc(causa(t)));
                }
            }
        } catch (Throwable t) {
            // entrada fechou: o PC saiu
        }
        System.exit(0);
    }

    static String pedido(String[] p) throws Exception {
        if ("a".equals(p[1]) && p.length >= 6) {
            return acao(desesc(p[2]), Integer.parseInt(p[3]),
                    Integer.parseInt(p[4]), desesc(p[5]));
        }
        if ("c".equals(p[1]) && p.length >= 4) {
            StatusBarNotification sbn = ativa(desesc(p[2]));
            PendingIntent pi = sbn.getNotification().contentIntent;
            if (pi == null) {
                throw new RuntimeException("sem toque");
            }
            mandar(pi, null, Integer.parseInt(p[3]));
            return "aberto";
        }
        if ("d".equals(p[1]) && p.length >= 3) {
            return depurar(desesc(p[2]));
        }
        throw new RuntimeException("pedido desconhecido");
    }

    /** (07/out) DIAGNOSTICO do layout proprio: as acoes guardadas no
     *  RemoteViews e o que aparece montando ele no contexto do app. */
    static String depurar(String chave) throws Exception {
        Notification n = ativa(chave).getNotification();
        Object rv = Notification.class.getField("contentView").get(n);
        if (rv == null) {
            return "sem contentView";
        }
        StringBuilder s = new StringBuilder();
        Object port = campo(rv, "mPortrait");
        Object base = port != null ? port : rv;
        s.append("layout=").append(Integer.toHexString((Integer) base.getClass()
                .getMethod("getLayoutId").invoke(base)));
        Object acts = campo(base, "mActions");
        s.append(" acoes=").append(acts == null ? "null"
                : String.valueOf(((java.util.List<?>) acts).size()));
        if (acts instanceof java.util.List) {
            for (Object a : (java.util.List<?>) acts) {
                s.append(" | ").append(a == null ? "null" : a.getClass().getSimpleName());
            }
        }
        try {
            java.util.Map<Integer, String> textos = new java.util.LinkedHashMap<Integer, String>();
            java.util.List<Object[]> cliques = new java.util.ArrayList<Object[]>();
            inflar(rv, chave.split("\\|")[1], textos, cliques);
            s.append(" || textos=").append(textos.values());
            s.append(" cliques=");
            for (Object[] c : cliques) {
                s.append("[").append(c[1]).append(" pi=").append(c[2] != null).append("]");
            }
        } catch (Throwable t) {
            s.append(" || inflar falhou: ").append(causa(t));
        }
        return s.toString();
    }

    // (07/out, achado no Gmail: "excluida · desfazer" e um layout proprio
    // sem setText -- os textos estao no DESENHO do app) MONTAR o layout no
    // contexto do app, como a barra do Android faz, e ler o que aparece:
    // os textos visiveis e as views clicaveis (com o PendingIntent que o
    // RemoteViews guarda na tag da view).
    static Object contextoDe(String pacote) throws Exception {
        Class<?> at = Class.forName("android.app.ActivityThread");
        Object t = at.getMethod("currentActivityThread").invoke(null);
        if (t == null) {
            t = at.getMethod("systemMain").invoke(null);
        }
        Object sys = at.getMethod("getSystemContext").invoke(t);
        return sys.getClass().getMethod("createPackageContext", String.class, int.class)
                .invoke(sys, pacote, 3);       // INCLUDE_CODE | IGNORE_SECURITY
    }

    static void inflar(Object rv, String pacote, java.util.Map<Integer, String> textos,
                       java.util.List<Object[]> cliques) throws Exception {
        Class<?> looper = Class.forName("android.os.Looper");
        if (looper.getMethod("myLooper").invoke(null) == null) {
            looper.getMethod("prepare").invoke(null);
        }
        Object ctx = contextoDe(pacote);
        Class<?> ctxC = Class.forName("android.content.Context");
        Class<?> vg = Class.forName("android.view.ViewGroup");
        Object pai = Class.forName("android.widget.FrameLayout").getConstructor(ctxC)
                .newInstance(ctx);
        Object v = rv.getClass().getMethod("apply", ctxC, vg).invoke(rv, ctx, pai);
        int tag = 0;
        try {
            Class<?> res = Class.forName("android.content.res.Resources");
            Object sis = res.getMethod("getSystem").invoke(null);
            tag = (Integer) res.getMethod("getIdentifier", String.class, String.class,
                    String.class).invoke(sis, "pending_intent_tag", "id", "android");
        } catch (Throwable t) {
            tag = 0;
        }
        andar(v, textos, cliques, tag, 0);
    }

    static void andar(Object v, java.util.Map<Integer, String> textos,
                      java.util.List<Object[]> cliques, int tag, int fundo) throws Exception {
        if (v == null || fundo > 12) {
            return;
        }
        Class<?> view = Class.forName("android.view.View");
        if ((Integer) view.getMethod("getVisibility").invoke(v) != 0) {
            return;                              // escondida: nao aparece
        }
        int id = (Integer) view.getMethod("getId").invoke(v);
        Class<?> tv = Class.forName("android.widget.TextView");
        String texto = null;
        if (tv.isInstance(v)) {
            Object t = tv.getMethod("getText").invoke(v);
            if (t != null && t.toString().trim().length() > 0) {
                texto = t.toString().trim();
                textos.put(id == -1 ? 1000000 + textos.size() : id, texto);
            }
        }
        boolean clica = (Boolean) view.getMethod("hasOnClickListeners").invoke(v);
        if (clica) {
            Object pi = null;
            if (tag != 0) {
                try {
                    pi = view.getMethod("getTag", int.class).invoke(v, tag);
                } catch (Throwable t) {
                    pi = null;
                }
            }
            cliques.add(new Object[] {v, texto == null ? textoDentro(v) : texto,
                    pi instanceof PendingIntent ? pi : null, id});
        }
        Class<?> vg = Class.forName("android.view.ViewGroup");
        if (vg.isInstance(v)) {
            int n = (Integer) vg.getMethod("getChildCount").invoke(v);
            for (int i = 0; i < n; i++) {
                andar(vg.getMethod("getChildAt", int.class).invoke(v, i), textos, cliques,
                        tag, fundo + 1);
            }
        }
    }

    /** O primeiro texto visivel dentro de uma view (o rotulo do botao). */
    static String textoDentro(Object v) {
        try {
            java.util.Map<Integer, String> t = new java.util.LinkedHashMap<Integer, String>();
            andar(v, t, new java.util.ArrayList<Object[]>(), 0, 0);
            for (String s : t.values()) {
                return s;
            }
        } catch (Throwable e) {
            // sem rotulo
        }
        return "";
    }

    static StatusBarNotification ativa(String chave) {
        StatusBarNotification sbn = ATIVAS.get(chave);
        if (sbn == null) {
            throw new RuntimeException("a notificacao ja saiu");
        }
        return sbn;
    }

    static String acao(String chave, int indice, int tela, String texto)
            throws Exception {
        Notification.Action[] acoes = ativa(chave).getNotification().actions;
        int doApp = acoes == null ? 0 : acoes.length;
        if (indice >= doApp) {
            // (07/out) um botao de dentro do layout proprio ("desfazer")
            java.util.List<PendingIntent> prop = PROPRIAS.get(chave);
            int i = indice - doApp;
            if (prop == null || i >= prop.size()) {
                throw new RuntimeException("a acao mudou");
            }
            String liberado = liberar(chave);
            return "feito" + liberado + " (" + tipo(prop.get(i)) + ", "
                    + mandar(prop.get(i), null, tela) + ")";
        }
        if (acoes == null || indice < 0) {
            throw new RuntimeException("a acao mudou");
        }
        Notification.Action a = acoes[indice];
        if (a.actionIntent == null) {
            throw new RuntimeException("acao sem destino");
        }
        Intent dados = null;
        RemoteInput[] ri = a.getRemoteInputs();
        if (temTexto(ri)) {
            if (texto.trim().isEmpty()) {
                throw new RuntimeException("texto vazio");
            }
            dados = new Intent();
            dados.addFlags(0x10000000);          // FLAG_RECEIVER_FOREGROUND
            Bundle b = new Bundle();
            for (RemoteInput r : ri) {
                if (r != null && r.getAllowFreeFormInput()) {
                    b.putCharSequence(r.getResultKey(), texto);
                }
            }
            RemoteInput.addResultsToIntent(ri, dados, b);
            try {
                RemoteInput.setResultsSource(dados, 0);   // SOURCE_FREE_FORM_INPUT
            } catch (Throwable t) {
                // Android < 9
            }
        }
        String liberado = liberar(chave);
        String entrega = mandar(a.actionIntent, dados, tela);
        return (dados != null ? "respondido" : "feito") + liberado + " ("
                + tipo(a.actionIntent) + ", " + entrega + ")";
    }

    /** (03/out, relato dele: "marcar como lida" nao fazia nada) A barra do
     *  Android poe o app numa lista temporaria antes de disparar o botao: o
     *  app pode entao rodar o servico dele em segundo plano (marcar como
     *  lida, apagar...). Sem isso o Android barra calado. O shell pode o
     *  mesmo: cmd deviceidle tempwhitelist. Chave = "usuario|pacote|...". */
    static String liberar(String chave) {
        try {
            String[] p = chave.split("\\|");
            Process pr = Runtime.getRuntime().exec(new String[] {"cmd", "deviceidle",
                    "tempwhitelist", "-u", p[0], "-d", "20000", p[1]});
            pr.getInputStream().close();
            return pr.waitFor() == 0 ? " (liberado)" : " (sem liberar)";
        } catch (Throwable t) {
            return " (sem liberar: " + causa(t) + ")";
        }
    }

    /** Dispara o PendingIntent como o toque na barra dispararia. Tela do app:
     *  na tela pedida (a janela do PC); o shell pode abrir tela "de fundo",
     *  mas no Android 14+ quem manda tem que dizer que permite. */
    static String mandar(PendingIntent pi, Intent dados, int tela) throws Exception {
        // (03/out) As opcoes de TELA so vao para o que abre tela: num botao
        // que e broadcast/servico (marcar como lida) elas nao cabem.
        Bundle opcoes = null;
        if ("a".equals(tipo(pi))) {
            try {
                ActivityOptions o = ActivityOptions.makeBasic();
                if (tela >= 0) {
                    o.setLaunchDisplayId(tela);
                }
                // (08/out, logcat no S22: "Background activity launch blocked!
                // ... Without BAL hardening this activity start would be
                // allowed") No Android 16 o ALLOWED (1) virou "so se quem
                // manda estiver a vista" -- e um app_process nunca esta: a
                // noticia do Google caia na home. ALLOW_ALWAYS (3) e o novo
                // "permitir sempre" (API 36); antes dele, o 1.
                try {
                    o.setPendingIntentBackgroundActivityStartMode(
                            sdk() >= 36 ? 3 : 1);
                } catch (Throwable t) {
                    try {
                        o.setPendingIntentBackgroundActivityStartMode(1);
                    } catch (Throwable t2) {
                        // Android < 14
                    }
                }
                opcoes = o.toBundle();
            } catch (Throwable t) {
                opcoes = null;
            }
        }
        // (07/out, logcat dele: "Unable to find app for caller ... (pid=-1)
        // when starting service ... MARK_AS_READ") O PendingIntent.send
        // manda junto o "ApplicationThread" deste processo, que o Android
        // nao conhece (somos um app_process): para TELA ele deixa passar,
        // para SERVICO e BROADCAST (marcar como lida, apagar, responder)
        // recusa. Sem tela: manda direto ao ActivityManager SEM quem chama.
        if (!"a".equals(tipo(pi))) {
            return semChamador(pi, dados);
        }
        // Diagnostico: o Android avisa quando terminou de entregar.
        final int[] codigo = {Integer.MIN_VALUE};
        final java.util.concurrent.CountDownLatch fim =
                new java.util.concurrent.CountDownLatch(1);
        PendingIntent.OnFinished aviso = new PendingIntent.OnFinished() {
            public void onSendFinished(PendingIntent p, Intent i, int c,
                                       String d, Bundle e) {
                codigo[0] = c;
                fim.countDown();
            }
        };
        pi.send(sCtx, 0, dados, aviso, null, null, opcoes);
        fim.await(3, java.util.concurrent.TimeUnit.SECONDS);
        return codigo[0] == Integer.MIN_VALUE ? "sem retorno"
                : "entregue " + codigo[0];
    }

    /** A versao do Android (Build.VERSION.SDK_INT, por reflexao: as cascas
     *  de compilar nao tem o Build). 0 se nao der. */
    static int sdk() {
        try {
            return Class.forName("android.os.Build$VERSION")
                    .getField("SDK_INT").getInt(null);
        } catch (Throwable t) {
            return 0;
        }
    }

    /** IActivityManager.sendIntentSender com caller = null (o mesmo que a
     *  barra faria, sem um app que o Android nao conhece). Android 12+: 9
     *  parametros (caller primeiro); antes: 8. Devolve "direto <res>". */
    static String semChamador(PendingIntent pi, Intent dados) throws Exception {
        Object am = Class.forName("android.app.ActivityManager")
                .getMethod("getService").invoke(null);
        Object alvo = PendingIntent.class.getMethod("getTarget").invoke(pi);
        Object ficha = null;
        try {
            Field f = PendingIntent.class.getDeclaredField("mWhitelistToken");
            f.setAccessible(true);
            ficha = f.get(pi);
        } catch (Throwable t) {
            ficha = null;
        }
        String tipoRes = null;          // a resposta (RemoteInput) nao tem tipo
        for (Method m : am.getClass().getMethods()) {
            if (!m.getName().equals("sendIntentSender")) {
                continue;
            }
            Object r;
            int n = m.getParameterTypes().length;
            if (n == 9) {
                r = m.invoke(am, null, alvo, ficha, 0, dados, tipoRes, null,
                        null, null);
            } else if (n == 8) {
                r = m.invoke(am, alvo, ficha, 0, dados, tipoRes, null, null,
                        null);
            } else {
                continue;
            }
            return "direto " + r;
        }
        throw new RuntimeException("sem sendIntentSender");
    }
}
