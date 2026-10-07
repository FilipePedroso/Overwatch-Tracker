"""Integração direta com a API do Windows via ctypes (sem dependências).

- Atalhos globais (funcionam com o jogo em foco).
- Captura de tela via GDI (reserva) e encoder PNG próprio.

A captura principal, que funciona em tela cheia, fica em captura.py (DXGI).
"""

import ctypes
import struct
import threading
import zlib
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000

# Assinaturas explícitas: handles são ponteiros de 64 bits.
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


def ativar_dpi_real():
    """Faz o Windows informar pixels reais (sem escala de 125%/150%)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


# ---------------------------------------------------------------- atalhos

class Atalhos:
    """Registra atalhos globais numa thread própria com loop de mensagens.

    O callback recebe o nome do atalho e roda NA THREAD DOS ATALHOS;
    quem usa Tkinter deve repassar para a thread da interface (ex.: fila).
    """

    def __init__(self, callback):
        self.callback = callback
        self._atalhos = {}  # id -> (nome, modificadores, tecla)
        self._thread = None
        self._thread_id = None
        self.falhas = []

    def adicionar(self, nome, modificadores, tecla):
        self._atalhos[len(self._atalhos) + 1] = (nome, modificadores | MOD_NOREPEAT, tecla)

    def iniciar(self):
        pronto = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(pronto,), daemon=True)
        self._thread.start()
        pronto.wait(2)

    def parar(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _loop(self, pronto):
        self._thread_id = kernel32.GetCurrentThreadId()
        registrados = []
        for id_, (nome, mods, tecla) in self._atalhos.items():
            if user32.RegisterHotKey(None, id_, mods, tecla):
                registrados.append(id_)
            else:
                self.falhas.append(nome)  # já usado por outro programa
        pronto.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in self._atalhos:
                try:
                    self.callback(self._atalhos[msg.wParam][0])
                except Exception as erro:  # não derruba o loop de atalhos
                    print("Erro no atalho:", erro)

        for id_ in registrados:
            user32.UnregisterHotKey(None, id_)


# ---------------------------------------------------------------- captura

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


def capturar_tela(x=0, y=0, largura=None, altura=None):
    """Captura uma região da tela principal. Retorna (largura, altura, bytes RGB)."""
    if largura is None:
        largura = user32.GetSystemMetrics(0) - x
    if altura is None:
        altura = user32.GetSystemMetrics(1) - y
    return largura, altura, bgra_para_rgb(capturar_tela_bgra(x, y, largura, altura))


def bgra_para_rgb(bgra):
    # Fatiamento roda em C: rápido mesmo em 4K.
    rgb = bytearray(len(bgra) // 4 * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    return bytes(rgb)


def capturar_tela_bgra(x, y, largura, altura):
    """Captura via GDI (não funciona em tela cheia exclusiva). Retorna bytes BGRA."""
    dc_tela = user32.GetDC(None)
    dc_mem = gdi32.CreateCompatibleDC(dc_tela)
    bitmap = gdi32.CreateCompatibleBitmap(dc_tela, largura, altura)
    antigo = gdi32.SelectObject(dc_mem, bitmap)
    try:
        gdi32.BitBlt(dc_mem, 0, 0, largura, altura, dc_tela, x, y, SRCCOPY | CAPTUREBLT)
        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.biWidth = largura
        info.biHeight = -altura  # negativo = linhas de cima para baixo
        info.biPlanes = 1
        info.biBitCount = 32
        bgra = ctypes.create_string_buffer(largura * altura * 4)
        gdi32.GetDIBits(dc_mem, bitmap, 0, altura, bgra, ctypes.byref(info), 0)
    finally:
        gdi32.SelectObject(dc_mem, antigo)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc_mem)
        user32.ReleaseDC(None, dc_tela)
    return bgra.raw


def salvar_png(caminho, largura, altura, rgb):
    """Encoder PNG mínimo (RGB 8 bits, sem filtro)."""
    passo = largura * 3
    visao = memoryview(rgb)
    cru = b"".join(b"\x00" + visao[i * passo:(i + 1) * passo] for i in range(altura))

    def bloco(tipo, dados):
        crc = zlib.crc32(tipo + dados) & 0xFFFFFFFF
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", crc)

    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    with open(caminho, "wb") as arq:
        arq.write(b"\x89PNG\r\n\x1a\n")
        arq.write(bloco(b"IHDR", cabecalho))
        arq.write(bloco(b"IDAT", zlib.compress(cru, 6)))
        arq.write(bloco(b"IEND", b""))
