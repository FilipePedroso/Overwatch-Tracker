"""Interpreta o texto lido da tela e decide quando uma partida terminou.

Não depende de captura nem de OCR: recebe linhas de texto com posição e
tamanho, o que permite testar com dados falsos ou com o log de diagnóstico.

O que observamos nas partidas reais (jogo em pt-BR, legendas ligadas):
- Os títulos do jogo usam uma fonte estilizada que o OCR do Windows não lê
  ("ROADHOG" vira "ROBOHOCO"). Textos em fonte comum ele lê bem.
- LEGENDAS: "[FILIPE (ROADHOG)] Na trilha." -> jogador e herói.
  Falas de inimigos aparecem só como "[HAZARD]", sem nome de jogador.
- Fim de partida: "[ATHENA] Derrota." / "[ATHENA] Vitória."
  (rodadas aparecem como "Rodada 2 perdida", que não confundem).
- Chat: "Filipe (Roadhog): Olá!" e "Ferb trocou para Tracer (era Genji)."
- Placar (Tab): "CONTROLE - COMPETITIVO | NEPAL" -> mapa e modo.
- Tela pós-partida: abas "RESUMO" e "RECOMPENSAS".
"""

import difflib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import catalogo, dados
from .placar import ler_placar, ler_times, tela_do_placar
from .habilidades import rastreaveis, suprema_pronta
from .retratos import FUNCAO_POR_POSICAO, identificar, reconhecer_vantagens

TAMANHO_MIN_RESULTADO = 0.035  # altura mínima de VITÓRIA/DERROTA grande, em fração da tela
ESPERA_POS_RESULTADO = 60      # s ignorando resultados depois de registrar
MAPA_ANTIGO = 180              # s sem ver o mapa: outro mapa = nova partida
MESMO_TAB = 15                 # s: leituras do placar tão próximas são o mesmo Tab aberto
PARTIDA_PARADA = 900           # s sem novidade: a partida em andamento é descartada
LEITURAS_MAPA_NOVO = 3         # leituras do Tab para aceitar um mapa fora do catálogo
INTERVALO_TIMES = 2.5          # s entre leituras completas dos dois times no Tab
TEMPO_MORTO = 3.5              # s sem contar habilidades depois de ver "RESSURGIR EM"
MESMA_FALA = 20                # s: o mesmo texto visto de novo antes disso é a mesma fala na tela
SEMELHANCA_FALA = 0.75         # textos lidos tão parecidos são a mesma fala (o OCR varia)
CONFIRMA_HEROI = 2             # peso para aceitar um herói seu (2 falas, ou Tab/troca)
DESISTIR_CANDIDATO = 90        # s: herói novo visto uma vez e nunca confirmado é descartado
                               # (a tela inteira é lida a cada ~3 s)
# Telas que não são partida (texto compactado, ver compactar()).
TEXTOS_FORA_DE_PARTIDA = ("campodetreinamento", "practicerange")

CONFUSOES_OCR = str.maketrans({"l": "i", "1": "i", "0": "o"})

# "[FILIPE (ROADHOG)]", "Filipe (Roadhog): Olá!", "[FILIPE( OAAHQG)]"...
# BattleTags não têm espaço, então o nome é uma palavra só, colada ao "(".
RE_FALA = re.compile(r"(\w{2,16})\s*\(\s*([^()\[\]]{2,16})")
RE_TROCA = re.compile(r"(\w{2,16})\s+trocou\s+para\s+(.{2,20}?)\s*\(\s*era", re.IGNORECASE)


def morto(texto):
    """'RESSURGIRÁ EM' (contagem para voltar); o OCR costuma ler torto,
    tipo 'RISSURGIM[M', então a comparação é aproximada."""
    t = compactar(texto)
    return "ssurg" in t or difflib.SequenceMatcher(None, t, compactar("ressurgira em")).ratio() >= 0.7


def compactar(texto):
    """'Soldado: 76' -> 'soidado76'; 'V I T Ó R I A' -> 'vitoria'.

    Remove acentos, espaços e pontuação, e iguala letras que o OCR confunde
    (l/I/1 e 0/O). Os nomes conhecidos passam pela mesma função, então a
    comparação continua justa.
    """
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if c.isalnum()).lower().translate(CONFUSOES_OCR)


def _indice(principal, apelidos):
    indice = {}
    for nome in principal:
        indice[compactar(nome)] = nome
        for apelido in apelidos.get(nome, []):
            indice[compactar(apelido)] = nome
    return indice


INDICE_MAPAS = _indice(dados.lista_mapas(), dados.APELIDOS_MAPAS)
INDICE_HEROIS = _indice(dados.lista_herois(), dados.APELIDOS_HEROIS)
INDICE_RESULTADOS = {compactar(p): r for r, ps in dados.PALAVRAS_RESULTADO.items() for p in ps}
INDICE_MODOS = {compactar(p): m for m, ps in dados.PALAVRAS_MODO.items() for p in ps}


