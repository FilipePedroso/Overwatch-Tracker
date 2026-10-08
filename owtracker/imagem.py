"""Operações simples em imagens BGRA (bytes), feitas com fatiamento (rápido),
e um leitor de PNG próprio (para os ícones baixados da wiki)."""

import struct
import zlib


def ler_png(caminho):
    """Lê um PNG de 8 bits (RGB, RGBA, cinza ou paleta). Retorna (largura,
    altura, bytes RGBA). Lança ValueError para formatos não suportados."""
    dados = open(caminho, "rb").read()
    if dados[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("não é PNG")
    i, idat, paleta, transparencia = 8, b"", b"", b""
    while i < len(dados):
        tamanho, tipo = struct.unpack(">I4s", dados[i:i + 8])
        corpo = dados[i + 8:i + 8 + tamanho]
        if tipo == b"IHDR":
            largura, altura, bits, cor, _, _, entrelacado = struct.unpack(">IIBBBBB", corpo)
        elif tipo == b"PLTE":
            paleta = corpo
        elif tipo == b"tRNS":
            transparencia = corpo
        elif tipo == b"IDAT":
            idat += corpo
        i += 12 + tamanho
    canais = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(cor)
    if bits != 8 or canais is None or entrelacado:
        raise ValueError("formato de PNG não suportado")
    cru = zlib.decompress(idat)
    passo = largura * canais
    pixels, anterior = bytearray(), bytearray(passo)
    for y in range(altura):
        filtro = cru[y * (passo + 1)]
        linha = bytearray(cru[y * (passo + 1) + 1:(y + 1) * (passo + 1)])
        if filtro:
            _desfiltrar(linha, anterior, filtro, canais)
        pixels += linha
        anterior = linha
    return largura, altura, _para_rgba(bytes(pixels), cor, paleta, transparencia)


def _desfiltrar(linha, anterior, filtro, canais):
    for x in range(len(linha)):
        a = linha[x - canais] if x >= canais else 0
        b = anterior[x]
        c = anterior[x - canais] if x >= canais else 0
        if filtro == 1:
            linha[x] = (linha[x] + a) & 255
        elif filtro == 2:
            linha[x] = (linha[x] + b) & 255
        elif filtro == 3:
            linha[x] = (linha[x] + (a + b) // 2) & 255
        else:  # Paeth
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            linha[x] = (linha[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255


def _para_rgba(pixels, cor, paleta, transparencia):
    if cor == 6:
        return pixels
    saida = bytearray()
    if cor == 2:
        for i in range(0, len(pixels), 3):
            saida += pixels[i:i + 3] + b"\xff"
    elif cor == 0:
        for v in pixels:
            saida += bytes((v, v, v, 255))
    elif cor == 4:
        for i in range(0, len(pixels), 2):
            saida += bytes((pixels[i],) * 3 + (pixels[i + 1],))
    else:  # paleta
        for indice in pixels:
            alfa = transparencia[indice] if indice < len(transparencia) else 255
            saida += paleta[indice * 3:indice * 3 + 3] + bytes((alfa,))
    return bytes(saida)


def recortar(bgra, largura, x, y, largura_recorte, altura_recorte):
    passo, inicio = largura * 4, x * 4
    return b"".join(
        bgra[(y + i) * passo + inicio:(y + i) * passo + inicio + largura_recorte * 4]
        for i in range(altura_recorte)
    )


def ampliar(bgra, largura, altura, fator):
    """Amplia por um fator inteiro (vizinho mais próximo). Retorna (bgra, largura, altura)."""
    passo, passo_novo = largura * 4, largura * 4 * fator
    linhas = []
    for y in range(altura):
        origem = bgra[y * passo:(y + 1) * passo]
        nova = bytearray(passo_novo)
        for k in range(fator):
            for canal in range(4):
                nova[k * 4 + canal::fator * 4] = origem[canal::4]
        linhas.extend([bytes(nova)] * fator)
    return b"".join(linhas), largura * fator, altura * fator


def isolar_texto_branco(bgra, limiar=170):
    """Texto branco vira preto sobre fundo branco; o resto some.

    O texto do placar é branco (azul alto); os fundos verde, amarelo e
    vermelho das linhas têm pouco azul. Olhar só o canal azul separa os dois.
    """
    tabela = bytes(0 if i >= limiar else 255 for i in range(256))
    cinza = bgra[0::4].translate(tabela)
    saida = bytearray(len(bgra))
    for canal in range(3):
        saida[canal::4] = cinza
    saida[3::4] = b"\xff" * len(cinza)
    return bytes(saida)


def reduzir(bgra, largura, altura, fator):
    """Reduz por um fator inteiro (vizinho mais próximo). Retorna (bgra, largura, altura)."""
    if fator == 1:
        return bgra, largura, altura
    passo = largura * 4
    nova_largura, nova_altura = largura // fator, altura // fator
    passo_novo = nova_largura * 4
    saida = bytearray(passo_novo * nova_altura)
    for y in range(nova_altura):
        origem = bgra[fator * y * passo:fator * y * passo + nova_largura * fator * 4]
        inicio = y * passo_novo
        for canal in range(4):
            saida[inicio + canal:inicio + passo_novo:4] = origem[canal::fator * 4]
    return bytes(saida), nova_largura, nova_altura
