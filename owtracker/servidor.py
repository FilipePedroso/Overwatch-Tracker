"""Servidor web local da interface (só 127.0.0.1).

Entrega a página (owtracker/web), as imagens (owtracker/referencia/assets) e
uma API JSON pequena sobre o Servico. Segurança:
- escuta apenas em 127.0.0.1;
- confere o cabeçalho Host (evita que um site use "DNS rebinding" para falar
  com o servidor);
- ações que alteram dados exigem o cabeçalho X-OWTracker, que uma página de
  outro site não consegue enviar sem permissão do servidor (CORS).
"""

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import catalogo

PASTA_WEB = Path(__file__).resolve().parent / "web"
PASTA_ASSETS = catalogo.PASTA / "assets"
TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".json": "application/json",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".svg": "image/svg+xml", ".webp": "image/webp", ".ico": "image/x-icon"}

log = logging.getLogger("owtracker.servidor")


def criar_servidor(servico, porta):
    class Manipulador(_Manipulador):
        pass
    Manipulador.servico = servico
    Manipulador.hosts = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
    return ThreadingHTTPServer(("127.0.0.1", porta), Manipulador)


def rodar_em_segundo_plano(servidor):
    threading.Thread(target=servidor.serve_forever, daemon=True, name="servidor").start()


class _Manipulador(BaseHTTPRequestHandler):
    servico = None
    hosts = set()

    def log_message(self, formato, *args):  # sem poluir o console
        pass

    # ------------------------------------------------------------ respostas

    def _enviar(self, codigo, corpo, tipo="application/json", cache=False):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dados, codigo=200):
        self._enviar(codigo, json.dumps(dados, ensure_ascii=False).encode("utf-8"))

    def _arquivo(self, base, relativo, cache=False):
        caminho = (base / relativo).resolve()
        if base.resolve() not in caminho.parents or not caminho.is_file():
            return self._json({"erro": "não encontrado"}, 404)
        self._enviar(200, caminho.read_bytes(), TIPOS.get(caminho.suffix.lower(), "application/octet-stream"),
                     cache)

    def _permitido(self, escrita=False):
        if self.headers.get("Host") not in self.hosts:
            self._json({"erro": "host não permitido"}, 403)
            return False
        if escrita and self.headers.get("X-OWTracker") != "1":
            self._json({"erro": "cabeçalho ausente"}, 403)
            return False
        return True

    def _corpo(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(tamanho) or b"{}") if tamanho else {}

    # ------------------------------------------------------------ rotas

    def do_GET(self):
        if not self._permitido():
            return
        rota = self.path.split("?")[0]
        s = self.servico
        try:
            if rota == "/":
                return self._arquivo(PASTA_WEB, "index.html")
            if rota.startswith("/assets/"):
                return self._arquivo(PASTA_ASSETS, rota[len("/assets/"):], cache=True)
            if rota == "/api/ping":
                return self._json({"app": "owtracker"})
            if rota == "/api/estado":
                return self._json(s.estado())
            if rota == "/api/partidas":
                return self._json(s.partidas())
            if rota == "/api/inimigos":
                return self._json(s.inimigos())
            if rota == "/api/catalogo":
                return self._json(s.catalogo())
            m = re.fullmatch(r"/api/partidas/(\d+)/jogadores", rota)
            if m:
                return self._json(s.jogadores(int(m.group(1))))
            m = re.fullmatch(r"/api/partidas/(\d+)/habilidades", rota)
            if m:
                return self._json(s.habilidades_da_partida(int(m.group(1))))
            m = re.fullmatch(r"/api/partidas/(\d+)/estatisticas", rota)
            if m:
                return self._json(s.estatisticas_da_partida(int(m.group(1))))
            m = re.fullmatch(r"/api/herois/([\w-]+)/estatisticas", rota)
            if m:
                return self._json(s.estatisticas_do_heroi(m.group(1)))
            m = re.fullmatch(r"/api/herois/([\w-]+)/habilidades", rota)
            if m:
                return self._json(s.habilidades_do_heroi(m.group(1)))
            m = re.fullmatch(r"/api/retratos/(\d+)/(aliados|inimigos)/([0-4])\.png", rota)
            if m:
                png = s.retrato(int(m.group(1)), m.group(2), int(m.group(3)))
                if png:
                    return self._enviar(200, png, "image/png", cache=True)
                return self._json({"erro": "não encontrado"}, 404)
            if re.fullmatch(r"/[\w.-]+\.(css|js|ico|png|svg)", rota):
                return self._arquivo(PASTA_WEB, rota[1:])
            self._json({"erro": "não encontrado"}, 404)
        except Exception:
            log.exception("erro em GET %s", rota)
            self._json({"erro": "erro interno"}, 500)

    def do_POST(self):
        self._alterar("POST")

    def do_PUT(self):
        self._alterar("PUT")

    def do_DELETE(self):
        self._alterar("DELETE")

    def _alterar(self, metodo):
        if not self._permitido(escrita=True):
            return
        rota, s = self.path.split("?")[0], self.servico
        try:
            corpo = self._corpo()
            id_ = re.fullmatch(r"/api/partidas/(\d+)", rota)
            if metodo == "POST" and rota == "/api/partidas":
                return self._json({"id": s.salvar_partida(corpo)})
            if metodo == "PUT" and id_:
                return self._json({"id": s.salvar_partida(corpo, int(id_.group(1)))})
            if metodo == "DELETE" and id_:
                s.apagar_partida(int(id_.group(1)))
                return self._json({"ok": True})
            jogador = re.fullmatch(r"/api/partidas/(\d+)/jogadores/(aliados|inimigos)/([0-4])", rota)
            if metodo == "PUT" and jogador:
                s.corrigir_jogador(int(jogador.group(1)), jogador.group(2), int(jogador.group(3)),
                                   corpo.get("heroi_id") or None)
                return self._json({"ok": True})
            if metodo == "POST" and rota == "/api/pendente":
                s.confirmar_pendente(corpo.get("resultado"))
                return self._json({"ok": True})
            if metodo == "POST" and rota == "/api/andamento/descartar":
                s.descartar_andamento()
                return self._json({"ok": True})
            if metodo == "POST" and rota == "/api/ajustes":
                s.ajustar(corpo)
                return self._json({"ok": True})
            if metodo == "POST" and rota == "/api/pasta-diagnostico":
                s.abrir_pasta_diagnostico()
                return self._json({"ok": True})
            if metodo == "POST" and rota in ("/api/sair", "/api/reiniciar"):
                self._json({"ok": True})
                s.reiniciar = rota == "/api/reiniciar"
                s.sair.set()
                return
            self._json({"erro": "não encontrado"}, 404)
        except ValueError as erro:
            self._json({"erro": str(erro)}, 400)
        except Exception:
            log.exception("erro em %s %s", metodo, rota)
            self._json({"erro": "erro interno"}, 500)
