// OW Tracker: interface. Conversa com o serviço local (servidor.py) via /api.
"use strict";

// ------------------------------------------------------------------ API

const api = {
  ler: (url) => fetch(url).then((r) => r.json()),
  enviar: async (metodo, url, corpo) => {
    const r = await fetch(url, {
      method: metodo,
      headers: { "Content-Type": "application/json", "X-OWTracker": "1" },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
    const dados = await r.json();
    if (!r.ok) throw new Error(dados.erro || "Algo deu errado.");
    return dados;
  },
};

// ------------------------------------------------------------------ estado

const app = {
  catalogo: null,
  partidas: [],
  estado: null,
  versao: -1,
  ultimoAviso: null,
  filtros: carregarFiltros(),
  ref: {},  // índices do catálogo
};

function carregarFiltros() {
  try {
    return { periodo: "tudo", fila: "todas", ...JSON.parse(localStorage.getItem("filtros") || "{}") };
  } catch {
    return { periodo: "tudo", fila: "todas" };
  }
}
function salvarFiltros() {
  try { localStorage.setItem("filtros", JSON.stringify(app.filtros)); } catch { /* sem armazenamento: tudo bem */ }
}

const normalizar = (t) => (t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/gi, "").toLowerCase();
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("pt-BR"));
const COLUNAS = ["eliminacoes", "assistencias", "mortes", "dano", "cura", "mitigado"];
const CORES_FUNCAO = { tank: "var(--tank)", damage: "var(--damage)", support: "var(--support)" };
const TIPOS_HABILIDADE = {
  arma: "Arma", habilidade: "Habilidade", suprema: "Suprema", passiva: "Passiva",
  vantagem_menor: "Vantagem menor", vantagem_maior: "Vantagem maior",
};

// Teclas e tempos vêm da wiki em inglês.
const TECLAS = {
  "primary fire": "Disparo primário", "secondary fire": "Disparo secundário", "ability 1": "Habilidade 1",
  "ability 2": "Habilidade 2", "ability 3": "Habilidade 3", "ultimate": "Suprema", "melee": "Corpo a corpo",
  "jump": "Pular", "crouch": "Agachar", "reload": "Recarregar", "interact": "Interagir",
};
const traduzirTecla = (t) => t.split(/\s*(?:,|\bor\b)\s*/i).map((k) => TECLAS[k.trim().toLowerCase()] || k.trim()).join(" ou ");
const traduzirTempo = (t) => t.replace(/\s*seconds?\b/gi, " s").replace(/\bper\b/gi, "por");

function indexar() {
  const c = app.catalogo, r = app.ref;
  r.heroi = Object.fromEntries(c.herois.map((h) => [h.id, h]));
  r.heroiNome = {};
  for (const h of c.herois) for (const n of [h.nome, h.nome_en, h.id]) r.heroiNome[normalizar(n)] = h;
  r.mapa = Object.fromEntries(c.mapas.map((m) => [m.id, m]));
  r.mapaNome = {};
  for (const m of c.mapas) for (const n of [m.nome, m.nome_en, m.id]) r.mapaNome[normalizar(n)] = m;
  r.funcao = Object.fromEntries(c.funcoes.map((f) => [f.id, f]));
  r.sub = Object.fromEntries(c.subfuncoes.map((s) => [s.id, s]));
  r.modo = Object.fromEntries(c.modos.map((m) => [m.id, m]));
}
const heroiDe = (p) => app.ref.heroi[p.heroi_id] || app.ref.heroiNome[normalizar(p.heroi)];
const mapaDe = (p) => app.ref.mapa[p.mapa_id] || app.ref.mapaNome[normalizar(p.mapa)];

// ------------------------------------------------------------------ cálculos

function filtradas() {
  const agora = new Date();
  const inicioHoje = new Date(agora.getFullYear(), agora.getMonth(), 1 * agora.getDate());
  const limite = { hoje: inicioHoje, "7d": new Date(agora - 7 * 864e5), "30d": new Date(agora - 30 * 864e5) }[app.filtros.periodo];
  return app.partidas.filter((p) =>
    (!limite || new Date(p.data_hora) >= limite) &&
    (app.filtros.fila === "todas" || p.modo === app.filtros.fila));
}
const vitorias = (l) => l.filter((p) => p.resultado === "Vitória").length;
const derrotas = (l) => l.filter((p) => p.resultado === "Derrota").length;
function taxa(l) {
  const decididas = vitorias(l) + derrotas(l);
  return decididas ? Math.round((100 * vitorias(l)) / decididas) : null;
}
function media(l, campo) {
  const v = l.map((p) => p[campo]).filter((x) => x !== null && x !== undefined);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}
const corTaxa = (t) => (t === null ? "var(--texto-3)" : t >= 55 ? "var(--vitoria)" : t >= 45 ? "var(--laranja)" : "var(--derrota)");
const pct = (t) => (t === null ? "—" : `${t}%`);
function agrupar(l, chave) {
  const g = new Map();
  for (const p of l) {
    const k = typeof chave === "function" ? chave(p) : p[chave];
    if (k === undefined || k === null) continue;
    if (!g.has(k)) g.set(k, []);
    g.get(k).push(p);
  }
  return g;
}
function quando(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) + " " +
         d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}
function haQuanto(iso) {
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return "agora há pouco";
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  return h < 48 ? `há ${h} h` : `há ${Math.round(h / 24)} dias`;
}

// ------------------------------------------------------------------ componentes

