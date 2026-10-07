"""OCR nativo do Windows (Windows.Media.Ocr), sem dependências.

Usa o idioma do perfil do Windows (aqui, pt-BR). Os índices de método seguem
a ordem declarada nos metadados do Windows (C:\\Windows\\System32\\WinMetadata).
"""

import ctypes
import time
from ctypes import POINTER, byref, c_char_p, c_float, c_int32, c_uint32, c_void_p
from dataclasses import dataclass

from .com import Objeto, fabrica_winrt, hstring_para_texto, iniciar_winrt

IID_OCR_ENGINE_STATICS = "5bffa85a-3384-3540-9940-699120d428a8"
IID_SOFTWARE_BITMAP_STATICS = "df0385db-672f-4a9d-806e-c2442f343e86"
IID_CRYPTO_BUFFER_STATICS = "320b7e22-3cb0-4cdf-8663-1d28910065eb"
IID_ASYNC_INFO = "00000036-0000-0000-c000-000000000046"

BGRA8 = 87
ASYNC_CONCLUIDO, ASYNC_CANCELADO, ASYNC_ERRO = 1, 2, 3


class Retangulo(ctypes.Structure):
    _fields_ = [("x", c_float), ("y", c_float), ("largura", c_float), ("altura", c_float)]


@dataclass
class Linha:
    texto: str
    x: float
    y: float
    largura: float
    altura: float


class OCR:
    """Deve ser criado e usado sempre na mesma thread."""

    def __init__(self):
        iniciar_winrt()
        estaticos = fabrica_winrt("Windows.Media.Ocr.OcrEngine", IID_OCR_ENGINE_STATICS)
        self.motor = estaticos.obter(10, onde="TryCreateFromUserProfileLanguages")
        if not self.motor:
            raise RuntimeError("Nenhum idioma de OCR instalado no Windows.")
        self.bitmaps = fabrica_winrt("Windows.Graphics.Imaging.SoftwareBitmap",
                                     IID_SOFTWARE_BITMAP_STATICS)
        self.buffers = fabrica_winrt("Windows.Security.Cryptography.CryptographicBuffer",
                                     IID_CRYPTO_BUFFER_STATICS)

    def ler(self, bgra, largura, altura, tempo_limite=5.0):
        """Reconhece texto numa imagem BGRA. Retorna lista de Linha (em pixels)."""
        if largura <= 0 or altura <= 0 or len(bgra) != largura * altura * 4:
            return []  # quadro incompleto (ex.: o jogo trocando de resolução)
        buffer = self.buffers.obter(9, c_uint32, c_char_p, args=(len(bgra), bgra),
                                    onde="CreateFromByteArray")
        bitmap = self.bitmaps.obter(9, c_void_p, c_int32, c_int32, c_int32,
                                    args=(buffer.p, BGRA8, largura, altura),
                                    onde="CreateCopyFromBuffer")
        operacao = self.motor.obter(6, c_void_p, args=(bitmap.p,), onde="RecognizeAsync")

        info = operacao.consultar(IID_ASYNC_INFO)
        status = c_int32()
        limite = time.monotonic() + tempo_limite
        while True:
            info.chamar(7, (POINTER(c_int32),), byref(status), onde="get_Status")
            if status.value != 0:
                break
            if time.monotonic() > limite:
                info.chamar(9, (), onde="Cancel")
                raise TimeoutError("OCR demorou demais")
            time.sleep(0.003)
        if status.value != ASYNC_CONCLUIDO:
            raise RuntimeError(f"OCR terminou com status {status.value}")

        resultado = operacao.obter(8, onde="GetResults")
        return self._linhas(resultado)

    def _linhas(self, resultado):
        linhas = []
        vetor = resultado.obter(6, onde="get_Lines")
        for linha in _itens(vetor):
            texto = _texto(linha)
            caixas = [_caixa(p) for p in _itens(linha.obter(6, onde="get_Words"))]
            if not caixas:
                continue
            x0 = min(c.x for c in caixas)
            y0 = min(c.y for c in caixas)
            x1 = max(c.x + c.largura for c in caixas)
            y1 = max(c.y + c.altura for c in caixas)
            linhas.append(Linha(texto, x0, y0, x1 - x0, y1 - y0))
        return linhas


def _itens(vetor):
    """Percorre um IVectorView do WinRT."""
    tamanho = c_uint32()
    vetor.chamar(7, (POINTER(c_uint32),), byref(tamanho), onde="get_Size")
    for i in range(tamanho.value):
        yield vetor.obter(6, c_uint32, args=(i,), onde="GetAt")


def _texto(objeto):
    hstr = c_void_p()
    objeto.chamar(7, (POINTER(c_void_p),), byref(hstr), onde="get_Text")
    return hstring_para_texto(hstr)


def _caixa(palavra):
    r = Retangulo()
    palavra.chamar(6, (POINTER(Retangulo),), byref(r), onde="get_BoundingRect")
    return r
