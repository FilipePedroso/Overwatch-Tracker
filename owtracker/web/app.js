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
  jogadores: {},  // times de cada partida, carregados sob demanda
  habilidadesPartida: {},  // uso de habilidades por partida (sob demanda)
  habilidadesHeroi: {},    // uso de habilidades por herói (sob demanda)
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
  return `<div class="partida ${classe}" data-abrir="${p.id}" title="Ver a partida">
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
      ${usosAoVivo(p.habilidades)}
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
      ${blocoHabilidadesHeroi(h)}
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
  return `<div class="partida ${classe}" data-abrir="${p.id}" style="grid-template-columns:4px minmax(0,1fr) 70px 78px">
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
        return `<a class="mapa ${x.length ? "" : "nunca"}" href="#/mapas/${m.id}" title="${esc(m.nome_en)}">
          <img src="${m.imagem}" alt="">
          <b>${esc(m.nome)}</b>
          <small><span>${esc(m.pais)}</span><span>${x.length ? `${x.length} jogo${x.length > 1 ? "s" : ""} · <b style="color:${corTaxa(t)};font:inherit">${pct(t)}</b>` : "nunca jogado"}</span></small></a>`;
      }).join("")}</div></section>`;
  }).join("")}`;
}

// ------------------------------------------------------------------ partida (os dois times)

const FONTES = {
  voce: ["Você", "o seu herói, pelas legendas"],
  legendas: ["Legendas", "o jogador falou nas legendas com esse herói"],
  retrato: ["Retrato", "retrato reconhecido de partidas anteriores"],
  vantagens: ["Vantagens", "reconhecido pelos ícones de vantagem (pode errar)"],
  corrigido: ["Corrigido", "corrigido por você"],
};

function carregarJogadores(id) {
  if (app.jogadores[id] !== undefined) return app.jogadores[id];
  app.jogadores[id] = null;  // carregando
  api.ler(`/api/partidas/${id}/jogadores`).then((lista) => {
    app.jogadores[id] = lista;
    if (rota().pagina === "partidas") desenhar();
  });
  return null;
}

// ------------------------------------------------------------------ uso de habilidades

function habilidadeDe(heroi, id) {
  const r = heroi.rastreaveis.find((a) => a.id === id) || {};
  const a = heroi.habilidades.find((x) => x.id === id) || {};
  return { id, nome: r.nome || a.nome || id, icone: a.icone, tecla: r.tecla_nome, recarga: r.recarga, tipo: r.tipo || a.tipo };
}

function usosAoVivo(lista) {
  // Contadores no cartão da partida em andamento (herói atual primeiro).
  if (!lista?.length) return "";
  return `<div class="usos-vivo">${lista.map((u) => {
    const h = app.ref.heroi[u.heroi_id];
    if (!h) return "";
    const a = habilidadeDe(h, u.habilidade_id);
    return `<span title="${esc(`${h.nome}: ${a.nome}`)}">${a.icone ? `<img src="${a.icone}" alt="">` : ""}<b>${u.usos}</b></span>`;
  }).join("")}</div>`;
}

function carregarSobDemanda(cache, chave, url) {
  if (app[cache][chave] !== undefined) return app[cache][chave];
  app[cache][chave] = null;  // carregando
  api.ler(url).then((dados) => { app[cache][chave] = dados; desenhar(); });
  return null;
}

function cartaoHabilidade(a, numero, rotulo, extra = "") {
  return `<div class="uso ${numero === 0 ? "zero" : ""}">
    <div class="uso-icone">${a.icone ? `<img src="${a.icone}" alt="">` : ""}</div>
    <div class="uso-texto"><b>${esc(a.nome)}</b>
      <small>${a.tecla ? `<kbd>${esc(a.tecla)}</kbd>` : ""}${a.recarga ? ` recarga ${String(a.recarga).replace(".", ",")} s` : a.tipo === "suprema" ? " suprema" : ""}</small>${extra}</div>
    <div class="uso-numero"><div class="numero">${numero}</div><small>${rotulo}</small></div>
  </div>`;
}

