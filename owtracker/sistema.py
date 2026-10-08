"""Integração com o Windows: iniciar com o sistema e abrir a janela do app."""

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
from ctypes import wintypes
from pathlib import Path

from .captura import nome_do_processo

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
CHAVE_INICIAR = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOME_INICIAR = "OW Tracker"

LOCAIS_EDGE = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / r"Microsoft\Edge\Application\msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / r"Microsoft\Edge\Application\msedge.exe",
)


def abrir_janela(url, esperar=False):
    """Abre a interface numa janela de aplicativo (Edge sem abas nem barra de
    endereço), ou traz para frente a que já estiver aberta.

    A janela usa um perfil do Edge só dela (dados/janela-edge): assim cada
    abertura sobe um Edge próprio, que respeita o tamanho pedido (um Edge já
    aberto ignoraria o tamanho e usaria o padrão dele, meia tela).
    O tamanho é o da última vez (ver lembrar_tamanho_da_janela) ou,
    na primeira vez, o padrão centralizado. Nada é forçado depois que a janela
    aparece: você pode mexer nela à vontade.
    esperar=True aguarda a janela aparecer (para quem vai encerrar logo em seguida).
    Sem o Edge, usa o navegador padrão."""
    abertas = _janelas_do_app()
    if abertas:
        _trazer_para_frente(abertas[0])
        return
    edge = next((p for p in LOCAIS_EDGE if p.exists()), None)
    if not edge:
        webbrowser.open(url)
        return
    x, y, largura, altura, maximizada = _tamanho_lembrado() or (*_retangulo_padrao(), False)
    escala = user32.GetDpiForSystem() / 96  # o Edge recebe o tamanho sem a escala do Windows
    comando = [str(edge), f"--app={url}", f"--user-data-dir={PERFIL_EDGE}",
               "--no-first-run", "--no-default-browser-check",
               f"--window-size={int(largura / escala)},{int(altura / escala)}",
               f"--window-position={int(x / escala)},{int(y / escala)}"]
    subprocess.Popen(comando, creationflags=subprocess.DETACHED_PROCESS)
    frente = threading.Thread(target=_frente_quando_abrir, args=(maximizada,), daemon=True, name="janela")
    frente.start()
    if esperar:
        frente.join()


# ---------------------------------------------------------------- janela (Win32)

TITULO_JANELA = "OW Tracker"  # <title> da interface = título da janela do Edge
PERFIL_EDGE = RAIZ_PROJETO / "dados" / "janela-edge"  # perfil do Edge só da janela do app
SW_RESTORE = 9
SW_MAXIMIZE = 3

user32 = ctypes.WinDLL("user32", use_last_error=True)
_ENUMERAR = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_ENUMERAR, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]


def _janelas_do_app():
    """Janelas visíveis do Edge com o título da interface."""
    achadas = []

    def visitar(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            tamanho = user32.GetWindowTextLengthW(hwnd)
            if tamanho == len(TITULO_JANELA):
                titulo = ctypes.create_unicode_buffer(tamanho + 1)
                user32.GetWindowTextW(hwnd, titulo, tamanho + 1)
                if titulo.value == TITULO_JANELA and nome_do_processo(hwnd) == "msedge.exe":
                    achadas.append(hwnd)
        return True

    user32.EnumWindows(_ENUMERAR(visitar), 0)
    return achadas


def _retangulo_padrao():
    """(x, y, largura, altura) centralizado na área útil do monitor principal
    (sem a barra de tarefas): 90% da largura e 92% da altura, até 1600×1000."""
    area = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
    livre_l, livre_a = area.right - area.left, area.bottom - area.top
    largura, altura = min(1600, int(livre_l * 0.90)), min(1000, int(livre_a * 0.92))
    return area.left + (livre_l - largura) // 2, area.top + (livre_a - altura) // 2, largura, altura


def _trazer_para_frente(hwnd):
    """Põe a janela na frente. O Windows só deixa quem está em primeiro plano
    passar o foco adiante; o app roda em segundo plano, então se liga por um
    instante à fila de entrada da janela em foco (AttachThreadInput)."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    em_foco = user32.GetForegroundWindow()
    deles = user32.GetWindowThreadProcessId(em_foco, None) if em_foco else 0
    nosso = kernel32.GetCurrentThreadId()
    ligado = bool(deles) and deles != nosso and user32.AttachThreadInput(nosso, deles, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if ligado:
            user32.AttachThreadInput(nosso, deles, False)


def _frente_quando_abrir(maximizar=False, limite=15.0):
    """Espera a janela nova aparecer, maximiza (se estava maximizada da última
    vez; o Edge ignora --start-maximized nesse modo) e traz para frente. Uma
    ação só: depois disso a janela é sua."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        abertas = _janelas_do_app()
        if abertas:
            if maximizar:
                user32.ShowWindow(abertas[0], SW_MAXIMIZE)
            for _ in range(10):  # a abertura demora um pouco: insiste até ficar na frente
                _trazer_para_frente(abertas[0])
                if user32.GetForegroundWindow() == abertas[0]:
                    return
                time.sleep(0.3)
            return
        time.sleep(0.1)


def lembrar_tamanho_da_janela(parar):
    """Roda no serviço: a cada 2 s, se a janela do app estiver aberta, anota
    tamanho/posição/maximizada para a próxima abertura (custo: ~1 ms)."""
    anterior = None
    while not parar.wait(2):
        abertas = _janelas_do_app()
        if not abertas or user32.IsIconic(abertas[0]):
            continue
        maximizada = bool(user32.IsZoomed(abertas[0]))
        # maximizada: mantém o tamanho "normal" de antes, para quando sair do maximizado
        retangulo = anterior[:4] if maximizada and anterior else _retangulo(abertas[0])
        atual = (*retangulo, maximizada)
        if atual != anterior:
            _lembrar_tamanho(atual)
            anterior = atual


ARQUIVO_JANELA = RAIZ_PROJETO / "dados" / "janela.json"


def _lembrar_tamanho(tamanho):
    try:
        ARQUIVO_JANELA.write_text(json.dumps(tamanho), "utf-8")
    except OSError:
        pass


def _tamanho_lembrado():
    """(x, y, largura, altura, maximizada) da última vez, se ainda couber na tela."""
    try:
        x, y, largura, altura, maximizada = json.loads(ARQUIVO_JANELA.read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    area = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
    cabe = (largura >= 600 and altura >= 400 and x + 100 < area.right and y >= area.top - 20
            and x + largura > area.left + 100 and y + 100 < area.bottom)
    return (x, y, largura, altura, maximizada) if cabe else None


def _retangulo(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def abrir_pasta(pasta):
    Path(pasta).mkdir(parents=True, exist_ok=True)
    os.startfile(pasta)


def comando_iniciar():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executavel = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{executavel}" "{RAIZ_PROJETO / "OW Tracker.pyw"}" --minimizado'


def inicia_com_windows():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_INICIAR) as chave:
            winreg.QueryValueEx(chave, NOME_INICIAR)
            return True
    except OSError:
        return False


def definir_iniciar_com_windows(ligado):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_INICIAR, 0, winreg.KEY_SET_VALUE) as chave:
        if ligado:
            winreg.SetValueEx(chave, NOME_INICIAR, 0, winreg.REG_SZ, comando_iniciar())
        else:
            try:
                winreg.DeleteValue(chave, NOME_INICIAR)
            except FileNotFoundError:
                pass
