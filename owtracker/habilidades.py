"""Quais habilidades de cada herói dá para contar pelas teclas, e com que recarga.

Revisão feita sobre os dados da wiki (ver ferramentas/revisar_habilidades.py):
- supremas vêm quase todas sem tecla: são sempre o Q;
- o botão direito às vezes é arma (tiro, sem recarga: Lifeweaver, Sojourn,
  Zenyatta...) e às vezes é habilidade (Roadhog, Juno, Doomfist...): só conta
  se tiver recarga;
- recarga curta demais (< 2 s: Anjo da Guarda, Rolagem, Matriz da D.Va) não dá
  para separar de apertos repetidos: não conta;
- barreiras de segurar (Reinhardt, Brigitte, D.Mon) só têm recarga quando são
  destruídas: levantar e abaixar não é "uso", não conta;
- teclas que o jogo também usa para outra coisa (pular, agachar, clique
  esquerdo) contariam cada pulo/tiro: não conta;
- sem recarga (Transição do Lúcio, Disparada do Soldado, orbes do Zenyatta):
  não dá para saber quando foi um uso de verdade: não conta;
- a recarga vem em formatos como "5 seconds;;destroyed" ou "8 seconds (base);
  6 seconds (...)": vale o primeiro número (a recarga base).
"""

import re
from functools import lru_cache

from . import catalogo

# Teclas padrão do Overwatch (códigos de tecla virtual do Windows).
VK = {"shift": 0x10, "e": 0x45, "q": 0x51, "botao_direito": 0x02, "r": 0x52}
TECLA_DO_SLOT = {  # slot da wiki -> tecla
    "ability 1": "shift", "ability 2": "e", "ultimate": "q",
    "secondary fire": "botao_direito", "reload": "r",
}
NOME_DA_TECLA = {"shift": "Shift", "e": "E", "q": "Q", "botao_direito": "Botão direito", "r": "R"}
RECARGA_MINIMA = 2.0  # s
# "5 seconds;;destroyed" / "5 seconds (destroyed)": barreira que se segura (Reinhardt,
# Brigitte, D.Mon); a recarga só existe quando ela quebra.
SO_QUANDO_DESTRUIDA = re.compile(r"^\s*\d+(?:\.\d+)?\s*seconds?\s*(?:;;|\()\s*destroyed", re.I)

# Correções dos dados da wiki (herói -> habilidades a acrescentar/ajustar).
CORRECOES = {
    # A Forma Nêmesis (Shift) não veio da wiki; a suprema veio como "ability 3".
    "ramattra": [{"id": "nemesis-form", "nome": "Forma Nêmesis", "tipo": "habilidade",
                  "slot": "ability 1", "recarga": 8.0}],
}


def recarga_em_segundos(texto):
    """'5 seconds;;destroyed' -> 5.0; '8 seconds (base); 6 seconds' -> 8.0; None -> None."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*seconds?", texto or "")
    return float(m.group(1)) if m else None


@lru_cache(maxsize=None)
def rastreaveis(heroi_id):
    """Habilidades contáveis do herói: [{id, nome, tipo, tecla, recarga}]."""
    heroi = next((h for h in catalogo.carregar()["herois"] if h["id"] == heroi_id), None)
    if not heroi:
        return []
    lista, usadas = [], set()
    for a in heroi["habilidades"] + CORRECOES.get(heroi_id, []):
        tipo = a.get("tipo")
        slot = (a.get("slot") or a.get("tecla") or "").lower()
        recarga = a["recarga"] if isinstance(a.get("recarga"), float) else recarga_em_segundos(a.get("recarga"))
        if tipo == "suprema":
            slot, recarga = "ultimate", None
        elif tipo not in ("habilidade", "arma") or slot not in TECLA_DO_SLOT:
            continue  # passivas, vantagens, clique esquerdo, pulo, agachar...
        elif recarga is None or recarga < RECARGA_MINIMA:
            continue  # tiro sem recarga ou recarga curta demais para contar
        elif SO_QUANDO_DESTRUIDA.match(str(a.get("recarga") or "")):
            continue  # barreira de segurar: só tem recarga quando é destruída
        tecla = TECLA_DO_SLOT[slot]
        if tecla in usadas:
            continue  # duas na mesma tecla (formas/mecha): fica a primeira
        usadas.add(tecla)
        lista.append({"id": a["id"], "nome": (a.get("nome") or a.get("nome_en")).strip(),
                      "tipo": tipo, "tecla": tecla, "recarga": recarga})
    return lista
