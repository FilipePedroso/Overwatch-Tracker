"""Catálogo de referência do jogo: heróis, habilidades, funções, subfunções,
mapas e modos de mapa (dados em owtracker/referencia/*.json, gerados por
ferramentas/coletar_referencia.py).

Também instala essas informações como tabelas no banco das partidas, para
cruzar com o histórico (ver instalar()).
"""

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "referencia"

# Nomes antigos/alternativos que podem estar no histórico ou na tela.
APELIDOS_EXTRAS_HEROIS = {"soldier-76": ["Soldier 76"]}
APELIDOS_EXTRAS_MAPAS = {"lijiang-tower": ["Torre de Lijiang"]}


def normalizar(texto):
    """'Soldado: 76' -> 'soldado76'; 'Oásis' -> 'oasis'."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem_acento if c.isalnum()).lower()


def _ler(nome):
    return json.loads((PASTA / f"{nome}.json").read_text("utf-8"))


@lru_cache(maxsize=None)
def carregar():
    funcoes = _ler("funcoes")
    return {
        "herois": _ler("herois"), "mapas": _ler("mapas"), "modos": _ler("modos"),
        "funcoes": funcoes["funcoes"], "subfuncoes": funcoes["subfuncoes"],
        "fontes": _ler("fontes"),
    }


@lru_cache(maxsize=None)
def _indices():
    c = carregar()
    herois, mapas = {}, {}
    for h in c["herois"]:
        for nome in [h["nome"], h["nome_en"], h["id"], *APELIDOS_EXTRAS_HEROIS.get(h["id"], [])]:
            herois.setdefault(normalizar(nome), h)
    for m in c["mapas"]:
        for nome in _nomes_do_mapa(m):
            mapas.setdefault(normalizar(nome), m)
    return herois, mapas


def _nomes_do_mapa(m):
    """Nomes pelos quais o mapa pode aparecer. O placar do jogo às vezes mostra
    só a parte depois dos dois-pontos ('GRÍMSVÖTN' para 'Observatório: Grímsvötn')."""
    nomes = [m["nome"], m["nome_en"], m["id"], *APELIDOS_EXTRAS_MAPAS.get(m["id"], [])]
    curtos = [n.split(":", 1)[1].strip() for n in (m["nome"], m["nome_en"]) if ":" in n]
    return nomes + [c for c in curtos if len(c) >= 5]


def heroi(nome):
    """Herói pelo nome em pt-BR, inglês ou id; None se não existir."""
    return _indices()[0].get(normalizar(nome))


def mapa(nome):
    return _indices()[1].get(normalizar(nome))


def apelidos_herois():
    """{nome pt-BR: [outros nomes]} para o detector reconhecer na tela."""
    return {h["nome"]: [h["nome_en"], *APELIDOS_EXTRAS_HEROIS.get(h["id"], [])]
            for h in carregar()["herois"]}


def apelidos_mapas():
    return {m["nome"]: [n for n in _nomes_do_mapa(m) if n != m["nome"]] for m in carregar()["mapas"]}


# ---------------------------------------------------------------- banco

ESQUEMA = """
DROP VIEW  IF EXISTS vw_partidas;
DROP TABLE IF EXISTS habilidade;
DROP TABLE IF EXISTS heroi;
DROP TABLE IF EXISTS subfuncao;
DROP TABLE IF EXISTS funcao;
DROP TABLE IF EXISTS mapa;
DROP TABLE IF EXISTS modo_mapa;

CREATE TABLE funcao (
    id TEXT PRIMARY KEY, nome TEXT, nome_en TEXT, descricao TEXT, icone_url TEXT);
CREATE TABLE subfuncao (
    id TEXT PRIMARY KEY, funcao_id TEXT REFERENCES funcao(id), nome TEXT, nome_en TEXT,
    descricao TEXT, descricao_en TEXT, icone_url TEXT);
