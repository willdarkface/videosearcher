# Plano — catálogo próprio e dashboard

A ideia muda a natureza do projeto. Hoje o sistema **consome** bancos de terceiros
a cada vídeo, do zero. Com catálogo próprio ele **acumula**: cada vídeo produzido
deixa o acervo maior, mais bem classificado e mais barato de usar.

O efeito é composto. No vídeo 1, tudo vem de API. No vídeo 30, a maior parte dos
blocos resolve offline, em segundos, sem gastar cota, com material que você já
aprovou antes. É a diferença entre uma ferramenta e um ativo.

---

## 1. O gate de direitos autorais vem primeiro

Você disse "precisamos de coisas livres de direitos autorais", e a investigação
mostrou que o sistema estava **violando isso sem perceber**.

O provedor do Internet Archive marcava tudo como `public-domain` por suposição.
A checagem real dos itens que ele escolheu:

| Item | Coleção | licenseurl | rights |
|---|---|---|---|
| The Mutiny of the HMS Bounty | `opensource_movies`, `community` | ausente | ausente |
| Frankenstein or The Modern Prometheus | `opensource_movies` | ausente | ausente |
| Napoleonic Wars Battle Of Waterloo 1815 | `opensource_movies` | ausente | ausente |
| wwii-nat-archives-videos | `opensource_movies` | ausente | ausente |

**`opensource_movies` não é licença.** É onde cai upload de qualquer usuário — os
uploaders desses itens são endereços de Gmail e Yahoo. Usar isso num canal
monetizado é apostar em strike.

Corrigido em `core/licenca.py`, com regra conservadora: **licença só é livre
quando o metadado prova.** Três caminhos de prova:

1. `licenseurl` declara domínio público, CC0, CC BY ou CC BY-SA
2. O item está em coleção institucional (`usgovfilms`, `prelinger`, `nasa`,
   `library_of_congress`, `nationalarchives`, `smithsonian`, `FedFlix`,
   `universal_newsreels`)
3. Nada disso → `unknown`, e o canal recusa por padrão
   (`politica.exigir_licenca_verificada: true`)

Licenças CC **NC** e **ND** são marcadas `nao-comercial` e bloqueadas: não servem
para canal monetizado.

**Consequência medida:** a busca no IA foi reordenada para procurar primeiro nas
coleções institucionais. O que existe lá é limpo e é bom:

```
title:(panzer OR tank) + collection:(institucionais) + year:[1935 TO 1950]
  → 23 itens · LIVRE [1944] MARINES USE FLAME THROWERS, TANK ACTION ON SAIPAN
title:(rifle OR musket) + collection:(institucionais)
  → 15 itens · LIVRE  FUNDAMENTALS OF RIFLE MARKSMANSHIP
                LIVRE  U.S. RIFLE, CALIBER 7.62MM, M14 - OPERATION AND CYCLE
```

E o limite honesto: para tema **pré-fotografia**, o acervo limpo é quase vazio
(`waterloo OR napoleonic` → 1 item, e é um filme da Ford). Não existe filme de
1815. Canal napoleônico vai depender de pintura e gravura — Wikimedia Commons e
Library of Congress, que entram na fase 6.

---

## 2. Banco de dados

**SQLite + `sqlite-vec`.** Zero infraestrutura, um arquivo, roda na sua máquina,
e o `sqlite-vec` dá busca vetorial no mesmo banco. Migra para Postgres+pgvector
só se um dia virar multiusuário.

