# OW Tracker

Registra **sozinho** as suas partidas de Overwatch 2 (herói, mapa, modo e
resultado), com histórico e winrate por herói, mapa e modo.

- **Automático**: lê a tela do jogo e registra quando aparece VITÓRIA/DERROTA/EMPATE.
- **Funciona em tela cheia exclusiva** e em qualquer resolução (detectada a cada leitura).
- **Zero dependências**: só Python 3.10+. Captura, OCR e atalhos usam APIs do próprio Windows.
- **Leve**: o registro roda em segundo plano (~31 MB de RAM, ~0% de CPU fora do
  jogo, prioridade abaixo do normal). A janela só abre quando você quer, e
  fechá-la não para o registro.
- **Seguro para a conta**: só vê a tela, como o OBS. Nunca lê a memória do jogo,
  não injeta nada, não aperta teclas e não mexe nos arquivos do Overwatch.

## Como usar

Dê dois cliques em `OW Tracker.pyw` (ou `python -m owtracker`) e jogue.
Em **Ajustes**, ligue *Iniciar com o Windows* para nunca precisar abrir o app.

- **Dashboard**: partida em andamento (atualiza a cada Tab), winrate, médias,
  partidas recentes, desempenho por função, subfunção e modo de mapa.
- **Histórico**: todas as partidas; clique numa para corrigir ou apagar, e use
  *+ Registrar partida* para uma que o automático não pegou.
- **Heróis**: os 54 heróis com suas estatísticas; clique para ver habilidades,
  vantagens e suas partidas com ele.
- **Mapas**: os 30 mapas agrupados por modo, com seu winrate.
- `Ctrl+Shift+O` abre a janela (funciona dentro do jogo). Para encerrar o registro
  de vez: **Ajustes → Sair**.

### Como o app é montado

```
OW Tracker.pyw ─► serviço em segundo plano (Python, sem dependências)
                   ├─ monitor: captura + OCR + detector (lê o jogo)
                   ├─ banco SQLite (dados/partidas.db)
                   └─ servidor local 127.0.0.1:47815 (página + API JSON)
                  janela: Edge em modo aplicativo (sem abas/barra), abre sob demanda
```

Para mexer na interface sem tocar nos seus dados:
`python ferramentas/interface_demo.py` (usa uma cópia do banco, sem o monitor).

## Como a detecção funciona

O OCR do Windows não lê a fonte estilizada dos títulos do Overwatch, mas lê
bem as **legendas** e o texto comum. Por isso **deixe as legendas ligadas** no jogo.

```
só com o Overwatch em primeiro plano:
  a cada 1 s   faixa das legendas  -> "[FILIPE (ROADHOG)] ..."  = seu herói
                                    -> "[ATHENA] Derrota."        = fim da partida
  a cada 3 s   tela inteira        -> "CONTROLE - COMPETITIVO | NEPAL" (placar/Tab) = mapa e modo
                                    -> "Filipe trocou para Ana (era Kiriko)" (chat)
                                    -> abas RESUMO/RECOMPENSAS = tela pós-partida
```

- **Tab**: o app percebe quando você segura a tecla Tab (só consulta o estado da
  tecla, não intercepta nada) e lê o placar na hora, e de novo a cada segundo.
  - Cabeçalho: "CONTROLE - COMPETITIVO | NEPAL" na Competitiva, "HÍBRIDO | HOLLYWOOD"
    na Partida Rápida, o que dá o mapa e o modo.
  - A sua linha (E, A, M, Dano, Cura, Mitigado) é achada pela cor (tem destaque) e
    ganha uma leitura extra ampliada. Quando a partida termina, os números do
    **último Tab aberto** são gravados junto com ela. Coluna não lida fica vazia.
  - Durante a partida, ela aparece em azul no topo do Histórico ("em andamento"),
    atualizada a cada Tab.
  - **Os dois times**: o Tab também é lido por inteiro (no máximo a cada 2,5 s):
    os números dos 10 jogadores, o retrato de cada um e o nome. Clique numa partida
    no Histórico para ver aliados e inimigos. O placar não escreve o herói, então
    ele é identificado (`retratos.py`) por: você e aliados que falaram nas legendas;
    biblioteca de retratos aprendida (o mesmo herói com a mesma skin tem sempre o
    mesmo retrato); ícones de vantagem comparados pela forma, limitados à função da
    linha. Herói errado/desconhecido: escolha o certo na página da partida e o app
    aprende aquele retrato. Os nomes vêm da fonte estilizada e podem sair errados
    (os confirmados pelas legendas são confiáveis).
  - **Vantagens escolhidas** de cada jogador: com o herói conhecido, cada ícone é
    comparado só com as 4 vantagens dele (menor/maior) e aparece na página da partida.
  - Partida registrada sem os times? Se o diagnóstico salvou um print do Tab:
    `python ferramentas/recuperar_times.py <id da partida> capturas/diagnostico/<print>_placar.png`
  - **Dica: aperte Tab quando aparecer DERROTA/VITÓRIA.** O placar ainda abre por
    uns 20 s depois do fim, com os números finais, e eles corrigem o registro.
  - Em cada Tab aberto vale o valor mais repetido entre as leituras, então uma
    leitura errada isolada não entra.
  - O app nunca aperta teclas no jogo (seria automação, contra os termos da Blizzard).
  - O OCR do Windows não lê um dígito sozinho (o "1"), e o jogo mostra o zero em
    cinza. Para isso há um reconhecedor de dígitos próprio (`digitos.py`): ele separa
    os dígitos, reconhece o "1" pela forma e aprende os outros com os números que o
    OCR acerta (modelos em `dados/digitos.json`).