function blocoHabilidadesPartida(p) {
  if (!p.tem_habilidades) {
    return `<section class="painel"><header><h2>Suas habilidades</h2></header>
      <div class="vazio">O uso de habilidades não foi registrado nesta partida (o recurso é mais novo que ela).</div></section>`;
  }
  const lista = carregarSobDemanda("habilidadesPartida", p.id, `/api/partidas/${p.id}/habilidades`);
  if (!lista) return `<section class="painel"><div class="vazio">Carregando as habilidades…</div></section>`;
  const porHeroi = agrupar(lista, "heroi_id");
  return `<section class="painel"><header><h2>Suas habilidades</h2><small>usos contados pelas teclas, respeitando a recarga</small></header>
    ${[...porHeroi.entries()].map(([heroiId, usos]) => {
      const h = app.ref.heroi[heroiId];
      if (!h) return "";
      const n = Object.fromEntries(usos.map((u) => [u.habilidade_id, u.usos]));
      return `<div class="usos-heroi">${porHeroi.size > 1 ? `<div class="usos-titulo"><img src="${h.retrato}" alt="">${esc(h.nome)}</div>` : ""}
        <div class="usos">${h.rastreaveis.map((r) => cartaoHabilidade(habilidadeDe(h, r.id), n[r.id] || 0, "usos")).join("")}</div></div>`;
    }).join("")}</section>`;
}

function blocoHabilidadesHeroi(h) {
  if (!h.rastreaveis.length) return "";
  const dados = carregarSobDemanda("habilidadesHeroi", h.id, `/api/herois/${h.id}/habilidades`);
  if (!dados) return `<section class="painel"><div class="vazio">Carregando o uso de habilidades…</div></section>`;
  if (!dados.partidas) {
    return `<section class="painel"><header><h2>Uso de habilidades</h2></header>
      <div class="vazio">Ainda não há partidas de ${esc(h.nome)} com o uso de habilidades registrado.</div></section>`;
  }
  const porHabilidade = Object.fromEntries(dados.habilidades.map((x) => [x.habilidade_id, x]));
  const partidas = [...new Set(dados.por_partida.map((x) => x.partida_id))].slice(-12);
  return `<section class="painel"><header><h2>Uso de habilidades</h2><small>${dados.partidas} partida${dados.partidas > 1 ? "s" : ""} registrada${dados.partidas > 1 ? "s" : ""}</small></header>
    <div class="usos">${h.rastreaveis.map((r) => {
      const x = porHabilidade[r.id] || { total: 0, media: 0, maximo: 0 };
      const porPartida = partidas.map((id) => dados.por_partida.find((u) => u.partida_id === id && u.habilidade_id === r.id)?.usos || 0);
      const maior = Math.max(1, ...porPartida);
      const barras = `<div class="mini-barras" title="usos nas últimas partidas">${porPartida.map((v) =>
        `<i style="height:${Math.max(6, (100 * v) / maior)}%"></i>`).join("")}</div>`;
      return cartaoHabilidade(habilidadeDe(h, r.id), String(x.media).replace(".", ","), "por partida",
        `<small class="uso-extra">total ${x.total} · máximo ${x.maximo}</small>${barras}`);
    }).join("")}</div></section>`;
}

function paginaPartida(id) {
  const p = app.partidas.find((x) => x.id === Number(id));
  if (!p) return `<div class="vazio">Partida não encontrada.</div>`;
  const h = heroiDe(p), m = mapaDe(p), modo = m ? app.ref.modo[m.modo] : null;
  const classe = { "Vitória": "vitoria", "Derrota": "derrota", "Empate": "empate" }[p.resultado];
  const jogadores = p.tem_times ? carregarJogadores(p.id) : [];
  const times = jogadores ? { aliados: jogadores.filter((j) => j.time === "aliados"), inimigos: jogadores.filter((j) => j.time === "inimigos") } : null;
  return `
  <div class="topo"><a class="botao" href="#/historico">← Histórico</a>
    <div class="filtros"><button class="botao" data-editar-partida="${p.id}">Corrigir partida</button></div></div>
  <section class="cabeca-mapa cabeca-partida ${classe}">
    ${m ? `<img class="fundo" src="${m.imagem}" alt="">` : ""}
    ${h ? `<img class="retrato-grande" src="${h.retrato}" alt="">` : ""}
    <div>
      <div class="resultado-grande">${esc(p.resultado)}</div>
      <h1>${esc(h ? h.nome : p.heroi)} <span>em</span> ${esc(m ? m.nome : p.mapa)}</h1>
      <div class="chips-info">
        ${modo ? `<span class="chip"><img src="${modo.icone}" alt="">${esc(modo.nome)}</span>` : ""}
        <span class="chip">${esc(p.modo)}</span>
        <span class="chip">${quando(p.data_hora)}</span>
        ${p.observacao ? `<span class="chip">${esc(p.observacao)}</span>` : ""}
      </div>
    </div>
  </section>
  ${blocoHabilidadesPartida(p)}
  ${!p.tem_times
    ? `<section class="painel"><div class="vazio">O placar dos dois times não foi capturado nesta partida.<br>
        Aperte <kbd>Tab</kbd> durante a partida e quando aparecer o resultado: o app registra aliados e inimigos.</div></section>`
    : !times ? `<section class="painel"><div class="vazio">Carregando os times…</div></section>`
    : `<div class="times">${painelTime("Seu time", "aliados", times.aliados, p)}${painelTime("Time inimigo", "inimigos", times.inimigos, p)}</div>
       <div class="nota-times">Herói errado ou desconhecido? Escolha o certo na lista: o app guarda esse retrato e passa a reconhecê-lo sozinho.</div>`}`;
}

