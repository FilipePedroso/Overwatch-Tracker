"""Reproduz um log de diagnóstico no detector, para calibrar sem jogar.

Uso:  python -m owtracker.reproduzir [dados/diagnostico.log] [NOME_DO_JOGADOR]
"""

import re
import sys
from datetime import datetime

from .detector import Detector
from .monitor import LOG_DIAGNOSTICO
from .ocr import Linha

RE_CABECALHO = re.compile(r"^(\S+ \S+) (\d+)x(\d+) .*? :: (.*)$")
RE_ITEM = re.compile(r"(.*?) \[(?:x=(\d+) )?y=(\d+) h=(\d+)\](?: \| |$)")


def ler_log(caminho):
    """Gera (segundos, largura, altura, linhas, tela_inteira) para cada leitura do log."""
    inicio = None
    for texto in open(caminho, encoding="utf-8"):
        m = RE_CABECALHO.match(texto.rstrip("\n"))
        if not m:
            continue
        quando = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        inicio = inicio or quando
        largura, altura = int(m.group(2)), int(m.group(3))
        linhas = [Linha(t, float(x or 0), float(y), 0.0, float(h))
                  for t, x, y, h in RE_ITEM.findall(m.group(4))]
        tela_inteira = "legendas" not in texto.split(" :: ")[0]
        yield (quando - inicio).total_seconds(), largura, altura, linhas, tela_inteira


def main():
    caminho = sys.argv[1] if len(sys.argv) > 1 else LOG_DIAGNOSTICO
    detector = Detector(sys.argv[2] if len(sys.argv) > 2 else "")
    for segundos, largura, altura, linhas, inteira in ler_log(caminho):
        registro, _ = detector.processar(linhas, largura, altura, segundos, inteira)
        if registro:
            print(f"[{segundos / 60:5.1f} min] {registro}")
        nome = detector.aprender_nome()
        if nome:
            print(f"[{segundos / 60:5.1f} min] nome do jogador aprendido: {nome}")
    print("partida em andamento no fim do log:", detector.resumo() or "(nada)")


if __name__ == "__main__":
    main()
