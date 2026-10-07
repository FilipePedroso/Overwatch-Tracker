"""Captura de tela que funciona com jogo em TELA CHEIA exclusiva.

Usa DXGI Desktop Duplication (a mesma API da "Captura de Tela" do OBS): a GPU
copia a imagem do monitor e só a região pedida é lida pela CPU.
Se a duplicação não estiver disponível, cai para a captura GDI.

Também localiza a janela do Overwatch e informa sua resolução real.
"""

import ctypes
from ctypes import POINTER, byref, c_uint32, c_void_p, wintypes

from . import janelas
from .com import GUID, ErroCOM, Objeto

d3d11 = ctypes.WinDLL("d3d11")
dxgi = ctypes.WinDLL("dxgi")
user32 = janelas.user32
kernel32 = janelas.kernel32

IID_IDXGIFactory1 = "770aae78-f26f-4dba-a829-253c83d1b387"
IID_IDXGIOutput1 = "00cddea8-939b-4b83-a340-a685226666cc"
IID_ID3D11Texture2D = "6f15aaf2-d208-4e89-9ab4-489535d34f9c"

DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ERROR_ACCESS_LOST = 0x887A0026
DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027

D3D_DRIVER_TYPE_UNKNOWN = 0
D3D11_SDK_VERSION = 7
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1

dxgi.CreateDXGIFactory1.argtypes = [POINTER(GUID), POINTER(c_void_p)]
d3d11.D3D11CreateDevice.argtypes = [
    c_void_p, ctypes.c_int, c_void_p, c_uint32, c_void_p, c_uint32, c_uint32,
    POINTER(c_void_p), c_void_p, POINTER(c_void_p)]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
user32.GetClientRect.argtypes = [wintypes.HWND, POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, POINTER(wintypes.POINT)]
user32.IsIconic.argtypes = [wintypes.HWND]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class DescricaoSaida(ctypes.Structure):  # DXGI_OUTPUT_DESC
    _fields_ = [("nome", ctypes.c_wchar * 32), ("area", wintypes.RECT),
                ("na_area_de_trabalho", wintypes.BOOL), ("rotacao", c_uint32),
                ("monitor", wintypes.HMONITOR)]


class InfoQuadro(ctypes.Structure):  # DXGI_OUTDUPL_FRAME_INFO
    _fields_ = [("ultimo_present", ctypes.c_int64), ("ultimo_mouse", ctypes.c_int64),
                ("quadros_acumulados", c_uint32), ("retangulos_unidos", wintypes.BOOL),
                ("conteudo_protegido", wintypes.BOOL), ("mouse_x", ctypes.c_long),
                ("mouse_y", ctypes.c_long), ("mouse_visivel", wintypes.BOOL),
                ("metadados", c_uint32), ("forma_mouse", c_uint32)]


class DescricaoTextura(ctypes.Structure):  # D3D11_TEXTURE2D_DESC
    _fields_ = [("largura", c_uint32), ("altura", c_uint32), ("mips", c_uint32),
                ("camadas", c_uint32), ("formato", c_uint32), ("amostras", c_uint32),
                ("qualidade", c_uint32), ("uso", c_uint32), ("bind", c_uint32),
                ("acesso_cpu", c_uint32), ("misc", c_uint32)]


class Mapeamento(ctypes.Structure):  # D3D11_MAPPED_SUBRESOURCE
    _fields_ = [("dados", c_void_p), ("passo_linha", c_uint32), ("passo_camada", c_uint32)]


# ---------------------------------------------------------------- janela do jogo

PROCESSOS_JOGO = ("overwatch.exe",)


