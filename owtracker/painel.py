"""Painel do herói no Tab (à direita do placar): estatísticas específicas do
herói que você está jogando.

    [retrato]   [ 8 JOGADORES SALVOS ]      <- destaque (tanques têm duas caixas)
    SOMBRA
    24%    PRECISÃO DA ARMA
    5.804  CURA COM AJUSTE
    10     KITS MÉDICOS HACKEADOS ...

Cada estatística é um valor em cima do rótulo. O painel muda de lugar na
horizontal conforme o placar, então a referência é o alinhamento dos próprios
rótulos. O OCR lê bem os rótulos e a maioria dos valores; dígito sozinho ele
pula, e aí entram o reconhecedor de dígitos próprio (digitos.py) e, na fonte
estilizada do destaque, o recorte repetido lado a lado ("8" -> "888").
"""

import re
import unicodedata
from collections import Counter

from .imagem import ampliar, recortar

# Em fração da tela (medido em 1920x1080). X é a borda esquerda dos rótulos.
BUSCA_X = (0.600, 0.870)
LISTA_Y = (0.385, 0.860)
MESMO_X = 0.006                                 # rótulos alinhados à esquerda
VALOR_ACIMA = (0.012, 0.036)                    # distância valor -> rótulo
ALTURA_VALOR = 0.022
NOME_HEROI = (-0.004, 0.335, 0.170, 0.055)      # x relativo a X, y, l, a
NOME_HEROI_ALTO = (-0.005, 0.324, 0.219, 0.074)  # recorte maior (nomes longos)
NOTA_NOME = 0.60                                # semelhança mínima do nome lido com o do herói
FOLGA_NOME = 0.12                               # ... e folga sobre o segundo herói mais parecido
DESTAQUE_ROTULO = (0.080, 0.185, 0.215, 0.320)  # x0/x1 relativos a X, y0, y1 (uma ou duas caixas)
DESTAQUE_VALOR = (0.091, -0.052, 0.099, 0.048)  # número: x relativo a X, y relativo ao rótulo, l, a
DESTAQUE_JUSTO = (0.1224, -0.0463, 0.0365, 0.0426)  # só o meio (um dígito)

RE_PORCENTO = re.compile(r"^(\d{1,3})\s*(?:%|0/0|º/o|o/o)$")
RE_TEMPO = re.compile(r"^(\d{1,2}):(\d{2})$")
RE_INTEIRO = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$|^\d+$")
RE_DECIMAL = re.compile(r"^(\d+),(\d{1,2})$")


def _singular(palavra):
    if palavra.endswith("oes"):
        return palavra[:-3] + "ao"          # eliminacoes -> eliminacao
    if len(palavra) > 4 and palavra.endswith(("res", "zes")):
        return palavra[:-2]                 # jogadores -> jogador
    if len(palavra) > 3 and palavra.endswith("s"):
        return palavra[:-1]                 # kits -> kit
    return palavra


