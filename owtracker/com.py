"""Mini camada para chamar objetos COM / WinRT do Windows via ctypes.

Um objeto COM é um ponteiro para uma tabela de funções (vtable). Chamamos o
método pelo índice dessa tabela, na ordem em que a interface foi declarada.
"""

import ctypes
import uuid
from ctypes import POINTER, byref, c_long, c_ulong, c_void_p

combase = ctypes.WinDLL("combase")
combase.WindowsCreateString.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, POINTER(c_void_p)]
combase.WindowsDeleteString.argtypes = [c_void_p]
combase.WindowsGetStringRawBuffer.argtypes = [c_void_p, POINTER(ctypes.c_uint32)]
combase.WindowsGetStringRawBuffer.restype = c_void_p
combase.RoGetActivationFactory.argtypes = [c_void_p, c_void_p, POINTER(c_void_p)]


class ErroCOM(OSError):
    def __init__(self, hr, onde=""):
        self.hr = hr & 0xFFFFFFFF
        super().__init__(f"{onde} falhou: HRESULT 0x{self.hr:08X}")


class GUID(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    @classmethod
    def de(cls, texto):
        g = cls()
        ctypes.memmove(byref(g), uuid.UUID(texto).bytes_le, 16)
        return g


class Objeto:
    """Referência a um objeto COM; libera automaticamente ao ser descartado."""

    def __init__(self, ponteiro):
        self.p = ponteiro if isinstance(ponteiro, c_void_p) else c_void_p(ponteiro)

    def __bool__(self):
        return bool(self.p.value)

    def metodo(self, indice, *tipos, retorno=c_long):
        vtable = ctypes.cast(self.p, POINTER(POINTER(c_void_p))).contents
        return ctypes.WINFUNCTYPE(retorno, c_void_p, *tipos)(vtable[indice])

    def hr(self, indice, tipos, *args):
        """Chama e devolve o HRESULT cru (para tratar códigos específicos)."""
        return self.metodo(indice, *tipos)(self.p, *args) & 0xFFFFFFFF

    def chamar(self, indice, tipos, *args, onde="método"):
        hr = self.metodo(indice, *tipos)(self.p, *args)
        if hr < 0:
            raise ErroCOM(hr, onde)

    def obter(self, indice, *tipos_antes, args=(), onde="método"):
        """Chama um método cujo último parâmetro é um ponteiro de saída para objeto."""
        saida = c_void_p()
        self.chamar(indice, (*tipos_antes, POINTER(c_void_p)), *args, byref(saida), onde=onde)
        return Objeto(saida)

    def consultar(self, iid):
        """QueryInterface: pede outra interface do mesmo objeto."""
        return self.obter(0, POINTER(GUID), args=(byref(GUID.de(iid)),), onde="QueryInterface")

    def liberar(self):
        if self.p.value:
            self.metodo(2, retorno=c_ulong)(self.p)
            self.p = c_void_p()

    def __del__(self):
        try:
            self.liberar()
        except Exception:
            pass


# ---------------------------------------------------------------- WinRT

def hstring_para_texto(hstr):
    if not hstr:
        return ""
    tamanho = ctypes.c_uint32()
    buffer = combase.WindowsGetStringRawBuffer(hstr, byref(tamanho))
    texto = ctypes.wstring_at(buffer, tamanho.value) if buffer else ""
    combase.WindowsDeleteString(hstr)
    return texto


def fabrica_winrt(classe, iid):
    """RoGetActivationFactory: obtém os métodos estáticos de uma classe WinRT."""
    nome = c_void_p()
    combase.WindowsCreateString(classe, len(classe), byref(nome))
    try:
        saida = c_void_p()
        hr = combase.RoGetActivationFactory(nome, byref(GUID.de(iid)), byref(saida))
        if hr < 0:
            raise ErroCOM(hr, f"RoGetActivationFactory({classe})")
        return Objeto(saida)
    finally:
        combase.WindowsDeleteString(nome)


def iniciar_winrt():
    """Inicializa WinRT/COM na thread atual (modo multithread)."""
    combase.RoInitialize(1)  # já inicializado também serve