function painelTime(titulo, time, lista, p) {
  const soma = (c) => lista.reduce((s, j) => s + (j[c] || 0), 0);
  const herois = [...app.catalogo.herois].sort((a, b) => a.nome.localeCompare(b.nome));
  return `<section class="painel time ${time}">
    <header><h2>${titulo}</h2><small>E ${soma("eliminacoes")} · M ${soma("mortes")} · Dano ${fmt(soma("dano"))} · Cura ${fmt(soma("cura"))}</small></header>
    <div class="jogadores">
      <div class="jogador cabecalho"><span></span><span></span><span>E</span><span>A</span><span>M</span><span>Dano</span><span>Cura</span><span>Mit.</span></div>
      ${lista.map((j) => {
        // Sem herói, mostra a função esperada pela posição (tanque, dano, dano, suporte, suporte).
        const h = app.ref.heroi[j.heroi_id];
        const f = app.ref.funcao[h ? h.funcao : ["tank", "damage", "damage", "support", "support"][j.posicao]];
        const [fonte, explica] = FONTES[j.fonte] || ["?", "herói não identificado"];
        const nomeConfiavel = ["voce", "legendas"].includes(j.fonte);
        return `<div class="jogador ${j.voce ? "voce" : ""}">
          <img class="retrato" src="/api/retratos/${p.id}/${time}/${j.posicao}.png?v=${app.versao}" alt="">
          <div class="quem">
            <div class="linha-heroi">${f ? `<img src="${f.icone}" alt="">` : ""}
              <select data-corrigir="${p.id}/${time}/${j.posicao}" title="Corrigir o herói">
                <option value="" ${h ? "" : "selected"}>Não identificado</option>
                ${herois.map((x) => `<option value="${x.id}" ${h && h.id === x.id ? "selected" : ""}>${esc(x.nome)}</option>`).join("")}
              </select>
              <span class="fonte f-${j.fonte || "nada"}" title="${esc(explica)}">${esc(fonte)}</span></div>
            <div class="linha-nome">
              <small class="${nomeConfiavel ? "" : "nome-incerto"}" title="${nomeConfiavel ? "" : "nome lido do placar (a fonte estilizada pode atrapalhar)"}">${esc(j.nome || "—")}</small>
              ${vantagensHtml(h, j.vantagens)}
            </div>
          </div>
          ${["eliminacoes", "assistencias", "mortes"].map((c) => `<b>${j[c] ?? "—"}</b>`).join("")}
          ${["dano", "cura", "mitigado"].map((c) => `<b>${fmt(j[c])}</b>`).join("")}
        </div>`;
      }).join("")}
    </div></section>`;
}

function vantagensHtml(heroi, escolhidas) {
  // Ícones das vantagens escolhidas (lidas no Tab), menor antes da maior.
  if (!heroi || !escolhidas?.length) return "";
  const porId = Object.fromEntries(heroi.habilidades.map((a) => [a.id, a]));
  const ordem = { vantagem_menor: 0, vantagem_maior: 1 };
  return `<span class="vantagens-jogador">${[...escolhidas].sort((a, b) => ordem[a.tipo] - ordem[b.tipo]).map((v) => {
    const a = porId[v.id] || {};
    const tipo = v.tipo === "vantagem_maior" ? "Vantagem maior" : "Vantagem menor";
    return `<span class="vantagem ${v.tipo}" title="${esc(`${tipo}: ${v.nome}${a.descricao ? ` — ${a.descricao}` : ""}`)}">
      ${a.icone ? `<img src="${a.icone}" alt="">` : esc(v.nome[0])}</span>`;
  }).join("")}</span>`;
}