- A tela pós-partida de votos ("DERROTA | ILIOS | TEMPO DA PARTIDA") também confirma o resultado.
- O seu nome no jogo fica em **Ajustes**. Se ficar vazio, o app aprende sozinho:
  é o nome que fala em várias partidas (os colegas mudam, você não).
- Falas de inimigos aparecem só como "[HAZARD]" e são ignoradas.
- Telas com vários mapas ou modos (menu Jogar, votação de mapa) não contam.
- O mapa vem do cabeçalho do Tab. Nome de mapa lido em outro lugar da tela só
  vale se o Tab não foi aberto na partida, porque nomes de jogadores confundem
  ("SAMOANP" virava Samoa). Uma partida só é dada como nova quando o Tab
  mostra outro mapa (2 leituras), mais de 3 min depois do último Tab.
- Se a tela pós-partida aparecer sem a legenda do resultado, o app preenche o
  Registro manual e só falta você clicar no resultado.
- Para calibrar sem jogar: `python -m owtracker.reproduzir dados/diagnostico.log FILIPE`.

## Heróis usados (trocas)

Cada partida guarda os seus heróis em ordem, com o tempo aproximado de cada um
(página da partida, "Heróis usados", e retratos pequenos no histórico). O
principal é o que você jogou por mais tempo.

A fonte do seu herói é o Tab: o nome escrito no painel à direita do placar.
- Depois que o Tab mostrou o seu herói, só outro Tab muda o herói; as legendas
  não trocam mais nada (um aliado "FELIPE" de Doomfist já virou "FILIPE").
- A linha do tempo da partida usa só as leituras do painel. A hora de uma
  troca é a sua primeira fala com o herói novo entre os dois Tabs.
- Antes do primeiro Tab (ou em partidas sem Tab) valem as legendas, com
  cuidado: a mesma fala parada na tela conta uma vez só; um herói só entra com
  2 falas distintas ou com a mensagem "X trocou para Y"; o nome tem de ser o
  seu, aceitando só um caractere a mais ou a menos na ponta.
- As habilidades contam para o herói atual; depois de trocar de herói, abra o
  Tab para o app saber.

## Estatísticas do herói (painel do Tab)

O Tab mostra, à direita do placar, as estatísticas próprias do herói que você
está jogando: precisão da arma, "Cura com Ajuste", "Kits médicos hackeados"...
O app lê esse painel a cada Tab (e no Tab depois do fim, com os números
finais) e mostra:

- na página da partida, "Estatísticas do herói", com cada número comparado à
  sua média nas outras partidas com o herói (contagens por 10 min jogados);
- na página do herói, a média, o melhor valor, a média nas vitórias e nas
  derrotas e as últimas partidas de cada estatística.

Como funciona (`painel.py`):
- os rótulos e a maioria dos valores vêm do OCR; dígito sozinho vem do
  reconhecedor próprio; os números das caixas do topo (fonte estilizada) são
  lidos com recortes ampliados e, se for um dígito só, com o recorte repetido
  lado a lado ("8" vira "888", que o OCR lê);
- o herói do painel é o nome escrito nele; sem o nome, o herói cujas
  estatísticas conhecidas batem com as da tela;