def chave_do_rotulo(rotulo):
    """'KITS MÉDICOS HACKEADOS' e 'KIT MÉDICO HACKEADO' -> 'kit-medico-hackeado':
    o jogo troca singular e plural conforme a quantidade."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", rotulo) if unicodedata.category(c) != "Mn")
    return "-".join(_singular(p) for p in re.findall(r"[a-z0-9]+", sem_acento.lower()))


def interpretar(texto):
    """'24%' -> (24, 'pct'); '5.804' -> (5804, 'num'); '1:23' -> (83, 'tempo').
    Outra coisa -> None."""
    texto = texto.strip()
    m = RE_PORCENTO.match(texto)
    if m:
        return (int(m.group(1)), "pct") if int(m.group(1)) <= 100 else None
    m = RE_TEMPO.match(texto)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)), "tempo"
    m = RE_DECIMAL.match(texto)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}"), "num"
    if RE_INTEIRO.match(texto):
        return int(re.sub(r"[.,]", "", texto)), "num"
    return None


def _parece_rotulo(texto):
    texto = texto.strip()
    letras = sum(c.isalpha() for c in texto)
    return letras >= 4 and letras >= 0.7 * len(texto.replace(" ", "")) and texto.upper() == texto


def _pelo_reconhecedor(tela, x, y, l, a):
    """Número de um retângulo pelo reconhecedor próprio (o que o OCR pulou)."""
    numeros = tela.numeros(int(x), int(y), int(l), int(a))
    return tela.reconhecedor.ler(numeros[0]) if len(numeros) == 1 else None


def _repetido(tela, x, y, l, a, vezes=3):
    """OCR do recorte repetido lado a lado: o OCR do Windows pula um caractere
    sozinho, mas lê "888". Retorna o trecho que se repete, ou None."""
    x, y, l, a = int(x), int(y), int(l), int(a)
    if x < 0 or y < 0 or x + l > tela.largura or y + a > tela.altura:
        return None
    recorte = recortar(tela.bgra, tela.largura, x, y, l, a)
    passo = l * 4
    lado_a_lado = b"".join(recorte[i * passo:(i + 1) * passo] * vezes for i in range(a))
    for ampliacao in (1, 2):
        grande, lg, ag = ampliar(lado_a_lado, l * vezes, a, ampliacao)
        for lida in tela.ocr.ler(grande, lg, ag):
            texto = lida.texto.replace(" ", "")
            if len(texto) % vezes == 0 and texto == texto[:len(texto) // vezes] * vezes:
                return texto[:len(texto) // vezes]
    return None


def ler_painel(linhas, largura, altura, tela=None):
    """{"heroi": nome lido ou None, "estatisticas": [{chave, rotulo, valor,
    tipo, ordem}]} ou None se o painel não está na tela."""
    candidatos = [l for l in linhas
                  if BUSCA_X[0] * largura <= l.x <= BUSCA_X[1] * largura
                  and LISTA_Y[0] * altura <= l.y <= LISTA_Y[1] * altura and _parece_rotulo(l.texto)]
    if len(candidatos) < 2:
        return None
    # A borda esquerda em que mais rótulos se alinham é a do painel.
    tolerancia = MESMO_X * largura
    alinhados = Counter()
    for c in candidatos:
        alinhados[c.x] = sum(abs(o.x - c.x) <= tolerancia for o in candidatos)
    x_painel, quantos = alinhados.most_common(1)[0]
    if quantos < 2:
        return None
    rotulos = sorted((c for c in candidatos if abs(c.x - x_painel) <= tolerancia), key=lambda l: l.y)

    estatisticas = []
    for rotulo in rotulos:
        valor = None
        for l in linhas:
            acima = rotulo.y - l.y
            if VALOR_ACIMA[0] * altura <= acima <= VALOR_ACIMA[1] * altura \
                    and abs(l.x - rotulo.x) <= 2 * tolerancia:
                valor = interpretar(l.texto)
                if valor:
                    break
        if not valor and tela is not None:
            caixa = (rotulo.x - 0.004 * largura, rotulo.y - 0.031 * altura, 0.10 * largura, ALTURA_VALOR * altura)
            numero = _pelo_reconhecedor(tela, *caixa)
            valor = (numero, "num") if numero is not None else None
        if valor:
            estatisticas.append(_estatistica(rotulo.texto, valor, len(estatisticas) + 1))
    if len(estatisticas) < 2:
        return None  # não é o painel (ou está coberto)

    if tela is None:
        return {"heroi": None, "estatisticas": estatisticas}
    chaves = {e["chave"] for e in estatisticas}
    destaques = [d for d in _destaques(linhas, x_painel, largura, altura, tela) if d["chave"] not in chaves]
    return {"heroi": _nome_do_heroi(x_painel, largura, altura, tela), "estatisticas": destaques + estatisticas}


def _estatistica(rotulo, valor, ordem):
    texto = " ".join(rotulo.split())
    return {"chave": chave_do_rotulo(texto), "rotulo": texto, "valor": valor[0], "tipo": valor[1], "ordem": ordem}


def _valor_da_caixa(tela, x, y, l, a):
    """Valor na fonte estilizada: o OCR oscila com o recorte ("47%" vira
    "4700"), então tenta alguns recortes e ampliações. Uma leitura em formato
    de porcentagem ganha; um número terminado em 00 é suspeito e pede mais
    tentativas."""
    achados = []
    for dy in (0, -2, 2):
        for ampliacao in (2, 3):
            for lida in tela.ler_faixa(x, y + dy, l, a, ampliacao=ampliacao):
                valor = interpretar(lida.texto.replace(" ", ""))
                if valor:
                    achados.append(valor)
            porcentos = [v for v in achados if v[1] == "pct"]
            if porcentos:
                return Counter(porcentos).most_common(1)[0][0]
            if achados and not any(v[1] == "num" and v[0] >= 100 and v[0] % 100 == 0 for v in achados):
                return Counter(achados).most_common(1)[0][0]
    return Counter(achados).most_common(1)[0][0] if achados else None


def _destaques(linhas, x_painel, largura, altura, tela):
    """As estatísticas das caixas do topo ("8 JOGADORES SALVOS"; tanques têm
    duas). O número é na fonte estilizada do jogo: OCR ampliado da caixa e,
    para um dígito só, o recorte repetido."""
    dx0, dy0, dx1, dy1 = DESTAQUE_ROTULO
    rotulos = sorted((l for l in linhas if x_painel + dx0 * largura <= l.x <= x_painel + dx1 * largura
                      and dy0 * altura <= l.y <= dy1 * altura and _parece_rotulo(l.texto)), key=lambda l: l.y)
    destaques = []
    for rotulo in rotulos:
        x, y, l, a = DESTAQUE_VALOR
        valor = _valor_da_caixa(tela, x_painel + x * largura, rotulo.y + y * altura, l * largura, a * altura)
        if not valor:
            x, y, l, a = DESTAQUE_JUSTO
            texto = _repetido(tela, x_painel + x * largura, rotulo.y + y * altura, l * largura, a * altura)
            valor = interpretar(texto) if texto else None
        if valor:
            destaques.append(_estatistica(rotulo.texto, valor, 0))
    return destaques


def _nome_do_heroi(x_painel, largura, altura, tela):
    """O nome do herói é na fonte estilizada do jogo e o OCR o lê torto
    ("ROBOHOG", "SOMBRI", "RRlNHIJUNKfR"). Por isso: várias leituras (dois
    recortes, três ampliações) e, em cada uma, o herói de nome mais parecido;
    ganha o mais votado, se for parecido o bastante e com folga sobre o
    segundo. Retorna o nome do herói ou None."""
    from .detector import INDICE_HEROIS, compactar, similaridade

    votos = Counter()
    for x, y, l, a in (NOME_HEROI, NOME_HEROI_ALTO):
        for ampliacao in (1, 2, 3):
            for lida in tela.ler_faixa(x_painel + x * largura, y * altura, l * largura, a * altura,
                                       ampliacao=ampliacao):
                texto = compactar(lida.texto)
                if len(texto) < 3:
                    continue
                notas = Counter()
                for chave, nome in INDICE_HEROIS.items():
                    notas[nome] = max(notas[nome], similaridade(texto, chave))
                (melhor, nota), (_, segunda) = notas.most_common(2)
                if nota >= NOTA_NOME and nota - segunda >= FOLGA_NOME:
                    votos[melhor] += nota
            if len(votos) == 1 and sum(votos.values()) >= 2 * NOTA_NOME + 0.2:
                return next(iter(votos))  # duas leituras boas do mesmo herói: basta
    if not votos:
        return None
    melhores = votos.most_common(2)
    if len(melhores) > 1 and melhores[0][1] < 2 * melhores[1][1]:
        return None  # leituras divididas entre dois heróis
    return melhores[0][0]
