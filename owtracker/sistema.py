"""Integração com o Windows: iniciar com o sistema e abrir a janela do app."""

import os
import subprocess
import sys
import webbrowser
import winreg
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
CHAVE_INICIAR = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOME_INICIAR = "OW Tracker"

LOCAIS_EDGE = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / r"Microsoft\Edge\Application\msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / r"Microsoft\Edge\Application\msedge.exe",
)


def abrir_janela(url, largura=1440, altura=900):
    """Abre a interface numa janela de aplicativo (Edge sem abas nem barra de
    endereço). Sem o Edge, usa o navegador padrão."""
    edge = next((p for p in LOCAIS_EDGE if p.exists()), None)
    if edge:
        subprocess.Popen([str(edge), f"--app={url}", f"--window-size={largura},{altura}"],
                         creationflags=subprocess.DETACHED_PROCESS)
    else:
        webbrowser.open(url)


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
