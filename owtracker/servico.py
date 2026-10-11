"""O "cérebro" do app em segundo plano: liga o monitor do jogo ao banco e
guarda o estado que a interface web consulta (ver servidor.py).

Tudo que mexe no banco passa pela trava: o monitor e o servidor rodam em
threads diferentes.
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from . import catalogo, dados, habilidades, retratos, sistema
from .banco import COLUNAS_PLACAR, Banco
from .monitor import PASTA_DIAGNOSTICO, Monitor, salvar_config


class Servico:
    def __init__(self):
        self.trava = threading.RLock()
        self.sair = threading.Event()
        self.reiniciar = False       # sair para abrir de novo (código atualizado)
        self.inicio = time.time()
        self.banco = Banco()
        self.versao = 0              # muda quando o histórico muda (a interface recarrega)
        self.status_monitor = "Iniciando…"
        self.parcial = None          # partida em andamento
        self.pendente = None         # partida que acabou sem o resultado lido
        self.aviso = None            # última notícia para a interface: {texto, quando}
        self.ultimo_auto_id = None   # recebe o placar final do Tab aberto depois do fim
        self._extras_pendentes = None  # Registro da partida pendente (times, habilidades, heróis)
        self.monitor = Monitor(
            avisar=self._ao_status, ao_registrar=self._ao_registrar,
            ao_atualizar=self._ao_parcial, ao_corrigir_placar=self._ao_placar_final)
        self._estatisticas_conhecidas()

    def iniciar(self):
        self.monitor.start()

    def parar(self):
        self.monitor.parar()

    # ------------------------------------------------------------ eventos do monitor

    def _noticia(self, texto):
        self.aviso = {"texto": texto, "quando": datetime.now().isoformat(timespec="seconds")}

    def _ao_status(self, texto):
        self.status_monitor = texto

    def _ao_parcial(self, parcial):
        self.parcial = parcial

    def _ao_registrar(self, r):
        with self.trava:
            if r.resultado is None:
                # Vimos a tela pós-partida, mas não o resultado: a interface pergunta.
                self.ultimo_auto_id = None
                self.pendente = {"heroi": r.heroi, "mapa": r.mapa, "modo": r.modo, "placar": r.placar,
                                 "observacao": ""}
                self._extras_pendentes = r
                self._noticia("A partida terminou, mas não li o resultado: confirme no app.")
                return
            self.ultimo_auto_id = self.banco.registrar(
                r.heroi, r.mapa, r.modo, r.resultado, origem="auto",
                placar=r.placar)
            self._salvar_extras(self.ultimo_auto_id, r)
            self.versao += 1
            self._noticia(f"Registrada: {r.resultado} · {r.heroi} · {r.mapa}")

    def _ao_placar_final(self, placar, times=None, estatisticas=None):
        with self.trava:
            if self.ultimo_auto_id:
                self.banco.atualizar_placar(self.ultimo_auto_id, placar)
                if times:  # Tab depois do fim: os números finais de todo mundo
                    self.banco.salvar_jogadores(self.ultimo_auto_id, times)
                if estatisticas:  # idem para o painel do herói
                    self.banco.salvar_estatisticas(self.ultimo_auto_id, estatisticas)
                    self._estatisticas_conhecidas()
                self.versao += 1
                self._noticia("Placar final atualizado pelo Tab depois do fim da partida.")

    # ------------------------------------------------------------ consultas

    def estado(self):
        config = self.monitor.config
        return {
            "versao": self.versao, "monitor": self.status_monitor, "parcial": self.parcial,
            "pendente": self.pendente, "aviso": self.aviso,
            "inicio": self.inicio, "atualizacao": codigo_mudou_desde(self.inicio),
            "ajustes": {"nome_jogador": config["nome_jogador"], "diagnostico": config["diagnostico"],
                        "iniciar_com_windows": sistema.inicia_com_windows()},
        }

    def partidas(self):
        with self.trava:
            partidas = self.banco.listar_completo()
            com_times = self.banco.partidas_com_jogadores()
            com_habilidades = self.banco.partidas_com_habilidades()
            herois = self.banco.herois_das_partidas()
            com_estatisticas = self.banco.partidas_com_estatisticas()
        for p in partidas:
            p["tem_estatisticas"] = p["id"] in com_estatisticas
            p["herois"] = herois.get(p["id"], [])
            p["tem_times"] = p["id"] in com_times
            p["tem_habilidades"] = p["id"] in com_habilidades
        return partidas

    def inimigos(self):
        with self.trava:
            return self.banco.inimigos_das_partidas()

    def estatisticas_da_partida(self, id_partida):
        with self.trava:
            return self.banco.estatisticas_da_partida(id_partida)

    def estatisticas_do_heroi(self, heroi_id):
        with self.trava:
            return self.banco.estatisticas_do_heroi(heroi_id)

    def habilidades_da_partida(self, id_partida):
        with self.trava:
            return self.banco.habilidades_da_partida(id_partida)

    def habilidades_do_heroi(self, heroi_id):
        with self.trava:
            return self.banco.habilidades_do_heroi(heroi_id)

    def jogadores(self, id_partida):
        with self.trava:
            return self.banco.jogadores(id_partida)

    def retrato(self, id_partida, time, posicao):
        with self.trava:
            return self.banco.retrato(id_partida, time, posicao)

    def corrigir_jogador(self, id_partida, time, posicao, heroi_id):
        """Corrige o herói de um jogador e ensina a biblioteca de retratos:
        da próxima vez, esse retrato (essa skin) é reconhecido sozinho."""
        if heroi_id and not catalogo.heroi(heroi_id):
            raise ValueError("Herói desconhecido.")
        biblioteca = self.monitor.biblioteca
        with self.trava:
            anterior = self.banco.definir_heroi_jogador(id_partida, time, posicao, heroi_id)
            if anterior is None:
                raise ValueError("Jogador não encontrado.")
            heroi_antigo, _, vetor, simbolos = anterior
            if heroi_antigo and heroi_antigo != heroi_id:
                biblioteca.esquecer(heroi_antigo, vetor)
            if heroi_id:
                biblioteca.aprender(heroi_id, vetor)
            biblioteca.salvar()
            # Com o herói certo, os ícones lidos viram as vantagens certas.
            self.banco.definir_vantagens_jogador(id_partida, time, posicao,
                                                 retratos.nomear_vantagens(heroi_id, simbolos))

    def catalogo(self):
        return catalogo_web()

    # ------------------------------------------------------------ ações da interface

    def salvar_partida(self, campos, id_partida=None):
        heroi, mapa = campos["heroi"].strip(), campos["mapa"].strip()
        modo, resultado = campos["modo"].strip(), campos["resultado"]
        if not heroi or not mapa or resultado not in dados.RESULTADOS:
            raise ValueError("Preencha herói, mapa e resultado.")
        placar = {c: int(campos[c]) for c in COLUNAS_PLACAR if str(campos.get(c, "")).strip() != ""}
        with self.trava:
            if id_partida is None:
                id_partida = self.banco.registrar(heroi, mapa, modo, resultado, origem="manual",
                                                  observacao=campos.get("observacao", ""), placar=placar)
            else:
                self.banco.atualizar(id_partida, heroi, mapa, modo, resultado)
                self.banco.definir_placar(id_partida, placar)
            self.versao += 1
        return id_partida

    def apagar_partida(self, id_partida):
        with self.trava:
            self.banco.apagar(id_partida)
            self.versao += 1

    def confirmar_pendente(self, resultado):
        """Grava a partida que acabou sem resultado lido (ou descarta, com None)."""
        with self.trava:
            p, self.pendente = self.pendente, None
            extras, self._extras_pendentes = self._extras_pendentes, None
            if p and resultado in dados.RESULTADOS:
                self.ultimo_auto_id = self.banco.registrar(
                    p["heroi"], p["mapa"], p["modo"], resultado, origem="auto",
                    observacao=p["observacao"], placar=p["placar"])
                if extras:
                    self._salvar_extras(self.ultimo_auto_id, extras)
                self.versao += 1

    def _salvar_extras(self, id_partida, r):
        """Times, uso de habilidades e linha do tempo de heróis de um Registro."""
        if r.times:
            self.banco.salvar_jogadores(id_partida, r.times)
        if r.habilidades:
            self.banco.salvar_habilidades(id_partida, r.habilidades)
        if r.herois:
            self.banco.salvar_herois(id_partida, r.herois)
        if r.estatisticas:
            self.banco.salvar_estatisticas(id_partida, r.estatisticas)
            self._estatisticas_conhecidas()

    def _estatisticas_conhecidas(self):
        """Entrega ao detector o que o banco já conhece do painel de cada herói
        (chave -> tipo): ele confere o tipo e aceita na primeira leitura."""
        conhecidas = self.monitor.detector.estatisticas_conhecidas
        conhecidas.clear()
        for heroi_id, lista in self.banco.definicoes_estatisticas().items():
            conhecidas[heroi_id] = {e["chave"]: e["tipo"] for e in lista}

    def descartar_andamento(self):
        self.monitor.descartar_partida()
        self.parcial = None

    def ajustar(self, campos):
        config = self.monitor.config
        if "nome_jogador" in campos:
            self.monitor.definir_nome(campos["nome_jogador"].split("#")[0].strip().upper())
        if "diagnostico" in campos:
            config["diagnostico"] = bool(campos["diagnostico"])
            salvar_config(config)
        if "iniciar_com_windows" in campos:
            sistema.definir_iniciar_com_windows(bool(campos["iniciar_com_windows"]))

    def abrir_pasta_diagnostico(self):
        sistema.abrir_pasta(PASTA_DIAGNOSTICO)


PASTA_CODIGO = Path(__file__).resolve().parent
ATUALIZACAO_ASSENTADA = 20  # s sem nenhum arquivo mudar antes de avisar


def codigo_mudou_desde(instante):
    """O app foi atualizado depois que abriu e a atualização já terminou?

    Conta o código Python e o catálogo (o reconhecimento durante a partida só
    os relê ao reiniciar; a interface web/ é relida a cada F5). Só avisa quando
    nada mudou nos últimos ATUALIZACAO_ASSENTADA segundos: reiniciar no meio de
    uma atualização aplicaria só parte dela (e pediria um segundo reinício)."""
    arquivos = [*PASTA_CODIGO.glob("*.py"), *catalogo.PASTA.glob("*.json")]
    mais_recente = max(a.stat().st_mtime for a in arquivos)
    return mais_recente > instante + 1 and time.time() - mais_recente > ATUALIZACAO_ASSENTADA




_CATALOGO_WEB = None
_VERSAO_CATALOGO = None


def _versao_arquivos():
    """Data de modificação dos arquivos do catálogo e do índice de imagens."""
    arquivos = list(catalogo.PASTA.glob("*.json")) + [catalogo.PASTA / "assets" / "indice.json"]
    return tuple(a.stat().st_mtime if a.exists() else 0 for a in arquivos)


def catalogo_web():
    """Catálogo enxuto para a interface, com o caminho local de cada imagem
    (ou a URL original, se os assets não foram baixados). É refeito quando
    os arquivos mudam (nova coleta ou novos assets), sem reiniciar o app."""
    global _CATALOGO_WEB, _VERSAO_CATALOGO
    versao = _versao_arquivos()
    if _CATALOGO_WEB is not None and versao == _VERSAO_CATALOGO:
        return _CATALOGO_WEB
    _VERSAO_CATALOGO = versao
    catalogo.carregar.cache_clear()
    catalogo._indices.cache_clear()  # o banco também passa a ligar partidas aos itens novos
    c = catalogo.carregar()
    try:
        indice = json.loads((catalogo.PASTA / "assets" / "indice.json").read_text("utf-8"))
    except (OSError, ValueError):
        indice = {}

    def imagem(chave, url):
        return "/" + indice[chave] if chave in indice else url

    _CATALOGO_WEB = {
        "funcoes": [{"id": f["id"], "nome": f["nome"], "descricao": f["descricao"],
                     "icone": imagem(f"funcoes/{f['id']}", f["icone_url"])} for f in c["funcoes"]],
        "subfuncoes": [{"id": s["id"], "nome": s["nome"], "funcao": s["funcao"], "descricao": s["descricao"],
                        "icone": imagem(f"subfuncoes/{s['id']}", s["icone_url"])} for s in c["subfuncoes"]],
        "modos": [{"id": m["id"], "nome": m["nome"], "descricao": m["descricao"],
                   "icone": imagem(f"modos/{m['id']}", m["icone_url"])} for m in c["modos"]],
        "mapas": [{"id": m["id"], "nome": m["nome"], "nome_en": m["nome_en"], "modo": m["modo"],
                   "pais": m["pais"], "lancamento": m["lancamento"],
                   "imagem": imagem(f"mapas/{m['id']}", m["imagem_url"])}
                  for m in c["mapas"]],
        "herois": [{
            "id": h["id"], "nome": h["nome"], "nome_en": h["nome_en"], "funcao": h["funcao"],
            "subfuncao": h["subfuncao"], "descricao": h["descricao"], "nome_real": h["nome_real"],
            "local": h["local"], "vida": h["vida"], "armadura": h["armadura"], "escudo": h["escudo"],
            "novo": h["novo"], "retrato": imagem(f"herois/{h['id']}", h["retrato_url"]),
            "habilidades": [{
                "id": a["id"], "nome": a["nome"] or a["nome_en"], "nome_en": a["nome_en"], "tipo": a["tipo"],
                "descricao": a["descricao"] or a["descricao_en"], "tecla": a["tecla"],
                "recarga": a["recarga"],
                "icone": imagem(f"habilidades/{h['id']}__{a['id']}", a["icone_url"] or a.get("imagem_wiki_url")),
            } for a in h["habilidades"]],
            # Habilidades contadas pelas teclas (ver habilidades.py)
            "rastreaveis": [{**r, "tecla_nome": habilidades.NOME_DA_TECLA[r["tecla"]]}
                            for r in habilidades.rastreaveis(h["id"])],
        } for h in c["herois"]],
        "modos_fila": dados.MODOS,
        "resultados": dados.RESULTADOS,
    }
    return _CATALOGO_WEB