function filtrosHtml() {
  const periodo = [["hoje", "Hoje"], ["7d", "7 dias"], ["30d", "30 dias"], ["tudo", "Tudo"]];
  const fila = [["todas", "Todas"], ["Competitivo", "Competitivo"], ["Partida Rápida", "Partida Rápida"]];
  const chips = (grupo, opcoes) => `<div class="chips" data-filtro="${grupo}">${opcoes.map(([v, n]) =>
    `<button data-valor="${v}" class="${app.filtros[grupo] === v ? "ativo" : ""}">${n}</button>`).join("")}</div>`;
  return `<div class="filtros">${chips("periodo", periodo)}${chips("fila", fila)}</div>`;
}

function linhaPartida(p, completa = false) {
  const h = heroiDe(p), m = mapaDe(p);
  const classe = { "Vitória": "vitoria", "Derrota": "derrota", "Empate": "empate" }[p.resultado];
  const modo = m ? app.ref.modo[m.modo] : null;
  const eam = [p.eliminacoes, p.assistencias, p.mortes].map((v) => v ?? "?").join("/");
  const extras = completa
    ? `<div class="stat"><b>${p.eliminacoes ?? "—"}</b><small>Elim.</small></div>
       <div class="stat"><b>${p.assistencias ?? "—"}</b><small>Assist.</small></div>
       <div class="stat"><b>${p.mortes ?? "—"}</b><small>Mortes</small></div>`
    : `<div class="stat"><b>${p.eliminacoes === null && p.mortes === null ? "—" : eam}</b><small>E / A / M</small></div>`;
  return `<div class="partida ${classe}" data-editar="${p.id}" title="Clique para corrigir">
    ${m ? `<img class="mapa-fundo" src="${m.imagem}" alt="">` : ""}
    <div class="faixa"></div>
    ${h ? `<img class="retrato" src="${h.retrato}" alt="">` : `<div class="retrato"></div>`}
    <div class="quem"><b>${esc(h ? h.nome : p.heroi)}</b>
      <span>${modo ? `<img src="${modo.icone}" alt="">` : ""}${esc(m ? m.nome : p.mapa)} <span class="fila">· ${esc(p.modo)}</span></span></div>
    ${extras}
    <div class="stat"><b>${fmt(p.dano)}</b><small>Dano</small></div>
    <div class="stat"><b>${fmt(p.cura)}</b><small>Cura</small></div>
    <div class="stat"><b>${fmt(p.mitigado)}</b><small>Mitigado</small></div>
    <div class="res">${esc(p.resultado)}<small>${quando(p.data_hora)}</small></div>
  </div>`;
}

function anel(t, tamanho = 64) {
  const raio = tamanho / 2 - 5, volta = 2 * Math.PI * raio, c = tamanho / 2;
  return `<svg class="anel" viewBox="0 0 ${tamanho} ${tamanho}"><circle cx="${c}" cy="${c}" r="${raio}" stroke="#263048"/>
    <circle cx="${c}" cy="${c}" r="${raio}" stroke="${corTaxa(t)}" stroke-linecap="round"
      stroke-dasharray="${(volta * (t || 0)) / 100} ${volta}" transform="rotate(-90 ${c} ${c})"/></svg>`;
}

function itemBarra(icone, cor, nome, lista) {
  const t = taxa(lista);
  return `<div class="item">
    <div class="icone" style="background:color-mix(in srgb, ${cor} 22%, transparent)"><img src="${icone}" alt=""></div>
    <div><div class="nome">${esc(nome)}<span>${lista.length} partida${lista.length === 1 ? "" : "s"}</span></div>
      <div class="barra"><i style="width:${Math.max(t ?? 0, lista.length ? 3 : 0)}%;background:${corTaxa(t)}"></i></div></div>
    <div class="pct" style="color:${corTaxa(t)}">${pct(t)}</div>
  </div>`;
}

function cartaoHeroiTop(h, lista) {
  const t = taxa(lista), e = media(lista, "eliminacoes"), m = media(lista, "mortes");
  return `<a class="heroi" href="#/herois/${h.id}">
    <img class="retrato" src="${h.retrato}" alt="">
    <div><b>${esc(h.nome)}<img src="${app.ref.funcao[h.funcao].icone}" alt=""></b>
      <div class="linha">${lista.length} partida${lista.length > 1 ? "s" : ""} · <span style="color:${corTaxa(t)};font-weight:600">${pct(t)}</span></div></div>
    <div class="barra"><i style="width:${Math.max(t ?? 0, 4)}%;background:${corTaxa(t)}"></i></div>
    <div class="numeros"><span>E/M <b>${e === null ? "—" : e.toFixed(1)}/${m === null ? "—" : m.toFixed(1)}</b></span><span>Dano <b>${fmt(media(lista, "dano"))}</b></span></div>
  </a>`;
}

