"""Identificação do herói de cada jogador no placar (Tab).

O placar não escreve o nome do herói: só mostra o retrato (que muda com a
skin) e, depois que o jogador escolhe, os ícones das vantagens (perks), que
são exclusivos de cada herói. Combinamos, do mais ao menos confiável:

1. a sua linha: o herói já é conhecido pelas legendas, e os aliados que
   falaram nas legendas ("[STRIKING (DOCTRINE)]"), casando o nome lido;
2. a biblioteca de retratos APRENDIDA: o retrato de um herói com uma skin é
   sempre o mesmo, então todo retrato identificado com segurança (o seu, ou
   um que você corrigir no app) é guardado e reconhecido nas próximas partidas;
3. os ícones de vantagem, comparados pela forma com os ícones da wiki,
   só quando a semelhança for alta.

A busca é limitada à função da linha: na fila por função o placar segue a
ordem tanque, dano, dano, suporte, suporte.
"""

import json
import threading
from functools import lru_cache

from . import catalogo
from .banco import PASTA_DADOS
from .imagem import ler_png

ARQUIVO_BIBLIOTECA = PASTA_DADOS / "retratos.json"
ARQUIVO_VANTAGENS = PASTA_DADOS / "vantagens.json"

LADO_VETOR = 12           # retrato reduzido a 12x12 (RGB) para comparar
LIMIAR_RETRATO = 14       # diferença média por canal (0-255) para aceitar
RETRATOS_POR_HEROI = 30   # skins/variações guardadas por herói
LADO_GRADE = 16           # símbolo de vantagem normalizado em 16x16
NOTA_VANTAGEM = 0.55      # semelhança mínima (IoU) para reconhecer o herói por um ícone
NOTA_NOMEAR = 0.40        # idem para dizer QUAL vantagem foi (herói já conhecido: só 4 opções)
VERSAO_MODELOS = 2        # muda quando o formato de dados/vantagens.json muda
BONUS_DUAS_VANTAGENS = 0.15
FUNCAO_POR_POSICAO = ("tank", "damage", "damage", "support", "support")


# ---------------------------------------------------------------- retratos

