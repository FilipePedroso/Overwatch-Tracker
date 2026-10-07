"""Operações simples em imagens BGRA (bytes), feitas com fatiamento (rápido)."""


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
