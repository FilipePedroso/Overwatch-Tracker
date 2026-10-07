"""Coleta os dados de referência do Overwatch (heróis, habilidades, funções,
subfunções, mapas e modos) e grava em owtracker/referencia/*.json.

Fontes:
- Site oficial (overwatch.blizzard.com, pt-BR e en-US): nomes em português,
  função, subfunção, habilidades e URLs dos ícones oficiais.
- Overwatch Wiki (overwatch.weirdgloop.org, API do MediaWiki): vida/armadura/
  escudo, tipo de cada habilidade (arma/habilidade/suprema/passiva), tecla,
  recarga, vantagens (perks), lista de mapas por modo e imagens.
- Nomes pt-BR dos mapas: conferidos nas notas de atualização oficiais em pt-BR.

Uso:  python ferramentas/coletar_referencia.py
As páginas baixadas ficam em ferramentas/.cache (apague para buscar de novo).
Não baixa imagens: só guarda as URLs (ver baixar_assets.py).
"""

import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / ".cache"
SAIDA = RAIZ / "owtracker" / "referencia"

SITE = "https://overwatch.blizzard.com"
WIKI_API = "https://overwatch.weirdgloop.org/api.php"
AGENTE = "OWTracker-referencia/1.0 (projeto pessoal; coleta ocasional)"
PAUSA = 0.4  # s entre requisições, para não sobrecarregar ninguém

# Nomes oficiais em pt-BR (notas de atualização / notícias da Blizzard em pt-BR).
# Mapas ausentes daqui mantêm o nome original no jogo em português.
MAPAS_PT = {
    "Antarctic Peninsula": "Península Antártica",
    "Lijiang Tower": "Torre Lijiang",
    "Oasis": "Oásis",
    "Route 66": "Rota 66",
    "Shambali Monastery": "Monastério de Shambali",
    "Watchpoint: Gibraltar": "Observatório: Gibraltar",
    "Neon Junction": "Junção Neon",
    "New Junk City": "Nova Junk City",
    "New Queen Street": "Nova Queen Street",
    "Watchpoint: Grímsvötn": "Observatório: Grímsvötn",
}

# Mapas já lançados que a wiki ainda não pôs na lista de modo padrão
# (modo em inglês, código do país, nome). Saem daqui sozinhos quando a wiki
# atualizar, porque duplicatas são ignoradas.
MAPAS_RECENTES = [
    ("Escort", "is", "Watchpoint: Grímsvötn"),  # Temporada 5 (06/10/2026)
]

MODOS = {
    # id: (nome pt-BR, nome en, descrição)
    "control": ("Controle", "Control",
                "As equipes disputam um ponto de controle; vence quem conquistar 2 de 3 rodadas."),
    "escort": ("Escolta", "Escort",
               "O ataque escolta a carga por três pontos de verificação; a defesa tenta impedir."),
    "hybrid": ("Híbrido", "Hybrid",
               "O ataque captura um ponto e depois escolta a carga até o destino."),
    "push": ("Avanço", "Push",
             "As equipes disputam o robô e o empurram em direção à base inimiga."),
    "flashpoint": ("Ponto de Tumulto", "Flashpoint",
                   "Pontos de controle surgem pelo mapa; vence quem capturar três primeiro."),
}

PAISES_PT = {
    "aq": "Antártida", "kr": "Coreia do Sul", "gr": "Grécia", "cn": "China", "np": "Nepal",
    "iq": "Iraque", "samoa": "Samoa", "mc": "Mônaco", "mx": "México", "cu": "Cuba",
    "au": "Austrália", "it": "Itália", "us": "Estados Unidos", "gi": "Gibraltar",
    "ma": "Marrocos", "in": "Índia", "de": "Alemanha", "uk": "Reino Unido", "jp": "Japão",
    "nb": "Numbani", "br": "Brasil", "pt": "Portugal", "ca": "Canadá", "pe": "Peru",
    "is": "Islândia",
}

SECOES_HABILIDADE = {
    "Passive Abilities": "passiva", "Weapons": "arma", "Special Abilities": "habilidade",
    "Ultimate Ability": "suprema", "Minor Perks": "vantagem_menor", "Major perks": "vantagem_maior",
    "Major Perks": "vantagem_maior",
}

TECLAS_PT = {
    "primary-fire": "Disparo primário", "secondary-fire": "Disparo secundário",
}


# ---------------------------------------------------------------- rede