function paginaMapa(id) {
  const m = app.ref.mapa[id];
  if (!m) return `<div class="vazio">Mapa não encontrado.</div>`;
  const modo = app.ref.modo[m.modo];
  const todas = filtradas();
  const l = todas.filter((p) => mapaDe(p)?.id === id), t = taxa(l);
  const doModo = todas.filter((p) => mapaDe(p)?.modo === m.modo);
  const comparar = (nome, outra) => {
    const to = taxa(outra);
    if (t === null || to === null) return `${nome}: ${pct(to)}`;
    const dif = t - to;
    return `${nome}: ${pct(to)} <b style="color:${dif >= 0 ? "var(--vitoria)" : "var(--derrota)"}">(${dif >= 0 ? "+" : ""}${dif} p.p.)</b>`;
  };
  const porHeroi = [...agrupar(l, (p) => heroiDe(p)?.id).entries()]
    .sort((a, b) => b[1].length - a[1].length || (taxa(b[1]) ?? 0) - (taxa(a[1]) ?? 0));
  const porFuncao = agrupar(l, (p) => heroiDe(p)?.funcao);
  const porFila = agrupar(l, "modo");
  const irmaos = app.catalogo.mapas.filter((x) => x.modo === m.modo && x.id !== id);
  const lancamento = m.lancamento ? new Date(m.lancamento + "T12:00").toLocaleDateString("pt-BR") : null;
  return `
  <div class="topo"><a class="botao" href="#/mapas">← Mapas</a>${filtrosHtml()}</div>
  <section class="cabeca-mapa">
    <img class="fundo" src="${m.imagem}" alt="">
    <div>
      <h1>${esc(m.nome)}</h1>
      <div class="chips-info">
        <span class="chip"><img src="${modo.icone}" alt="">${esc(modo.nome)}</span>
        <span class="chip">${esc(m.pais)}</span>
        ${lancamento ? `<span class="chip">Lançado em ${lancamento}</span>` : ""}
        ${m.nome_en !== m.nome ? `<span class="chip">${esc(m.nome_en)}</span>` : ""}
      </div>
      <p>${esc(modo.descricao)}</p>
    </div>
  </section>
  <section class="kpis">
    <div class="painel kpi winrate">${anel(t)}<div><small>Winrate</small><div class="numero">${t ?? "—"}<em>${t === null ? "" : "%"}</em></div>
      <div class="detalhe vde"><b>${vitorias(l)}V</b> · <i>${derrotas(l)}D</i> · ${l.length - vitorias(l) - derrotas(l)}E</div></div></div>
    <div class="painel kpi"><small>Partidas</small><div class="numero">${l.length}</div>
      <div class="detalhe">${[...porFila.entries()].map(([f, x]) => `${x.length} ${esc(f)}`).join(" · ") || "nunca jogado"}</div></div>
    <div class="painel kpi"><small>Comparação</small><div class="detalhe" style="white-space:normal;line-height:1.7">
      ${comparar("Geral", todas)}<br>${comparar(modo.nome, doModo)}</div></div>
    <div class="painel kpi"><small>E / A / M</small><div class="numero" style="font-size:28px">${["eliminacoes", "assistencias", "mortes"].map((c) => (media(l, c) === null ? "—" : media(l, c).toFixed(1))).join(" / ")}</div><div class="detalhe">média por partida</div></div>
    <div class="painel kpi"><small>Dano / Cura</small><div class="numero" style="font-size:28px">${fmt(media(l, "dano"))}<em> / ${fmt(media(l, "cura"))}</em></div><div class="detalhe">média por partida</div></div>
  </section>
  <div class="grade">
    <div class="coluna">
      <section class="painel"><header><h2>Suas partidas aqui</h2><small>${l.length} no filtro</small></header>
        <div class="partidas">${l.map((p) => linhaPartida(p)).join("") || `<div class="vazio">Você ainda não jogou em ${esc(m.nome)} neste filtro.</div>`}</div></section>
    </div>
    <div class="coluna">
      <section class="painel"><header><h2>Heróis neste mapa</h2></header>
        ${porHeroi.length ? `<div class="herois-top" style="grid-template-columns:1fr">${porHeroi.map(([hid, x]) => cartaoHeroiTop(app.ref.heroi[hid], x)).join("")}</div>` : `<div class="vazio">Sem partidas.</div>`}</section>
      <section class="painel"><header><h2>Por função</h2></header><div class="lista">
        ${app.catalogo.funcoes.map((f) => itemBarra(f.icone, CORES_FUNCAO[f.id], f.nome, porFuncao.get(f.id) || [])).join("")}</div></section>
      <section class="painel"><header><h2>Outros mapas de ${esc(modo.nome)}</h2></header>
        <div class="lista">${irmaos.map((x) => { const lx = todas.filter((p) => mapaDe(p)?.id === x.id), tx = taxa(lx);
          return `<a class="item" href="#/mapas/${x.id}" style="text-decoration:none">
            <img src="${x.imagem}" alt="" style="width:30px;height:30px;border-radius:6px;object-fit:cover">
            <div class="nome" style="margin:0">${esc(x.nome)}<span>${lx.length} jogo${lx.length === 1 ? "" : "s"}</span></div>
            <div class="pct" style="color:${corTaxa(tx)}">${pct(tx)}</div></a>`; }).join("")}</div></section>
    </div>
  </div>`;
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

const paginas = { dashboard: paginaDashboard, historico: paginaHistorico, herois: paginaHerois, mapas: paginaMapas, ajustes: paginaAjustes, partidas: paginaHistorico };
const detalhes = { herois: paginaHeroi, mapas: paginaMapa, partidas: paginaPartida };  // #/<pagina>/<id>
const MENU_DE = { partidas: "historico" };  // item do menu aceso em cada página
function rota() {
  const [, pagina = "dashboard", id] = location.hash.split("/");
  return { pagina: paginas[pagina] ? pagina : "dashboard", id };
}
function desenhar() {
  if (!app.catalogo) return;
  const { pagina, id } = rota();
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("ativo", a.dataset.pagina === (MENU_DE[pagina] || pagina)));
  const foco = document.activeElement?.id;
  document.getElementById("pagina").innerHTML = id && detalhes[pagina] ? detalhes[pagina](decodeURIComponent(id)) : paginas[pagina]();
  if (foco === "busca") { const b = document.getElementById("busca"); b.focus(); b.setSelectionRange(b.value.length, b.value.length); }
}

