# scrcpy-f

Programa de bandeja para Windows que usa o
[scrcpy](https://github.com/Genymobile/scrcpy) para usar o celular Android
junto do PC — espelhar, ouvir, estender a tela e abrir cada app do celular
numa janela própria do Windows.

## Baixar e começar

1. Baixe o `scrcpy-f-<versão>.zip` em **Releases** (nesta página, à direita),
   extraia onde quiser e dê dois cliques em **`scrcpy-f.exe`**. Não precisa
   instalar nada.
2. Na primeira vez a janela abre em **Opções**: clique em **instalar** e o
   programa baixa o scrcpy mais novo sozinho (o Windows pede permissão de
   administrador). Já tem o scrcpy? Use **usar outra pasta**. Até o scrcpy
   existir, só **Opções › geral** fica liberada.
3. No celular, ligue a **Depuração sem fio** (Opções do desenvolvedor), deixe
   na mesma rede Wi-Fi do PC (ou a **Depuração USB**, com o cabo). Ele
   aparece em **Parear › conexão**: já pareado, entra sozinho; novo, aparece
   com **conectar** — pelo cabo basta aceitar o aviso no celular; sem fio, o
   programa abre a tela do código e preenche o endereço sozinho quando você
   abre "parear com código" no celular.

O programa fica na bandeja, ao lado do relógio. Clique no ícone para abrir a
janela; botão direito para o menu.

**Requisitos:** Windows 10 (1803 ou mais novo) ou 11, 64 bits. Android 5 ou
mais novo para espelhar; o **som no PC pede Android 11**, e os **apps em
janela própria, Android 10**. O programa confere o que cada celular aceita e avisa quando um
recurso não existe na versão dele, em vez de quebrar.

## O que ele faz

| Item | Para que serve |
|---|---|
| **Espelhar** (Ctrl+Alt+1) | a tela e/ou o som do celular no PC, com vídeo ajustado para a menor latência. No modo **só som** você joga no celular e ouve no PC |
| **Extensão** (Ctrl+Alt+2) | o celular vira uma tela a mais do PC: o mouse e o teclado passam para ele pela borda (veja abaixo) |
| **Apps** | cada app do celular numa janela própria do Windows, com o ícone e o nome do app e um botão separado na barra de tarefas. O celular continua livre na sua mão |
| **Status** | bateria, temperatura, memória e o que mais pesa no celular |
| **Notificações** | as notificações do celular no PC, como no celular: **×** remove lá também, e o que você tira no celular some aqui. Um aviso no canto da tela quando chega uma (clique abre o app numa janela do PC; respeita o "não perturbe" do Windows). **histórico** das últimas 24 horas. Em **ajustes**, uma chave geral (todos os apps) e uma por app; o botão direito num app, em Apps, também liga ou desliga. Mostra quais apps estão com as notificações desligadas no próprio celular. Nada disso muda o celular. **No Windows:** as notificações também ficam na Central de Notificações (clique abre no scrcpy-f) e a música que toca no celular aparece nos controles de mídia do Windows, com as teclas de música do teclado. O **player** fica no topo da aba, com barra de progresso e botões; botão direito numa notificação traz as opções do Android (configurações, desativar...); código de verificação ganha "copiar código". **Responder pelo PC** (sem instalar nada no celular): os botões do próprio app (Responder, Marcar como lida, Curtir...) no cartão aberto, no aviso do canto e na Central do Windows; clicar na notificação abre o item exato (a conversa, o e-mail) na janela do app; foto de quem mandou e imagem da notificação. **Mini player**: o player do celular numa janelinha junto do relógio (menu do ícone ou atalho) |
| **Parear** | **conexão**: o celular em uso, os outros por perto — inclusive os ainda não conectados, com **conectar** — e a conexão preferida — **sem fio** ou **cabo** (trocar não derruba nada: o que está aberto segue como está, o que abrir depois usa a nova; preferindo o cabo, funciona mesmo sem Wi-Fi). Preferindo o sem fio, **ligar o cabo abre o sem fio sozinho** (depois é só tirar o cabo). **adicionar**: parear à mão, com cabo ou com código. O quadradinho fica verde com o celular conectado, em tempo real |
| **Opções** | avisos do programa, abrir com o Windows, página inicial, pasta do scrcpy e atualizações; atalhos de teclado (com busca); **rodapé** com indicadores de conexão e som (cada gesto pode ganhar uma função). **Qualidade**, igual no cabo e no sem fio: **imagem** 540p / 720p / 1080p (4 / 8 / 16 Mb/s, 60 quadros, sem atraso), **som** normal ou alto, **janela dos apps** (pc / tablet ou celular) e **tamanho nos apps** (90% a 130%). Espelhar, Extensão e cada app podem ter a sua. No sem fio, o codificador do celular trabalha em tempo real e o Wi-Fi do celular entra no modo de baixa latência enquanto houver sessão (volta ao normal sozinho) |

Tudo é gravado no instante do clique, sem botão de salvar.

### Apps em janela própria

- **Clique** abre o app (ou traz a janela dele para a frente); **botão
  direito** abre em tela cheia, fixa na lista, cria o atalho e leva às
  **configurações personalizadas** daquele app: imagem, som, **janela**
  (pc / tablet — a tela de tablet do app, como num monitor — ou celular),
  **tamanho** (90% a 130%), onde o som toca, ao fechar, sempre em tela cheia
  e correções para apps que não se dão bem com mouse e teclado.
- **Modo pc / tablet automático**: ao conectar, o programa lê de cada app se
  ele tem tela de tablet (nada é baixado) e indica o melhor modo; jogos abrem
  deitados em 16:9.
- **Busca** na lista (e nos atalhos e nas notificações): os apps que saem
  somem esmaecendo e os outros deslizam até o lugar; agiu num resultado, a
  busca se apaga.
- **Apps duplicados** (Dual Messenger do Samsung, "apps duplos" do Xiaomi,
  perfil de trabalho...) aparecem duas vezes — "WhatsApp" e "WhatsApp (2)",
  com um número no ícone — e cada um abre na sua janela, com ajustes e
  atalho próprios. A Pasta Segura do Samsung fica de fora.
- **Atalho na área de trabalho** de cada app: dois cliques abrem o app direto,
  mesmo com o scrcpy-f fechado (e avisa se o celular não estiver conectado).
- **Samsung DeX** aparece no topo da lista em celulares Samsung: a área de
  trabalho do DeX numa janela do PC.
- A tela do celular pode ficar apagada enquanto os apps rodam no PC; o botão
  de ligar do celular acende e apaga a tela sem pausar os apps.

### Extensão: o celular ao lado do PC

1. Na aba **Extensão**, arraste o desenho do celular para o lado da tela onde
   ele fica de verdade.
2. Ligue a extensão e leve o mouse até aquela borda: o ponteiro passa para o
   celular. Mouse, teclado e controle de videogame mandam nele, e o som dele
   sai no PC.
3. Para voltar: leve o cursor até a borda do lado do PC e **continue
   empurrando**, ou aperte **Tab duas vezes rápido**.

Com o mouse no celular, **Ctrl+Alt+=** / **Ctrl+Alt+-** mudam o volume dele
(**Ctrl+Alt+0** deixa mudo). A extensão não entra com um jogo em tela cheia
na frente. Ctrl+Alt+Del e Windows+L continuam sendo do PC.

### Atualizações

Em **Opções › geral**, a tabela **atualizações** mostra a versão do
**scrcpy-f** e do **scrcpy** e se cada um está em dia. **Procurar agora**
confere na hora; em **procurar sozinho** você escolhe diário, semanal,
mensal ou nunca. Versão nova aparece em laranja — clique nela para
atualizar. Quando
sai uma, o programa pergunta antes; com o sim, baixa, confere o arquivo e
troca (pedindo permissão de administrador). Seus ajustes, apps e atalhos
ficam como estão. A internet só é usada para isso, e só no GitHub.

## A janela

`–` minimiza; `X` com **clique** esconde a janela (o programa continua na
bandeja) e **segurado 1 s** fecha o programa. `Esc` volta um passo. Pelo
teclado: `Tab` anda entre os controles, as setas escolhem dentro de uma
fileira, `Enter` ou `Espaço` acionam. A janela se adapta à tela e à escala do
Windows.

## Se algo der errado

- Celular não encontrado: o programa diz o que conferir. Se nada resolver,
  plugue o cabo USB e use **Parear › adicionar › com cabo**.
- O que o programa fez fica registrado em `_internal\relatorios\` (no
  pacote). Ao relatar um problema, esses arquivos ajudam.

## Compilando do código-fonte

1. Clone este repositório e instale o Python 3.10 ou mais novo.
2. `pip install -r publicacao\requirements.txt` — e dois cliques em
   **`scrcpy-f.bat`** já rodam pelo código.
3. Dois cliques em **`publicar.bat`**: ele instala o PyInstaller se faltar e
   monta `dist\scrcpy-f-<versão>.zip`, o mesmo pacote das Releases.

Uma versão nova publicada em Releases precisa da tag `v<versão>` e do arquivo
`scrcpy-f-<versão>.zip` — é o que o atualizador procura.

## Licença

GPLv3 — veja `LICENSE`. O scrcpy é da Genymobile (Apache 2.0) e não vem
junto; os demais componentes estão em `docs\THIRD-PARTY-NOTICES.txt`.