def vetor_retrato(rgb, largura, altura):
    """Média de cor em blocos 12x12: resume o retrato e tolera pequenas diferenças."""
    v = []
    for j in range(LADO_VETOR):
        y0, y1 = j * altura // LADO_VETOR, (j + 1) * altura // LADO_VETOR
        for i in range(LADO_VETOR):
            x0, x1 = i * largura // LADO_VETOR, (i + 1) * largura // LADO_VETOR
            soma, n = [0, 0, 0], 0
            for y in range(y0, max(y1, y0 + 1)):
                inicio = (y * largura + x0) * 3
                for k in range(inicio, inicio + max(x1 - x0, 1) * 3, 3):
                    soma[0] += rgb[k]
                    soma[1] += rgb[k + 1]
                    soma[2] += rgb[k + 2]
                    n += 1
            v += [s // n for s in soma]
    return v


def distancia(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


class Biblioteca:
    """Retratos já identificados: {heroi_id: [vetores]} em dados/retratos.json."""

    def __init__(self):
        self.trava = threading.Lock()
        try:
            self.retratos = json.loads(ARQUIVO_BIBLIOTECA.read_text("utf-8"))
        except (OSError, ValueError):
            self.retratos = {}

    def aprender(self, heroi_id, vetor):
        if not heroi_id or not vetor:
            return
        with self.trava:
            lista = self.retratos.setdefault(heroi_id, [])
            if any(distancia(vetor, v) < LIMIAR_RETRATO / 3 for v in lista):
                return  # já conhecido (mesma skin)
            lista.append(vetor)
            del lista[:-RETRATOS_POR_HEROI]

    def esquecer(self, heroi_id, vetor):
        """Remove um retrato que tinha sido atribuído ao herói errado."""
        with self.trava:
            lista = self.retratos.get(heroi_id, [])
            lista[:] = [v for v in lista if distancia(vetor, v) >= LIMIAR_RETRATO / 3]

    def reconhecer(self, vetor, funcao=None):
        """(heroi_id, distância) do retrato mais parecido, ou (None, None)."""
        permitidos = _herois_da_funcao(funcao)
        melhor, menor = None, LIMIAR_RETRATO
        with self.trava:
            for heroi_id, lista in self.retratos.items():
                if permitidos and heroi_id not in permitidos:
                    continue
                for v in lista:
                    d = distancia(vetor, v)
                    if d < menor:
                        melhor, menor = heroi_id, d
        return (melhor, menor) if melhor else (None, None)

    def salvar(self):
        with self.trava:
            PASTA_DADOS.mkdir(parents=True, exist_ok=True)
            ARQUIVO_BIBLIOTECA.write_text(json.dumps(self.retratos), "utf-8")


def _herois_da_funcao(funcao):
    if not funcao:
        return None
    return {h["id"] for h in catalogo.carregar()["herois"] if h["funcao"] == funcao}


# ---------------------------------------------------------------- vantagens

def grade_simbolo(mascara, largura, altura):
    """Recorta o símbolo (pixels ligados) e o normaliza num quadrado 16x16.
    Retorna uma string de '0'/'1' (ou None se não há símbolo)."""
    xs = [x for y in range(altura) for x in range(largura) if mascara[y][x]]
    if len(xs) < 12:
        return None
    ys = [y for y in range(altura) for x in range(largura) if mascara[y][x]]
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    lado = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bits = []
    for j in range(LADO_GRADE):
        ya = int(cy - lado / 2 + j * lado / LADO_GRADE)
        yb = max(ya + 1, int(cy - lado / 2 + (j + 1) * lado / LADO_GRADE))
        for i in range(LADO_GRADE):
            xa = int(cx - lado / 2 + i * lado / LADO_GRADE)
            xb = max(xa + 1, int(cx - lado / 2 + (i + 1) * lado / LADO_GRADE))
            total = ligados = 0
            for y in range(ya, yb):
                for x in range(xa, xb):
                    total += 1
                    if 0 <= y < altura and 0 <= x < largura and mascara[y][x]:
                        ligados += 1
            bits.append("1" if ligados * 2 >= total else "0")
    return "".join(bits)


def semelhanca(a, b):
    """Interseção sobre união das duas formas (1 = idênticas)."""
    inter = sum(1 for x, y in zip(a, b) if x == "1" and y == "1")
    uniao = sum(1 for x, y in zip(a, b) if x == "1" or y == "1")
    return inter / uniao if uniao else 0.0


@lru_cache(maxsize=1)
def modelos_vantagens():
    """[(heroi_id, id da vantagem, nome, tipo, grade)] a partir dos ícones da
    wiki em referencia/assets (símbolo branco sobre fundo transparente). O
    cálculo é guardado em dados/vantagens.json e refeito se os ícones mudarem."""
    arquivos = []
    for h in catalogo.carregar()["herois"]:
        for a in h["habilidades"]:
            if (a["tipo"] or "").startswith("vantagem"):
                caminho = catalogo.PASTA / "assets" / "habilidades" / f"{h['id']}__{a['id']}.png"
                if caminho.exists():
                    arquivos.append((h["id"], a["id"], a["nome"] or a["nome_en"], a["tipo"], caminho))
    assinatura = [VERSAO_MODELOS] + [[str(c.name), c.stat().st_size] for *_, c in arquivos]
    try:
        salvo = json.loads(ARQUIVO_VANTAGENS.read_text("utf-8"))
        if salvo["assinatura"] == assinatura:
            return [tuple(m) for m in salvo["modelos"]]
    except (OSError, ValueError, KeyError):
        pass
    modelos = []
    for heroi_id, vantagem_id, nome, tipo, caminho in arquivos:
        try:
            largura, altura, rgba = ler_png(caminho)
        except ValueError:
            continue
        mascara = [[rgba[(y * largura + x) * 4 + 3] > 128 for x in range(largura)] for y in range(altura)]
        grade = grade_simbolo(mascara, largura, altura)
        if grade:
            modelos.append((heroi_id, vantagem_id, nome, tipo, grade))
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    ARQUIVO_VANTAGENS.write_text(json.dumps({"assinatura": assinatura, "modelos": modelos}), "utf-8")
    return modelos


def simbolos_de_vantagem(bgra, largura_tela, x0, x1, yc, raio_busca):
    """Acha os discos brancos dos ícones de vantagem numa linha do placar e
    devolve a grade do símbolo escuro de cada um (no jogo: preto sobre branco)."""
    x0, x1 = max(0, int(x0)), int(x1)
    y0, y1 = int(yc - raio_busca), int(yc + raio_busca)
    l, a = x1 - x0, y1 - y0

    def pixel(x, y):
        k = ((y0 + y) * largura_tela + x0 + x) * 4
        return bgra[k + 2], bgra[k + 1], bgra[k]

    branco = [[min(pixel(x, y)) > 200 for x in range(l)] for y in range(a)]
    visto, grades = set(), []
    minimo = (raio_busca * 0.8) ** 2  # área mínima de um disco
    for j in range(a):
        for i in range(l):
            if not branco[j][i] or (i, j) in visto:
                continue
            pilha, pontos = [(i, j)], []
            visto.add((i, j))
            while pilha:  # componente conectado (flood fill)
                p, q = pilha.pop()
                pontos.append((p, q))
                for np_, nq in ((p + 1, q), (p - 1, q), (p, q + 1), (p, q - 1)):
                    if 0 <= np_ < l and 0 <= nq < a and branco[nq][np_] and (np_, nq) not in visto:
                        visto.add((np_, nq))
                        pilha.append((np_, nq))
            if len(pontos) < minimo:
                continue
            xs, ys = [p[0] for p in pontos], [p[1] for p in pontos]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            r = (max(xs) - min(xs)) / 2 * 0.85  # dentro do disco, sem a borda
            mascara = [[(x - cx) ** 2 + (y - cy) ** 2 <= r * r and max(pixel(x, y)) < 110
                        for x in range(l)] for y in range(a)]
            grade = grade_simbolo(mascara, l, a)
            if grade:
                grades.append((cx, grade))
    return [g for _, g in sorted(grades)]


def reconhecer_vantagens(grades, funcao=None):
    """(heroi_id, nota) pelo(s) ícone(s) de vantagem, ou (None, None)."""
    permitidos = _herois_da_funcao(funcao)
    melhores = []
    for grade in grades:
        notas = [(semelhanca(grade, g), heroi_id) for heroi_id, *_, g in modelos_vantagens()
                 if not permitidos or heroi_id in permitidos]
        if notas:
            melhores.append(max(notas))
    if not melhores:
        return None, None
    nota, heroi_id = max(melhores)
    if len(melhores) == 2 and melhores[0][1] == melhores[1][1]:
        nota += BONUS_DUAS_VANTAGENS  # os dois ícones apontam para o mesmo herói
    return (heroi_id, round(nota, 2)) if nota >= NOTA_VANTAGEM else (None, None)


def nomear_vantagens(heroi_id, grades):
    """Quais vantagens o jogador escolheu: cada ícone é comparado só com as
    vantagens DO SEU HERÓI (são 4), o que é bem mais seguro que reconhecer o
    herói. Retorna [{"id", "nome", "tipo"}] (menor/maior), sem repetir."""
    if not heroi_id:
        return []
    do_heroi = [m for m in modelos_vantagens() if m[0] == heroi_id]
    escolhidas = []
    for grade in grades:
        notas = sorted(((semelhanca(grade, m[4]), m) for m in do_heroi), reverse=True)
        if notas and notas[0][0] >= NOTA_NOMEAR:
            _, vantagem_id, nome, tipo, _ = notas[0][1]
            if all(e["id"] != vantagem_id for e in escolhidas):
                escolhidas.append({"id": vantagem_id, "nome": nome, "tipo": tipo})
    return escolhidas


# ---------------------------------------------------------------- times

NOTA_APRENDER = 0.70       # vantagens tão parecidas que o retrato pode ir para a biblioteca
SEMELHANCA_NOME = 0.6      # nome lido no placar x nome nas legendas


def identificar(times, heroi_jogador, biblioteca, falas=None, nome_jogador=""):
    """Preenche heroi_id/fonte (e corrige o nome, quando dá) de cada jogador
    dos dois times. Ensina à biblioteca os retratos identificados com segurança.

    falas: {NOME: Counter(herói)} das legendas da partida: "[STRIKING (DOCTRINE)]"
    dá o nome e o herói certos de aliados que falaram."""
    from .detector import compactar, mesmo_nome, similaridade

    seu = catalogo.heroi(heroi_jogador) if heroi_jogador else None
    falantes = {}
    for nome, herois in (falas or {}).items():
        heroi = catalogo.heroi(herois.most_common(1)[0][0]) if herois else None
        if nome_jogador and mesmo_nome(nome, nome_jogador):
            continue  # as suas falas são da sua linha, não de um aliado de nome parecido
        if heroi:
            falantes[nome] = heroi["id"]
    for time in ("aliados", "inimigos"):
        for posicao, j in enumerate(times.get(time, [])):
            funcao = FUNCAO_POR_POSICAO[posicao] if len(times[time]) == 5 else None
            if j.get("voce"):
                if nome_jogador:
                    j["nome"] = nome_jogador
                if seu:
                    j["heroi_id"], j["fonte"] = seu["id"], "voce"
                    biblioteca.aprender(seu["id"], j["vetor"])
                    continue
            if time == "aliados" and j.get("nome"):
                lido = compactar(j["nome"])
                nota, falante = max(((similaridade(lido, compactar(n)), n) for n in falantes), default=(0, None))
                if nota >= SEMELHANCA_NOME:
                    j["nome"], j["heroi_id"], j["fonte"] = falante, falantes[falante], "legendas"
                    biblioteca.aprender(j["heroi_id"], j["vetor"])
                    continue
            heroi_id, _ = biblioteca.reconhecer(j["vetor"], funcao)
            if heroi_id:
                j["heroi_id"], j["fonte"] = heroi_id, "retrato"
                continue
            heroi_id, nota = reconhecer_vantagens(j.get("vantagens", []), funcao)
            j["heroi_id"], j["fonte"] = (heroi_id, "vantagens") if heroi_id else (None, None)
            if heroi_id and nota >= NOTA_APRENDER:
                biblioteca.aprender(heroi_id, j["vetor"])
    for time in ("aliados", "inimigos"):
        for j in times.get(time, []):
            j["escolhidas"] = nomear_vantagens(j.get("heroi_id"), j.get("vantagens", []))
    return times
