"""Armazenamento das partidas em SQLite (arquivo local, sem servidor)."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from . import catalogo, janelas

PASTA_DADOS = Path(__file__).resolve().parent.parent / "dados"
ARQUIVO_BANCO = PASTA_DADOS / "partidas.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS partidas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora  TEXT    NOT NULL,
    heroi      TEXT    NOT NULL,
    mapa       TEXT    NOT NULL,
    modo       TEXT    NOT NULL,
    resultado  TEXT    NOT NULL CHECK (resultado IN ('Vitória', 'Derrota', 'Empate')),
    origem     TEXT    NOT NULL DEFAULT 'manual',
    observacao TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_partidas_data ON partidas (data_hora);

-- Os 10 jogadores da partida, lidos no Tab (aliados e inimigos).
CREATE TABLE IF NOT EXISTS jogadores (
    partida_id   INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
    time         TEXT    NOT NULL CHECK (time IN ('aliados', 'inimigos')),
    posicao      INTEGER NOT NULL,          -- 0 a 4, de cima para baixo
    voce         INTEGER NOT NULL DEFAULT 0,
    heroi_id     TEXT,                      -- NULL = não identificado
    fonte        TEXT,                      -- voce, legendas, retrato, vantagens, corrigido
    nome         TEXT,
    eliminacoes  INTEGER, assistencias INTEGER, mortes INTEGER,
    dano         INTEGER, cura INTEGER, mitigado INTEGER,
    retrato      BLOB,                      -- PNG recortado do placar
    vetor        TEXT,                      -- resumo do retrato (JSON), para reaprender
    vantagens    TEXT,                      -- vantagens escolhidas (JSON: id, nome, tipo)
    simbolos     TEXT,                      -- formas dos ícones lidos (JSON), para renomear
    PRIMARY KEY (partida_id, time, posicao)
);

-- Quantas vezes você usou cada habilidade na partida (teclas + recarga).
CREATE TABLE IF NOT EXISTS habilidades_partida (
    partida_id    INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
    heroi_id      TEXT    NOT NULL,
    habilidade_id TEXT    NOT NULL,
    usos          INTEGER NOT NULL,
    PRIMARY KEY (partida_id, heroi_id, habilidade_id)
);
-- Estatísticas específicas de cada herói (painel do Tab, ver painel.py).
-- As definições vêm de referencia/estatisticas.json e crescem com o que o
-- app lê no jogo; por isso não ficam nas tabelas do catálogo (recriadas).
CREATE TABLE IF NOT EXISTS estatistica_heroi (
    heroi_id TEXT    NOT NULL,
    chave    TEXT    NOT NULL,
    rotulo   TEXT    NOT NULL,
    tipo     TEXT    NOT NULL,   -- num, pct ou tempo (segundos)
    ordem    INTEGER NOT NULL,
    PRIMARY KEY (heroi_id, chave)
);
CREATE TABLE IF NOT EXISTS estatisticas_partida (
    partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
    heroi_id   TEXT    NOT NULL,
    chave      TEXT    NOT NULL,
    valor      REAL    NOT NULL,
    PRIMARY KEY (partida_id, heroi_id, chave)
);
-- Seus heróis na partida, na ordem em que foram jogados (trocas).
CREATE TABLE IF NOT EXISTS herois_partida (
    partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
    ordem      INTEGER NOT NULL,
    heroi_id   TEXT    NOT NULL,
    segundos   INTEGER NOT NULL,
    PRIMARY KEY (partida_id, ordem)
);
"""

# Placar (Tab) da sua linha; vazio (NULL) quando não foi lido.
COLUNAS_PLACAR = ("eliminacoes", "assistencias", "mortes", "dano", "cura", "mitigado")


def _ids(heroi, mapa):
    """(heroi_id, mapa_id) da referência; None quando o nome não é conhecido."""
    h, m = catalogo.heroi(heroi), catalogo.mapa(mapa)
    return (h["id"] if h else None), (m["id"] if m else None)


