.class public Lscrcpyf/Icones;
.super Ljava/lang/Object;
.source "Icones.smali"

# scrcpy-f: devolve o icone de cada app pedido, como PNG em base64.
# Uso (no celular):  CLASSPATH=<este jar> app_process / scrcpyf.Icones <tamanho> <pacote>...
# Saida: uma linha por pacote, "pacote<TAB>base64" (ou
# "pacote<TAB>-<TAB>C: motivo | A: motivo" se os dois caminhos falharem).

.method public static main([Ljava/lang/String;)V
    .registers 16

    invoke-static {}, Landroid/os/Looper;->prepareMainLooper()V

    # ActivityThread criada por reflexao (o construtor nao e publico) -- o
    # mesmo caminho que o scrcpy usa para ter um Context rodando como shell.
    const-string v0, "android.app.ActivityThread"
    invoke-static {v0}, Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;
    move-result-object v0
    const/4 v1, 0x0
    new-array v1, v1, [Ljava/lang/Class;
    invoke-virtual {v0, v1}, Ljava/lang/Class;->getDeclaredConstructor([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;
    move-result-object v1
    const/4 v2, 0x1
    invoke-virtual {v1, v2}, Ljava/lang/reflect/Constructor;->setAccessible(Z)V
    const/4 v2, 0x0
    new-array v2, v2, [Ljava/lang/Object;
    invoke-virtual {v1, v2}, Ljava/lang/reflect/Constructor;->newInstance([Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v1

    :campo_ini
    const-string v2, "sCurrentActivityThread"
    invoke-virtual {v0, v2}, Ljava/lang/Class;->getDeclaredField(Ljava/lang/String;)Ljava/lang/reflect/Field;
    move-result-object v2
    const/4 v3, 0x1
    invoke-virtual {v2, v3}, Ljava/lang/reflect/Field;->setAccessible(Z)V
    const/4 v3, 0x0
    invoke-virtual {v2, v3, v1}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V
    :campo_fim
    .catch Ljava/lang/Throwable; {:campo_ini .. :campo_fim} :depois_do_campo
    :depois_do_campo

    # O One UI (CompatSandbox) pede a configuracao da tela a ActivityThread,
    # que so a tem com um ConfigurationController -- sem ele: NullPointer e
    # o processo morre (sonda de 23/set/2026). O scrcpy-server faz o mesmo
    # (Workarounds.fillConfigurationController).
    :cc_ini
    const-string v2, "android.app.ConfigurationController"
    invoke-static {v2}, Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;
    move-result-object v2
    const-string v3, "android.app.ActivityThreadInternal"
    invoke-static {v3}, Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;
    move-result-object v3
    const/4 v4, 0x1
    new-array v4, v4, [Ljava/lang/Class;
    const/4 v5, 0x0
    aput-object v3, v4, v5
    invoke-virtual {v2, v4}, Ljava/lang/Class;->getDeclaredConstructor([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;
    move-result-object v2
    const/4 v3, 0x1
    invoke-virtual {v2, v3}, Ljava/lang/reflect/Constructor;->setAccessible(Z)V
    const/4 v3, 0x1
    new-array v3, v3, [Ljava/lang/Object;
    const/4 v4, 0x0
    aput-object v1, v3, v4
    invoke-virtual {v2, v3}, Ljava/lang/reflect/Constructor;->newInstance([Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v2
    # Uma configuracao de fabrica dentro do controlador: sem ela a pergunta
    # do One UI volta vazia e o problema so muda de lugar.
    :conf_ini
    invoke-virtual {v2}, Ljava/lang/Object;->getClass()Ljava/lang/Class;
    move-result-object v5
    const-string v6, "mConfiguration"
    invoke-virtual {v5, v6}, Ljava/lang/Class;->getDeclaredField(Ljava/lang/String;)Ljava/lang/reflect/Field;
    move-result-object v5
    const/4 v6, 0x1
    invoke-virtual {v5, v6}, Ljava/lang/reflect/Field;->setAccessible(Z)V
    new-instance v6, Landroid/content/res/Configuration;
    invoke-direct {v6}, Landroid/content/res/Configuration;-><init>()V
    invoke-virtual {v6}, Landroid/content/res/Configuration;->setToDefaults()V
    # Densidade de verdade (480): com 0 o Android nao achava nem o icone
    # padrao do sistema (sonda de 23/set/2026, 09:43).
    const/16 v7, 0x1e0
    iput v7, v6, Landroid/content/res/Configuration;->densityDpi:I
    invoke-virtual {v5, v2, v6}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V
    :conf_fim
    .catch Ljava/lang/Throwable; {:conf_ini .. :conf_fim} :depois_da_conf
    :depois_da_conf
    const-string v3, "mConfigurationController"
    invoke-virtual {v0, v3}, Ljava/lang/Class;->getDeclaredField(Ljava/lang/String;)Ljava/lang/reflect/Field;
    move-result-object v3
    const/4 v4, 0x1
    invoke-virtual {v3, v4}, Ljava/lang/reflect/Field;->setAccessible(Z)V
    invoke-virtual {v3, v1, v2}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V
    :cc_fim
    .catch Ljava/lang/Throwable; {:cc_ini .. :cc_fim} :depois_do_cc
    :depois_do_cc

    # mSystemThread = true, tambem como o scrcpy-server.
    :st_ini
    const-string v3, "mSystemThread"
    invoke-virtual {v0, v3}, Ljava/lang/Class;->getDeclaredField(Ljava/lang/String;)Ljava/lang/reflect/Field;
    move-result-object v3
    const/4 v4, 0x1
    invoke-virtual {v3, v4}, Ljava/lang/reflect/Field;->setAccessible(Z)V
    invoke-virtual {v3, v1, v4}, Ljava/lang/reflect/Field;->setBoolean(Ljava/lang/Object;Z)V
    :st_fim
    .catch Ljava/lang/Throwable; {:st_ini .. :st_fim} :depois_do_st
    :depois_do_st

    const-string v2, "getSystemContext"
    const/4 v3, 0x0
    new-array v3, v3, [Ljava/lang/Class;
    invoke-virtual {v0, v2, v3}, Ljava/lang/Class;->getDeclaredMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;
    move-result-object v2
    const/4 v3, 0x1
    invoke-virtual {v2, v3}, Ljava/lang/reflect/Method;->setAccessible(Z)V
    const/4 v3, 0x0
    new-array v3, v3, [Ljava/lang/Object;
    invoke-virtual {v2, v1, v3}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;
    move-result-object v2
    check-cast v2, Landroid/content/Context;

    # Um Application de mentira, com o Context do sistema por baixo, como
    # "o app atual" da ActivityThread: o AdaptiveIconDrawable (o icone
    # moderno, em camadas) pede currentApplication().getResources() para a
    # mascara do icone e, sem ele, estourava NullPointer (sonda v5).
    :app_ini
    new-instance v3, Landroid/app/Application;
    invoke-direct {v3}, Landroid/app/Application;-><init>()V
    const-class v5, Landroid/content/ContextWrapper;
    const-string v6, "attachBaseContext"
    const/4 v7, 0x1
    new-array v7, v7, [Ljava/lang/Class;
    const-class v8, Landroid/content/Context;
    const/4 v9, 0x0
    aput-object v8, v7, v9
    invoke-virtual {v5, v6, v7}, Ljava/lang/Class;->getDeclaredMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;
    move-result-object v5
    const/4 v6, 0x1
    invoke-virtual {v5, v6}, Ljava/lang/reflect/Method;->setAccessible(Z)V
    const/4 v6, 0x1
    new-array v6, v6, [Ljava/lang/Object;
    aput-object v2, v6, v9
    invoke-virtual {v5, v3, v6}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;
    const-string v5, "mInitialApplication"
    invoke-virtual {v0, v5}, Ljava/lang/Class;->getDeclaredField(Ljava/lang/String;)Ljava/lang/reflect/Field;
    move-result-object v5
    const/4 v6, 0x1
    invoke-virtual {v5, v6}, Ljava/lang/reflect/Field;->setAccessible(Z)V
    invoke-virtual {v5, v1, v3}, Ljava/lang/reflect/Field;->set(Ljava/lang/Object;Ljava/lang/Object;)V
    :app_fim
    .catch Ljava/lang/Throwable; {:app_ini .. :app_fim} :depois_da_app
    :depois_da_app
    invoke-virtual {v2}, Landroid/content/Context;->getPackageManager()Landroid/content/pm/PackageManager;
    move-result-object v4

    const/4 v0, 0x0
    aget-object v0, p0, v0
    invoke-static {v0}, Ljava/lang/Integer;->parseInt(Ljava/lang/String;)I
    move-result v5

    sget-object v6, Ljava/lang/System;->out:Ljava/io/PrintStream;
    array-length v7, p0
    const/4 v8, 0x1

    :laco
    if-ge v8, v7, :fim
    aget-object v9, p0, v8

    # Caminho 1 (v4): os recursos do PROPRIO app, pedindo o icone numa
    # densidade fixa. Se falhar, caminho 2: getApplicationIcon (o de antes).
    const/4 v10, 0x0
    const-string v1, ""
    :c_ini
    const/4 v0, 0x0
    invoke-virtual {v4, v9, v0}, Landroid/content/pm/PackageManager;->getApplicationInfo(Ljava/lang/String;I)Landroid/content/pm/ApplicationInfo;
    move-result-object v2
    iget v3, v2, Landroid/content/pm/ApplicationInfo;->icon:I
    invoke-virtual {v4, v2}, Landroid/content/pm/PackageManager;->getResourcesForApplication(Landroid/content/pm/ApplicationInfo;)Landroid/content/res/Resources;
    move-result-object v2
    const/16 v12, 0x1e0
    const/4 v13, 0x0
    invoke-virtual {v2, v3, v12, v13}, Landroid/content/res/Resources;->getDrawableForDensity(IILandroid/content/res/Resources$Theme;)Landroid/graphics/drawable/Drawable;
    move-result-object v10
    :c_fim
    .catch Ljava/lang/Throwable; {:c_ini .. :c_fim} :c_falhou
    goto :tenta_ini
    :c_falhou
    move-exception v13
    invoke-static {v13}, Lscrcpyf/Icones;->motivo(Ljava/lang/Throwable;)Ljava/lang/String;
    move-result-object v1
    const/4 v10, 0x0

    :tenta_ini
    if-nez v10, :tem_desenho
    invoke-virtual {v4, v9}, Landroid/content/pm/PackageManager;->getApplicationIcon(Ljava/lang/String;)Landroid/graphics/drawable/Drawable;
    move-result-object v10
    :tem_desenho
    sget-object v0, Landroid/graphics/Bitmap$Config;->ARGB_8888:Landroid/graphics/Bitmap$Config;
    invoke-static {v5, v5, v0}, Landroid/graphics/Bitmap;->createBitmap(IILandroid/graphics/Bitmap$Config;)Landroid/graphics/Bitmap;
    move-result-object v11
    new-instance v12, Landroid/graphics/Canvas;
    invoke-direct {v12, v11}, Landroid/graphics/Canvas;-><init>(Landroid/graphics/Bitmap;)V
    const/4 v0, 0x0
    invoke-virtual {v10, v0, v0, v5, v5}, Landroid/graphics/drawable/Drawable;->setBounds(IIII)V
    invoke-virtual {v10, v12}, Landroid/graphics/drawable/Drawable;->draw(Landroid/graphics/Canvas;)V
    new-instance v12, Ljava/io/ByteArrayOutputStream;
    invoke-direct {v12}, Ljava/io/ByteArrayOutputStream;-><init>()V
    sget-object v0, Landroid/graphics/Bitmap$CompressFormat;->PNG:Landroid/graphics/Bitmap$CompressFormat;
    const/16 v13, 0x64
    invoke-virtual {v11, v0, v13, v12}, Landroid/graphics/Bitmap;->compress(Landroid/graphics/Bitmap$CompressFormat;ILjava/io/OutputStream;)Z
    invoke-virtual {v12}, Ljava/io/ByteArrayOutputStream;->toByteArray()[B
    move-result-object v0
    invoke-static {}, Ljava/util/Base64;->getEncoder()Ljava/util/Base64$Encoder;
    move-result-object v13
    invoke-virtual {v13, v0}, Ljava/util/Base64$Encoder;->encodeToString([B)Ljava/lang/String;
    move-result-object v13
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v14, "\t"
    invoke-virtual {v0, v14}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, v13}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-virtual {v6, v0}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V
    :tenta_fim
    .catch Ljava/lang/Throwable; {:tenta_ini .. :tenta_fim} :falhou

    :proximo
    add-int/lit8 v8, v8, 0x1
    goto :laco

    :falhou
    move-exception v13
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v14, "\t-\tC: "
    invoke-virtual {v0, v14}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v14, " | A: "
    invoke-virtual {v0, v14}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    # o motivo, numa linha so (o PC anota os primeiros)
    invoke-static {v13}, Lscrcpyf/Icones;->motivo(Ljava/lang/Throwable;)Ljava/lang/String;
    move-result-object v13
    invoke-virtual {v0, v13}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-virtual {v6, v0}, Ljava/io/PrintStream;->println(Ljava/lang/String;)V
    goto :proximo

    :fim
    invoke-virtual {v6}, Ljava/io/PrintStream;->flush()V
    const/4 v0, 0x0
    invoke-static {v0}, Ljava/lang/System;->exit(I)V
    return-void
.end method


# O motivo inteiro, numa linha: a corrente de causas ("A <- B <- C") e as
# primeiras linhas de onde a ultima causa nasceu (v5, sonda de 23/set/2026:
# o NotFound sozinho nao dizia por que o XML do icone nao carrega).
.method static motivo(Ljava/lang/Throwable;)Ljava/lang/String;
    .registers 6
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    const/4 v1, 0x0
    const/4 v4, 0x0
    :volta
    if-eqz p0, :fim
    const/4 v2, 0x6
    if-ge v1, v2, :fim
    if-eqz v1, :sem_seta
    const-string v2, " <- "
    invoke-virtual {v0, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    :sem_seta
    invoke-virtual {p0}, Ljava/lang/Throwable;->toString()Ljava/lang/String;
    move-result-object v2
    invoke-virtual {v0, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    move-object v4, p0
    invoke-virtual {p0}, Ljava/lang/Throwable;->getCause()Ljava/lang/Throwable;
    move-result-object p0
    add-int/lit8 v1, v1, 0x1
    goto :volta
    :fim
    if-eqz v4, :pronto
    invoke-virtual {v4}, Ljava/lang/Throwable;->getStackTrace()[Ljava/lang/StackTraceElement;
    move-result-object v4
    array-length v3, v4
    const/4 v2, 0x6
    if-le v3, v2, :sem_corte
    move v3, v2
    :sem_corte
    const/4 v1, 0x0
    :frames
    if-ge v1, v3, :pronto
    const-string v2, " @ "
    invoke-virtual {v0, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    aget-object v2, v4, v1
    invoke-virtual {v2}, Ljava/lang/Object;->toString()Ljava/lang/String;
    move-result-object v2
    invoke-virtual {v0, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    add-int/lit8 v1, v1, 0x1
    goto :frames
    :pronto
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v2
    const-string v3, "\n"
    const-string v1, " "
    invoke-virtual {v2, v3, v1}, Ljava/lang/String;->replace(Ljava/lang/CharSequence;Ljava/lang/CharSequence;)Ljava/lang/String;
    move-result-object v2
    return-object v2
.end method
