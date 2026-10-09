"""Leitura das teclas de habilidade enquanto você joga.

Só consulta o ESTADO das teclas (GetAsyncKeyState), 60 vezes por segundo, e
só com o Overwatch em primeiro plano: não intercepta nada, não envia nada ao
jogo e não guarda o que você digita. Cada aperto vira (tecla, instante); quem
decide se foi um uso de habilidade é o detector (herói, recarga, morte...).

O chat é respeitado: Enter abre/fecha, Esc fecha; com o chat aberto nada é
registrado (o "E" e o "Q" digitados numa mensagem não contam).
"""

import threading
import time
from collections import deque

from . import janelas
from .captura import jogo_em_foco
from .habilidades import VK

FREQUENCIA = 60            # leituras por segundo
CHECAR_JOGO = 0.5          # s entre checagens de qual janela está em foco
CHAT_ESQUECIDO = 15.0      # s: depois disso o chat é considerado fechado
VK_ENTER, VK_ESC = 0x0D, 0x1B


def _apertada(vk):
    return bool(janelas.user32.GetAsyncKeyState(vk) & 0x8000)


class Entradas(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="entradas")
        self._parar = threading.Event()
        self._apertos = deque(maxlen=500)
        self.chat_aberto_desde = None

    def parar(self):
        self._parar.set()

    def pegar(self):
        """Apertos desde a última chamada: [(tecla, instante monotonic, chat_aberto)].
        Enter e Esc vêm junto (só para o registro de teclas)."""
        lista = []
        while self._apertos:
            lista.append(self._apertos.popleft())
        return lista

    def run(self):
        teclas = {**VK, "enter": VK_ENTER, "esc": VK_ESC}
        antes = {nome: False for nome in teclas}
        no_jogo, proxima_checagem = False, 0.0
        while not self._parar.is_set():
            agora = time.monotonic()
            if agora >= proxima_checagem:
                no_jogo = jogo_em_foco() is not None
                proxima_checagem = agora + CHECAR_JOGO
            if not no_jogo:
                antes = {nome: False for nome in teclas}
                self._parar.wait(CHECAR_JOGO)
                continue
            if self.chat_aberto_desde and agora - self.chat_aberto_desde > CHAT_ESQUECIDO:
                self.chat_aberto_desde = None
            for nome, vk in teclas.items():
                apertada = _apertada(vk)
                if apertada and not antes[nome]:  # acabou de apertar
                    self._ao_apertar(nome, agora)
                antes[nome] = apertada
            self._parar.wait(1 / FREQUENCIA)

    def _ao_apertar(self, nome, agora):
        if nome == "enter":
            self.chat_aberto_desde = None if self.chat_aberto_desde else agora
        elif nome == "esc":
            self.chat_aberto_desde = None
        self._apertos.append((nome, agora, self.chat_aberto_desde is not None))
