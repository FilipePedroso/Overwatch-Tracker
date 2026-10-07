"""Listas usadas pela interface e pelo detector.

Heróis e mapas vêm do catálogo de referência (owtracker/referencia/*.json,
atualizado com ferramentas/coletar_referencia.py). Os campos da interface
também aceitam texto livre, então nada quebra se algo estiver faltando.
"""

from . import catalogo

MODOS = ["Competitivo", "Partida Rápida", "Arcade", "Personalizada"]

RESULTADOS = ["Vitória", "Derrota", "Empate"]

NAO_DETECTADO = "Não detectado"

# Outros nomes que podem aparecer na tela (jogo em pt-BR ou inglês).
# Acentos, maiúsculas e pontuação são ignorados na comparação.
APELIDOS_MAPAS = catalogo.apelidos_mapas()
APELIDOS_HEROIS = catalogo.apelidos_herois()

PALAVRAS_RESULTADO = {
    "Vitória": ["Vitória", "Victory"],
    "Derrota": ["Derrota", "Defeat"],
    "Empate": ["Empate", "Draw"],
}

PALAVRAS_MODO = {
    "Competitivo": ["Competitivo", "Competitiva", "Competitive"],
    "Partida Rápida": ["Partida Rápida", "Quick Play"],
    "Arcade": ["Arcade", "Fliperama"],
    "Personalizada": ["Partida Personalizada", "Custom Game"],
}


def lista_herois():
    return sorted(h["nome"] for h in catalogo.carregar()["herois"])


def lista_mapas():
    return sorted(m["nome"] for m in catalogo.carregar()["mapas"])
