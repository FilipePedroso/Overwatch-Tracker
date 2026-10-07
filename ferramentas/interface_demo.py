"""Abre a interface com uma CÓPIA do banco e sem o monitor do jogo, para
desenvolver/testar a tela sem mexer nos seus dados.

Uso:  python ferramentas/interface_demo.py [porta] [--pendente]
Simula uma partida em andamento (e, com --pendente, uma partida sem resultado).
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from owtracker import banco, servico  # noqa: E402
from owtracker.servidor import criar_servidor  # noqa: E402


def main():
    porta = int(next((a for a in sys.argv[1:] if a.isdigit()), 47816))
    copia = Path(tempfile.mkdtemp()) / "partidas.db"
    if banco.ARQUIVO_BANCO.exists():
        shutil.copy(banco.ARQUIVO_BANCO, copia)
    servico.Banco = lambda: banco.Banco(copia)

    s = servico.Servico()  # o monitor é criado, mas não iniciado
    s.status_monitor = "Automático: lendo o jogo em 1920×1080 (DXGI) · partida: Domina · Junção Neon"
    s.parcial = {"heroi": "Domina", "mapa": "Junção Neon", "modo": "Partida Rápida",
                 "placar": {"eliminacoes": 9, "assistencias": 4, "mortes": 3, "dano": 7412,
                            "cura": 1105, "mitigado": 6890}}
    if "--pendente" in sys.argv:
        s.pendente = {"heroi": "Ana", "mapa": "Busan", "modo": "Competitivo", "placar": {}, "observacao": ""}
    print(f"demo em http://127.0.0.1:{porta}/  (banco: cópia em {copia})")
    criar_servidor(s, porta).serve_forever()


if __name__ == "__main__":
    main()
