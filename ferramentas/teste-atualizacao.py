"""
Bancada da atualizacao do PROPRIO scrcpy-f (r168), sem publicar nada no
GitHub. Precisa do pacote pronto (publicar.bat -> dist\\scrcpy-f).

1. Copia dist\\scrcpy-f para dist\\teste-atualizacao\\scrcpy-f (o seu
   config.json vai junto, para conferir que ele sobrevive).
2. Monta um zip "versao 9.9.9" com o mesmo pacote + MARCA-VERSAO-NOVA.txt
   e um "release" falso (arquivo .json) apontando para ele.
3. Abre a COPIA com SCRCPYF_TESTE_API apontando para o release falso.

Na copia: Opcoes > procurar agora -> "Saiu o scrcpy-f 9.9.9" -> Sim ->
administrador -> fecha e abre sozinho -> aviso "scrcpy-f atualizado".
Resultado em relatorios\\teste-atualizacao.txt (este script) e no
relatorios\\atualizar.txt de dentro da copia.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PACOTE = RAIZ / "dist" / "scrcpy-f"
TESTE = RAIZ / "dist" / "teste-atualizacao"
RELATORIO = RAIZ / "relatorios" / "teste-atualizacao.txt"


def anotar(texto):
    linha = "%s  %s" % (time.strftime("%d/%m/%Y %H:%M:%S"), texto)
    print(linha)
    RELATORIO.parent.mkdir(exist_ok=True)
    with open(RELATORIO, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def main():
    with open(RELATORIO, "w", encoding="utf-8") as f:
        f.write("=== ABERTURA %s ===\n" % time.strftime("%d/%m/%Y %H:%M:%S"))
    if not (PACOTE / "scrcpy-f.exe").exists():
        anotar("FALTA o pacote: rode o publicar.bat primeiro")
        return 1
    if TESTE.exists():
        shutil.rmtree(TESTE)
    copia = TESTE / "scrcpy-f"
    shutil.copytree(PACOTE, copia)
    if (RAIZ / "config.json").exists():
        shutil.copy2(RAIZ / "config.json", copia / "config.json")
    anotar("copia pronta: %s" % copia)

    # (r182) O ZIP DE VERDADE do publicar.bat (o mesmo que vai pro GitHub),
    # so com a marca acrescentada: assim o teste pega problema do formato
    # do zip (antes o zip era refeito aqui e escondia isso).
    zips = sorted(PACOTE.parent.glob("scrcpy-f-*.zip"),
                  key=lambda p: p.stat().st_mtime)
    if not zips:
        anotar("FALTA o zip: rode o publicar.bat primeiro")
        return 1
    zip_ = TESTE / "scrcpy-f-9.9.9.zip"
    shutil.copy2(zips[-1], zip_)
    with zipfile.ZipFile(zip_, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("scrcpy-f/MARCA-VERSAO-NOVA.txt",
                   "veio do zip de teste 9.9.9\n")
    anotar("zip usado: %s" % zips[-1].name)
    soma = hashlib.sha256(zip_.read_bytes()).hexdigest()
    release = {"tag_name": "v9.9.9", "assets": [{
        "name": zip_.name, "size": zip_.stat().st_size,
        "digest": "sha256:" + soma,
        "browser_download_url": zip_.resolve().as_uri()}]}
    api = TESTE / "release.json"
    api.write_text(json.dumps(release), encoding="utf-8")
    anotar("zip falso: %d bytes, sha %s" % (zip_.stat().st_size, soma[:12]))

    ambiente = dict(os.environ, SCRCPYF_TESTE_API=api.resolve().as_uri())
    subprocess.Popen([str(copia / "scrcpy-f.exe")], cwd=str(copia),
                     env=ambiente)
    anotar("copia aberta com o release falso")
    with open(RELATORIO, "a", encoding="utf-8") as f:
        f.write("=== FECHAMENTO %s ===\n" % time.strftime("%d/%m/%Y %H:%M:%S"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        anotar("ERRO: %s" % erro)
        sys.exit(1)