CREATE TABLE heroi (
    id TEXT PRIMARY KEY, nome TEXT, nome_en TEXT,
    funcao_id TEXT REFERENCES funcao(id), subfuncao_id TEXT REFERENCES subfuncao(id),
    descricao TEXT, nome_real TEXT, local TEXT, vida INTEGER, armadura INTEGER,
    escudo INTEGER, novo INTEGER, retrato_url TEXT);
CREATE TABLE habilidade (
    heroi_id TEXT REFERENCES heroi(id), id TEXT, ordem INTEGER, nome TEXT, nome_en TEXT,
    tipo TEXT, descricao TEXT, descricao_en TEXT, tecla TEXT, recarga TEXT, duracao TEXT,
    custo_suprema TEXT, icone_url TEXT, imagem_wiki_url TEXT,
    PRIMARY KEY (heroi_id, id));
CREATE TABLE modo_mapa (
    id TEXT PRIMARY KEY, nome TEXT, nome_en TEXT, descricao TEXT, icone_url TEXT);
CREATE TABLE mapa (
    id TEXT PRIMARY KEY, nome TEXT, nome_en TEXT, modo_id TEXT REFERENCES modo_mapa(id),
    pais TEXT, local_en TEXT, lancamento TEXT, imagem_url TEXT);

-- Histórico já cruzado com a referência (função, subfunção, modo do mapa).
CREATE VIEW vw_partidas AS
SELECT p.*,
       h.nome  AS heroi_nome,  f.nome  AS funcao,  s.nome AS subfuncao,
       m.nome  AS mapa_nome,   mm.nome AS modo_mapa
FROM partidas p
LEFT JOIN heroi     h  ON h.id  = p.heroi_id
LEFT JOIN funcao    f  ON f.id  = h.funcao_id
LEFT JOIN subfuncao s  ON s.id  = h.subfuncao_id
LEFT JOIN mapa      m  ON m.id  = p.mapa_id
LEFT JOIN modo_mapa mm ON mm.id = m.modo_id;
"""


def instalar(con):
    """(Re)cria as tabelas de referência no banco e preenche a partir dos JSON.
    É rápido (poucas centenas de linhas) e roda a cada abertura do app, então
    o banco sempre reflete a versão atual de owtracker/referencia/."""
    c = carregar()
    with con:
        con.executescript(ESQUEMA)
        con.executemany("INSERT INTO funcao VALUES (?,?,?,?,?)", [
            (f["id"], f["nome"], f["nome_en"], f["descricao"], f["icone_url"]) for f in c["funcoes"]])
        con.executemany("INSERT INTO subfuncao VALUES (?,?,?,?,?,?,?)", [
            (s["id"], s["funcao"], s["nome"], s["nome_en"], s["descricao"], s["descricao_en"],
             s["icone_url"]) for s in c["subfuncoes"]])
        con.executemany("INSERT INTO heroi VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (h["id"], h["nome"], h["nome_en"], h["funcao"], h["subfuncao"], h["descricao"],
             h["nome_real"], h["local"], h["vida"], h["armadura"], h["escudo"], int(h["novo"]),
             h["retrato_url"]) for h in c["herois"]])
        con.executemany("INSERT OR IGNORE INTO habilidade VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (h["id"], a["id"], i, a["nome"], a["nome_en"], a["tipo"], a["descricao"],
             a["descricao_en"], a["tecla"], a["recarga"], a["duracao"], a["custo_suprema"],
             a["icone_url"], a.get("imagem_wiki_url"))
            for h in c["herois"] for i, a in enumerate(h["habilidades"])])
        con.executemany("INSERT INTO modo_mapa VALUES (?,?,?,?,?)", [
            (m["id"], m["nome"], m["nome_en"], m["descricao"], m["icone_url"]) for m in c["modos"]])
        con.executemany("INSERT INTO mapa VALUES (?,?,?,?,?,?,?,?)", [
            (m["id"], m["nome"], m["nome_en"], m["modo"], m["pais"], m["local_en"],
             m["lancamento"], m["imagem_url"]) for m in c["mapas"]])
