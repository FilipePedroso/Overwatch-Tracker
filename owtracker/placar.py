"""Leitura do placar (tela do Tab): E, A, M, Dano, Cura e Mitigado da sua linha.

O que sabemos da tela (medido em 1920x1080, guardado em proporções):
- Os cabeçalhos "DAN" e "MIT" o OCR lê bem; eles dão a escala e a posição
  das colunas, então funciona em qualquer resolução.
- As 5 linhas do seu time ficam sempre na mesma distância abaixo do "DAN".
- A sua linha é achada pela COR do fundo (ver linha_do_jogador).
- O fundo claro da sua linha atrapalha o OCR, então ela ganha uma leitura
  extra só dela, ampliada (ver monitor.ler_faixa).
"""

import re

COLUNAS = ("eliminacoes", "assistencias", "mortes", "dano", "cura", "mitigado")
# Borda esquerda de cada coluna, a partir do "DAN", em unidades da distância DAN -> MIT.
POSICOES = (-0.925, -0.652, -0.374, -0.032, 0.481, 0.973)
TOLERANCIA_COLUNA = 0.13
PRIMEIRA_LINHA = 0.050     # centro da 1ª linha abaixo do "DAN" (fração da altura da tela)
ENTRE_LINHAS = 0.0611      # distância entre linhas (fração da altura da tela)
ALTURA_LINHA = 0.040
ACIMA_DOS_NUMEROS = 0.019  # onde medir o fundo da linha: acima dos números (sem texto)
DESTAQUE_MINIMO = 25       # quanto a sua linha precisa ser mais clara que as outras

RE_NUMERO = re.compile(r"^[\d.,oOlI ]+$")


def numero(texto):
    """'11.029' -> 11029; '1 1.247' -> 11247; 'o' -> 0. Outra coisa -> None."""
    texto = texto.strip()
    if not texto or not RE_NUMERO.match(texto):
        return None
    limpo = texto.translate(str.maketrans("oOlI", "0011", ".,  "))
    return int(limpo) if limpo.isdigit() else None


def _cabecalho(linhas, nome):
    return next((l for l in linhas if l.texto.strip().upper() == nome), None)


class Geometria:
    """Onde ficam as colunas e as linhas do seu time nesta tela."""

    def __init__(self, dan, mit, altura):
        self.passo = mit.x - dan.x
        self.ancoras = [dan.x + p * self.passo for p in POSICOES]
        self.linhas_y = [dan.y + (PRIMEIRA_LINHA + i * ENTRE_LINHAS) * altura for i in range(5)]
        self.altura_linha = ALTURA_LINHA * altura

    def coluna(self, x):
        distancias = [abs(x - a) for a in self.ancoras]
        indice = min(range(len(distancias)), key=distancias.__getitem__)
        return COLUNAS[indice] if distancias[indice] <= TOLERANCIA_COLUNA * self.passo else None

    def faixa_da_linha(self, y):
        """Retângulo (x, y, largura, altura) com os números de uma linha."""
        x0 = self.ancoras[0] - 0.15 * self.passo
        x1 = self.ancoras[-1] + 0.30 * self.passo
        return int(x0), int(y - self.altura_linha / 2), int(x1 - x0), int(self.altura_linha)


def tela_do_placar(linhas, altura):
    """Geometria se a tela é o placar (Tab), senão None."""
    dan, mit = _cabecalho(linhas, "DAN"), _cabecalho(linhas, "MIT")
    if not dan or not mit or mit.x <= dan.x:
        return None
    return Geometria(dan, mit, altura)


def valores_da_linha(linhas, geometria, y_centro):
    valores = {}
    for linha in linhas:
        valor = numero(linha.texto)
        if valor is None or abs(linha.y + linha.altura / 2 - y_centro) > geometria.altura_linha / 2:
            continue
        coluna = geometria.coluna(linha.x)
        if coluna:
            valores.setdefault(coluna, valor)
    return valores


def linha_do_jogador(geometria, altura, tela):
    """Centro (y) da sua linha no placar, pelo tom do fundo.

    Medido em 47 Tabs: linha comum ~108 (verde), a sua ~171, e a linha sob o
    MOUSE fica ainda mais clara (~224). Então: uma linha clara = a sua (mesmo
    com o mouse em cima dela); duas = a sua é a menos clara."""
    tons = [(tela.fundo(geometria.ancoras[0], geometria.ancoras[-1], y - ACIMA_DOS_NUMEROS * altura), y)
            for y in geometria.linhas_y]
    comum = sorted(t for t, _ in tons)[len(tons) // 2]
    claras = sorted((t, y) for t, y in tons if t - comum >= DESTAQUE_MINIMO)
    if len(claras) in (1, 2):
        return claras[0][1]
    return None


def ler_placar(linhas, largura, altura, tela=None):
    """Retorna dict com as colunas da SUA linha, ou None se não der.

    tela: acesso à imagem (ver monitor.Tela), com
      fundo(x0, x1, y)        tom típico (mediana do verde) de um trecho horizontal;
      ler_faixa(x, y, l, a)   OCR extra, ampliado, de um retângulo;
      numeros(x, y, l, a)     números separados pelo reconhecedor próprio;
      reconhecedor            digitos.Reconhecedor (lê o que o OCR pula).
    Sem a imagem não dá para saber qual é a sua linha.
    """
    geometria = tela_do_placar(linhas, altura)
    if geometria is None or tela is None:
        return None

    y_jogador = linha_do_jogador(geometria, altura, tela)
    if y_jogador is None:
        return None  # não deu para saber qual é a sua linha: melhor não chutar
    faixa = geometria.faixa_da_linha(y_jogador)

    valores = valores_da_linha(tela.ler_faixa(*faixa), geometria, y_jogador)
    for coluna, valor in valores_da_linha(linhas, geometria, y_jogador).items():
        valores.setdefault(coluna, valor)

    # O OCR pula dígitos sozinhos (o "1"). O reconhecedor próprio aprende com
    # as colunas que o OCR leu e completa as que faltaram.
    colunas_brancas = set()
    for numero in tela.numeros(*faixa):
        coluna = geometria.coluna(numero.x)
        if coluna is None:
            continue
        colunas_brancas.add(coluna)
        if coluna in valores and len(str(valores[coluna])) != len(numero.glifos):
            # O OCR leu mais/menos dígitos do que há na célula (ex.: "16" -> "116"):
            # vale a contagem de dígitos do reconhecedor, se ele souber ler.
            valor = tela.reconhecedor.ler(numero)
            if valor is not None:
                valores[coluna] = valor
        elif coluna in valores:
            tela.reconhecedor.aprender(numero, valores[coluna])
        else:
            valor = tela.reconhecedor.ler(numero)
            if valor is not None:
                valores[coluna] = valor

    # O jogo mostra o zero em cinza: coluna sem texto branco e com um único
    # dígito cinza é 0.
    for numero in tela.numeros(*faixa, apagados=True):
        coluna = geometria.coluna(numero.x)
        if coluna and coluna not in valores and coluna not in colunas_brancas \
                and len(numero.glifos) == 1:
            valores[coluna] = 0
    return valores or None