```sql
-- Item original da fonte, antes de qualquer corte
CREATE TABLE fontes (
  id            INTEGER PRIMARY KEY,
  provider      TEXT NOT NULL,          -- pexels | pixabay | internet_archive | ...
  provider_id   TEXT NOT NULL,
  titulo        TEXT,
  descricao     TEXT,
  source_page   TEXT,
  download_url  TEXT,
  duracao_s     REAL,
  largura       INTEGER,
  altura        INTEGER,
  data_original TEXT,                   -- ano ou intervalo do conteúdo
  -- licença: nunca nula, nunca suposta
  licenca_id    TEXT NOT NULL,
  licenca_url   TEXT,
  licenca_verificada INTEGER NOT NULL,  -- 0 = não usar comercialmente
  licenca_motivo TEXT NOT NULL,         -- por que foi classificada assim
  atribuicao    INTEGER NOT NULL,
  credito       TEXT,
  ingerido_em   TEXT NOT NULL,
  UNIQUE (provider, provider_id)
);

-- O ativo de verdade: pedaço utilizável, de 4 a 8 segundos
CREATE TABLE clipes (
  id           INTEGER PRIMARY KEY,
  fonte_id     INTEGER NOT NULL REFERENCES fontes(id) ON DELETE CASCADE,
  tipo         TEXT NOT NULL,           -- video | photo
  arquivo      TEXT NOT NULL,           -- caminho no acervo local
  keyframe     TEXT,                    -- jpg extraído do meio
  inicio_s     REAL,                    -- offset na fonte (null para foto)
  fim_s        REAL,
  duracao_s    REAL NOT NULL,
  largura      INTEGER NOT NULL,
  altura       INTEGER NOT NULL,
  fps          REAL,
  cena_id      INTEGER,                 -- agrupa clipes da mesma cena
  hash_visual  TEXT,                    -- pHash, para deduplicação
  bytes        INTEGER,
  criado_em    TEXT NOT NULL
);

-- Classificação: legenda gerada por modelo de visão
CREATE TABLE descricoes (
  clipe_id  INTEGER PRIMARY KEY REFERENCES clipes(id) ON DELETE CASCADE,
  caption   TEXT NOT NULL,              -- frase descritiva em inglês
  modelo    TEXT NOT NULL,              -- quem gerou, para auditar qualidade
  criado_em TEXT NOT NULL
);

-- Palavras-chave, com origem rastreável
CREATE TABLE palavras (
  id    INTEGER PRIMARY KEY,
  termo TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE clipe_palavras (
  clipe_id INTEGER NOT NULL REFERENCES clipes(id) ON DELETE CASCADE,
  palavra_id INTEGER NOT NULL REFERENCES palavras(id) ON DELETE CASCADE,
  origem   TEXT NOT NULL,               -- vlm | provedor | manual
  peso     REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (clipe_id, palavra_id, origem)
);

-- Atributos derivados, usados pelas regras de ranqueamento
CREATE TABLE atributos (
  clipe_id      INTEGER PRIMARY KEY REFERENCES clipes(id) ON DELETE CASCADE,
  look          TEXT,                   -- bw_archival | painting | color_modern | sepia
  saturacao     REAL,                   -- medida, não adivinhada
  movimento     TEXT,                   -- still | slow | fast
  tem_rosto     INTEGER,
  tem_texto     INTEGER,                -- marca d'água e legenda queimada
  sensibilidade TEXT                    -- none | sensitive | graphic
);

-- Busca semântica
CREATE VIRTUAL TABLE clipe_vetores USING vec0(
  clipe_id INTEGER PRIMARY KEY,
  embedding FLOAT[768]
);

-- Busca textual rápida em caption e palavras
CREATE VIRTUAL TABLE clipes_fts USING fts5(
  caption, palavras, titulo, content=''
);

-- Histórico de uso: é o que impede repetir clipe no mesmo canal
CREATE TABLE usos (
  id        INTEGER PRIMARY KEY,
  clipe_id  INTEGER NOT NULL REFERENCES clipes(id) ON DELETE CASCADE,
  canal     TEXT NOT NULL,
  video     TEXT NOT NULL,              -- nome do projeto/legenda
  bloco     INTEGER NOT NULL,
  aprovado  INTEGER,                    -- 1 aprovado, 0 trocado por você
  usado_em  TEXT NOT NULL
);
CREATE INDEX idx_usos_canal ON usos(canal, clipe_id);
```

`usos.aprovado` é o sinal de aprendizado: quando você troca um clipe no
dashboard, isso fica gravado e o ranqueamento aprende.

---

## 3. Ingestão e corte