def baixar(url):
    """GET com cache em disco e pausa entre requisições."""
    CACHE.mkdir(parents=True, exist_ok=True)
    arquivo = CACHE / (re.sub(r"[^\w.-]+", "_", url)[-180:] + ".txt")
    if arquivo.exists():
        return arquivo.read_text("utf-8")
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(pedido, timeout=30) as resposta:
        texto = resposta.read().decode("utf-8")
    arquivo.write_text(texto, "utf-8")
    time.sleep(PAUSA)
    return texto


def wiki(parametros):
    return json.loads(baixar(WIKI_API + "?" + urllib.parse.urlencode(
        {**parametros, "format": "json", "formatversion": "2"})))


def wikitexto(pagina):
    dados = wiki({"action": "parse", "page": pagina, "prop": "wikitext", "redirects": "1"})
    if "error" in dados:
        raise LookupError(f"wiki: página '{pagina}' não encontrada")
    return dados["parse"]["wikitext"]


def urls_de_arquivos(nomes, largura=None):
    """Arquivo da wiki -> URL da imagem (em lotes de 50)."""
    urls, nomes = {}, sorted({n for n in nomes if n})
    for i in range(0, len(nomes), 50):
        lote = nomes[i:i + 50]
        parametros = {"action": "query", "prop": "imageinfo", "iiprop": "url",
                      "titles": "|".join("File:" + n for n in lote)}
        if largura:
            parametros["iiurlwidth"] = str(largura)
        dados = wiki(parametros)
        normalizados = {n["to"]: n["from"] for n in dados["query"].get("normalized", [])}
        for pagina in dados["query"]["pages"]:
            if "imageinfo" not in pagina:
                continue
            info = pagina["imageinfo"][0]
            original = normalizados.get(pagina["title"], pagina["title"])[len("File:"):]
            urls[original] = info.get("thumburl") or info["url"]
    return urls


# ---------------------------------------------------------------- texto

