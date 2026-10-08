"""Recupera os dois times de uma partida a partir de um print do Tab salvo
pelo modo diagnóstico (capturas/diagnostico/*_placar.png).

Útil quando a partida foi registrada sem os times (ex.: app aberto antes da
atualização). Usa o mesmo código do app: leitura do placar, retratos e
identificação dos heróis (que também ensina a biblioteca de retratos).

Uso:  python ferramentas/recuperar_times.py <id da partida> <print do Tab>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from owtracker import catalogo, digitos, retratos  # noqa: E402
from owtracker.banco import Banco  # noqa: E402
from owtracker.imagem import ler_png  # noqa: E402
from owtracker.monitor import ARQUIVO_DIGITOS, Tela, carregar_config  # noqa: E402
from owtracker.ocr import OCR  # noqa: E402
from owtracker.placar import ler_times  # noqa: E402


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    id_partida, caminho = int(sys.argv[1]), sys.argv[2]
    banco = Banco()
    partida = banco.obter(id_partida)
    if not partida:
        sys.exit(f"Partida {id_partida} não existe.")

    largura, altura, rgba = ler_png(caminho)
    bgra = bytearray(len(rgba))
    bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = rgba[2::4], rgba[1::4], rgba[0::4], rgba[3::4]
    bgra = bytes(bgra)
    ocr = OCR()
    tela = Tela(ocr, bgra, largura, altura, digitos.carregar(ARQUIVO_DIGITOS))
    times = ler_times(ocr.ler(bgra, largura, altura), largura, altura, tela)
    if not times:
        sys.exit("Esse print não parece o placar completo (Tab).")

    biblioteca = retratos.Biblioteca()
    retratos.identificar(times, partida["heroi"], biblioteca, nome_jogador=carregar_config()["nome_jogador"])
    banco.salvar_jogadores(id_partida, times)
    biblioteca.salvar()

    print(f"Partida {id_partida}: {partida['heroi']} em {partida['mapa']} ({partida['resultado']})")
    for time in ("aliados", "inimigos"):
        for j in times[time]:
            heroi = catalogo.heroi(j["heroi_id"]) if j.get("heroi_id") else None
            v = j["valores"]
            print(f"  {time:8} {j['posicao'] + 1} {'(você)' if j['voce'] else '      '} "
                  f"{(heroi['nome'] if heroi else '?'):14} [{j.get('fonte') or '-':9}] "
                  f"E/A/M {v.get('eliminacoes', '?')}/{v.get('assistencias', '?')}/{v.get('mortes', '?')} "
                  f"dano {v.get('dano', '?')} cura {v.get('cura', '?')} mit {v.get('mitigado', '?')} "
                  f"| vantagens: {', '.join(e['nome'] for e in j.get('escolhidas', [])) or '—'}")


if __name__ == "__main__":
    main()