```
URL do Internet Archive (ou asset já baixado)
   │
① GATE DE LICENÇA      metadado → licenca.py. Reprovado para aqui.
   │
② DOWNLOAD             filme completo para área temporária
   │
③ DETECÇÃO DE CENA     PySceneDetect (ContentDetector) → lista de cortes
   │
④ SEGMENTAÇÃO          dentro de cada cena, fatias de 4, 6 ou 8s.
   │                    Segmento nunca cruza corte de cena — é isso que evita
   │                    o clipe que troca de assunto no meio.
   │
⑤ CORTE ffmpeg         -ss/-t com keyframe, sem áudio, fps e resolução alvo
   │
⑥ KEYFRAME             jpg do meio do segmento
   │
⑦ CLASSIFICAÇÃO        VLM no keyframe → caption + palavras-chave
   │                    GLM-4.6V-Flash é gratuito na API da Z.ai
   │
⑧ ATRIBUTOS            saturação medida (define look), pHash, detecção de texto
   │
⑨ EMBEDDING            SigLIP local → clipe_vetores
   │
⑩ GRAVAÇÃO             fontes + clipes + descricoes + palavras + atributos
```

**ffmpeg sem dor de instalação:** o pacote `imageio-ffmpeg` traz binário estático
via pip. Testado aqui: ffmpeg 7.0.2, nenhum pacote de sistema necessário.

**Rendimento:** um filme institucional de 20 minutos com corte de 6s rende
~200 clipes. Baixa uma vez, rende para sempre, em qualquer canal.

**Custo:** R$ 0. O VLM é gratuito, o embedding roda local, o ffmpeg é local.

---

## 4. Dashboard

**Stack: FastAPI + HTML renderizado no servidor + HTMX.** Um comando
(`videosearcher dash`) sobe em `localhost:8000`.

Por que não Streamlit: preview de vídeo em grade fica ruim e o controle de
layout é pobre. Por que não Next.js: exigiria build, Node e um segundo runtime
para manter. HTMX dá interatividade sem nada disso, e `<video>` nativo resolve
o preview.

### Telas

**1. Projeto** — sobe a legenda, escolhe o canal, ajusta os sliders de
**% vídeo / % imagem** (já implementado como `midia.proporcao_video`), duração de
bloco, resolução mínima. Botão processar, com progresso ao vivo.

**2. Blocos** — a tela principal. Uma linha por bloco: timecode, texto,
briefing, e o asset escolhido com preview tocável. Ao lado, as alternativas.
Clicar numa alternativa promove; o arquivo é renomeado e a troca vai para
`usos.aprovado = 0`. Botão de buscar manualmente no catálogo quando nada serve.

**3. Catálogo** — busca no seu acervo por palavra-chave, por texto livre
(semântica, via embedding) e por filtro de licença, look, duração e canal já
usado. Grade de keyframes. Clicar abre o clipe com suas palavras-chave
editáveis — é aqui que você melhora a base à mão.

**4. Ingestão** — cola URL do Internet Archive, o sistema mostra a licença
**antes** de baixar, você escolhe a duração de corte (4/6/8s) e acompanha a
classificação. Também aceita pasta local de material seu.

**5. Entrega** — a pasta numerada, com download em zip e os créditos.

---

## 5. Ordem de construção

| Fase | Entrega | Por que nesta ordem |
|---|---|---|
| **A** | Banco + camada de catálogo, e o pipeline atual gravando tudo que busca | Sem isso nada acumula. É a fundação, e já começa a render acervo hoje |
| **B** | Ingestão com corte por cena e classificação por VLM | É o que transforma filme institucional em acervo utilizável |
| **C** | Dashboard telas 1, 2 e 5 (projeto, blocos, entrega) | Fecha o ciclo de produção com revisão visual |
| **D** | Dashboard telas 3 e 4 (catálogo e ingestão) | Curadoria e crescimento da base |
| **E** | Busca semântica no ranqueamento, consumindo o catálogo | Resolve o problema de relevância, e só funciona com base populada |

A fase A destrava as outras e é a que tem mais valor imediato: a partir dela,
cada execução do pipeline deixa registro em vez de jogar tudo fora.

---

## 6. Riscos

| Risco | Resposta |
|---|---|
| Acervo local cresce sem controle | `bytes` por clipe no banco, teto configurável, remoção por menos usado |
| Classificação por VLM erra | Palavra-chave editável no dashboard, com `origem = manual` vencendo a automática |
| Mesmo clipe entra duas vezes por fontes diferentes | `hash_visual` (pHash) na ingestão |
| Licença muda ou é contestada depois | `licenca_motivo` gravado por item, então dá para reauditar a base inteira com uma query |
| Corte por cena gera clipe sem conteúdo (tela preta, transição) | Descartar por variância de pixel e por caption vazia |