class Banco:
    def __init__(self, caminho=ARQUIVO_BANCO):
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        # Usado por várias threads (monitor e servidor web): quem chama
        # serializa o acesso (ver servico.Servico.trava).
        self.con = sqlite3.connect(caminho, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)
        self._migrar()
        catalogo.instalar(self.con)
        self._ligar_referencia()
        self._semear_estatisticas()

    def _migrar(self):
        existentes = {linha["name"] for linha in self.con.execute("PRAGMA table_info(partidas)")}
        with self.con:
            for coluna in COLUNAS_PLACAR:
                if coluna not in existentes:
                    self.con.execute(f"ALTER TABLE partidas ADD COLUMN {coluna} INTEGER")
            # Ligação com a referência (tabelas heroi e mapa, ver catalogo.py).
            for coluna in ("heroi_id", "mapa_id"):
                if coluna not in existentes:
                    self.con.execute(f"ALTER TABLE partidas ADD COLUMN {coluna} TEXT")
            de_jogadores = {linha["name"] for linha in self.con.execute("PRAGMA table_info(jogadores)")}
            for coluna in ("vantagens", "simbolos"):
                if coluna not in de_jogadores:
                    self.con.execute(f"ALTER TABLE jogadores ADD COLUMN {coluna} TEXT")

    def _ligar_referencia(self):
        """Preenche heroi_id/mapa_id das partidas que ainda não têm."""
        pendentes = self.con.execute(
            "SELECT id, heroi, mapa FROM partidas WHERE heroi_id IS NULL OR mapa_id IS NULL").fetchall()
        with self.con:
            for p in pendentes:
                self.con.execute("UPDATE partidas SET heroi_id = ?, mapa_id = ? WHERE id = ?",
                                 (*_ids(p["heroi"], p["mapa"]), p["id"]))

    def registrar(self, heroi, mapa, modo, resultado, origem="manual", observacao="", placar=None):
        agora = datetime.now().isoformat(timespec="seconds")
        placar = placar or {}
        valores = [placar.get(c) for c in COLUNAS_PLACAR]
        with self.con:
            cur = self.con.execute(
                "INSERT INTO partidas (data_hora, heroi, mapa, modo, resultado, origem, observacao, "
                + ", ".join(COLUNAS_PLACAR) + ", heroi_id, mapa_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agora, heroi, mapa, modo, resultado, origem, observacao, *valores,
                 *_ids(heroi, mapa)),
            )
        return cur.lastrowid

    def atualizar(self, id_partida, heroi, mapa, modo, resultado):
        with self.con:
            self.con.execute(
                "UPDATE partidas SET heroi = ?, mapa = ?, modo = ?, resultado = ?, "
                "heroi_id = ?, mapa_id = ? WHERE id = ?",
                (heroi, mapa, modo, resultado, *_ids(heroi, mapa), id_partida),
            )

    def definir_placar(self, id_partida, placar):
        """Substitui o placar inteiro (coluna ausente fica vazia)."""
        with self.con:
            self.con.execute(
                f"UPDATE partidas SET {', '.join(c + ' = ?' for c in COLUNAS_PLACAR)} WHERE id = ?",
                (*(placar.get(c) for c in COLUNAS_PLACAR), id_partida),
            )

    def atualizar_placar(self, id_partida, placar):
        colunas = [c for c in COLUNAS_PLACAR if c in placar]
        if not colunas:
            return
        with self.con:
            self.con.execute(
                f"UPDATE partidas SET {', '.join(c + ' = ?' for c in colunas)} WHERE id = ?",
                (*(placar[c] for c in colunas), id_partida),
            )

    # ------------------------------------------------------------ jogadores

    def salvar_jogadores(self, id_partida, times):
        """Grava (substituindo) os dois times lidos no Tab."""
        linhas = []
        for time in ("aliados", "inimigos"):
            for j in times.get(time, []):
                v = j.get("valores", {})
                linhas.append((
                    id_partida, time, j["posicao"], int(bool(j.get("voce"))), j.get("heroi_id"),
                    j.get("fonte"), j.get("nome"), *(v.get(c) for c in COLUNAS_PLACAR),
                    janelas.png_bytes(j["lado"], j["lado"], j["retrato"]), json.dumps(j["vetor"]),
                    json.dumps(j.get("escolhidas", [])), json.dumps(j.get("vantagens", [])),
                ))
        with self.con:
            self.con.execute("DELETE FROM jogadores WHERE partida_id = ?", (id_partida,))
            self.con.executemany(
                "INSERT INTO jogadores (partida_id, time, posicao, voce, heroi_id, fonte, nome, "
                + ", ".join(COLUNAS_PLACAR) + ", retrato, vetor, vantagens, simbolos) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", linhas)

    def jogadores(self, id_partida):
        jogadores = [dict(j) for j in self.con.execute(
            "SELECT partida_id, time, posicao, voce, heroi_id, fonte, nome, vantagens, "
            + ", ".join(COLUNAS_PLACAR) + " FROM jogadores WHERE partida_id = ? "
            "ORDER BY time, posicao", (id_partida,))]
        for j in jogadores:
            j["vantagens"] = json.loads(j["vantagens"] or "[]")
        return jogadores

    def definir_vantagens_jogador(self, id_partida, time, posicao, vantagens):
        with self.con:
            self.con.execute(
                "UPDATE jogadores SET vantagens = ? WHERE partida_id = ? AND time = ? AND posicao = ?",
                (json.dumps(vantagens), id_partida, time, posicao))

    def retrato(self, id_partida, time, posicao):
        linha = self.con.execute(
            "SELECT retrato FROM jogadores WHERE partida_id = ? AND time = ? AND posicao = ?",
            (id_partida, time, posicao)).fetchone()
        return linha["retrato"] if linha else None

    def definir_heroi_jogador(self, id_partida, time, posicao, heroi_id):
        """Corrige o herói de um jogador. Retorna (herói antigo, fonte antiga,
        vetor do retrato, símbolos das vantagens) para reaprender, ou None."""
        linha = self.con.execute(
            "SELECT heroi_id, fonte, vetor, simbolos FROM jogadores "
            "WHERE partida_id = ? AND time = ? AND posicao = ?",
            (id_partida, time, posicao)).fetchone()
        if not linha:
            return None
        with self.con:
            self.con.execute(
                "UPDATE jogadores SET heroi_id = ?, fonte = 'corrigido' "
                "WHERE partida_id = ? AND time = ? AND posicao = ?",
                (heroi_id or None, id_partida, time, posicao))
        return (linha["heroi_id"], linha["fonte"], json.loads(linha["vetor"] or "[]"),
                json.loads(linha["simbolos"] or "[]"))

    # ------------------------------------------------------------ habilidades

    def salvar_habilidades(self, id_partida, usos):
        with self.con:
            self.con.execute("DELETE FROM habilidades_partida WHERE partida_id = ?", (id_partida,))
            self.con.executemany(
                "INSERT INTO habilidades_partida VALUES (?, ?, ?, ?)",
                [(id_partida, u["heroi_id"], u["habilidade_id"], u["usos"]) for u in usos])

    def habilidades_da_partida(self, id_partida):
        return [dict(r) for r in self.con.execute(
            "SELECT heroi_id, habilidade_id, usos FROM habilidades_partida WHERE partida_id = ?",
            (id_partida,))]

    def habilidades_do_heroi(self, heroi_id):
        """Uso de cada habilidade do herói em todas as partidas em que ele foi
        contado: total, média por partida e o máximo numa partida."""
        partidas = self.con.execute(
            "SELECT COUNT(DISTINCT partida_id) FROM habilidades_partida WHERE heroi_id = ?",
            (heroi_id,)).fetchone()[0]
        linhas = [dict(r) for r in self.con.execute(
            "SELECT habilidade_id, SUM(usos) AS total, MAX(usos) AS maximo "
            "FROM habilidades_partida WHERE heroi_id = ? GROUP BY habilidade_id", (heroi_id,))]
        for linha in linhas:
            linha["media"] = round(linha["total"] / partidas, 1) if partidas else 0
        por_partida = [dict(r) for r in self.con.execute(
            "SELECT h.partida_id, p.data_hora, p.resultado, h.habilidade_id, h.usos "
            "FROM habilidades_partida h JOIN partidas p ON p.id = h.partida_id "
            "WHERE h.heroi_id = ? ORDER BY p.data_hora", (heroi_id,))]
        return {"partidas": partidas, "habilidades": linhas, "por_partida": por_partida}

    # ------------------------------------------------------------ estatísticas do herói

    def _semear_estatisticas(self):
        """Definições já mapeadas (referencia/estatisticas.json); as que o app
        aprendeu no jogo continuam."""
        arquivo = catalogo.PASTA / "estatisticas.json"
        if not arquivo.exists():
            return
        with self.con:
            for heroi_id, lista in json.loads(arquivo.read_text("utf-8")).items():
                self.con.executemany(
                    "INSERT OR IGNORE INTO estatistica_heroi VALUES (?, ?, ?, ?, ?)",
                    [(heroi_id, e["chave"], e["rotulo"], e["tipo"], i + 1) for i, e in enumerate(lista)])

    def definicoes_estatisticas(self, heroi_id=None):
        """{heroi_id: [{chave, rotulo, tipo, ordem}]} na ordem do painel."""
        saida = {}
        for r in self.con.execute(
                "SELECT * FROM estatistica_heroi WHERE ? IS NULL OR heroi_id = ? ORDER BY heroi_id, ordem, rotulo",
                (heroi_id, heroi_id)):
            saida.setdefault(r["heroi_id"], []).append(
                {"chave": r["chave"], "rotulo": r["rotulo"], "tipo": r["tipo"], "ordem": r["ordem"]})
        return saida

    def salvar_estatisticas(self, id_partida, estatisticas):
        """Grava (ou atualiza) as estatísticas lidas no painel e aprende as
        definições novas. estatisticas: [{heroi_id, chave, rotulo, valor, tipo, ordem}]."""
        with self.con:
            for e in estatisticas:
                atual = self.con.execute(
                    "SELECT rotulo, tipo FROM estatistica_heroi WHERE heroi_id = ? AND chave = ?",
                    (e["heroi_id"], e["chave"])).fetchone()
                if atual is None:
                    ordem = e["ordem"] or 1 + self.con.execute(
                        "SELECT COALESCE(MAX(ordem), 0) FROM estatistica_heroi WHERE heroi_id = ?",
                        (e["heroi_id"],)).fetchone()[0]
                    self.con.execute("INSERT INTO estatistica_heroi VALUES (?, ?, ?, ?, ?)",
                                     (e["heroi_id"], e["chave"], e["rotulo"], e["tipo"], ordem))
                elif atual["tipo"] != e["tipo"]:
                    continue
                elif len(e["rotulo"]) > len(atual["rotulo"]):  # plural no lugar do singular
                    self.con.execute("UPDATE estatistica_heroi SET rotulo = ? WHERE heroi_id = ? AND chave = ?",
                                     (e["rotulo"], e["heroi_id"], e["chave"]))
                self.con.execute("INSERT OR REPLACE INTO estatisticas_partida VALUES (?, ?, ?, ?)",
                                 (id_partida, e["heroi_id"], e["chave"], e["valor"]))

    def estatisticas_da_partida(self, id_partida):
        return [dict(r) for r in self.con.execute(
            "SELECT v.heroi_id, v.chave, d.rotulo, d.tipo, d.ordem, v.valor "
            "FROM estatisticas_partida v JOIN estatistica_heroi d ON d.heroi_id = v.heroi_id AND d.chave = v.chave "
            "WHERE v.partida_id = ? ORDER BY v.heroi_id, d.ordem, d.rotulo", (id_partida,))]

    def estatisticas_do_heroi(self, heroi_id):
        """Definições do herói e, por partida, os valores e o tempo jogado com
        ele (para as médias por 10 min): {definicoes, partidas: [{partida_id,
        data_hora, resultado, segundos, valores: {chave: valor}}]}."""
        partidas = {}
        for r in self.con.execute(
                "SELECT v.partida_id, p.data_hora, p.resultado, v.chave, v.valor, "
                "  (SELECT SUM(segundos) FROM herois_partida h "
                "    WHERE h.partida_id = v.partida_id AND h.heroi_id = v.heroi_id) AS segundos "
                "FROM estatisticas_partida v JOIN partidas p ON p.id = v.partida_id "
                "WHERE v.heroi_id = ? ORDER BY p.data_hora", (heroi_id,)):
            partida = partidas.setdefault(r["partida_id"], {
                "partida_id": r["partida_id"], "data_hora": r["data_hora"], "resultado": r["resultado"],
                "segundos": r["segundos"], "valores": {}})
            partida["valores"][r["chave"]] = r["valor"]
        return {"definicoes": self.definicoes_estatisticas(heroi_id).get(heroi_id, []),
                "partidas": list(partidas.values())}

    def partidas_com_estatisticas(self):
        return {r[0] for r in self.con.execute("SELECT DISTINCT partida_id FROM estatisticas_partida")}

    def salvar_herois(self, id_partida, herois):
        with self.con:
            self.con.execute("DELETE FROM herois_partida WHERE partida_id = ?", (id_partida,))
            self.con.executemany(
                "INSERT INTO herois_partida VALUES (?, ?, ?, ?)",
                [(id_partida, i, h["heroi_id"], h["segundos"]) for i, h in enumerate(herois)])

    def herois_das_partidas(self):
        """{partida_id: [{heroi_id, segundos}]} em ordem."""
        saida = {}
        for r in self.con.execute(
                "SELECT partida_id, heroi_id, segundos FROM herois_partida ORDER BY partida_id, ordem"):
            saida.setdefault(r[0], []).append({"heroi_id": r[1], "segundos": r[2]})
        return saida

    def partidas_com_habilidades(self):
        return {r[0] for r in self.con.execute("SELECT DISTINCT partida_id FROM habilidades_partida")}

    def partidas_com_jogadores(self):
        return {r[0] for r in self.con.execute("SELECT DISTINCT partida_id FROM jogadores")}

    def obter(self, id_partida):
        return self.con.execute("SELECT * FROM partidas WHERE id = ?", (id_partida,)).fetchone()

    def apagar(self, id_partida):
        with self.con:
            self.con.execute("DELETE FROM jogadores WHERE partida_id = ?", (id_partida,))
            self.con.execute("DELETE FROM habilidades_partida WHERE partida_id = ?", (id_partida,))
            self.con.execute("DELETE FROM herois_partida WHERE partida_id = ?", (id_partida,))
            self.con.execute("DELETE FROM estatisticas_partida WHERE partida_id = ?", (id_partida,))
            self.con.execute("DELETE FROM partidas WHERE id = ?", (id_partida,))

    def listar_completo(self):
        """Todas as partidas já cruzadas com a referência (view vw_partidas)."""
        return [dict(p) for p in self.con.execute(
            "SELECT * FROM vw_partidas ORDER BY data_hora DESC, id DESC")]

    def listar(self, limite=500):
        return self.con.execute(
            "SELECT * FROM partidas ORDER BY data_hora DESC, id DESC LIMIT ?", (limite,)
        ).fetchall()

    def resumo_por(self, coluna):
        """Vitórias/derrotas/empates agrupados por 'heroi', 'mapa' ou 'modo'."""
        if coluna not in ("heroi", "mapa", "modo"):
            raise ValueError(coluna)
        return self.con.execute(
            f"""
            SELECT {coluna} AS chave,
                   COUNT(*) AS total,
                   SUM(resultado = 'Vitória') AS vitorias,
                   SUM(resultado = 'Derrota') AS derrotas,
                   SUM(resultado = 'Empate')  AS empates,
                   AVG(eliminacoes) AS media_eliminacoes,
                   AVG(mortes)      AS media_mortes,
                   AVG(dano)        AS media_dano,
                   AVG(cura)        AS media_cura,
                   AVG(mitigado)    AS media_mitigado
            FROM partidas
            GROUP BY {coluna}
            ORDER BY total DESC, chave
            """
        ).fetchall()

    def resumo_geral(self):
        return self.con.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(resultado = 'Vitória'), 0) AS vitorias,
                   COALESCE(SUM(resultado = 'Derrota'), 0) AS derrotas,
                   COALESCE(SUM(resultado = 'Empate'), 0)  AS empates
            FROM partidas
            """
        ).fetchone()

    def ultimo(self):
        return self.con.execute(
            "SELECT * FROM partidas ORDER BY id DESC LIMIT 1"
        ).fetchone()


def taxa_vitoria(vitorias, derrotas):
    """Winrate ignorando empates, como o próprio jogo faz."""
    decididas = vitorias + derrotas
    return (vitorias / decididas * 100) if decididas else 0.0
