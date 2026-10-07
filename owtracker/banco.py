"""Armazenamento das partidas em SQLite (arquivo local, sem servidor)."""

import sqlite3
from datetime import datetime
from pathlib import Path

from . import catalogo

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

    def obter(self, id_partida):
        return self.con.execute("SELECT * FROM partidas WHERE id = ?", (id_partida,)).fetchone()

    def apagar(self, id_partida):
        with self.con:
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