document.addEventListener("click", async (e) => {
  const alvo = e.target.closest("button, [data-abrir], [data-fechar]");
  if (!alvo) return;
  const d = alvo.dataset;
  const chips = alvo.closest("[data-filtro]");
  if (chips && d.valor !== undefined) { app.filtros[chips.dataset.filtro] = d.valor; salvarFiltros(); return desenhar(); }
  if (alvo.closest("[data-funcao-herois]") && d.valor) { funcaoHerois = d.valor; return desenhar(); }
  if (alvo.closest("#resultado") && d.valor) {
    alvo.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("ativo", b === alvo));
    return;
  }
  if (d.abrir !== undefined && alvo.classList.contains("partida")) { location.hash = `#/partidas/${d.abrir}`; return; }
  if (d.editarPartida) return abrirEdicao(Number(d.editarPartida));
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
  if (d.reiniciar !== undefined) {
    alvo.disabled = true;
    alvo.textContent = "Reiniciando…";
    await api.enviar("POST", "/api/reiniciar");
    return;  // a página se recarrega quando o serviço novo responder
  }
  if (d.sair !== undefined) {
    if (!confirm("Encerrar o OW Tracker? As partidas deixam de ser registradas até você abrir o app de novo.")) return;
    await api.enviar("POST", "/api/sair");
    document.body.innerHTML = `<main><div class="vazio" style="margin:auto">OW Tracker encerrado. Pode fechar esta janela.</div></main>`;
  }
});

document.addEventListener("change", async (e) => {
  const corrigir = e.target.dataset.corrigir;
  if (corrigir) {  // herói de um jogador da partida: "<partida>/<time>/<posição>"
    const [partida, time, posicao] = corrigir.split("/");
    try {
      await api.enviar("PUT", `/api/partidas/${partida}/jogadores/${time}/${posicao}`, { heroi_id: e.target.value });
      delete app.jogadores[partida];
      desenhar();
      mostrarToast(e.target.value ? "Herói corrigido. Esse retrato será reconhecido nas próximas partidas." : "Herói removido.");
    } catch (erro) { mostrarToast(erro.message); }
    return;
  }
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
    // O serviço reiniciou (versão nova): recarrega a página para pegar tudo novo.
    if (app.inicioServico && app.estado.inicio !== app.inicioServico) return location.reload();
    app.inicioServico = app.estado.inicio;
    document.getElementById("atualizacao").hidden = !app.estado.atualizacao;
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
  app.jogadores = {};  // os times podem ter mudado (ex.: Tab depois do fim)
  app.habilidadesPartida = {};
  app.habilidadesHeroi = {};
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
