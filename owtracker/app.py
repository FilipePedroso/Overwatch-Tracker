"""Ponto de entrada do OW Tracker.

Roda em segundo plano (monitor do jogo + servidor local) e abre a interface
numa janela de aplicativo do Edge. Fechar a janela NÃO para o registro; para
encerrar de vez, use "Sair" nos Ajustes.

    python -m owtracker               abre o app
    python -m owtracker --minimizado  só o segundo plano (iniciar com o Windows)
"""

import json
import logging
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from . import janelas, sistema
from .banco import PASTA_DADOS
from .servico import Servico
from .servidor import criar_servidor, rodar_em_segundo_plano

PORTA = 47815
URL = f"http://127.0.0.1:{PORTA}/"
PASTA_CAPTURAS = Path(__file__).resolve().parent.parent / "capturas"

VK_O, VK_P = 0x4F, 0x50
ATALHOS = {  # nome: (modificadores, tecla)
    "abrir": (janelas.MOD_CONTROL | janelas.MOD_SHIFT, VK_O),   # Ctrl+Shift+O: abrir o app
    "print": (janelas.MOD_CONTROL | janelas.MOD_SHIFT, VK_P),   # Ctrl+Shift+P: print da tela
}


def ja_rodando():
    """Outra cópia do app já está no ar? (responde no /api/ping)"""
    try:
        with urllib.request.urlopen(URL + "api/ping", timeout=1) as resposta:
            return json.load(resposta).get("app") == "owtracker"
    except OSError:
        return False


def configurar_log():
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=PASTA_DADOS / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stderr is None:  # pythonw não tem console: erros vão para o log
        sys.stderr = open(PASTA_DADOS / "app.log", "a", encoding="utf-8")


def ao_atalho(nome):
    if nome == "abrir":
        sistema.abrir_janela(URL)
    elif nome == "print":
        PASTA_CAPTURAS.mkdir(exist_ok=True)
        arquivo = PASTA_CAPTURAS / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
        janelas.salvar_png(arquivo, *janelas.capturar_tela())


def main():
    configurar_log()
    janelas.ativar_dpi_real()
    minimizado = "--minimizado" in sys.argv
    if ja_rodando():
        if not minimizado:
            sistema.abrir_janela(URL, esperar=True)  # esta cópia encerra em seguida
        return

    servico = Servico()
    servidor = criar_servidor(servico, PORTA)
    rodar_em_segundo_plano(servidor)
    servico.iniciar()

    atalhos = janelas.Atalhos(ao_atalho)
    for nome, (modificadores, tecla) in ATALHOS.items():
        atalhos.adicionar(nome, modificadores, tecla)
    atalhos.iniciar()

    logging.getLogger("owtracker").info("no ar em %s", URL)
    if not minimizado:
        sistema.abrir_janela(URL)

    try:
        while not servico.sair.wait(1):  # até "Sair" na interface (ou Ctrl+C no terminal)
            pass
    except KeyboardInterrupt:
        pass
    atalhos.parar()
    servico.parar()
    servidor.shutdown()
