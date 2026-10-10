"""Preenche as estatísticas do herói (painel do Tab) de partidas já gravadas,
a partir dos prints do Tab que o modo diagnóstico guardou
(capturas/diagnostico/*_placar.png; só os 300 mais recentes ficam).

Uso:  python ferramentas/recuperar_estatisticas.py [--gravar]

Sem --gravar só mostra o que encontrou. Cada print vale para a partida que
terminou logo depois dele (ou até 90 s antes: o Tab aberto depois do fim).
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from owtracker import banco, digitos  # noqa: E402
from owtracker.detector import Detector  # noqa: E402
from owtracker.imagem import ler_png  # noqa: E402
from owtracker.monitor import ARQUIVO_DIGITOS, PASTA_DIAGNOSTICO, Tela  # noqa: E402
from owtracker.ocr import OCR  # noqa: E402

DEPOIS_DO_FIM = timedelta(seconds=90)


def main():
    gravar = "--gravar" in sys.argv
    b = banco.Banco()
    detector = Detector()
    detector.estatisticas_conhecidas = {h: {e["chave"]: e["tipo"] for e in lista}
                                        for h, lista in b.definicoes_estatisticas().items()}
    ocr, reconhecedor = OCR(), digitos.carregar(ARQUIVO_DIGITOS)
    prints = sorted((datetime.strptime(f.name[:19], "%Y-%m-%d_%H-%M-%S"), f)
                    for f in PASTA_DIAGNOSTICO.glob("*_placar.png"))
    partidas = [dict(p) for p in b.con.execute("SELECT id, data_hora, heroi, heroi_id, mapa FROM partidas ORDER BY data_hora")]
    ja_tem = b.partidas_com_estatisticas()
    anterior = datetime.min
    for p in partidas:
        fim = datetime.fromisoformat(p["data_hora"])
        dela = [f for quando, f in prints if anterior + DEPOIS_DO_FIM < quando <= fim + DEPOIS_DO_FIM]
        anterior = fim
        if not dela or p["id"] in ja_tem:
            continue
        guardadas = {}
        for arquivo in dela:
            largura, altura, rgba = ler_png(arquivo)
            bgra = bytearray(len(rgba))
            bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = rgba[2::4], rgba[1::4], rgba[0::4], rgba[3::4]
            bgra = bytes(bgra)
            tela = Tela(ocr, bgra, largura, altura, reconhecedor)
            detector._painel(ocr.ler(bgra, largura, altura), largura, altura, tela, guardadas, p["heroi_id"])
        da_partida = {p["heroi_id"]} | {r[0] for r in b.con.execute(
            "SELECT heroi_id FROM herois_partida WHERE partida_id = ?", (p["id"],))}
        estatisticas = [e for e in detector._estatisticas_finais(guardadas) if e["heroi_id"] in da_partida]
        if not any(e["valor"] for e in estatisticas):
            continue  # nada, ou só zeros (Tab aberto no começo da partida)
        print(f"partida {p['id']} ({p['data_hora']}, {p['heroi']} em {p['mapa']}): {len(dela)} prints")
        for e in estatisticas:
            print(f"   {e['heroi_id']:<10} {e['rotulo']:<40} {e['valor']} ({e['tipo']})")
        if gravar:
            b.salvar_estatisticas(p["id"], estatisticas)
    print("gravado." if gravar else "nada foi gravado (use --gravar).")


if __name__ == "__main__":
    main()