function tendencia(lista) {
  const seq = [...lista].reverse().slice(-20);
  if (seq.length < 2) return `<div class="vazio">Jogue mais partidas para ver a tendência.</div>`;
  const pontos = seq.map((_, i) => taxa(seq.slice(0, i + 1)) ?? 0);
  const L = 300, H = 90, x = (i) => 6 + (i * (L - 12)) / (pontos.length - 1), y = (t) => H - 8 - (t * (H - 16)) / 100;
  const caminho = pontos.map((t, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(t).toFixed(1)}`).join(" ");
  const cor = (p) => (p.resultado === "Vitória" ? "var(--vitoria)" : p.resultado === "Derrota" ? "var(--derrota)" : "var(--empate)");
  return `<svg viewBox="0 0 ${L} ${H}" preserveAspectRatio="none">
      <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f99e1a" stop-opacity=".35"/><stop offset="1" stop-color="#f99e1a" stop-opacity="0"/></linearGradient></defs>
      <line x1="0" x2="${L}" y1="${y(50)}" y2="${y(50)}" stroke="#2a3550" stroke-dasharray="4 4"/>
      <path d="${caminho} L${x(pontos.length - 1)},${H} L${x(0)},${H} Z" fill="url(#g)"/>
      <path d="${caminho}" fill="none" stroke="#f99e1a" stroke-width="2.5" vector-effect="non-scaling-stroke"/>
      ${pontos.map((t, i) => `<circle cx="${x(i)}" cy="${y(t)}" r="3" fill="${cor(seq[i])}"/>`).join("")}
    </svg>
    <div class="sequencia">${seq.map((p) => `<i style="background:${cor(p)}" title="${quando(p.data_hora)} · ${esc(p.heroi)} · ${esc(p.resultado)}"></i>`).join("")}</div>`;
}

// ------------------------------------------------------------------ dashboard

function blocoAoVivo() {
  const e = app.estado;
  let html = "";
  if (e && e.pendente) {
    const p = e.pendente, h = app.ref.heroiNome[normalizar(p.heroi)];
    html += `<section class="pendente">
      ${h ? `<img src="${h.retrato}" alt="">` : ""}
      <div class="texto"><b>A partida terminou, mas não li o resultado</b>
        <span>${esc(p.heroi)} · ${esc(p.mapa)} · ${esc(p.modo)}. Como foi?</span></div>
      <div class="acoes">
        <button class="botao vitoria" data-pendente="Vitória">Vitória</button>
        <button class="botao derrota" data-pendente="Derrota">Derrota</button>
        <button class="botao" data-pendente="Empate">Empate</button>
        <button class="botao" data-pendente="">Descartar</button>
      </div></section>`;
  }
  const p = e && e.parcial;
  if (!p) {
    const ultima = app.partidas[0];
    return html + `<section class="ocioso">
      <span class="ponto" style="background:var(--texto-3)"></span>
      <div><b>Nenhuma partida em andamento.</b> Assim que você entrar numa partida, ela aparece aqui e é registrada sozinha.
      ${ultima ? `<br><small>Última registrada ${haQuanto(ultima.data_hora)}: ${esc(ultima.heroi)} · ${esc(ultima.mapa)} · ${esc(ultima.resultado)}</small>` : ""}</div>
    </section>`;
  }
  const h = app.ref.heroiNome[normalizar(p.heroi)], m = app.ref.mapaNome[normalizar(p.mapa)];
  const modo = m ? app.ref.modo[m.modo] : null, f = h ? app.ref.funcao[h.funcao] : null, s = h ? app.ref.sub[h.subfuncao] : null;
  const v = (c) => (p.placar && p.placar[c] !== undefined ? fmt(p.placar[c]) : "—");
  const temPlacar = p.placar && Object.keys(p.placar).length;
  return html + `<section class="ao-vivo">
    ${m ? `<img class="fundo" src="${m.imagem}" alt="">` : ""}
    ${h ? `<img class="retrato-grande" src="${h.retrato}" alt="">` : `<div class="retrato-grande"></div>`}
    <div>
      <div class="selo-vivo"><span class="ponto"></span>EM ANDAMENTO</div>
      <h2>${esc(h ? h.nome : p.heroi)}</h2>
      <div class="detalhes">
        <span>${modo ? `<img src="${modo.icone}" alt="">` : ""}${esc(m ? `${m.nome} · ${modo.nome}` : p.mapa)}</span>
        ${f ? `<span><img src="${f.icone}" alt="">${esc(f.nome)} · ${esc(s.nome)}</span>` : ""}
        <span>${esc(p.modo)}</span>
      </div>
    </div>
    <div class="placar-vivo">
      <div><div class="numero">${v("eliminacoes")}</div><small>Elim.</small></div>
      <div><div class="numero">${v("assistencias")}</div><small>Assist.</small></div>
      <div><div class="numero">${v("mortes")}</div><small>Mortes</small></div>
      <div><div class="numero">${v("dano")}</div><small>Dano</small></div>
      <div><div class="numero">${v("cura")}</div><small>Cura</small></div>
      <div><div class="numero">${v("mitigado")}</div><small>Mitigado</small></div>
    </div>
    <div class="rodape"><span>${temPlacar ? "Placar do último Tab" : "Aperte Tab durante a partida para ver o placar aqui"} · aperte Tab quando aparecer o resultado para gravar os números finais</span>
      <button data-descartar>Não é uma partida? Descartar</button></div>
  </section>`;
}

function paginaDashboard() {
  const l = filtradas();
  const t = taxa(l), v = vitorias(l), d = derrotas(l), em = l.length - v - d;
  const e = media(l, "eliminacoes"), m = media(l, "mortes");
  const melhor = (campo) => l.reduce((a, p) => (p[campo] !== null && (!a || p[campo] > a[campo]) ? p : a), null);
  const melhorDano = melhor("dano"), melhorCura = melhor("cura");
  const porFila = agrupar(l, "modo");

  const porHeroi = [...agrupar(l, (p) => heroiDe(p)?.id).entries()]
    .sort((a, b) => b[1].length - a[1].length || (taxa(b[1]) ?? 0) - (taxa(a[1]) ?? 0)).slice(0, 6);
  const porFuncao = agrupar(l, (p) => heroiDe(p)?.funcao);
  const porSub = [...agrupar(l, (p) => heroiDe(p)?.subfuncao).entries()].sort((a, b) => b[1].length - a[1].length);
  const porModo = agrupar(l, (p) => mapaDe(p)?.modo);

  return `
  <div class="topo"><div><h1>Dashboard</h1>
    <div class="sub">${app.partidas.length ? `Última partida registrada ${haQuanto(app.partidas[0].data_hora)}` : "Nenhuma partida registrada ainda"} · registro automático ligado</div></div>
    ${filtrosHtml()}</div>
  <div id="ao-vivo">${blocoAoVivo()}</div>
  <section class="kpis">
    <div class="painel kpi winrate">${anel(t)}
      <div><small>Winrate</small><div class="numero">${t ?? "—"}<em>${t === null ? "" : "%"}</em></div>
      <div class="detalhe vde"><b>${v}V</b> · <i>${d}D</i> · ${em}E</div></div></div>
    <div class="painel kpi"><small>Partidas</small><div class="numero">${l.length}</div>
      <div class="detalhe">${[...porFila.entries()].map(([f, x]) => `${x.length} ${esc(f)}`).join(" · ") || "—"}</div></div>
    <div class="painel kpi"><small>Elim. / Mortes</small><div class="numero">${e === null ? "—" : e.toFixed(1)}<em> / ${m === null ? "—" : m.toFixed(1)}</em></div>
      <div class="detalhe">${e !== null && m ? `razão ${(e / m).toFixed(2)} por partida` : "média por partida"}</div></div>
    <div class="painel kpi"><small>Dano médio</small><div class="numero">${fmt(media(l, "dano"))}</div>
      <div class="detalhe">${melhorDano ? `melhor: ${fmt(melhorDano.dano)} de ${esc(melhorDano.heroi)}` : "—"}</div></div>
    <div class="painel kpi"><small>Cura média</small><div class="numero">${fmt(media(l, "cura"))}</div>
      <div class="detalhe">${melhorCura ? `melhor: ${fmt(melhorCura.cura)} de ${esc(melhorCura.heroi)}` : "—"}</div></div>
  </section>
  <div class="grade">
    <div class="coluna">
      <section class="painel"><header><h2>Partidas recentes</h2><a href="#/historico">Ver histórico →</a></header>
        <div class="partidas">${l.slice(0, 8).map((p) => linhaPartida(p)).join("") || `<div class="vazio">Nenhuma partida neste filtro.</div>`}</div></section>
      <section class="painel"><header><h2>Heróis mais jogados</h2><a href="#/herois">Todos os heróis →</a></header>
        ${porHeroi.length ? `<div class="herois-top">${porHeroi.map(([id, x]) => cartaoHeroiTop(app.ref.heroi[id], x)).join("")}</div>` : `<div class="vazio">Sem partidas.</div>`}</section>
    </div>
    <div class="coluna">
      <section class="painel"><header><h2>Por função</h2></header><div class="lista">
        ${app.catalogo.funcoes.map((f) => itemBarra(f.icone, CORES_FUNCAO[f.id], f.nome, porFuncao.get(f.id) || [])).join("")}</div></section>
      <section class="painel"><header><h2>Modos de mapa</h2><a href="#/mapas">Mapas →</a></header><div class="modos">
        ${app.catalogo.modos.map((mo) => { const x = porModo.get(mo.id) || [], tm = taxa(x);
          return `<div class="modo" title="${esc(mo.descricao)}"><img src="${mo.icone}" alt=""><b style="color:${corTaxa(tm)}">${pct(tm)}</b><small>${esc(mo.nome)}</small><small>${x.length} jogos</small></div>`; }).join("")}</div></section>
      <section class="painel"><header><h2>Subfunções</h2></header><div class="lista">
        ${porSub.map(([id, x]) => { const s = app.ref.sub[id]; return itemBarra(s.icone, CORES_FUNCAO[s.funcao], s.nome, x); }).join("") || `<div class="vazio">Sem partidas.</div>`}</div></section>
      <section class="painel"><header><h2>Tendência</h2><small>winrate acumulado · últimas 20</small></header>
        <div class="tendencia">${tendencia(l)}</div></section>
    </div>
  </div>`;
}

// ------------------------------------------------------------------ histórico

let buscaHistorico = "";
function paginaHistorico() {
  const termo = normalizar(buscaHistorico);
  const l = filtradas().filter((p) => !termo || normalizar(`${p.heroi} ${p.mapa} ${p.modo} ${p.resultado} ${p.modo_mapa}`).includes(termo));
  return `
  <div class="topo"><div><h1>Histórico</h1><div class="sub">Clique numa partida para corrigir ou apagar</div></div>${filtrosHtml()}</div>
  <section class="painel historico">
    <header><h2>${l.length} partida${l.length === 1 ? "" : "s"}</h2><span></span></header>
    <div class="ferramentas">
      <input class="busca" id="busca" placeholder="Buscar herói, mapa, modo…" value="${esc(buscaHistorico)}">
      <button class="botao principal" data-nova>+ Registrar partida</button>
    </div>
    <div class="partidas">${l.map((p) => linhaPartida(p, true)).join("") || `<div class="vazio">Nenhuma partida encontrada.</div>`}</div>
  </section>`;
}

// ------------------------------------------------------------------ heróis

let funcaoHerois = "todas";
function paginaHerois() {
  const porHeroi = agrupar(filtradas(), (p) => heroiDe(p)?.id);
  const lista = app.catalogo.herois
    .filter((h) => funcaoHerois === "todas" || h.funcao === funcaoHerois)
    .sort((a, b) => (porHeroi.get(b.id)?.length || 0) - (porHeroi.get(a.id)?.length || 0) || a.nome.localeCompare(b.nome));
  const abas = [["todas", "Todos"], ...app.catalogo.funcoes.map((f) => [f.id, f.nome])];
  return `
  <div class="topo"><div><h1>Heróis</h1><div class="sub">${app.catalogo.herois.length} heróis · ordenados pelos que você mais joga</div></div>${filtrosHtml()}</div>
  <section class="painel">
    <header><div class="chips" data-funcao-herois>${abas.map(([id, n]) => `<button data-valor="${id}" class="${funcaoHerois === id ? "ativo" : ""}">${n}</button>`).join("")}</div><span></span></header>
    <div class="galeria">${lista.map((h) => {
      const x = porHeroi.get(h.id) || [], t = taxa(x);
      return `<a class="cartao-heroi ${x.length ? "" : "nunca"}" href="#/herois/${h.id}">
        ${h.novo ? `<span class="novo">NOVO</span>` : ""}
        <img class="retrato" src="${h.retrato}" alt="">
        <div class="info"><b>${esc(h.nome)}<img src="${app.ref.sub[h.subfuncao].icone}" alt="" title="${esc(app.ref.sub[h.subfuncao].nome)}"></b>
          <small>${x.length ? `${x.length} partida${x.length > 1 ? "s" : ""} · <span style="color:${corTaxa(t)}">${pct(t)}</span>` : "Nunca jogado"}</small></div></a>`;
    }).join("")}</div>
  </section>`;
}

function paginaHeroi(id) {
  const h = app.ref.heroi[id];
  if (!h) return `<div class="vazio">Herói não encontrado.</div>`;
  const f = app.ref.funcao[h.funcao], s = app.ref.sub[h.subfuncao];
  const l = filtradas().filter((p) => heroiDe(p)?.id === id), t = taxa(l);
  const melhorMapa = [...agrupar(l, (p) => mapaDe(p)?.id).entries()].sort((a, b) => b[1].length - a[1].length)[0];
  const grupos = ["arma", "habilidade", "suprema", "passiva", null];
  const habs = grupos.flatMap((g) => h.habilidades.filter((a) => (a.tipo || null) === g));
  const vantagens = h.habilidades.filter((a) => a.tipo && a.tipo.startsWith("vantagem"));
  const habilidadeHtml = (a) => `<div class="habilidade">
      ${a.icone ? `<img src="${a.icone}" alt="">` : "<span></span>"}
      <div>${a.tipo ? `<span class="tipo ${a.tipo}">${TIPOS_HABILIDADE[a.tipo]}</span>` : ""}
        <b>${esc(a.nome)}${a.nome_en && a.nome_en !== a.nome ? `<small>${esc(a.nome_en)}</small>` : ""}</b>
        <p>${esc(a.descricao || "")}</p></div>
      <div class="meta">${a.tecla ? `<kbd>${esc(traduzirTecla(a.tecla))}</kbd><br>` : ""}${a.recarga ? `recarga ${esc(traduzirTempo(a.recarga))}` : ""}</div>
    </div>`;
  return `
  <div class="topo"><a class="botao" href="#/herois">← Heróis</a>${filtrosHtml()}</div>
  <section class="cabeca-heroi">
    <img class="retrato" src="${h.retrato}" alt="">
    <div><h1>${esc(h.nome)}</h1>
      <div class="chips-info">
        <span class="chip"><img src="${f.icone}" alt="">${esc(f.nome)}</span>
        <span class="chip" title="${esc(s.descricao)}"><img src="${s.icone}" alt="">${esc(s.nome)}: ${esc(s.descricao)}</span>
        ${h.local ? `<span class="chip">${esc(h.local)}</span>` : ""}
        ${h.nome_real ? `<span class="chip">${esc(h.nome_real)}</span>` : ""}
      </div>
      <p>${esc(h.descricao)}</p></div>
    <div class="vitais">
      <div><div class="numero">${h.vida}</div><small>Vida</small></div>
      ${h.armadura ? `<div><div class="numero">${h.armadura}</div><small>Armadura</small></div>` : ""}
      ${h.escudo ? `<div><div class="numero">${h.escudo}</div><small>Escudo</small></div>` : ""}
    </div>
  </section>
  <section class="kpis">
    <div class="painel kpi winrate">${anel(t)}<div><small>Winrate</small><div class="numero">${t ?? "—"}<em>${t === null ? "" : "%"}</em></div>
      <div class="detalhe vde"><b>${vitorias(l)}V</b> · <i>${derrotas(l)}D</i></div></div></div>
    <div class="painel kpi"><small>Partidas</small><div class="numero">${l.length}</div>
      <div class="detalhe">${melhorMapa ? `mais jogado em ${esc(app.ref.mapa[melhorMapa[0]]?.nome || "?")}` : "—"}</div></div>
    <div class="painel kpi"><small>E / A / M</small><div class="numero" style="font-size:28px">${["eliminacoes", "assistencias", "mortes"].map((c) => (media(l, c) === null ? "—" : media(l, c).toFixed(1))).join(" / ")}</div><div class="detalhe">média por partida</div></div>
    <div class="painel kpi"><small>Dano médio</small><div class="numero">${fmt(media(l, "dano"))}</div><div class="detalhe">mitigado ${fmt(media(l, "mitigado"))}</div></div>
    <div class="painel kpi"><small>Cura média</small><div class="numero">${fmt(media(l, "cura"))}</div><div class="detalhe">por partida</div></div>
  </section>
  <div class="grade">
    <div class="coluna">
      <section class="painel"><header><h2>Habilidades</h2></header><div class="habilidades">${habs.map(habilidadeHtml).join("")}</div></section>
      ${vantagens.length ? `<section class="painel"><header><h2>Vantagens</h2><small>escolhidas durante a partida</small></header><div class="habilidades">${vantagens.map(habilidadeHtml).join("")}</div></section>` : ""}
    </div>
    <div class="coluna">
      <section class="painel"><header><h2>Suas partidas</h2></header>
        <div class="partidas">${l.slice(0, 10).map((p) => linhaPartidaCurta(p)).join("") || `<div class="vazio">Você ainda não jogou de ${esc(h.nome)} neste filtro.</div>`}</div></section>
    </div>
  </div>`;
}

function linhaPartidaCurta(p) {
  const m = mapaDe(p), modo = m ? app.ref.modo[m.modo] : null;
  const classe = { "Vitória": "vitoria", "Derrota": "derrota", "Empate": "empate" }[p.resultado];
  return `<div class="partida ${classe}" data-editar="${p.id}" style="grid-template-columns:4px minmax(0,1fr) 70px 78px">
    ${m ? `<img class="mapa-fundo" src="${m.imagem}" alt="">` : ""}
    <div class="faixa"></div>
    <div class="quem"><b>${esc(m ? m.nome : p.mapa)}</b><span>${modo ? `<img src="${modo.icone}" alt="">${esc(modo.nome)}` : ""} · ${esc(p.modo)}</span></div>
    <div class="stat"><b>${[p.eliminacoes, p.assistencias, p.mortes].map((v) => v ?? "?").join("/")}</b><small>E / A / M</small></div>
    <div class="res">${esc(p.resultado)}<small>${quando(p.data_hora)}</small></div></div>`;
}

// ------------------------------------------------------------------ mapas

function paginaMapas() {
  const porMapa = agrupar(filtradas(), (p) => mapaDe(p)?.id);
  return `
  <div class="topo"><div><h1>Mapas</h1><div class="sub">${app.catalogo.mapas.length} mapas da Partida Rápida e da Competitiva</div></div>${filtrosHtml()}</div>
  ${app.catalogo.modos.map((mo) => {
    const mapas = app.catalogo.mapas.filter((m) => m.modo === mo.id);
    const todas = mapas.flatMap((m) => porMapa.get(m.id) || []), tm = taxa(todas);
    return `<section class="painel">
      <div class="secao-modo"><img src="${mo.icone}" alt=""><h2>${esc(mo.nome)}</h2>
        <small style="color:var(--texto-3)">${todas.length} partidas</small><span class="pct" style="color:${corTaxa(tm)}">${pct(tm)}</span></div>
      <div class="mapas">${mapas.map((m) => {
        const x = porMapa.get(m.id) || [], t = taxa(x);
        return `<div class="mapa ${x.length ? "" : "nunca"}" title="${esc(m.nome_en)}">
          <img src="${m.imagem}" alt="">
          <b>${esc(m.nome)}</b>
          <small><span>${esc(m.pais)}</span><span>${x.length ? `${x.length} jogo${x.length > 1 ? "s" : ""} · <b style="color:${corTaxa(t)};font:inherit">${pct(t)}</b>` : "nunca jogado"}</span></small></div>`;
      }).join("")}</div></section>`;
  }).join("")}`;
}

// ------------------------------------------------------------------ ajustes

function paginaAjustes() {
  const a = app.estado?.ajustes || {};
  return `
  <div class="topo"><div><h1>Ajustes</h1></div></div>
  <section class="painel"><header><h2>Detecção</h2></header><div class="ajustes">
    <div class="ajuste"><div class="texto"><b>Seu nome no jogo</b>
      <span>BattleTag sem o #. Usado para achar o seu herói nas legendas, ex.: [FILIPE (ROADHOG)]. Vazio = o app aprende sozinho.</span></div>
      <input type="text" id="nome-jogador" value="${esc(a.nome_jogador || "")}"><button class="botao" data-salvar-nome>Salvar</button></div>
    <div class="ajuste"><div class="texto"><b>Modo diagnóstico</b>
      <span>Guarda o texto lido da tela e alguns prints, para calibrar a detecção.</span></div>
      <label class="interruptor"><input type="checkbox" data-ajuste="diagnostico" ${a.diagnostico ? "checked" : ""}><span></span></label></div>
    <div class="ajuste"><div class="texto"><b>Pasta de diagnóstico</b><span>Prints e registros usados na calibração.</span></div>
      <button class="botao" data-pasta>Abrir pasta</button></div>
  </div></section>
  <section class="painel"><header><h2>Sistema</h2></header><div class="ajustes">
    <div class="ajuste"><div class="texto"><b>Iniciar com o Windows</b>
      <span>Começa a registrar sozinho, sem abrir esta janela.</span></div>
      <label class="interruptor"><input type="checkbox" data-ajuste="iniciar_com_windows" ${a.iniciar_com_windows ? "checked" : ""}><span></span></label></div>
    <div class="ajuste"><div class="texto"><b>Encerrar o OW Tracker</b>
      <span>Fechar esta janela não para o registro. Isto para tudo até você abrir o app de novo.</span></div>
      <button class="botao perigo" data-sair>Sair</button></div>
  </div></section>
  <section class="painel"><header><h2>Atalhos</h2></header><div class="atalhos">
    <div><kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>O</kbd> abre esta janela (funciona dentro do jogo)</div>
    <div><kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd> salva um print da tela em <code>capturas/</code></div>
    <div><kbd>Tab</kbd> no jogo: o app lê o placar na hora. Aperte também quando aparecer o resultado.</div>
  </div></section>`;
}

// ------------------------------------------------------------------ modal de partida

function abrirEdicao(id) {
  const p = id ? app.partidas.find((x) => x.id === id) : null;
  const h = p ? heroiDe(p) : null, m = p ? mapaDe(p) : null;
  const herois = [...app.catalogo.herois].sort((a, b) => a.nome.localeCompare(b.nome));
  const opcoesHeroi = (h || !p ? "" : `<option selected>${esc(p.heroi)}</option>`) +
    herois.map((x) => `<option value="${esc(x.nome)}" ${h && h.id === x.id ? "selected" : ""}>${esc(x.nome)}</option>`).join("");
  const opcoesMapa = (m || !p ? "" : `<option selected>${esc(p.mapa)}</option>`) +
    app.catalogo.modos.map((mo) => `<optgroup label="${esc(mo.nome)}">${app.catalogo.mapas.filter((x) => x.modo === mo.id)
      .map((x) => `<option value="${esc(x.nome)}" ${m && m.id === x.id ? "selected" : ""}>${esc(x.nome)}</option>`).join("")}</optgroup>`).join("");
  const filas = app.catalogo.modos_fila.includes(p?.modo) || !p ? app.catalogo.modos_fila : [p.modo, ...app.catalogo.modos_fila];
  const resultado = p?.resultado || "";
  const nomes = { eliminacoes: "Elim.", assistencias: "Assist.", mortes: "Mortes", dano: "Dano", cura: "Cura", mitigado: "Mitigado" };
  const modal = document.getElementById("modal");
  modal.innerHTML = `<div class="caixa" role="dialog" aria-modal="true">
    <header><h2>${p ? "Corrigir partida" : "Registrar partida"}</h2><button data-fechar aria-label="Fechar">×</button></header>
    <form class="corpo" id="form-partida">
      <div class="campo"><label>Herói</label><select name="heroi" required><option value="" ${p ? "" : "selected"} disabled>Escolha…</option>${opcoesHeroi}</select></div>
      <div class="campo"><label>Mapa</label><select name="mapa" required><option value="" ${p ? "" : "selected"} disabled>Escolha…</option>${opcoesMapa}</select></div>
      <div class="campo"><label>Fila</label><select name="modo">${filas.map((f) => `<option ${f === (p?.modo || "Partida Rápida") ? "selected" : ""}>${esc(f)}</option>`).join("")}</select></div>
      <div class="campo"><label>Resultado</label><div class="segmentado" id="resultado">${app.catalogo.resultados.map((r) =>
        `<button type="button" data-valor="${r}" class="${r === resultado ? "ativo" : ""}">${r}</button>`).join("")}</div></div>
      <div class="campo largo"><label>Placar (Tab)</label></div>
      <div class="placar-campos">${COLUNAS.map((c) => `<div class="campo"><label>${nomes[c]}</label>
        <input type="number" min="0" name="${c}" value="${p && p[c] !== null ? p[c] : ""}"></div>`).join("")}</div>
      ${p ? `<div class="campo largo"><label>Registrada</label><span style="color:var(--texto-2)">${quando(p.data_hora)} · ${p.origem === "auto" ? "automaticamente" : "manualmente"}${p.observacao ? ` · ${esc(p.observacao)}` : ""}</span></div>` : ""}
      <div class="erro-form" id="erro-form"></div>
    </form>
    <footer>
      ${p ? `<button class="botao perigo" data-apagar="${p.id}">Apagar</button>` : ""}
      <button class="botao" data-fechar>Cancelar</button>
      <button class="botao principal" data-salvar="${p ? p.id : ""}">Salvar</button>
    </footer></div>`;
  modal.hidden = false;
}
const fecharModal = () => { document.getElementById("modal").hidden = true; };

async function salvarEdicao(id) {
  const form = document.getElementById("form-partida");
  const dados = Object.fromEntries(new FormData(form).entries());
  dados.resultado = form.querySelector("#resultado .ativo")?.dataset.valor || "";
  try {
    if (id) await api.enviar("PUT", `/api/partidas/${id}`, dados);
    else await api.enviar("POST", "/api/partidas", dados);
    fecharModal();
    await recarregarPartidas();
    mostrarToast(id ? "Partida corrigida." : "Partida registrada.");
  } catch (erro) {
    document.getElementById("erro-form").textContent = erro.message;
  }
}

// ------------------------------------------------------------------ navegação e eventos

const paginas = { dashboard: paginaDashboard, historico: paginaHistorico, herois: paginaHerois, mapas: paginaMapas, ajustes: paginaAjustes };
function rota() {
  const [, pagina = "dashboard", id] = location.hash.split("/");
  return { pagina: paginas[pagina] || pagina === "herois" ? pagina : "dashboard", id };
}
function desenhar() {
  if (!app.catalogo) return;
  const { pagina, id } = rota();
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("ativo", a.dataset.pagina === pagina));
  const foco = document.activeElement?.id;
  document.getElementById("pagina").innerHTML = pagina === "herois" && id ? paginaHeroi(id) : (paginas[pagina] || paginaDashboard)();
  if (foco === "busca") { const b = document.getElementById("busca"); b.focus(); b.setSelectionRange(b.value.length, b.value.length); }
}

document.addEventListener("click", async (e) => {
  const alvo = e.target.closest("button, [data-editar], [data-fechar]");
  if (!alvo) return;
  const d = alvo.dataset;
  const chips = alvo.closest("[data-filtro]");
  if (chips && d.valor !== undefined) { app.filtros[chips.dataset.filtro] = d.valor; salvarFiltros(); return desenhar(); }
  if (alvo.closest("[data-funcao-herois]") && d.valor) { funcaoHerois = d.valor; return desenhar(); }
  if (alvo.closest("#resultado") && d.valor) {
    alvo.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("ativo", b === alvo));
    return;
  }
  if (d.editar !== undefined && alvo.classList.contains("partida")) return abrirEdicao(Number(d.editar));
  if (d.nova !== undefined) return abrirEdicao(null);
  if (d.fechar !== undefined) return fecharModal();
  if (d.salvar !== undefined) return salvarEdicao(d.salvar ? Number(d.salvar) : null);
  if (d.apagar) {
    if (!confirm("Apagar esta partida? Não dá para desfazer.")) return;
    await api.enviar("DELETE", `/api/partidas/${d.apagar}`);
    fecharModal(); await recarregarPartidas(); return mostrarToast("Partida apagada.");
  }
  if (d.pendente !== undefined) {
    await api.enviar("POST", "/api/pendente", { resultado: d.pendente || null });
    await atualizarEstado(); return recarregarPartidas();
  }
  if (d.descartar !== undefined) {
    if (!confirm("Descartar a partida em andamento? Ela não será registrada.")) return;
    await api.enviar("POST", "/api/andamento/descartar");
    return atualizarEstado();
  }
  if (d.salvarNome !== undefined) {
    await api.enviar("POST", "/api/ajustes", { nome_jogador: document.getElementById("nome-jogador").value });
    await atualizarEstado(); return mostrarToast("Nome salvo.");
  }
  if (d.pasta !== undefined) return api.enviar("POST", "/api/pasta-diagnostico");
  if (d.sair !== undefined) {
    if (!confirm("Encerrar o OW Tracker? As partidas deixam de ser registradas até você abrir o app de novo.")) return;
    await api.enviar("POST", "/api/sair");
    document.body.innerHTML = `<main><div class="vazio" style="margin:auto">OW Tracker encerrado. Pode fechar esta janela.</div></main>`;
  }
});

document.addEventListener("change", async (e) => {
  const campo = e.target.dataset.ajuste;
  if (!campo) return;
  try {
    await api.enviar("POST", "/api/ajustes", { [campo]: e.target.checked });
    await atualizarEstado();
  } catch (erro) { mostrarToast(erro.message); }
});

document.addEventListener("input", (e) => {
  if (e.target.id === "busca") { buscaHistorico = e.target.value; desenhar(); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") fecharModal(); });
document.getElementById("modal").addEventListener("click", (e) => { if (e.target.id === "modal") fecharModal(); });
window.addEventListener("hashchange", () => { desenhar(); window.scrollTo(0, 0); });

// ------------------------------------------------------------------ atualização periódica

function mostrarToast(texto) {
  const t = document.getElementById("toast");
  t.textContent = texto; t.hidden = false;
  clearTimeout(mostrarToast.tempo);
  mostrarToast.tempo = setTimeout(() => { t.hidden = true; }, 5000);
}

function desenharLateral() {
  const e = app.estado;
  const caixa = document.getElementById("monitor");
  const texto = e ? e.monitor.replace(/^Automático:\s*/, "") : "Sem conexão com o serviço";
  const lendo = /lendo o jogo/i.test(texto);
  caixa.className = "monitor " + (!e ? "erro" : lendo ? "lendo" : /erro|indispon/i.test(texto) ? "erro" : "aguardando");
  document.getElementById("monitor-titulo").textContent = !e ? "Desconectado" : lendo ? "Lendo o jogo" : "Aguardando o jogo";
  document.getElementById("monitor-detalhe").textContent = lendo ? texto.replace(/^lendo o jogo em /i, "").split(" · partida")[0] : texto;
  const nome = e?.ajustes?.nome_jogador;
  const ultimo = app.partidas[0] && heroiDe(app.partidas[0]);
  document.getElementById("jogador").innerHTML = nome
    ? `${ultimo ? `<img src="${ultimo.retrato}" alt="">` : ""}<div><b>${esc(nome)}</b><small>Seu nome no jogo</small></div>` : "";
}

async function atualizarEstado() {
  try {
    const anterior = JSON.stringify([app.estado?.parcial, app.estado?.pendente]);
    app.estado = await api.ler("/api/estado");
    if (app.estado.versao !== app.versao) await recarregarPartidas();
    else if (JSON.stringify([app.estado.parcial, app.estado.pendente]) !== anterior && rota().pagina === "dashboard") {
      const bloco = document.getElementById("ao-vivo");
      if (bloco) bloco.innerHTML = blocoAoVivo();
    }
    const aviso = app.estado.aviso;
    if (aviso && aviso.quando !== app.ultimoAviso) {
      if (app.ultimoAviso !== null) mostrarToast(aviso.texto);
      app.ultimoAviso = aviso.quando;
    } else if (!aviso && app.ultimoAviso === null) app.ultimoAviso = "";
  } catch {
    app.estado = null;
  }
  desenharLateral();
}

async function recarregarPartidas() {
  app.partidas = await api.ler("/api/partidas");
  app.versao = app.estado ? app.estado.versao : app.versao;
  if (document.getElementById("modal").hidden) desenhar();
}

async function iniciar() {
  app.catalogo = await api.ler("/api/catalogo");
  indexar();
  await atualizarEstado();
  if (app.versao === -1) await recarregarPartidas();
  desenhar();
  setInterval(atualizarEstado, 2000);
}
iniciar();