def similaridade(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def achar_exato_ou_parecido(texto, indice, tamanho_min_parecido=5, minimo=0.8):
    """Nome cuja forma compacta é igual (ou quase, para nomes longos) ao texto."""
    if texto in indice:
        return indice[texto]
    if len(texto) >= tamanho_min_parecido:
        for chave, nome in indice.items():
            if len(chave) >= tamanho_min_parecido and abs(len(chave) - len(texto)) <= 2 \
                    and similaridade(texto, chave) >= minimo:
                return nome
    return None


def achar_contido(texto, indice):
    """Nome contido no texto (ex.: 'controiecompetitivonepai' contém 'nepai')."""
    melhor = None
    for chave, nome in indice.items():
        if len(chave) >= 4 and chave in texto and (melhor is None or len(chave) > len(melhor[0])):
            melhor = (chave, nome)
    return melhor[1] if melhor else achar_exato_ou_parecido(texto, indice)


def heroi_no_inicio(texto):
    """Herói no começo do texto, tolerando erros de OCR e lixo depois.

    'ROADkOG' -> Roadhog; 'ROADHOGfi Já tava' -> Roadhog; 'era Emre' -> None.
    """
    alvo = compactar(texto)
    melhor, melhor_nota = None, 0.0
    for chave, nome in INDICE_HEROIS.items():
        inicio = alvo[:len(chave)]
        if len(chave) <= 4:
            nota = 1.0 if inicio == chave else 0.0  # nomes curtos: só exato
        else:
            nota = similaridade(inicio, chave)
        if nota > melhor_nota:
            melhor, melhor_nota = nome, nota
    return melhor if melhor_nota >= 0.8 else None


def resultado_da_narradora(texto):
    """'[ATHENA] Derrota.' -> 'Derrota'. Frases de rodada não contam."""
    alvo = compactar(texto)
    posicao = alvo.find("athena")
    if posicao < 0:
        return None
    resto = alvo[posicao + len("athena"):]
    return achar_exato_ou_parecido(resto, INDICE_RESULTADOS, 6) if resto else None


def fala_nova(recentes, agora, texto):
    """True se o texto não é a mesma fala vista há pouco (ela fica alguns
    segundos na tela e o chat a mantém ainda mais). recentes: [(instante, texto)]
    que esta função atualiza."""
    # Só o que foi dito, sem "[FILIPE (SOMBRA)]": falas diferentes do mesmo
    # herói têm esse começo igual.
    chave = compactar(texto.split(")", 1)[-1]) or compactar(texto)
    recentes[:] = [(t, x) for t, x in recentes if agora - t < MESMA_FALA]
    for i, (t, x) in enumerate(recentes):
        if x == chave or similaridade(x, chave) >= SEMELHANCA_FALA:
            recentes[i] = (agora, x)  # ainda na tela: renova
            return False
    recentes.append((agora, chave))
    return True


def mesmo_nome(a, b):
    a, b = compactar(a), compactar(b)
    return a == b or (min(len(a), len(b)) >= 4 and similaridade(a, b) >= 0.8)


INDICE_MODOS_MAPA = {compactar(n) for m in catalogo.carregar()["modos"] for n in (m["nome"], m["nome_en"])}
# O OCR lê a barra do cabeçalho "ESCOLTA | GRÍMSVÖTN" como "|", "I", "l" ou "1".
RE_SEPARADOR = re.compile(r"\s+[|Il1]\s+")


def mapa_do_cabecalho(linhas, altura):
    """Nome do mapa no cabeçalho do Tab: "ESCOLTA | GRÍMSVÖTN",
    "CONTROLE - COMPETITIVO | NEPAL". Começa por um modo de mapa conhecido."""
    for linha in linhas:
        if linha.y > altura * 0.08:
            continue
        partes = RE_SEPARADOR.split(linha.texto.strip())
        if len(partes) < 2 or not any(compactar(partes[0]).startswith(m) for m in INDICE_MODOS_MAPA):
            continue
        nome = partes[-1].strip(" :|-")
        if len(compactar(nome)) >= 4:
            return nome
    return None


def parece_mapa_conhecido(nome):
    alvo = compactar(nome)
    return any(similaridade(alvo, chave) >= 0.5 for chave in INDICE_MAPAS)


def _seus_valores(times):
    return next((j["valores"] for j in times["aliados"] if j["voce"]), {})


def coerente(novo, anterior):
    """Os números do placar só sobem durante a partida. Se 2+ colunas
    diminuíram, a leitura é de outra linha (ex.: mouse sobre outro jogador).
    Uma coluna só pode ser erro de leitura da anterior, então é tolerada."""
    return sum(1 for c, v in novo.items() if c in anterior and v < anterior[c]) < 2


class LeiturasPlacar:
    """Leituras do placar (Tab) de uma partida."""

    def __init__(self):
        self.leituras = []  # [(quando, {coluna: valor})]

    def adicionar(self, placar, agora):
        self.leituras.append((agora, placar))

    def final(self):
        """Valores do último Tab aberto. Em cada coluna vale o valor mais
        repetido entre as leituras desse Tab (uma leitura errada isolada não
        ganha); empate fica com o mais recente. Coluna não lida nesse Tab fica
        vazia: um valor de um Tab anterior estaria desatualizado."""
        if not self.leituras:
            return {}
        ultimo = self.leituras[-1][0]
        recentes = [placar for quando, placar in self.leituras if ultimo - quando <= MESMO_TAB]
        resultado = {}
        for coluna in {c for placar in recentes for c in placar}:
            valores = [placar[coluna] for placar in reversed(recentes) if coluna in placar]
            contagem = Counter(valores)
            resultado[coluna] = max(valores, key=lambda v: contagem[v])  # empate: o 1º (mais recente)
        return resultado


@dataclass
class Partida:
    mapas: Counter = field(default_factory=Counter)
    modos: Counter = field(default_factory=Counter)
    falas: defaultdict = field(default_factory=lambda: defaultdict(Counter))  # nome -> heróis
    mapa_visto_em: dict = field(default_factory=dict)
    placar: "LeiturasPlacar" = field(default_factory=lambda: LeiturasPlacar())
    times: dict = None                  # última leitura dos dois times no Tab
    times_em: float = float("-inf")
    tab_competitivo: bool = None  # None = Tab não visto; o cabeçalho diz se é Competitivo
    mapas_tab: Counter = field(default_factory=Counter)        # mapa lido no cabeçalho do Tab
    mapas_desconhecidos: Counter = field(default_factory=Counter)  # idem, fora do catálogo
    # Uso de habilidades (ver Detector.teclas)
    heroi_atual: str = None                                    # id do seu herói agora
    usos: Counter = field(default_factory=Counter)            # (heroi_id, habilidade_id) -> usos
    ultimo_uso: dict = field(default_factory=dict)            # (heroi_id, tecla) -> instante
    apertos_pendentes: list = field(default_factory=list)     # antes de confirmar o herói
    candidato: dict = None                                     # herói novo visto, a confirmar
    # Linha do tempo dos seus heróis (ver herois_confirmados)
    inicio: float = None                                       # quando a partida foi notada
    sinais_heroi: list = field(default_factory=list)          # (instante, nome, herói, texto, peso)
    heroi_no_tab: list = field(default_factory=list)          # (instante, heroi_id, peso) pela sua linha do Tab
    q_em: float = float("-inf")                                # último Q apertado
    suprema_pronta_em: float = None                            # última leitura com a suprema pronta

    def mapa_final(self):
        """O cabeçalho do Tab ("ESCOLTA | GRÍMSVÖTN") é a fonte mais confiável.
        Um mapa fora do catálogo (lançado depois da última coleta) vale pelo
        nome lido, se apareceu em várias leituras do Tab."""
        if self.mapas_tab:
            return self.mais_votado(self.mapas_tab)
        if self.mapas_desconhecidos:
            nome, vezes = self.mapas_desconhecidos.most_common(1)[0]
            if vezes >= LEITURAS_MAPA_NOVO:
                return nome
        return self.mais_votado(self.mapas)

    def modo_final(self):
        # O cabeçalho do Tab é a fonte mais confiável: "CONTROLE - COMPETITIVO | NEPAL"
        # na Competitiva, só "HÍBRIDO | HOLLYWOOD" na Partida Rápida.
        if self.tab_competitivo is not None:
            return "Competitivo" if self.tab_competitivo else "Partida Rápida"
        return self.mais_votado(self.modos)

    def herois_confirmados(self, nome_jogador, fim):
        """Seus heróis em ordem, com o tempo de cada um:
        [{"heroi_id", "desde", "segundos"}].

        Cada fala distinta vale 1 (a mesma fala parada na tela, lida a cada
        segundo, conta uma vez só); a sua linha do Tab e "X trocou para Y"
        valem 2. Um trecho só entra com peso 2 ou mais: uma leitura errada
        isolada (comum no começo da partida) some, e os vizinhos se juntam."""
        if not nome_jogador and self.falas:
            nome_jogador = max(self.falas, key=lambda n: sum(self.falas[n].values()))
        eventos, recentes = [], []
        for t, nome, heroi_nome, texto, peso in self.sinais_heroi:
            heroi = catalogo.heroi(heroi_nome)
            if heroi and mesmo_nome(nome, nome_jogador or "") and fala_nova(recentes, t, texto):
                eventos.append((t, heroi["id"], peso))
        eventos += self.heroi_no_tab
        eventos.sort(key=lambda e: e[0])
        trechos = []
        for t, h, peso in eventos:
            if trechos and trechos[-1]["heroi_id"] == h:
                trechos[-1]["peso"] += peso
            else:
                trechos.append({"heroi_id": h, "desde": t, "peso": peso})
        fortes = [x for x in trechos if x["peso"] >= CONFIRMA_HEROI]
        if not fortes and trechos:  # nada confirmado: fica o mais visto
            pesos = Counter()
            for x in trechos:
                pesos[x["heroi_id"]] += x["peso"]
            melhor = pesos.most_common(1)[0][0]
            fortes = [next(x for x in trechos if x["heroi_id"] == melhor)]
        juntos = []
        for x in fortes:
            if juntos and juntos[-1]["heroi_id"] == x["heroi_id"]:
                continue
            juntos.append({"heroi_id": x["heroi_id"], "desde": x["desde"]})
        if juntos and self.inicio is not None:
            juntos[0]["desde"] = min(juntos[0]["desde"], self.inicio)
        for i, x in enumerate(juntos):
            ate = juntos[i + 1]["desde"] if i + 1 < len(juntos) else max(fim, x["desde"])
            x["segundos"] = round(ate - x["desde"])
        return juntos

    def vazia(self):
        return not (self.mapas or self.modos or self.falas or self.placar.leituras)

    @staticmethod
    def mais_votado(contador):
        return contador.most_common(1)[0][0] if contador else dados.NAO_DETECTADO

    def herois_do_jogador(self, nome_jogador):
        """Heróis do jogador. Sem nome conhecido, usa quem mais falou
        (as falas do seu próprio herói são as que mais aparecem)."""
        if nome_jogador:
            total = Counter()
            for nome, herois in self.falas.items():
                if mesmo_nome(nome, nome_jogador):
                    total.update(herois)
            return total
        if not self.falas:
            return Counter()
        return max(self.falas.values(), key=lambda c: sum(c.values()))


@dataclass
class Registro:
    heroi: str
    mapa: str
    modo: str
    resultado: str  # None = partida acabou, mas o resultado não foi lido
    herois_jogados: list
    placar: dict = field(default_factory=dict)  # E/A/M/dano/cura/mitigado (último Tab)
    times: dict = None  # aliados e inimigos lidos no Tab (ver placar.ler_times)
    habilidades: list = field(default_factory=list)  # [{heroi_id, habilidade_id, usos}]
    herois: list = field(default_factory=list)  # seus heróis em ordem: [{heroi_id, segundos}]


class Detector:
    def __init__(self, nome_jogador="", partidas_por_falante=None):
        self.nome_jogador = nome_jogador
        self.partida = Partida()
        self.ignorar_ate = 0.0
        self.ultimo_fim = float("-inf")
        self.ultima_novidade = 0.0     # última vez que a partida em andamento mudou
        self.fora_de_partida = False   # no Campo de Treinamento
        self.morto_ate = float("-inf")  # "RESSURGIR EM" na tela: apertos não contam
        self.placar_registrado = {}    # placar gravado com a última partida
        self.pos_fim = LeiturasPlacar()  # Tabs abertos logo depois do resultado
        self.biblioteca = None           # retratos.Biblioteca (o monitor entrega)
        self.contexto_fim = (None, {})   # herói e falas da partida que acabou
        self.times_pos_fim, self.times_pos_fim_em = None, float("-inf")
        # Em quantas partidas cada nome falou: os colegas mudam, você não.
        self.partidas_por_falante = Counter(partidas_por_falante or {})

    def resumo(self):
        p = self.partida
        herois = p.herois_do_jogador(self.nome_jogador)
        return " · ".join(v for v in (
            p.mais_votado(herois) if herois else "",
            p.mapa_final() if p.mapas or p.mapas_tab or p.mapas_desconhecidos else "",
            p.modo_final() if p.modos or p.tab_competitivo is not None else "") if v)

    def parcial(self):
        """A partida em andamento como está agora (para mostrar na tela), ou None."""
        p = self.partida
        if p.vazia():
            return None
        herois = p.herois_do_jogador(self.nome_jogador)
        atual = catalogo.heroi(p.heroi_atual) if p.heroi_atual else None
        return {"heroi": atual["nome"] if atual else p.mais_votado(herois), "mapa": p.mapa_final(),
                "modo": p.modo_final(), "placar": p.placar.final(),
                "habilidades": self._usos_da_partida(p)}

    # ------------------------------------------------------------ habilidades

    def teclas(self, apertos):
        """Recebe os apertos de tecla [(tecla, instante)] (ver entradas.py) e
        conta os usos de habilidade do seu herói atual. Um aperto só conta se:
        você está numa partida, vivo, com o herói conhecido, a tecla é de uma
        habilidade contável dele e ela já saiu da recarga desde o último uso.
        O Q não conta aqui: a suprema é confirmada pelo % do HUD (_suprema)."""
        p = self.partida
        for tecla, quando in apertos:
            if self.fora_de_partida or quando < self.ignorar_ate or quando < self.morto_ate:
                continue
            if p.candidato and quando - p.candidato["desde"] > DESISTIR_CANDIDATO:
                p.candidato = None  # nunca confirmado: era leitura errada
                if p.heroi_atual:
                    self._soltar_apertos(p, p.heroi_atual)
            if tecla == "q":
                p.q_em = quando
            elif not p.heroi_atual or p.candidato:
                p.apertos_pendentes.append((tecla, quando))  # contam quando o herói for confirmado
                del p.apertos_pendentes[:-300]
            else:
                self._contar_aperto(p, p.heroi_atual, tecla, quando)

    def _contar_aperto(self, p, heroi_id, tecla, quando):
        if tecla == "suprema":  # já confirmada pelo HUD (ver _suprema)
            suprema = next((h for h in rastreaveis(heroi_id) if h["tecla"] == "q"), None)
            if suprema:
                p.usos[(heroi_id, suprema["id"])] += 1
            return
        habilidade = next((h for h in rastreaveis(heroi_id) if h["tecla"] == tecla), None)
        if not habilidade or not habilidade["recarga"]:
            return
        anterior = p.ultimo_uso.get((heroi_id, tecla))
        # Margem de 15%: vantagens e subfunções reduzem um pouco a recarga.
        if anterior is None or quando - anterior >= habilidade["recarga"] * 0.85:
            p.usos[(heroi_id, habilidade["id"])] += 1
            p.ultimo_uso[(heroi_id, tecla)] = quando

    def _heroi_do_jogador(self, heroi_nome, texto, agora, peso=1):
        """Uma fala sua nas legendas. O herói atual (o dono das habilidades
        apertadas) só muda depois de confirmado: duas falas distintas, a troca
        anunciada pelo jogo ou a sua linha do Tab. Enquanto isso os apertos
        esperam, e depois contam para o herói certo."""
        heroi = catalogo.heroi(heroi_nome)
        if not heroi:
            return
        p, h = self.partida, heroi["id"]
        if h == p.heroi_atual:
            if p.candidato:  # o candidato era leitura errada
                p.candidato = None
                self._soltar_apertos(p, h)
            return
        if not p.candidato or p.candidato["heroi_id"] != h:
            p.candidato = {"heroi_id": h, "desde": agora, "peso": 0, "falas": []}
        if fala_nova(p.candidato["falas"], agora, texto):
            p.candidato["peso"] += peso
        if p.candidato["peso"] >= CONFIRMA_HEROI:
            self._confirmar_heroi(h)

    def _confirmar_heroi(self, heroi_id):
        p = self.partida
        p.heroi_atual, p.candidato = heroi_id, None
        self._soltar_apertos(p, heroi_id)

    def _soltar_apertos(self, p, heroi_id):
        for tecla, quando in p.apertos_pendentes:
            self._contar_aperto(p, heroi_id, tecla, quando)
        p.apertos_pendentes.clear()

    def _heroi_na_sua_linha(self, times):
        """Seu herói pela sua linha do Tab: (heroi_id, peso). O retrato já
        conhecido confirma sozinho; as vantagens (podem errar) valem 1."""
        for posicao, j in enumerate(times.get("aliados", [])):
            if not j.get("voce"):
                continue
            funcao = FUNCAO_POR_POSICAO[posicao] if len(times["aliados"]) == 5 else None
            if self.biblioteca is not None and j.get("vetor"):
                heroi_id, _ = self.biblioteca.reconhecer(j["vetor"], funcao)
                if heroi_id:
                    return heroi_id, CONFIRMA_HEROI
            heroi_id, _ = reconhecer_vantagens(j.get("vantagens", []), funcao)
            return heroi_id, 1
        return None, 0

    def _suprema(self, tela, agora):
        """Suprema usada: o HUD mostrava a suprema pronta, você apertou Q e
        ela deixou de estar pronta (ver habilidades.suprema_pronta). Morrer
        com ela pronta não conta: sem Q, o HUD sumir é só a morte."""
        if tela is None:
            return
        p = self.partida
        pronta = suprema_pronta(tela.pixel, tela.largura, tela.altura)
        if pronta:
            p.suprema_pronta_em = agora
        elif p.suprema_pronta_em is not None:
            if p.q_em >= p.suprema_pronta_em - 1.5:
                self._usou_suprema(p, p.q_em)
            p.suprema_pronta_em = None

    def _usou_suprema(self, p, quando):
        if not p.heroi_atual or p.candidato:
            p.apertos_pendentes.append(("suprema", quando))  # conta com o herói confirmado
        else:
            self._contar_aperto(p, p.heroi_atual, "suprema", quando)

    @staticmethod
    def _usos_da_partida(p):
        return [{"heroi_id": h, "habilidade_id": a, "usos": n} for (h, a), n in sorted(p.usos.items())]

    def processar(self, linhas, largura, altura, agora, tela_inteira=True, tela=None):
        """Recebe as linhas do OCR de um quadro (ou só da faixa de legendas).

        tela: acesso à imagem, usado no placar (ver placar.ler_placar).
        Retorna (registro ou None, lista de mensagens do que foi visto).
        """
        if agora < self.ignorar_ate:
            # Logo depois do resultado o placar ainda abre com os números FINAIS
            # da partida: eles corrigem o que foi registrado (ver placar_pos_fim).
            if tela_inteira and tela_do_placar(linhas, altura):
                placar = ler_placar(linhas, largura, altura, tela)
                if placar and not coerente(placar, {**self.placar_registrado, **self.pos_fim.final()}):
                    return None, [f"Placar ignorado (diminuiu: outra linha?): {placar}"]
                if placar:
                    self.pos_fim.adicionar(placar, agora)
                    if agora - self.times_pos_fim_em >= INTERVALO_TIMES:
                        times = ler_times(linhas, largura, altura, tela)
                        if times and coerente(_seus_valores(times), self.placar_pos_fim()):
                            heroi, falas = self.contexto_fim
                            self.times_pos_fim = self._identificar(times, heroi, falas, self.placar_pos_fim())
                            self.times_pos_fim_em = agora
                    return None, [f"Placar pós-fim: {placar}"]
            return None, []  # tela de fim/destaque da partida que acabou de ser registrada

        # Campo de Treinamento: não é partida. Descarta o que estava sendo montado
        # e ignora tudo até aparecer um mapa de verdade (seleção de herói, Tab...).
        if tela_inteira and any(t in compactar(l.texto) for l in linhas for t in TEXTOS_FORA_DE_PARTIDA):
            self.fora_de_partida = True
            self.partida = Partida()
            return None, ["Fora de partida (Campo de Treinamento)"]
        if self.fora_de_partida:
            if not (tela_inteira and len(self._mapas_na_tela(linhas)) == 1):
                return None, []
            self.fora_de_partida = False

        # Partida sem nenhuma novidade há muito tempo (saiu no meio, menu...): descarta.
        if not self.partida.vazia() and agora - self.ultima_novidade > PARTIDA_PARADA:
            self.partida = Partida()

        resultado = self._resultado(linhas, largura, altura)
        if resultado:
            if tela_inteira:  # o quadro do fim pode mostrar o Tab (mapa, modo, placar)
                self._mapa_e_modo(linhas, agora)
                if tela_do_placar(linhas, altura):
                    self._tab(linhas, largura, altura, agora, tela)
            return self._finalizar(resultado, agora), [f"Fim de partida: {resultado}"]
        if tela_inteira and self._tela_pos_partida(linhas) and not self.partida.vazia() \
                and agora - self.ultimo_fim > 300:
            # Acabou e não lemos o resultado: entrega o resto para você confirmar.
            return self._finalizar(None, agora), ["Fim de partida sem resultado lido"]

        mensagens = []
        for linha in linhas:
            for nome, heroi, peso in self._falas(linha.texto):
                self.partida.falas[nome.upper()][heroi] += 1
                self.partida.sinais_heroi.append((agora, nome, heroi, linha.texto, peso))
                if self.nome_jogador and mesmo_nome(nome, self.nome_jogador):
                    self._heroi_do_jogador(heroi, linha.texto, agora, peso)
                mensagens.append(f"Fala: {nome} ({heroi})")

        self._suprema(tela, agora)
        if tela_inteira:
            # "RESSURGIRÁ EM" no canto superior direito: você está morto.
            if any(l.x > largura * 0.7 and l.y < altura * 0.08 and morto(l.texto) for l in linhas):
                self.morto_ate = agora + TEMPO_MORTO
            mensagens += self._mapa_e_modo(linhas, agora)
            if tela_do_placar(linhas, altura):
                mensagens += self._tab(linhas, largura, altura, agora, tela)
        if mensagens:
            self.ultima_novidade = agora
        if self.partida.inicio is None and not self.partida.vazia():
            self.partida.inicio = agora
        return None, mensagens

    def descartar_partida(self):
        """Joga fora a partida em andamento (ex.: o jogador não estava jogando de verdade)."""
        self.partida = Partida()

    def _tab(self, linhas, largura, altura, agora, tela):
        p = self.partida
        cabecalho = " ".join(compactar(l.texto) for l in linhas if l.y < altura * 0.08)
        p.tab_competitivo = bool(p.tab_competitivo) or "competitiv" in cabecalho
        mensagens = ["Tab: " + ("Competitivo" if p.tab_competitivo else "Partida Rápida")]
        nome = mapa_do_cabecalho(linhas, altura)
        if nome:
            conhecido = achar_contido(compactar(nome), INDICE_MAPAS)
            if conhecido:
                p.mapas_tab[conhecido] += 1
            elif not parece_mapa_conhecido(nome):  # "wos" é ILIOS mal lido, não mapa novo
                p.mapas_desconhecidos[nome.title()] += 1
                mensagens.append(f"Mapa fora do catálogo no Tab: {nome}")
        placar = ler_placar(linhas, largura, altura, tela)
        if placar and not coerente(placar, p.placar.final()):
            mensagens.append(f"Placar ignorado (diminuiu: outra linha?): {placar}")
        elif placar:
            p.placar.adicionar(placar, agora)
            mensagens.append(f"Placar: {placar}")
        # Os dois times (retratos, números de todos): mais pesado, então no
        # máximo a cada INTERVALO_TIMES enquanto o Tab estiver aberto.
        if agora - p.times_em >= INTERVALO_TIMES:
            times = ler_times(linhas, largura, altura, tela)
            if times and coerente(_seus_valores(times), p.placar.final()):
                p.times, p.times_em = times, agora
                mensagens.append("Times lidos no Tab")
                heroi_id, peso = self._heroi_na_sua_linha(times)
                if heroi_id:
                    p.heroi_no_tab.append((agora, heroi_id, peso))
                    if peso >= CONFIRMA_HEROI and heroi_id != p.heroi_atual:
                        self._confirmar_heroi(heroi_id)
                    mensagens.append(f"Seu herói no Tab: {heroi_id} (peso {peso})")
        return mensagens

    def _identificar(self, times, heroi, falas, placar):
        """Heróis de cada linha (ver retratos.identificar). Na sua linha valem
        os números do placar registrado (lidos com OCR extra)."""
        for j in times["aliados"]:
            if j["voce"]:
                j["valores"] = {**j["valores"], **placar}
        if self.biblioteca is not None:
            identificar(times, heroi, self.biblioteca, falas, self.nome_jogador)
        return times

    # ------------------------------------------------------------ leituras

    @staticmethod
    def _falas(texto):
        for nome, trecho in RE_FALA.findall(texto):
            heroi = heroi_no_inicio(trecho)
            if heroi and not heroi_no_inicio(nome):  # "[HAZARD]" sozinho é inimigo
                yield nome, heroi, 1
        for nome, trecho in RE_TROCA.findall(texto):
            heroi = heroi_no_inicio(trecho)
            if heroi:  # mensagem do jogo: vale como confirmação
                yield nome, heroi, CONFIRMA_HEROI

    def _resultado(self, linhas, largura, altura):
        # Tela pós-partida de votos: "DERROTA | ILIOS | TEMPO DA PARTIDA: 11:..."
        # (o resultado aparece ali em fonte que o OCR lê).
        if any("tempodapartida" in compactar(l.texto) for l in linhas):
            for linha in linhas:
                if linha.y < altura * 0.12:
                    resultado = INDICE_RESULTADOS.get(compactar(linha.texto))
                    if resultado:
                        return resultado
        for linha in linhas:
            resultado = resultado_da_narradora(linha.texto)
            if resultado:
                return resultado
            # VITÓRIA/DERROTA em letras grandes no centro (se o OCR conseguir ler).
            centro = linha.x + linha.largura / 2
            if linha.altura >= altura * TAMANHO_MIN_RESULTADO and largura * 0.2 < centro < largura * 0.8:
                resultado = INDICE_RESULTADOS.get(compactar(linha.texto))
                if resultado:
                    return resultado
        return None

    @staticmethod
    def _tela_pos_partida(linhas):
        textos = {compactar(l.texto) for l in linhas}
        return "resumo" in textos and "recompensas" in textos

    @staticmethod
    def _textos_de_tela(linhas):
        """Linhas que valem para mapa/modo: legendas e chat citam nomes à toa."""
        for linha in linhas:
            texto = compactar(linha.texto)
            if len(texto) >= 3 and not RE_FALA.search(linha.texto):
                yield texto

    def _mapas_na_tela(self, linhas):
        return {m for m in (achar_contido(t, INDICE_MAPAS) for t in self._textos_de_tela(linhas)) if m}

    def _mapa_e_modo(self, linhas, agora):
        # Telas com vários mapas/modos (menu Jogar, votação de mapa) não contam:
        # só vale quando o quadro mostra exatamente um.
        mensagens, mapas = [], self._mapas_na_tela(linhas)
        modos = {modo for texto in self._textos_de_tela(linhas)
                 for chave, modo in INDICE_MODOS.items() if chave in texto}
        if len(mapas) == 1:
            mapa = mapas.pop()
            self._votar_mapa(mapa, agora)
            mensagens.append(f"Mapa: {mapa}")
        if len(modos) == 1:
            modo = modos.pop()
            self.partida.modos[modo] += 1
            mensagens.append(f"Modo: {modo}")
        return mensagens

    def _votar_mapa(self, mapa, agora):
        p = self.partida
        lider = p.mais_votado(p.mapas) if p.mapas else None
        if lider and mapa != lider and agora - p.mapa_visto_em.get(lider, agora) > MAPA_ANTIGO:
            self.partida = p = Partida()  # outro mapa muito depois: é outra partida
        p.mapas[mapa] += 1
        p.mapa_visto_em[mapa] = agora

    # ------------------------------------------------------------ fim

    def aprender_nome(self):
        """Se ainda não sabemos o nome do jogador, deduz pelas legendas: o nome
        que fala em 3+ partidas, com folga sobre o segundo (um amigo que joga
        sempre junto empata e aí nada é decidido). Retorna o nome novo ou None."""
        if self.nome_jogador or not self.partidas_por_falante:
            return None
        comuns = self.partidas_por_falante.most_common(2)
        nome, vezes = comuns[0]
        segundo = comuns[1][1] if len(comuns) > 1 else 0
        if vezes >= 3 and vezes >= 2 * segundo:
            self.nome_jogador = nome
            return nome
        return None

    def _finalizar(self, resultado, agora):
        p = self.partida
        linha_do_tempo = p.herois_confirmados(self.nome_jogador, agora)
        nomes = {x["heroi_id"]: catalogo.heroi(x["heroi_id"])["nome"] for x in linha_do_tempo}
        tempo = Counter()
        for x in linha_do_tempo:
            tempo[x["heroi_id"]] += x["segundos"]
        if tempo:  # o principal é o que você jogou por mais tempo
            heroi = nomes[tempo.most_common(1)[0][0]]
        else:
            heroi = p.mais_votado(p.herois_do_jogador(self.nome_jogador))
        registro = Registro(
            heroi=heroi,
            mapa=p.mapa_final(),
            modo=p.modo_final(),
            resultado=resultado,
            herois_jogados=list(dict.fromkeys(nomes[x["heroi_id"]] for x in linha_do_tempo)),
            placar=p.placar.final(),
        )
        registro.herois = [{"heroi_id": x["heroi_id"], "segundos": x["segundos"]} for x in linha_do_tempo]
        if p.apertos_pendentes and (p.heroi_atual or linha_do_tempo):
            # apertos esperando confirmação: vão para o herói em que você terminou
            self._soltar_apertos(p, p.heroi_atual or linha_do_tempo[-1]["heroi_id"])
        registro.habilidades = self._usos_da_partida(p)
        if p.times:
            # na sua linha do Tab está o herói daquele momento (pode ter trocado)
            no_tab = [x for x in linha_do_tempo if x["desde"] <= p.times_em]
            heroi_no_tab = nomes[no_tab[-1]["heroi_id"]] if no_tab else registro.heroi
            registro.times = self._identificar(p.times, heroi_no_tab, p.falas, registro.placar)
        # o Tab depois do fim mostra o herói com que você terminou
        ultimo = nomes[linha_do_tempo[-1]["heroi_id"]] if linha_do_tempo else registro.heroi
        self.contexto_fim = (ultimo, p.falas)
        self.times_pos_fim, self.times_pos_fim_em = None, float("-inf")
        # Só conta quem falou de verdade (3+ vezes), não um nome lido errado uma vez.
        self.partidas_por_falante.update(
            nome for nome, herois in p.falas.items() if sum(herois.values()) >= 3)
        self.partida = Partida()
        self.ignorar_ate = agora + ESPERA_POS_RESULTADO
        self.ultimo_fim = agora
        self.placar_registrado = registro.placar
        self.pos_fim = LeiturasPlacar()
        return registro

    def placar_pos_fim(self):
        """Placar da partida que acabou, corrigido pelo Tab aberto depois do
        resultado: as colunas lidas ali substituem as do registro."""
        return {**self.placar_registrado, **self.pos_fim.final()}
