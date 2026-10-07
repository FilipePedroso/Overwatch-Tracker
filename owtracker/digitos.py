"""Reconhecedor de dígitos próprio para os números do placar.

Por que existe: o OCR do Windows não lê um dígito sozinho e estreito (o "1"
de "1 assistência" some). Os números do placar usam sempre a mesma fonte, então:

1. separamos cada dígito pelas colunas de pixels brancos;
2. o "1" é reconhecido pela forma (bem mais estreito que os outros);
3. os demais são comparados com modelos que o app APRENDE sozinho com os
   números que o OCR leu certo (ex.: o "3" de outra coluna da mesma tela).
"""

import json
from dataclasses import dataclass

LIMIAR_BRANCO = 180       # texto do placar é branco: os 3 canais altos
LIMIAR_APAGADO = 120      # o jogo mostra o zero em cinza claro (~170), abaixo do branco
GRADE = (6, 10)           # tamanho normalizado dos modelos (largura, altura)
PROPORCAO_DO_UM = 0.5     # largura/altura abaixo disso é "1"
MODELOS_POR_DIGITO = 8
DISTANCIA_MAXIMA = 0.18   # fração de pixels diferentes para aceitar um modelo


@dataclass
class Glifo:
    x: int
    largura: int
    altura: int
    pixels: list  # linhas de bool, recortadas no tamanho do glifo

    def normalizado(self):
        lg, ag = GRADE
        return tuple(
            int(self.pixels[min(self.altura - 1, j * self.altura // ag)]
                [min(self.largura - 1, i * self.largura // lg)])
            for j in range(ag) for i in range(lg))


@dataclass
class Numero:
    x: int          # borda esquerda, em coordenadas da tela
    glifos: list    # só os dígitos (pontos de milhar já descartados)


def segmentar(bgra, largura, x0, y0, l, a, limiar=LIMIAR_BRANCO):
    """Separa os números (grupos de dígitos) de um retângulo da tela."""
    branco = []
    for y in range(y0, y0 + a):
        inicio = (y * largura + x0) * 4
        linha = bgra[inicio:inicio + l * 4]
        branco.append([min(linha[i], linha[i + 1], linha[i + 2]) >= limiar
                       for i in range(0, l * 4, 4)])

    colunas = [any(branco[y][x] for y in range(a)) for x in range(l)] + [False]
    pedacos, inicio = [], None
    for x, tem in enumerate(colunas):
        if tem and inicio is None:
            inicio = x
        elif not tem and inicio is not None:
            pedacos.append((inicio, x))
            inicio = None

    glifos = []
    for x_ini, x_fim in pedacos:
        linhas = [y for y in range(a) if any(branco[y][x_ini:x_fim])]
        topo, base = linhas[0], linhas[-1] + 1
        pixels = [branco[y][x_ini:x_fim] for y in range(topo, base)]
        glifos.append(Glifo(x0 + x_ini, x_fim - x_ini, base - topo, pixels))
    if not glifos:
        return []

    altura_digito = max(g.altura for g in glifos)
    numeros, atual, fim_anterior = [], [], None
    for g in glifos:
        ponto = g.altura <= altura_digito * 0.4
        if fim_anterior is not None and g.x - fim_anterior > altura_digito * 0.8:
            numeros.append(atual)
            atual = []
        atual.append((g, ponto))
        fim_anterior = g.x + g.largura
    numeros.append(atual)
    return [Numero(grupo[0][0].x, [g for g, ponto in grupo if not ponto])
            for grupo in numeros if any(not ponto for _, ponto in grupo)]


class Reconhecedor:
    def __init__(self, modelos=None):
        self.modelos = {d: [tuple(m) for m in ms] for d, ms in (modelos or {}).items()}

    def exportar(self):
        return {d: [list(m) for m in ms] for d, ms in self.modelos.items()}

    def aprender(self, numero, valor):
        """Usa um número que o OCR leu (valor) para guardar modelos dos dígitos."""
        texto = str(valor)
        if len(texto) != len(numero.glifos):
            return  # separação e OCR não batem: não arrisca
        for digito, glifo in zip(texto, numero.glifos):
            modelos = self.modelos.setdefault(digito, [])
            forma = glifo.normalizado()
            if forma not in modelos:
                modelos.append(forma)
                del modelos[:-MODELOS_POR_DIGITO]

    def digito(self, glifo):
        if glifo.largura / glifo.altura < PROPORCAO_DO_UM:
            return "1"
        forma = glifo.normalizado()
        melhor, menor = None, DISTANCIA_MAXIMA * len(forma)
        for digito, modelos in self.modelos.items():
            if digito == "1":
                continue
            for modelo in modelos:
                diferenca = sum(a != b for a, b in zip(forma, modelo))
                if diferenca < menor:
                    melhor, menor = digito, diferenca
        return melhor

    def ler(self, numero):
        """Valor do número, ou None se algum dígito for desconhecido."""
        digitos = [self.digito(g) for g in numero.glifos]
        return int("".join(digitos)) if digitos and None not in digitos else None


def carregar(caminho):
    try:
        return Reconhecedor(json.loads(caminho.read_text("utf-8")))
    except (OSError, ValueError):
        return Reconhecedor()


def salvar(reconhecedor, caminho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(reconhecedor.exportar()), "utf-8")
