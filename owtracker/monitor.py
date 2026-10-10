"""Thread que observa o jogo e registra partidas sozinha.

Só trabalha com o Overwatch em primeiro plano. A cada 1 s lê a faixa das
legendas (recorte pequeno, barato): é lá que aparecem "[FILIPE (ROADHOG)]" e
"[ATHENA] Vitória.". A cada 3 s lê a tela inteira (placar com mapa e modo,
chat, tela pós-partida).
Fora do jogo, só confere a janela em foco a cada 3 s (custo ~zero).
"""

import ctypes
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import digitos, janelas, retratos
from .banco import PASTA_DADOS
from .digitos import segmentar
from .captura import Captura, jogo_em_foco
from .entradas import Entradas
from .detector import Detector
from .imagem import ampliar, isolar_texto_branco, recortar, reduzir
from .ocr import OCR, Linha

ARQUIVO_CONFIG = PASTA_DADOS / "config.json"
PASTA_DIAGNOSTICO = Path(__file__).resolve().parent.parent / "capturas" / "diagnostico"
LOG_DIAGNOSTICO = PASTA_DADOS / "diagnostico.log"
LOG_TECLAS = PASTA_DADOS / "teclas.log"  # teclas de habilidade e o que o detector fez com cada uma
ARQUIVO_DIGITOS = PASTA_DADOS / "digitos.json"  # modelos aprendidos do reconhecedor

CONFIG_PADRAO = {"diagnostico": True, "nome_jogador": "", "partidas_por_falante": {}}
INTERVALO = 1.0          # s entre leituras das legendas
TELA_INTEIRA_A_CADA = 3  # leituras (ou seja, a cada ~3 s)
VERIFICAR_TAB = 0.1      # s entre checagens da tecla Tab (custo desprezível)
ESPERA_TAB = 0.25        # s com Tab segurado antes de ler (o placar leva um instante para abrir)
VK_TAB = 0x09
MAX_PRINTS_DIAGNOSTICO = 300
MAX_LOG_BYTES = 5_000_000
PRINT_A_CADA = 30  # s, no modo diagnóstico

# Faixa das legendas (frações da tela: x, y, largura, altura).
FAIXA_LEGENDAS = (0.15, 0.84, 0.70, 0.16)


def carregar_config():
    try:
        return {**CONFIG_PADRAO, **json.loads(ARQUIVO_CONFIG.read_text("utf-8"))}
    except (OSError, ValueError):
        return dict(CONFIG_PADRAO)


def salvar_config(config):
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    ARQUIVO_CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False), "utf-8")


def tab_pressionado():
    """Só consulta o estado da tecla (não intercepta nada nem mexe no jogo)."""
    return bool(janelas.user32.GetAsyncKeyState(VK_TAB) & 0x8000)


