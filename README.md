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
   na mesma rede Wi-Fi do PC e conecte em **Parear** — procurando, pelo cabo
   USB ou com código.

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
| **Parear** | conectar o celular. O quadradinho fica verde com ele conectado — em tempo real: desligou a depuração ou saiu da rede, o programa percebe |
| **Opções** | notificações, abrir com o Windows, página inicial, pasta do scrcpy e atualizações; atalhos de teclado; qualidade de imagem e som (predefinições **leve**, **equilibrado** e **celular**, e até 3 suas; resolução em 480p/720p/1080p/1440p ou a do celular) |

Tudo é gravado no instante do clique, sem botão de salvar.

### Apps em janela própria

- **Clique** abre o app (ou traz a janela dele para a frente); **botão
  direito** abre em tela cheia, cria o atalho e leva às **configurações
  personalizadas** daquele app, separadas em **vídeo**, **áudio** e
  **outros**:
  - **formato** da janela: celular (em pé, como no aparelho), 4:3, 16:9 ou
    21:9 — jogo costuma pedir 16:9;
  - **resolução**: a do celular ou de 480p a 2160p — só aparecem as que o
    celular consegue transmitir naquele formato;
  - qualidade de imagem e som, onde o som toca, teclado do celular e fechar
    o app no celular quando a janela fecha.
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

Em **Opções**, escolha de quanto em quanto tempo procurar versão nova (todo
dia, semana, mês ou nunca) — do **scrcpy** e do próprio **scrcpy-f** — ou
clique em **procurar atualização** para ver na hora. Quando
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
  plugue o cabo USB e use **Parear > pelo cabo**.
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
