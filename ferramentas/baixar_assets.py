"""Baixa os ícones e imagens listados no catálogo para owtracker/referencia/assets/.

Fontes: site oficial da Blizzard (retratos, ícones de habilidade, função e
subfunção) e Overwatch Wiki (ícones de modo, imagens dos mapas e de vantagens).
As imagens são da Blizzard: uso pessoal, não redistribuir (a pasta fica fora do git).

Uso:  python ferramentas/baixar_assets.py
Arquivos já baixados são pulados; rode de novo depois de atualizar o catálogo.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from owtracker import catalogo  # noqa: E402

DESTINO = catalogo.PASTA / "assets"
AGENTE = "OWTracker-referencia/1.0 (projeto pessoal; coleta ocasional)"
PAUSA = 0.15


def extensao(url):
    sufixo = Path(urlparse(url).path).suffix.lower()
    return sufixo if sufixo in (".png", ".svg", ".jpg", ".jpeg", ".webp") else ".png"


def itens():
    """(pasta, nome do arquivo sem extensão, url) de tudo que o catálogo referencia."""
    c = catalogo.carregar()
    for h in c["herois"]:
        yield "herois", h["id"], h["retrato_url"]
        for a in h["habilidades"]:
            yield "habilidades", f"{h['id']}__{a['id']}", a["icone_url"] or a.get("imagem_wiki_url")
    for f in c["funcoes"]:
        yield "funcoes", f["id"], f["icone_url"]
    for s in c["subfuncoes"]:
        yield "subfuncoes", s["id"], s["icone_url"]
    for m in c["modos"]:
        yield "modos", m["id"], m["icone_url"]
    for m in c["mapas"]:
        yield "mapas", m["id"], m["imagem_url"]


def main():
    indice, baixados, pulados, falhas = {}, 0, 0, []
    lista = [i for i in itens() if i[2]]
    for n, (pasta, nome, url) in enumerate(lista, 1):
        arquivo = DESTINO / pasta / (nome + extensao(url))
        indice[f"{pasta}/{nome}"] = str(arquivo.relative_to(catalogo.PASTA)).replace("\\", "/")
        if arquivo.exists():
            pulados += 1
            continue
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        try:
            pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                arquivo.write_bytes(resposta.read())
            baixados += 1
        except OSError as erro:
            falhas.append((url, str(erro)))
            del indice[f"{pasta}/{nome}"]
        if n % 50 == 0:
            print(f"{n}/{len(lista)}...")
        time.sleep(PAUSA)
    (DESTINO / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), "utf-8")
    print(f"ok: {baixados} baixados, {pulados} já existiam, {len(falhas)} falhas")
    for url, erro in falhas:
        print("  falhou:", url, erro)


if __name__ == "__main__":
    main()