def limpar_html(texto):
    texto = re.sub(r"<img[^>]*alt='overwatch\.page\.herodetail\.ability\.([\w-]+)'[^>]*>",
                   lambda m: f" {TECLAS_PT.get(m.group(1), m.group(1))}: ", texto)
    texto = re.sub(r"<br\s*/?>", " ", texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def limpar_wikitexto(texto):
    """Simplifica wikitexto para texto legível ('{{tt|8 seconds|...}}' -> '8 seconds')."""
    if not texto:
        return ""
    texto = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", texto, flags=re.S)
    for _ in range(4):  # modelos aninhados, de dentro para fora
        texto = re.sub(r"\{\{#vardefineecho:\s*[^|{}]*\|\s*([^{}]*)\}\}", r"\1", texto)
        texto = re.sub(r"\{\{#var:[^{}]*\}\}", "", texto)
        texto = re.sub(r"\{\{(?:tt|al|abbr)\|([^|{}]*)(?:\|[^{}]*)?\}\}", r"\1", texto)
        texto = re.sub(r"\{\{[^{}]*\}\}", "", texto)
    texto = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", texto)
    texto = re.sub(r"<br\s*/?>", "; ", texto)
    texto = re.sub(r"'''?|<[^>]+>", "", texto)
    return re.sub(r"\s+", " ", texto).strip(" ;")


def slug(texto):
    """'Esperança' -> 'esperanca'; 'Watchpoint: Gibraltar' -> 'watchpoint-gibraltar'."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto.lower())
                         if not unicodedata.combining(c) and c not in "'’")
    return re.sub(r"[^a-z0-9]+", "-", sem_acento).strip("-")


def modelos(texto, nomes):
    """Encontra blocos {{Nome ...}} (com aninhamento) e devolve seus campos."""
    padrao = re.compile(r"\{\{\s*(?:" + "|".join(nomes) + r")\s*\n?\|", re.I)
    for m in padrao.finditer(texto):
        nivel, i = 0, m.start()
        while i < len(texto):
            if texto.startswith("{{", i):
                nivel, i = nivel + 1, i + 2
            elif texto.startswith("}}", i):
                nivel, i = nivel - 1, i + 2
                if nivel == 0:
                    break
            else:
                i += 1
        yield m.start(), campos(texto[m.start() + 2:i - 2])


def campos(corpo):
    """Campos '| nome = valor' do primeiro nível de um modelo."""
    resultado, nivel, atual = {}, 0, ""
    partes = []
    i = 0
    while i < len(corpo):
        par = corpo[i:i + 2]
        if par in ("{{", "[["):
            nivel += 1
            atual += par
            i += 2
            continue
        if par in ("}}", "]]"):
            nivel -= 1
            atual += par
            i += 2
            continue
        if corpo[i] == "|" and nivel == 0:
            partes.append(atual)
            atual = ""
        else:
            atual += corpo[i]
        i += 1
    partes.append(atual)
    for parte in partes[1:]:
        if "=" in parte:
            chave, valor = parte.split("=", 1)
            resultado[chave.strip().lower().replace(" ", "_")] = valor.strip()
    return resultado


# ---------------------------------------------------------------- site oficial

def lista_oficial():
    pagina = baixar(f"{SITE}/pt-br/heroes/")
    herois = []
    for atributos, corpo in re.findall(r'<a class="hero-card"([^>]*)>(.*?)</a>', pagina, re.S):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', atributos))
        retrato = re.search(r'class="heroCardPortrait"[^>]*src="([^"]+)"', corpo)
        herois.append({
            "id": a["id"], "funcao": a["data-role"], "subfuncao": a["data-subrole"],
            "novo": a.get("data-new") == "true",
            "retrato_url": retrato.group(1) if retrato else None,
        })
    return herois


def pagina_heroi(id_heroi, idioma):
    pagina = baixar(f"{SITE}/{idioma}/heroes/{id_heroi}/")
    cabecalho = pagina[pagina.find("<blz-page-header"):pagina.find("</blz-page-header>")]
    funcao = re.search(r'<blz-list-item class="role" descriptiontext="([^"]*)" imagesrc="([^"]*)">'
                       r'<div class="role-container" slot="image" blz-tooltip="([^"]*)"', cabecalho)
    subfuncao = re.search(r'<blz-list-item class="subrole" descriptiontext="([^"]*)">.*?'
                          r'<blz-icon role="presentation" src="([^"]*)".*?'
                          r'<p slot="description">([^<]*)</p>', cabecalho, re.S)
    local = re.search(r'class="location".*?<p slot="description">([^<]*)</p>', cabecalho, re.S)
    inicio = pagina.find('class="abilities-container"')
    bloco = pagina[inicio:pagina.find("</blz-carousel-section", inicio)] if inicio >= 0 else ""
    controles = re.findall(r'<blz-tab-control id="([^"]+)" variant="icon-text" label="([^"]*)">'
                           r'.*?<blz-image slot="icon" src="([^"]*)"', bloco, re.S)
    textos = re.findall(r'<h3 class="heading" slot="heading">(.*?)</h3>'
                        r'<p slot="description">(.*?)</p>', bloco, re.S)
    habilidades = []
    for (id_hab, nome, icone), (_, descricao) in zip(controles, textos):
        habilidades.append({"id": id_hab, "nome": html.unescape(nome),
                            "descricao": limpar_html(descricao), "icone_url": icone})
    return {
        "nome": html.unescape(re.search(r'<h2 slot="heading">(.*?)</h2>', cabecalho).group(1)),
        "descricao": limpar_html(re.search(r'<p slot="description">(.*?)</p>', cabecalho, re.S).group(1)),
        "funcao": {"nome": html.unescape(funcao.group(1)), "icone_url": funcao.group(2),
                   "descricao": html.unescape(funcao.group(3))} if funcao else None,
        "subfuncao": {"descricao": html.unescape(subfuncao.group(1)), "icone_url": subfuncao.group(2),
                      "nome": html.unescape(subfuncao.group(3))} if subfuncao else None,
        "local": html.unescape(local.group(1)) if local else None,
        "habilidades": habilidades,
    }


# ---------------------------------------------------------------- wiki

def dados_wiki_heroi(nome_en):
    texto = wikitexto(nome_en)
    caixa = next((c for _, c in modelos(texto, ["Infobox character"])), {})

    def numero(campo):
        m = re.match(r"\d+", limpar_wikitexto(caixa.get(campo, "")))
        return int(m.group()) if m else 0

    habilidades = []
    secoes = [(m.start(), m.group(1).strip()) for m in re.finditer(r"^===?\s*([^=]+?)\s*===?\s*$", texto, re.M)]

    def secao_em(posicao):
        atual = None
        for inicio, nome in secoes:
            if inicio > posicao:
                break
            atual = nome
        return atual

    for posicao, c in modelos(texto, ["Ability[ _]details"]):
        tipo = SECOES_HABILIDADE.get(secao_em(posicao))
        if not tipo or not c.get("ability_name"):
            continue
        habilidades.append({
            "nome_en": limpar_wikitexto(c["ability_name"]),
            "tipo": tipo,
            "tecla": limpar_wikitexto(c.get("key", "")) or None,
            "descricao_en": limpar_wikitexto(c.get("official_description", "")) or None,
            "recarga": limpar_wikitexto(c.get("cooldown", "")) or None,
            "duracao": limpar_wikitexto(c.get("duration", "")) or None,
            "custo_suprema": limpar_wikitexto(c.get("ult_req", "")) or None,
            "imagem_wiki": c.get("ability_image", "").strip() or None,
        })
    return {
        "nome_real": limpar_wikitexto(caixa.get("realname", "")) or None,
        "vida": numero("health"), "armadura": numero("armor"), "escudo": numero("shield"),
        "habilidades": habilidades,
    }


def mapas_wiki():
    texto = wikitexto("Maps")
    padrao = texto[texto.find("== Standard Play =="):]
    padrao = padrao[:re.search(r"^== [^=]", padrao[5:], re.M).start() + 5]
    mapas = []
    for secao in re.split(r"^=== ", padrao, flags=re.M)[1:]:
        modo_en = secao.split("===")[0].strip()
        for pais, nome in re.findall(r"\{\{flag\|(\w+)\|[^}]*\}\} \[\[([^\]|]+)", secao):
            mapas.append((modo_en, pais, nome))
    conhecidos = {nome for _, _, nome in mapas}
    return mapas + [m for m in MAPAS_RECENTES if m[2] not in conhecidos]


# ---------------------------------------------------------------- montagem

def chave(texto):
    return re.sub(r"[^a-z0-9]", "", slug(texto or ""))


def par_oficial(nome_en, oficiais_pt, oficiais_en, usadas):
    """Habilidade oficial correspondente a uma da wiki. Tolera grafias
    ('B.O.B.' x 'bob', "Widow's Kiss" x 'widows-kiss') e formas
    ('Void Accelerator' x 'void-accelerator-omnic-form')."""
    alvo = chave(nome_en)
    for oficial in oficiais_pt:
        if oficial["id"] in usadas:
            continue
        candidatos = {chave(oficial["id"]), chave(oficiais_en.get(oficial["id"], {}).get("nome"))}
        if alvo in candidatos or any(c.startswith(alvo) for c in candidatos if c):
            return oficial
    return None


def coletar_herois():
    lista = lista_oficial()
    print(f"{len(lista)} heróis no site oficial")
    herois, funcoes, subfuncoes, imagens_wiki = [], {}, {}, set()
    for i, item in enumerate(lista, 1):
        pt = pagina_heroi(item["id"], "pt-br")
        en = pagina_heroi(item["id"], "en-us")
        print(f"[{i:2d}/{len(lista)}] {pt['nome']}")
        try:
            wk = dados_wiki_heroi(en["nome"])
        except LookupError as erro:
            print("   aviso:", erro)
            wk = {"nome_real": None, "vida": 0, "armadura": 0, "escudo": 0, "habilidades": []}

        if pt["funcao"]:
            funcoes.setdefault(item["funcao"], {
                "id": item["funcao"], "nome": pt["funcao"]["nome"], "nome_en": en["funcao"]["nome"],
                "descricao": pt["funcao"]["descricao"], "icone_url": pt["funcao"]["icone_url"]})
        if pt["subfuncao"]:
            subfuncoes.setdefault(item["subfuncao"], {
                "id": item["subfuncao"], "funcao": item["funcao"], "nome": pt["subfuncao"]["nome"],
                "nome_en": en["subfuncao"]["nome"], "descricao": pt["subfuncao"]["descricao"],
                "descricao_en": en["subfuncao"]["descricao"], "icone_url": pt["subfuncao"]["icone_url"]})

        # Junta habilidades: oficiais (pt-BR + ícone) com detalhes da wiki (tipo, recarga...).
        oficiais_en = {h["id"]: h for h in en["habilidades"]}
        habilidades, usadas = [], set()
        for h in wk["habilidades"]:
            oficial = None if h["tipo"].startswith("vantagem") else \
                par_oficial(h["nome_en"], pt["habilidades"], oficiais_en, usadas)
            if oficial:
                usadas.add(oficial["id"])
            imagens_wiki.add(h["imagem_wiki"])
            habilidades.append({
                "id": oficial["id"] if oficial else slug(h["nome_en"]),
                "nome": oficial["nome"] if oficial else None,
                "nome_en": h["nome_en"], "tipo": h["tipo"],
                "descricao": oficial["descricao"] if oficial else None,
                "descricao_en": h["descricao_en"] or (oficiais_en.get(oficial["id"], {}).get("descricao")
                                                       if oficial else None),
                "tecla": h["tecla"], "recarga": h["recarga"], "duracao": h["duracao"],
                "custo_suprema": h["custo_suprema"],
                "icone_url": oficial["icone_url"] if oficial else None,
                "imagem_wiki": h["imagem_wiki"],
            })
        for oficial in pt["habilidades"]:  # oficiais que a wiki não tinha
            if oficial["id"] not in usadas:
                en_h = oficiais_en.get(oficial["id"], {})
                habilidades.append({
                    "id": oficial["id"], "nome": oficial["nome"], "nome_en": en_h.get("nome"),
                    "tipo": None, "descricao": oficial["descricao"],
                    "descricao_en": en_h.get("descricao"), "tecla": None, "recarga": None,
                    "duracao": None, "custo_suprema": None,
                    "icone_url": oficial["icone_url"], "imagem_wiki": None})

        herois.append({
            "id": item["id"], "nome": pt["nome"], "nome_en": en["nome"],
            "funcao": item["funcao"], "subfuncao": item["subfuncao"],
            "descricao": pt["descricao"], "nome_real": wk["nome_real"], "local": pt["local"],
            "vida": wk["vida"], "armadura": wk["armadura"], "escudo": wk["escudo"],
            "novo": item["novo"], "retrato_url": item["retrato_url"],
            "habilidades": habilidades,
        })

    urls = urls_de_arquivos(imagens_wiki, largura=128)
    for heroi in herois:
        for h in heroi["habilidades"]:
            h["imagem_wiki_url"] = urls.get(h.pop("imagem_wiki") or "")
    return herois, list(funcoes.values()), list(subfuncoes.values())


def coletar_mapas():
    lista = mapas_wiki()
    print(f"{len(lista)} mapas no modo padrão")
    nomes_modo = {en: id_ for id_, (_, en, _) in MODOS.items()}
    mapas, imagens = [], {}
    for modo_en, pais, nome_en in lista:
        caixa = next((c for _, c in modelos(wikitexto(nome_en), ["Infobox map"])), {})
        imagens[nome_en] = caixa.get("image", "").strip()
        mapas.append({
            "id": slug(nome_en), "nome": MAPAS_PT.get(nome_en, nome_en), "nome_en": nome_en,
            "modo": nomes_modo[modo_en], "pais": PAISES_PT.get(pais, pais),
            "local_en": limpar_wikitexto(caixa.get("location", "")) or None,
            "lancamento": caixa.get("releasedate", "").strip() or None,
        })
    urls = urls_de_arquivos(imagens.values(), largura=640)
    for mapa in mapas:
        mapa["imagem_url"] = urls.get(imagens[mapa["nome_en"]])

    icones = urls_de_arquivos([f"{en}.png" for _, en, _ in MODOS.values()], largura=128)
    modos = [{"id": id_, "nome": pt, "nome_en": en, "descricao": descricao,
              "icone_url": icones.get(f"{en}.png")}
             for id_, (pt, en, descricao) in MODOS.items()]
    return mapas, modos


def gravar(nome, dados):
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / f"{nome}.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=1), "utf-8")


def main():
    herois, funcoes, subfuncoes = coletar_herois()
    mapas, modos = coletar_mapas()
    gravar("herois", herois)
    gravar("funcoes", {"funcoes": funcoes, "subfuncoes": subfuncoes})
    gravar("mapas", mapas)
    gravar("modos", modos)
    gravar("fontes", {
        "coletado_em": date.today().isoformat(),
        "fontes": [f"{SITE}/pt-br/heroes/", f"{SITE}/en-us/heroes/",
                   "https://overwatch.weirdgloop.org (Overwatch Wiki, CC BY-SA)",
                   f"{SITE}/pt-br/news/patch-notes/ (nomes pt-BR dos mapas)"],
    })
    total = sum(len(h["habilidades"]) for h in herois)
    print(f"ok: {len(herois)} heróis, {total} habilidades/vantagens, {len(funcoes)} funções, "
          f"{len(subfuncoes)} subfunções, {len(mapas)} mapas, {len(modos)} modos")


if __name__ == "__main__":
    sys.exit(main())