def nome_do_processo(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    processo = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not processo:
        return ""
    try:
        tamanho = wintypes.DWORD(1024)
        caminho = ctypes.create_unicode_buffer(tamanho.value)
        if kernel32.QueryFullProcessImageNameW(processo, 0, caminho, byref(tamanho)):
            return caminho.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(processo)


def jogo_em_foco():
    """Se o Overwatch está em primeiro plano, retorna (hwnd, x, y, largura, altura)
    da área do jogo em coordenadas de tela. Senão, None."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or user32.IsIconic(hwnd) or nome_do_processo(hwnd) not in PROCESSOS_JOGO:
        return None
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, byref(rect))
    canto = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, byref(canto))
    largura, altura = rect.right - rect.left, rect.bottom - rect.top
    if largura < 200 or altura < 200:
        return None
    return hwnd, canto.x, canto.y, largura, altura


# ---------------------------------------------------------------- captura

class Captura:
    """Captura regiões da tela. Crie e use sempre na mesma thread."""

    def __init__(self):
        self._monitor = None
        self._dup = None
        self.metodo = "nenhum"

    # -- preparação --------------------------------------------------

    def _preparar(self, hmonitor):
        self._liberar()
        fabrica = c_void_p()
        hr = dxgi.CreateDXGIFactory1(byref(GUID.de(IID_IDXGIFactory1)), byref(fabrica))
        if hr < 0:
            raise ErroCOM(hr, "CreateDXGIFactory1")
        fabrica = Objeto(fabrica)

        i = 0
        while True:
            adaptador = c_void_p()
            if fabrica.hr(7, (c_uint32, POINTER(c_void_p)), i, byref(adaptador)) == DXGI_ERROR_NOT_FOUND:
                raise RuntimeError("Monitor do jogo não encontrado em nenhuma placa de vídeo.")
            adaptador = Objeto(adaptador)
            j = 0
            while True:
                saida = c_void_p()
                if adaptador.hr(7, (c_uint32, POINTER(c_void_p)), j, byref(saida)) == DXGI_ERROR_NOT_FOUND:
                    break
                saida = Objeto(saida)
                desc = DescricaoSaida()
                saida.chamar(7, (POINTER(DescricaoSaida),), byref(desc), onde="IDXGIOutput::GetDesc")
                if desc.monitor == hmonitor:
                    self._abrir(adaptador, saida, desc)
                    self._monitor = hmonitor
                    return
                j += 1
            i += 1

    def _abrir(self, adaptador, saida, desc):
        dispositivo, contexto = c_void_p(), c_void_p()
        hr = d3d11.D3D11CreateDevice(adaptador.p, D3D_DRIVER_TYPE_UNKNOWN, None, 0, None, 0,
                                     D3D11_SDK_VERSION, byref(dispositivo), None, byref(contexto))
        if hr < 0:
            raise ErroCOM(hr, "D3D11CreateDevice")
        self._dispositivo, self._contexto = Objeto(dispositivo), Objeto(contexto)
        self._dup = saida.consultar(IID_IDXGIOutput1).obter(
            22, c_void_p, args=(self._dispositivo.p,), onde="DuplicateOutput")
        self.area = desc.area  # posição do monitor na área de trabalho
        self._copia = None
        self._tem_quadro = False

    def _liberar(self):
        for nome in ("_copia", "_dup", "_contexto", "_dispositivo"):
            obj = getattr(self, nome, None)
            if obj:
                obj.liberar()
            setattr(self, nome, None)
        self._monitor = None

    # -- captura -----------------------------------------------------

    def capturar(self, x, y, largura, altura, hwnd=None):
        """Captura a região (coordenadas de tela). Retorna bytes BGRA ou None."""
        try:
            hmonitor = user32.MonitorFromWindow(hwnd, 2) if hwnd else None  # NEAREST
            if hmonitor and hmonitor != self._monitor:
                self._preparar(hmonitor)
            if self._dup:
                dados = self._capturar_dxgi(x, y, largura, altura)
                if dados is not None:
                    self.metodo = "DXGI"
                    return dados
        except (OSError, RuntimeError) as erro:
            print("DXGI indisponível, usando GDI:", erro)
            self._liberar()
        self.metodo = "GDI"
        return self._capturar_gdi(x, y, largura, altura)

    def _capturar_dxgi(self, x, y, largura, altura):
        info, recurso = InfoQuadro(), c_void_p()
        hr = self._dup.hr(8, (c_uint32, POINTER(InfoQuadro), POINTER(c_void_p)),
                          100, byref(info), byref(recurso))
        if hr == DXGI_ERROR_ACCESS_LOST:
            # O jogo trocou a resolução ou o modo de tela: recomeça.
            monitor = self._monitor
            self._liberar()
            self._preparar(monitor)
            return None
        if hr == DXGI_ERROR_WAIT_TIMEOUT:
            if not self._tem_quadro:
                return None  # tela parada e ainda sem cópia: tenta de novo depois
        elif hr & 0x80000000:
            raise ErroCOM(hr, "AcquireNextFrame")
        else:
            recurso = Objeto(recurso)
            try:
                textura = recurso.consultar(IID_ID3D11Texture2D)
                if self._copia is None:
                    self._criar_copia(textura)
                self._contexto.metodo(47, c_void_p, c_void_p, retorno=None)(
                    self._contexto.p, self._copia.p, textura.p)  # CopyResource
                self._tem_quadro = True
            finally:
                recurso.liberar()
                self._dup.hr(14, ())  # ReleaseFrame
        return self._ler_regiao(x - self.area.left, y - self.area.top, largura, altura)

    def _criar_copia(self, textura):
        desc = DescricaoTextura()
        textura.metodo(10, POINTER(DescricaoTextura), retorno=None)(textura.p, byref(desc))
        desc.mips, desc.camadas, desc.amostras, desc.qualidade = 1, 1, 1, 0
        desc.uso, desc.bind = D3D11_USAGE_STAGING, 0
        desc.acesso_cpu, desc.misc = D3D11_CPU_ACCESS_READ, 0
        self._copia = self._dispositivo.obter(5, POINTER(DescricaoTextura), c_void_p,
                                              args=(byref(desc), None), onde="CreateTexture2D")
        self.tamanho_monitor = (desc.largura, desc.altura)

    def _ler_regiao(self, x, y, largura, altura):
        lm, am = self.tamanho_monitor
        x, y = max(0, x), max(0, y)
        largura, altura = min(largura, lm - x), min(altura, am - y)
        mapa = Mapeamento()
        self._contexto.chamar(14, (c_void_p, c_uint32, c_uint32, c_uint32, POINTER(Mapeamento)),
                              self._copia.p, 0, D3D11_MAP_READ, 0, byref(mapa), onde="Map")
        try:
            passo, inicio, n = mapa.passo_linha, mapa.dados + x * 4, largura * 4
            if x == 0 and largura * 4 == passo:
                return ctypes.string_at(inicio + y * passo, passo * altura), largura, altura
            linhas = [ctypes.string_at(inicio + (y + i) * passo, n) for i in range(altura)]
            return b"".join(linhas), largura, altura
        finally:
            self._contexto.metodo(15, c_void_p, c_uint32, retorno=None)(self._contexto.p, self._copia.p, 0)

    def _capturar_gdi(self, x, y, largura, altura):
        bgra = janelas.capturar_tela_bgra(x, y, largura, altura)
        return bgra, largura, altura

    def fechar(self):
        self._liberar()