class Tela:
    """Acesso à imagem capturada, para o placar (ver placar.ler_placar)."""

    def __init__(self, ocr, bgra, largura, altura, reconhecedor):
        self.ocr, self.bgra, self.largura, self.altura = ocr, bgra, largura, altura
        self.reconhecedor = reconhecedor

    def _dentro(self, x, y, l, a):
        x, y = max(0, int(x)), max(0, int(y))
        return x, y, min(int(l), self.largura - x), min(int(a), self.altura - y)

    def fundo(self, x0, x1, y):
        """Mediana do canal verde no trecho (x0..x1, y): o tom do fundo,
        sem se deixar levar pelos números brancos por cima."""
        x0, x1, y = max(0, int(x0)), min(self.largura, int(x1)), int(y)
        if not (0 <= y < self.altura) or x1 <= x0:
            return 0
        inicio = (y * self.largura + x0) * 4
        verdes = sorted(self.bgra[inicio + 1:inicio + (x1 - x0) * 4:8])  # 1 a cada 2 pixels
        return verdes[len(verdes) // 2]

    def ler_faixa(self, x, y, l, a, ampliacao=2):
        """OCR extra do retângulo, ampliado, em duas versões: normal e com o
        texto branco isolado. Coordenadas da tela."""
        x, y, l, a = self._dentro(x, y, l, a)
        if l <= 0 or a <= 0:
            return []
        recorte = recortar(self.bgra, self.largura, x, y, l, a)
        linhas = []
        for versao in (recorte, isolar_texto_branco(recorte)):
            grande, lg, ag = ampliar(versao, l, a, ampliacao)
            linhas += [Linha(t.texto, x + t.x / ampliacao, y + t.y / ampliacao,
                             t.largura / ampliacao, t.altura / ampliacao)
                       for t in self.ocr.ler(grande, lg, ag)]
        return linhas

    def pixel(self, x, y):
        i = (y * self.largura + x) * 4
        b, g, r = self.bgra[i], self.bgra[i + 1], self.bgra[i + 2]
        return r, g, b

    def rgb(self, x, y, l, a):
        """Recorte RGB (para os retratos dos heróis no placar)."""
        x, y, l, a = self._dentro(x, y, l, a)
        return janelas.bgra_para_rgb(recortar(self.bgra, self.largura, x, y, l, a))

    def numeros(self, x, y, l, a, apagados=False):
        """Números separados pelo reconhecedor próprio. apagados=True inclui
        o texto cinza (o jogo mostra o zero em cinza)."""
        x, y, l, a = self._dentro(x, y, l, a)
        if l <= 0 or a <= 0:
            return []
        limiar = digitos.LIMIAR_APAGADO if apagados else digitos.LIMIAR_BRANCO
        return segmentar(self.bgra, self.largura, x, y, l, a, limiar)


def ler_legendas(ocr, bgra, largura, altura):
    """OCR só da faixa das legendas, devolvido em coordenadas da tela."""
    fx, fy, fl, fa = FAIXA_LEGENDAS
    x0, y0 = int(largura * fx), int(altura * fy)
    lr, ar = int(largura * fl), min(int(altura * fa), altura - y0)
    faixa = recortar(bgra, largura, x0, y0, lr, ar)
    return [Linha(l.texto, x0 + l.x, y0 + l.y, l.largura, l.altura) for l in ocr.ler(faixa, lr, ar)]


class Monitor(threading.Thread):
    def __init__(self, avisar, ao_registrar, ao_atualizar=None, ao_corrigir_placar=None):
        super().__init__(daemon=True, name="monitor")
        self.avisar = avisar              # avisar(texto): status para a interface
        self.ao_registrar = ao_registrar  # ao_registrar(Registro)
        self.ao_atualizar = ao_atualizar  # ao_atualizar(dict ou None): partida em andamento
        self.ao_corrigir_placar = ao_corrigir_placar  # (placar, times, estatisticas): finais da última partida
        self._ultimo_parcial = None
        self._descartar = False
        self.config = carregar_config()
        self.detector = Detector(self.config["nome_jogador"], self.config["partidas_por_falante"])
        self.reconhecedor = digitos.carregar(ARQUIVO_DIGITOS)
        self.biblioteca = retratos.Biblioteca()  # retratos de heróis já identificados
        self.detector.biblioteca = self.biblioteca
        self.entradas = Entradas()  # teclas de habilidade (só com o jogo em foco)
        self._parar = threading.Event()
        self._ultimo_print = 0.0
        self._ultimo_texto = None

    def parar(self):
        self._parar.set()

    def descartar_partida(self):
        """Pedido da interface: jogar fora a partida em andamento. É feito na
        thread do monitor (a única que mexe no detector)."""
        self._descartar = True

    def definir_nome(self, nome):
        self.detector.nome_jogador = nome
        self.config["nome_jogador"] = nome
        salvar_config(self.config)

    def run(self):
        # Prioridade abaixo do normal: o jogo sempre tem preferência na CPU.
        kernel32 = ctypes.windll.kernel32
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x4000)
        try:
            ocr = OCR()
        except Exception as erro:
            self.avisar(f"Modo automático indisponível: {erro}")
            return
        captura = Captura()
        self.entradas.start()
        detector = self.detector
        estado_anterior = None
        proxima_legenda = proxima_inteira = 0.0
        tab_desde, ultimo_tab = None, 0.0

        while not self._parar.is_set():
            try:
                if self._descartar:
                    self._descartar = False
                    detector.descartar_partida()
                    self._avisar_parcial()
                apertos = self.entradas.pegar()
                if apertos:
                    detector.teclas(apertos)
                self._gravar_eventos(detector)
                jogo = jogo_em_foco()
                if not jogo:
                    if estado_anterior != "fora":
                        self.avisar("Automático: aguardando o Overwatch em primeiro plano.")
                        estado_anterior = "fora"
                    tab_desde = None
                    self._parar.wait(3)
                    continue
                estado_anterior = "jogo"

                # Tab segurado: lê o placar na hora e de novo a cada segundo.
                agora = time.monotonic()
                if tab_pressionado():
                    tab_desde = tab_desde or agora
                else:
                    tab_desde = None
                ler_tab = tab_desde is not None and agora - tab_desde >= ESPERA_TAB \
                    and agora - ultimo_tab >= INTERVALO
                if not ler_tab and agora < proxima_legenda:
                    self._parar.wait(VERIFICAR_TAB)
                    continue

                hwnd, x, y, largura, altura = jogo
                quadro = captura.capturar(x, y, largura, altura, hwnd)
                if quadro is None:
                    self._parar.wait(0.5)
                    continue
                bgra, largura, altura = quadro

                tela_inteira = ler_tab or agora >= proxima_inteira
                proxima_legenda = agora + INTERVALO
                if tela_inteira:
                    proxima_inteira = agora + INTERVALO * TELA_INTEIRA_A_CADA
                    linhas = ocr.ler(bgra, largura, altura)
                else:
                    linhas = ler_legendas(ocr, bgra, largura, altura)
                if ler_tab:
                    ultimo_tab = agora
                registro, vistos = detector.processar(
                    linhas, largura, altura, agora, tela_inteira,
                    tela=Tela(ocr, bgra, largura, altura, self.reconhecedor))

                atual = detector.resumo()
                self.avisar(f"Automático: lendo o jogo em {largura}×{altura} ({captura.metodo})"
                            + (f" · partida: {atual}" if atual else ""))

                self._gravar_eventos(detector)
                if registro:
                    detector.eventos.append((time.monotonic(), "PARTIDA REGISTRADA: "
                                             f"{registro.heroi} em {registro.mapa} · {registro.resultado} · "
                                             f"heróis {registro.herois} · usos {registro.habilidades}"))
                    self._gravar_eventos(detector)
                    self.ao_registrar(registro)
                    self._salvar_aprendizado()
                if any(v.startswith("Placar pós-fim") for v in vistos) and self.ao_corrigir_placar:
                    self.ao_corrigir_placar(detector.placar_pos_fim(), detector.times_pos_fim,
                                            detector.estatisticas_pos_fim())
                self._avisar_parcial()
                if self.config["diagnostico"]:
                    self._diagnostico(bgra, largura, altura, linhas, vistos, registro, tela_inteira)
            except Exception as erro:
                self.avisar(f"Automático: erro ({erro}); tentando de novo.")
                self._registrar_log(f"ERRO: {erro!r}")
                self._parar.wait(5)
                continue
            self._parar.wait(VERIFICAR_TAB)
        captura.fechar()
        self.entradas.parar()
        digitos.salvar(self.reconhecedor, ARQUIVO_DIGITOS)
        self.biblioteca.salvar()

    def _avisar_parcial(self):
        parcial = self.detector.parcial()
        if self.ao_atualizar and parcial != self._ultimo_parcial:
            self._ultimo_parcial = parcial
            self.ao_atualizar(parcial)

    def _salvar_aprendizado(self):
        digitos.salvar(self.reconhecedor, ARQUIVO_DIGITOS)
        self.biblioteca.salvar()
        detector = self.detector
        self.config["partidas_por_falante"] = dict(detector.partidas_por_falante.most_common(50))
        nome = detector.aprender_nome()
        if nome:
            self.config["nome_jogador"] = nome
            self.avisar(f"Automático: aprendi que o seu nome no jogo é {nome}.")
        salvar_config(self.config)

    # ------------------------------------------------------------ diagnóstico

    def _diagnostico(self, bgra, largura, altura, linhas, vistos, registro, tela_inteira):
        texto = " | ".join(f"{l.texto} [x={l.x:.0f} y={l.y:.0f} h={l.altura:.0f}]" for l in linhas)
        if texto != self._ultimo_texto:
            self._ultimo_texto = texto
            tipo = "" if tela_inteira else " legendas"
            self._registrar_log(f"{largura}x{altura}{tipo} vistos={vistos} :: {texto}")

        if not tela_inteira:
            return
        agora = time.monotonic()
        placar = any(v.startswith(("Tab", "Placar")) for v in vistos)
        evento = bool(registro) or placar or any(v.startswith(("Mapa", "Fala")) for v in vistos)
        if registro or agora - self._ultimo_print >= PRINT_A_CADA or \
                (evento and agora - self._ultimo_print >= 10):
            self._ultimo_print = agora
            # Placar em resolução cheia: os números pequenos precisam de detalhe.
            sufixo = "fim" if registro else "placar" if placar else ""
            self._salvar_print(bgra, largura, altura, sufixo, reducao=1 if placar else 2)

    def _gravar_eventos(self, detector):
        """Teclas e decisões do detector (contou, em recarga, chat, morto,
        suprema pronta no HUD...) em dados/teclas.log, com a hora de cada uma."""
        if not detector.eventos:
            return
        agora_m, agora = time.monotonic(), datetime.now()
        linhas = []
        while detector.eventos:
            quando, texto = detector.eventos.popleft()
            hora = agora - timedelta(seconds=agora_m - quando)
            linhas.append(f"{hora:%Y-%m-%d %H:%M:%S.%f}"[:-3] + f" {texto}\n")
        if not self.config["diagnostico"]:
            return
        PASTA_DADOS.mkdir(parents=True, exist_ok=True)
        if LOG_TECLAS.exists() and LOG_TECLAS.stat().st_size > MAX_LOG_BYTES:
            LOG_TECLAS.replace(LOG_TECLAS.with_suffix(".log.1"))
        with open(LOG_TECLAS, "a", encoding="utf-8") as arq:
            arq.writelines(linhas)

    def _registrar_log(self, linha):
        PASTA_DADOS.mkdir(parents=True, exist_ok=True)
        if LOG_DIAGNOSTICO.exists() and LOG_DIAGNOSTICO.stat().st_size > MAX_LOG_BYTES:
            LOG_DIAGNOSTICO.replace(LOG_DIAGNOSTICO.with_suffix(".log.1"))
        with open(LOG_DIAGNOSTICO, "a", encoding="utf-8") as arq:
            arq.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {linha}\n")

    def _salvar_print(self, bgra, largura, altura, sufixo, reducao=2):
        PASTA_DIAGNOSTICO.mkdir(parents=True, exist_ok=True)
        pequeno, l2, a2 = reduzir(bgra, largura, altura, reducao)
        nome = f"{datetime.now():%Y-%m-%d_%H-%M-%S}{'_' + sufixo if sufixo else ''}.png"
        janelas.salvar_png(PASTA_DIAGNOSTICO / nome, l2, a2, janelas.bgra_para_rgb(pequeno))
        antigos = sorted(PASTA_DIAGNOSTICO.glob("*.png"))
        for arquivo in antigos[:-MAX_PRINTS_DIAGNOSTICO]:
            arquivo.unlink()