- singular e plural viram a mesma estatística ("Kit médico hackeado" = "Kits
  médicos hackeados"); um valor de outro tipo (um tempo lido como número) é
  descartado.

As estatísticas de cada herói ficam na tabela `estatistica_heroi`: começa com
as já mapeadas (`referencia/estatisticas.json`) e aprende as dos outros heróis
quando você joga com eles. Para preencher partidas antigas a partir dos prints
guardados: `python ferramentas/recuperar_estatisticas.py --gravar`.

## Uso de habilidades

Com o seu herói conhecido (pela legenda), o app conta quantas vezes você usou
cada habilidade e mostra isso na página da partida ("Suas habilidades"), na
página do herói ("Uso de habilidades": média por partida, total, máximo e as
últimas partidas) e no cartão da partida em andamento.

- As teclas são lidas de forma passiva (`GetAsyncKeyState`, `entradas.py`), só
  com o jogo em primeiro plano. Nada é enviado ao jogo e a memória dele não é lida.
- Teclas consideradas: Shift, E, Q, botão direito e R, nas posições padrão do
  jogo. Quem mudou as teclas no jogo terá contagens erradas.
- Um aperto só conta se a habilidade já saiu da recarga (85% do tempo base,
  porque vantagens e subfunções reduzem um pouco a recarga). Assim, apertar
  várias vezes seguidas conta um uso só.
- Não conta com o chat aberto (Enter… Enter/Esc) nem morto ("RESSURGIRÁ EM").
- A suprema conta pelos pixels do HUD: o círculo do centro mostra a suprema
  pronta (anel branco com brilho amarelo-esverdeado). Conta quando você aperta
  Q com ela vista pronta nos últimos 4 s e depois ela some por 2 leituras
  seguidas (a leitura oscila com efeitos na tela, como a invisibilidade da
  Sombra). Sem o Q (morreu com ela pronta, abriu o Tab) não conta.
- O que conta como habilidade fica em `habilidades.py`. Ficam de fora: tiros
  (o botão direito da Lifeweaver, por exemplo), habilidades sem recarga ou com
  recarga muito curta, e barreiras de segurar (Reinhardt, Brigitte...).

Com o modo diagnóstico ligado, `dados/teclas.log` grava cada tecla de
habilidade e o que o detector fez com ela: contou, estava em recarga, chat
aberto, morto, aguardando confirmar o herói. Grava também quando o HUD mostra a
suprema pronta e quando ela deixa de estar pronta, com ou sem Q. Só as teclas
de habilidade, Enter e Esc entram no registro, nunca o que você digita.

## Modo diagnóstico (ligado por padrão nesta fase)

Para calibrar com as telas reais do jogo, o app guarda:
- `dados/diagnostico.log`: o texto lido em cada tela;
- `capturas/diagnostico/`: alguns prints reduzidos (no máximo 300, os antigos são apagados).

Pode desligar em **Ajustes** quando a detecção estiver redonda.

## Referência do jogo (heróis, habilidades, mapas, modos)

`owtracker/referencia/*.json` tem o catálogo atual do jogo, em pt-BR e inglês:
54 heróis (função, subfunção, vida/armadura/escudo, habilidades com tipo, tecla,
recarga e descrição, vantagens), 3 funções, 10 subfunções, 30 mapas de
Partida Rápida/Competitiva e seus 5 modos, com as URLs dos ícones oficiais.

Ao abrir, o app instala isso como tabelas no próprio banco (`dados/partidas.db`):
`funcao`, `subfuncao`, `heroi`, `habilidade`, `modo_mapa` e `mapa`. Cada partida
tem `heroi_id`/`mapa_id`, e a view **`vw_partidas`** traz o histórico já cruzado
(função, subfunção, modo do mapa). Exemplo:

```sql
SELECT subfuncao, COUNT(*) AS jogos, SUM(resultado = 'Vitória') AS vitorias
FROM vw_partidas GROUP BY subfuncao;
```

Atualizar quando sair herói/mapa novo:

```
python ferramentas/coletar_referencia.py   # site oficial (pt-BR/en) + Overwatch Wiki
python ferramentas/baixar_assets.py        # ícones e imagens (~26 MB, uso pessoal)
```

## Estrutura

```
owtracker/
  app.py       ponto de entrada: sobe o serviço, o servidor e abre a janela
  servico.py   liga o monitor ao banco; estado consultado pela interface
  servidor.py  servidor local (127.0.0.1) com a página e a API JSON
  sistema.py   Windows: abrir a janela (Edge), iniciar com o sistema
  web/         interface (index.html, estilo.css, app.js)
  monitor.py   thread do modo automático + diagnóstico
  detector.py  regras: mapa, herói, modo e fim de partida
  captura.py   captura DXGI (tela cheia) com reserva GDI; acha a janela do jogo
  ocr.py       OCR do Windows (Windows.Media.Ocr) via ctypes
  placar.py    leitura do placar (Tab): acha a sua linha e as colunas
  painel.py    painel do herói no Tab: estatísticas específicas do herói
  habilidades.py  habilidades contáveis de cada herói (tecla e recarga)
  entradas.py  leitura passiva das teclas de habilidade
  digitos.py   reconhecedor de dígitos próprio (completa o que o OCR pula)
  com.py       mini camada para chamar COM/WinRT
  imagem.py    recorte e redução de imagens
  janelas.py   atalhos globais, captura GDI, encoder PNG
  banco.py     SQLite e estatísticas
  catalogo.py  referência do jogo (lê referencia/*.json e cria as tabelas)
  dados.py     listas da interface/detector (vêm do catálogo)
  referencia/  catálogo em JSON (+ assets/ com as imagens, fora do git)
ferramentas/
  coletar_referencia.py  gera o catálogo a partir das fontes
  baixar_assets.py       baixa os ícones e imagens do catálogo
```

Herói ou mapa novo: adicione em `owtracker/dados.py`. Se o jogo mostrar o nome
diferente (tradução), coloque em `APELIDOS_MAPAS` / `APELIDOS_HEROIS`.
