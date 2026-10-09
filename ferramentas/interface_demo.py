"""Abre a interface com uma CÓPIA do banco e sem o monitor do jogo, para
desenvolver/testar a tela sem mexer nos seus dados.

Uso:  python ferramentas/interface_demo.py [porta] [--pendente] [--tab print.png]
Simula uma partida em andamento (e, com --pendente, uma partida sem resultado).
--tab registra uma partida de teste lida de um print do Tab (os dois times).
O banco e a biblioteca de retratos usados são cópias temporárias.
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from owtracker import banco, retratos, servico  # noqa: E402
from owtracker.servidor import criar_servidor  # noqa: E402


def partida_de_teste(s, print_do_tab):
    """Registra na cópia do banco uma partida montada pelo detector de verdade
    a partir de um print do Tab salvo pelo diagnóstico (capturas/diagnostico)."""
    from owtracker.imagem import ler_png
    from owtracker.monitor import Tela
    from owtracker.ocr import OCR, Linha

    if not Path(print_do_tab).exists():
        print("print do Tab não encontrado (o diagnóstico guarda só os 300 mais recentes):", print_do_tab)
        return
    largura, altura, rgba = ler_png(print_do_tab)
    bgra = bytearray(len(rgba))
    bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = rgba[2::4], rgba[1::4], rgba[0::4], rgba[3::4]
    bgra = bytes(bgra)
    ocr, detector = OCR(), s.monitor.detector
    def fala(texto, t):
        detector.processar([Linha(texto, 800, 1030, 300, 18)], largura, altura, t, False)
    # começou de Ana, trocou para Sombra (uma leitura errada de Genji no meio some)
    fala("[FILIPE (ANA)] Eu estou aqui.", 1)
    fala("[FILIPE (ANA)] Ninguém escapa do meu olhar.", 40)
    fala("[FILIPE (GENJI)] Preciso de cura!", 120)
    fala("[FILIPE (SOMBRA)] Boop.", 150)
    fala("[FILIPE (SOMBRA)] Sistemas hackeados.", 160)
    # apertos de tecla simulados (o E repetido dentro da recarga conta uma vez só)
    detector.teclas([(t, q, False) for t, q in [("e", 163.2), ("e", 163.4), ("shift", 164.0), ("botao_direito", 165.0), ("e", 179.9)]])
    tela = Tela(ocr, bgra, largura, altura, s.monitor.reconhecedor)
    detector.processar(ocr.ler(bgra, largura, altura), largura, altura, 400, True, tela=tela)
    registro, _ = detector.processar([Linha("[ATHENA] Vitória.", 800, 1030, 300, 18)], largura, altura, 600, False)
    s._ao_registrar(registro)
    print("partida de teste:", registro.heroi, registro.mapa, registro.resultado,
          "| times:", "sim" if registro.times else "não")


def main():
    porta = int(next((a for a in sys.argv[1:] if a.isdigit()), 47816))
    temporaria = Path(tempfile.mkdtemp())
    copia = temporaria / "partidas.db"
    if banco.ARQUIVO_BANCO.exists():
        shutil.copy(banco.ARQUIVO_BANCO, copia)
    servico.Banco = lambda: banco.Banco(copia)
    # Correções feitas na demonstração não vão para a biblioteca de retratos real.
    if retratos.ARQUIVO_BIBLIOTECA.exists():
        shutil.copy(retratos.ARQUIVO_BIBLIOTECA, temporaria / "retratos.json")
    retratos.ARQUIVO_BIBLIOTECA = temporaria / "retratos.json"

    s = servico.Servico()  # o monitor é criado, mas não iniciado
    s.status_monitor = "Automático: lendo o jogo em 1920×1080 (DXGI) · partida: Domina · Junção Neon"
    s.parcial = {"heroi": "Domina", "mapa": "Junção Neon", "modo": "Partida Rápida",
                 "placar": {"eliminacoes": 9, "assistencias": 4, "mortes": 3, "dano": 7412,
                            "cura": 1105, "mitigado": 6890}}
    if "--pendente" in sys.argv:
        s.pendente = {"heroi": "Ana", "mapa": "Busan", "modo": "Competitivo", "placar": {}, "observacao": ""}
    if "--tab" in sys.argv:
        partida_de_teste(s, sys.argv[sys.argv.index("--tab") + 1])
    print(f"demo em http://127.0.0.1:{porta}/  (banco: cópia em {copia})")
    criar_servidor(s, porta).serve_forever()


if __name__ == "__main__":
    main()
