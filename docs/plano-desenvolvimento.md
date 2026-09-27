# Plano de desenvolvimento — Níveis 1 e 2 (grátis + arquivo público)

**Objetivo:** entrada = arquivo de legenda (SRT/VTT). Saída = para cada bloco do roteiro, uma lista ranqueada de assets (vídeo **ou** foto) já baixados, normalizados, com licença e crédito registrados, prontos para montagem.

**Escopo desta fase:** apenas Nível 1 (Pexels, Pixabay, Coverr) e Nível 2 (Internet Archive, NARA, Library of Congress, Wikimedia Commons, NASA, Openverse-imagens). Níveis 3 e 4 (Storyblocks, Wan self-host) entram depois **sem reescrever nada** — é exatamente o que a arquitetura de plugin garante.

---

## 1. Premissas assumidas (corrija se estiver errado)

| # | Premissa |
|---|---|
| A1 | Legenda de entrada em **português**; a busca nos provedores precisa ser em **inglês** → existe um passo de tradução/normalização de query |
| A2 | **Multi-nicho e multi-canal desde o dia 1**: fitness, saúde, religioso, espiritual, história de armas, guerra, militar — e novos canais sempre. Nenhuma regra de nicho fica hardcoded |
| A3 | Rodar **local em Python**, via CLI, sem depender de SaaS |
| A4 | Custo alvo desta fase: **R$ 0** de infra; único gasto opcional é LLM/VLM por token (centavos por vídeo) |
| A5 | Foto é cidadã de primeira classe, não fallback — para temas históricos frequentemente é a **única** opção |
| A6 | **Não existe export para editor.** A entrega é uma pasta de arquivos nomeados pelo número do bloco. Bloco sem resultado simplesmente não gera arquivo, e a numeração continua alinhada |
| A7 | Acervo **preto e branco de época** é requisito de primeira classe, não exceção |

---

## 2. Arquitetura em 8 camadas

```
legenda.srt
   │
① INGESTÃO DE ROTEIRO      parse SRT/VTT → cues com timecode
   │
② SEGMENTAÇÃO EM BLOCOS    cues → blocos visuais de 3-10s com fronteira semântica
   │
③ BRIEFING VISUAL (LLM)    bloco → intenção, entidades, era, queries EN, tipo de mídia
   │
④ CAMADA DE PROVEDORES     ← PLUG-AND-PLAY. brief → N adaptadores em paralelo
   │                          cada um traduz o brief pro seu dialeto de busca
⑤ NORMALIZAÇÃO             respostas heterogêneas → schema Asset único
   │
⑥ RANQUEAMENTO             estágio 1 (metadados, barato) → estágio 2 (visual, caro)
   │
⑦ AQUISIÇÃO                download, sub-clipe de arquivo longo, normalização ffmpeg
   │
⑧ SAÍDA                    plano de edição JSON + créditos + revisão humana
   │
plano.json + /assets + CREDITS.md
```

---

## 3. O que cada camada precisa de desenvolvimento

### ① Ingestão de roteiro
- Parser SRT + VTT (`pysubs2` resolve os dois).
- Saída: lista de `Cue(index, start, end, text)`.
- **Trabalho:** baixo. ~80 linhas.

### ② Segmentação em blocos — decisão de design importante
Legenda vem picada em cues de 1-3s, que é granularidade errada para escolher imagem. Blocos precisam ser **unidades visuais**: 3-10s, terminando em fronteira de frase/ideia.

- Algoritmo: agrupar cues até atingir duração alvo, quebrando preferencialmente em pontuação forte; nunca quebrar no meio de frase.
- Configurável: `min_duration`, `max_duration`, `target_duration` por perfil (shorts quer 2-4s, longo quer 5-10s).
- **Trabalho:** médio. Precisa de tuning com legendas reais.

### ③ Briefing visual (LLM) — o coração da relevância
Aqui é onde o sistema deixa de ser "busca por palavra-chave" e passa a entender o roteiro. Um LLM recebe **o bloco + os blocos vizinhos + o tema geral do vídeo** e devolve um brief estruturado:

```json
{
  "block_id": 14,
  "text": "e em poucos meses a economia do país simplesmente entrou em colapso",
  "intent": "metaforico",
  "media_preference": ["video", "photo"],
  "era": null,
  "entities": [],
  "queries": {
    "primary": ["stock market crash trading floor panic"],
    "secondary": ["empty factory abandoned", "currency banknotes falling"],
    "archival": ["great depression bread line 1930s"]
  },
  "tone": "somber",
  "motion": "slow",
  "look": "any",
  "sensitivity": "none",
  "slug": "colapso-economico"
}
```

Campos que governam o pipeline inteiro:
- **`intent`**: `literal` | `metaforico` | `arquivo` | `grafico` | `retrato`. Decide **para quais provedores** o brief é roteado. `arquivo` não vai pro Pexels; `metaforico` não vai pro NARA.
- **`era`**: quando presente (`"1939-1945"`), ativa provedores de arquivo e filtra por data.
- **`queries`**: múltiplas, em inglês, já no vocabulário de stock (não tradução literal do português).
- **`look`**: `any` | `bw_archival` | `color_modern` | `sepia`. Canal de guerra/militar frequentemente exige **preto e branco de época**; canal de fitness exige o oposto. Vira filtro no ranqueamento (saturação medida no keyframe) e prioridade de provedor.
- **`sensitivity`**: `none` | `sensitive` | `graphic` → alimenta o filtro de monetização, com política definida por canal.
- **`slug`**: descrição curta em português, já higienizada — é o que vai no **nome do arquivo entregue**.

- **Trabalho:** médio-alto. O prompt é o ativo mais valioso do sistema e vai ser iterado muito. Usar modelo barato e rápido (Gemini Flash / GPT-mini), batch de ~20 blocos por chamada, cache por hash do texto.

### ④ Camada de provedores — o núcleo plug-and-play

**Contrato único.** Todo provedor implementa a mesma interface e se registra sozinho. Adicionar Storyblocks ou Wan depois = criar 1 arquivo, zero mudança no resto.

```python
# core/provider.py
class Capabilities(BaseModel):
    media_types: set[Literal["video", "photo"]]
    content_kind: set[Literal["broll", "archival", "editorial"]]
    supports_orientation_filter: bool
    supports_date_filter: bool
    license_default: str
    attribution_required: bool
    max_requests_per_hour: int | None
    cache_ttl_hours: int          # Pixabay exige 24
    needs_subclip: bool           # arquivo longo → True
    cost_per_asset: float         # 0.0 nos níveis 1 e 2

class Provider(Protocol):
    name: str
    capabilities: Capabilities

    def accepts(self, brief: VisualBrief) -> bool: ...
    def search(self, brief: VisualBrief, limit: int) -> list[RawResult]: ...
    def normalize(self, raw: RawResult) -> Asset: ...
    def download(self, asset: Asset, dest: Path) -> Path: ...
```

```python
# providers/pexels.py
@register                       # entra no registry automaticamente
class PexelsProvider:
    name = "pexels"
    capabilities = Capabilities(
        media_types={"video", "photo"},
        content_kind={"broll"},
        supports_orientation_filter=True,
        supports_date_filter=False,
        license_default="pexels",
        attribution_required=False,
        max_requests_per_hour=200,
        cache_ttl_hours=24,
        needs_subclip=False,
        cost_per_asset=0.0,
    )

    def accepts(self, brief):        # não serve para arquivo histórico
        return brief.intent != "arquivo" and brief.era is None
```

**O roteador** consulta `accepts()` de cada provedor registrado e dispara só os compatíveis, em paralelo, respeitando cota de cada um. Adicionar provedor novo é declarativo.

**Adaptadores a desenvolver nesta fase (8):**

| Provedor | Mídia | Dificuldade | Nota |
|---|---|---|---|
| Pexels | vídeo + foto | **fácil** | API limpa, paginada, filtro de orientação |
| Pixabay | vídeo + foto | **fácil** | obrigar cache de 24h no adaptador |
| Coverr | vídeo | **fácil** | cota baixa (50/h) → usar como complemento |
| Openverse | foto | **fácil** | ⚠️ filtrar só CC0/PDM para evitar obrigação de atribuição viral |
| NASA | vídeo + foto | **fácil** | `images-api.nasa.gov`, domínio restrito (espaço/ciência) |
| Library of Congress | foto + vídeo | **média** | `?fo=json`, metadados irregulares |
| NARA | vídeo + foto | **média-alta** | API v2 + objetos digitais em outra rota; paginação chata |
| Internet Archive | vídeo | **alta** | ver ⑦: itens são filmes longos, não clipes |

- **Trabalho:** o maior bloco da fase. Fáceis ~1 dia cada; NARA e IA valem 2-3 dias cada.

### ⑤ Normalização — schema Asset único
Tudo que sai de qualquer provedor vira o mesmo objeto. Sem isso o ranqueamento não funciona.

```python
class Asset(BaseModel):
    uid: str                    # f"{provider}:{provider_id}"
    provider: str
    media_type: Literal["video", "photo"]
    title: str | None
    description: str | None
    tags: list[str]
    # vídeo
    duration_s: float | None
    fps: float | None
    # comum
    width: int
    height: int
    orientation: Literal["landscape", "portrait", "square"]
    preview_url: str            # thumb/keyframe para o re-rank visual
    download_url: str
    # licença — obrigatório, nunca nulo
    license_id: str
    license_url: str | None
    attribution_required: bool
    credit_string: str | None
    # arquivo
    date_original: str | None
    is_archival: bool
    source_page: str            # rastreabilidade
```

### ⑥ Ranqueamento — dois estágios
Rodar embedding visual em 200 candidatos por bloco é caro. Filtra barato primeiro.

**Estágio 1 — barato, sobre metadados** (candidatos → top 15):
- similaridade textual brief ↔ título/tags/descrição (BM25 ou embedding de texto);
- **regras duras** (eliminam): orientação incompatível, resolução abaixo do mínimo, licença com atribuição quando o perfil proíbe, `sensitivity` bloqueada;
- **regras suaves** (pontuam): duração ≥ duração do bloco, prioridade do provedor, `date_original` dentro da `era` do brief.

**Estágio 2 — visual, sobre os top 15** (→ top 3 + fallbacks):
- embedding do keyframe/thumb com CLIP ou SigLIP contra embedding do texto do brief;
- **penalidade de repetição**: pHash contra assets já usados neste vídeo e nos últimos N vídeos — isso é o que separa canal profissional de canal de robô;
- deduplicação cross-provider (o mesmo clipe de arquivo está no IA e no Commons).

Score final ponderado e **auditável** — cada bloco guarda por que aquele asset ganhou. Sem isso não é possível ajustar o sistema.

- **Trabalho:** alto. Estágio 1 na semana 2, estágio 2 depois.

### ⑦ Aquisição — o problema específico do arquivo público
Pexels devolve um clipe de 12s pronto. O Internet Archive devolve **um filme de 22 minutos**. São coisas diferentes e o pipeline precisa tratar:

1. **Download** com resume, hash, disco cache, limite de tamanho.
2. **Detecção de cenas** em itens longos (`PySceneDetect`) → quebra em sub-clipes de 4-12s.
3. **Indexação por cena**, não por item: cada sub-clipe ganha keyframe + caption por VLM + embedding e entra no catálogo local como asset autônomo. O filme de 22 min viaja uma vez e rende 150 assets reutilizáveis para sempre.
4. **Normalização ffmpeg**: resolução alvo, fps alvo, sem áudio, codec único, tratamento de 4:3 (pillarbox/blur ou crop).
5. **Foto → movimento**: gerar Ken Burns (pan/zoom) com duração exata do bloco. Fundamental — é o que faz foto histórica funcionar em vídeo.

- **Trabalho:** alto. A indexação por cena é o que transforma o Nível 2 de "curiosidade" em acervo real.

### ⑧ Entrega — pasta numerada por bloco

Saída única e simples: **uma pasta por vídeo**, com o melhor asset de cada bloco, nomeado pelo número do bloco. Bloco sem resultado não gera arquivo, e a numeração **não é reordenada** — o buraco fica visível e a numeração continua batendo com a legenda.

```
saida/2026-09-26_armas-ww2/
├── 001 - video soldados marchando na neve.mp4
├── 002 - imagem tanque panzer em campo aberto.jpg
├── 004 - video comboio de caminhoes militares.mp4
├── 007 - imagem retrato piloto cabine aviao.jpg
├── 008 - video explosao artilharia noturna.mp4
├── ...
├── _alternativas/
│   ├── 001b - video tropas em trincheira.mp4
│   ├── 001c - imagem coluna de soldados.jpg
│   └── 002b - video tanque cruzando rio.mp4
├── _manifest.csv
├── _nao-encontrados.txt
└── _CREDITOS.md
```

**Regras de nomeação** (módulo `output/naming.py`):
- **Prefixo numérico com zero-padding** calculado pelo total de blocos: 100 blocos → `001`–`100`; 40 blocos → `01`–`40`. Garante ordenação correta em qualquer explorador de arquivos.
- Separador `" - "`, depois o **tipo** (`video` ou `imagem`), depois o **slug em português** vindo do brief.
- Higienização: sem `/ \ : * ? " < > |`, sem acento problemático em FS estrangeiro (configurável), colapso de espaços, corte em ~60 caracteres preservando palavra inteira.
- Extensão real do arquivo baixado após normalização (`.mp4`, `.jpg`, `.png`).
- Colisão de nome → sufixo incremental, nunca sobrescreve.
- **Alternativas** (2º e 3º colocados) vão para `_alternativas/` com sufixo `b`/`c`, mesma numeração. Pasta raiz fica com **exatamente 1 arquivo por bloco**, pra você não ter que escolher nada.

**Arquivos de controle:**
- **`_manifest.csv`** — uma linha por bloco: número, timecode início/fim, duração, texto da legenda, arquivo entregue, provedor, licença, crédito, score e justificativa da escolha. É o que permite auditar e ajustar o sistema.
- **`_nao-encontrados.txt`** — blocos sem resultado, com o texto e as queries tentadas. É o seu retrabalho manual mínimo, e também o mapa do que o Nível 4 (geração) vai cobrir no futuro.
- **`_CREDITOS.md`** — gerado só com os assets que têm `attribution_required`, pronto pra colar na descrição do vídeo.

**Revisão humana (opcional, fase 8):** página HTML estática local mostrando bloco a bloco o escolhido e as 2 alternativas, com botão de promover alternativa. Promover = renomear arquivos e registrar o sinal no catálogo, que realimenta o ranqueamento.

---

## 4. Catálogo local — o ativo que o sistema constrói

Toda busca alimenta um banco local. Na segunda vez o sistema consulta o **seu** acervo antes de bater em qualquer API.

- **SQLite** (`assets`, `blocks`, `matches`, `usage_history`, `provider_quota`) + **`sqlite-vec`** para os embeddings. Sem Docker, sem servidor, migra para pgvector/Qdrant depois se crescer.
- `usage_history` é o que impede repetir clipe entre vídeos.
- Resolve de graça a exigência de cache de 24h do Pixabay.
- Efeito composto: no vídeo 30 a maioria dos blocos resolve offline, em segundos e sem cota.

---

## 4b. Packs de canal — como o sistema atende N nichos sem virar N sistemas

Você tem canais de fitness, saúde, religioso, espiritual, história de armas, guerra e militar — e vai criar mais. A resposta não é código por nicho, é **um arquivo YAML por canal**, no mesmo espírito plug-and-play dos provedores. Criar canal novo = copiar um YAML.

```yaml
# channels/guerra-ww2.yaml
extends: _base
nome: "Guerra WW2"
idioma_legenda: pt-BR

provedores:
  prioridade: [internet_archive, nara, loc, wikimedia, pexels, pixabay]
  pesos: { internet_archive: 1.3, nara: 1.3, pexels: 0.7 }

estetica:
  look_padrao: bw_archival        # vira default do brief quando o LLM não decide
  aceita_4x3: true                # arquivo de época vem em 4:3 e isso é desejável
  grao_permitido: true

briefing:
  vocabulario: |
    Prefira termos de arquivo militar: newsreel, war footage, troops,
    armored column, panzer, artillery barrage, trench, airfield, convoy.
    Nomes de operação, unidade e local aumentam a precisão.
  intent_padrao: arquivo

politica:
  sensitivity_maxima: sensitive   # bloqueia "graphic": corpos, ferimentos, execução
  licencas_proibidas: [cc-by-sa]  # evita licença viral

entrega:
  duracao_bloco: [4, 10]
  resolucao_minima: 720
  alternativas_por_bloco: 2
```

```yaml
# channels/fitness.yaml
extends: _base
provedores:
  prioridade: [pexels, pixabay, coverr]
  pesos: { pexels: 1.3 }
estetica:
  look_padrao: color_modern
  aceita_4x3: false
briefing:
  vocabulario: |
    Termos de stock moderno: gym workout, barbell deadlift, kettlebell,
    running outdoors sunrise, meal prep healthy food, stretching mat.
  intent_padrao: literal
politica:
  sensitivity_maxima: none
entrega:
  duracao_bloco: [3, 7]
  resolucao_minima: 1080
```

O que o pack controla:
- **prioridade e peso de provedor** — canal militar joga Internet Archive e NARA na frente; canal fitness joga Pexels na frente. O mesmo motor, ordens opostas.
- **vocabulário injetado no prompt do briefing** — é o que faz o LLM gerar query de stock boa em vez de tradução literal. Ativo que você refina canal por canal.
- **estética** (`look_padrao`, aceita 4:3, grão) — preto e branco de época num, cor moderna 1080p+ no outro.
- **política de sensibilidade e licença** — canal de guerra precisa de material forte mas não gráfico; canal religioso tem outra régua.
- **escopo de deduplicação** — `usage_history` é filtrado **por canal**: o mesmo clipe de tanque pode aparecer em dois canais diferentes, mas nunca duas vezes no mesmo canal. Isso é o que torna N canais viável sem esgotar acervo.

Uso: `pipeline plan legenda.srt --canal guerra-ww2`

**Taxonomia de conteúdo que já cobre tudo que você pediu** — e é só metadado no catálogo, não código:
`militar` (tanque, comboio, blindado, artilharia, aviação, naval, infantaria) · `armas` (arma de fogo, munição, fábrica, teste) · `epoca-bw` (newsreel, cotidiano, cidade, retrato) · `veiculos` (carro clássico, caminhão, moto, trem) · `pessoas` (rosto, multidão, trabalho, emoção) · `fitness` · `saude` · `religioso` · `espiritual` · `natureza` · `abstrato`.

Cada asset no catálogo ganha essas tags na indexação. Consequência prática: quando você criar o 8º canal, boa parte do acervo **já está indexado e disponível offline**, sem gastar cota nenhuma.

---

## 5. Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Linguagem | Python 3.11+ | ecossistema de vídeo e ML |
| HTTP | `httpx` async + `tenacity` | provedores em paralelo, retry com backoff |
| Schemas | `pydantic v2` | contrato do plugin é validado, não é convenção |
| CLI | `typer` | `pipeline plan legenda.srt --profile longform` |
| Banco | SQLite + `sqlite-vec` | zero infra |
| Vídeo | `ffmpeg` + `PySceneDetect` | corte, normalização, Ken Burns |
| Embedding visual | SigLIP / CLIP via `transformers` (ou `fastembed` em CPU) | roda local, sem custo por chamada |
| LLM do brief | Gemini Flash ou GPT-mini | centavos por vídeo, com cache |
| Config | YAML + `.env` | perfis (`longform`, `shorts`) e chaves |
| Testes | `pytest` + respostas de API gravadas | não queimar cota em teste |

---

## 6. Estrutura de pastas

```
video-matcher/
├── core/
│   ├── models.py          Cue, Block, VisualBrief, Asset, Match
│   ├── provider.py        Protocol + Capabilities + @register
│   ├── registry.py        descoberta e roteamento por accepts()
│   ├── quota.py           rate limit e cota por provedor
│   └── cache.py           cache HTTP + TTL por provedor
├── providers/             ← 1 arquivo = 1 provedor. adicionar é só criar aqui
│   ├── pexels.py  pixabay.py  coverr.py  openverse.py
│   ├── nasa.py  loc.py  nara.py  internet_archive.py
│   └── _template.py       esqueleto comentado para o próximo
├── script/
│   ├── parser.py          SRT/VTT → Cue
│   ├── blocker.py         Cue → Block
│   └── briefing.py        Block → VisualBrief (LLM)
├── ranking/
│   ├── stage1_meta.py  stage2_visual.py  rules.py  dedupe.py
├── acquire/
│   ├── downloader.py  scenes.py  normalize.py  kenburns.py
├── catalog/
│   ├── db.py  schema.sql  index.py
├── output/
│   ├── naming.py          regra de nome do arquivo
│   ├── deliver.py         monta a pasta, move, renomeia, trata colisão
│   ├── manifest.py        _manifest.csv + _nao-encontrados.txt
│   ├── credits.py         _CREDITOS.md
│   └── review_ui.py       HTML estático de revisão (fase 8)
├── channels/              ← 1 arquivo = 1 canal/nicho. adicionar canal é só criar aqui
│   ├── _base.yaml         herança comum
│   ├── guerra-ww2.yaml  armas.yaml  militar.yaml
│   ├── fitness.yaml  saude.yaml
│   └── religioso.yaml  espiritual.yaml
└── cli.py
```

---

## 7. Fases de entrega

Cada fase termina em algo **rodando e verificável** — sem big bang.

| Fase | Entrega | Critério de pronto |
|---|---|---|
| **0** | Esqueleto + models + registry + packs de canal + CLI | `pipeline providers` e `pipeline channels` listam o que está registrado |
| **1** | Parser SRT/VTT + blocker | `pipeline blocks legenda.srt` mostra blocos numerados com timecode e duração coerentes |
| **2** | Briefing LLM com vocabulário por canal + cache | briefs de uma legenda real de cada nicho fazem sentido na leitura |
| **3** | Pexels + Pixabay + ranqueamento estágio 1 + **entrega em pasta numerada** | `pipeline run legenda.srt --canal fitness` gera a pasta com arquivos nomeados, manifest e não-encontrados — **primeiro ciclo fechado ponta a ponta** |
| **4** | Aquisição completa: download, normalização ffmpeg, Ken Burns em foto, tratamento de 4:3 | todo arquivo entregue já sai no formato final, foto inclusive |
| **5** | **Internet Archive + NARA + detecção de cena** | bloco `intent: arquivo` de um canal de guerra retorna sub-clipe relevante de filme de época em B&W |
| **6** | LoC + Wikimedia + Openverse + NASA + Coverr | cobertura de foto histórica e de nichos secundários; template de provedor validado por repetição |
| **7** | Ranqueamento estágio 2 (visual SigLIP) + filtro de `look` + dedupe por canal + histórico | melhora mensurável vs fase 3 nas mesmas legendas; nada repete dentro do canal |
| **8** | UI de revisão HTML + créditos + pré-aquecimento de catálogo por tema | você revisa 100 blocos em minutos e promove alternativa com um clique |

**Mudança de ordem em relação ao plano inicial:** Internet Archive e NARA subiram da fase 6 para a **fase 5**, na frente dos provedores fáceis. Motivo: seus canais de guerra, armas e militar dependem de acervo de época, e Pexels não entrega nada disso. Fazer os fáceis primeiro adiaria o valor real.

Fase 3 é o marco que importa: a partir dela você já recebe a pasta pronta. Tudo depois é ampliação de cobertura e qualidade.

---

## 8. Riscos e como a arquitetura já responde

| Risco | Resposta |
|---|---|
| Provedor muda ou morre API | plugin isolado; registry ignora provedor com erro, pipeline segue |
| Cota estourada no meio do vídeo | `quota.py` degrada para outro provedor e para o catálogo local |
| Arquivo histórico gráfico desmonetiza | `sensitivity` no brief + regra dura no estágio 1, configurável por perfil |
| Licença viral (CC-BY-SA) entrando sem controle | `attribution_required` é campo obrigatório do Asset; perfil pode banir |
| Clipe repetido entre vídeos | `usage_history` + pHash como penalidade no estágio 2 |
| Brief ruim e ninguém percebe | score auditável por bloco + UI de revisão registrando suas trocas |
| Ranqueamento "melhorar" e piorar | conjunto fixo de legendas de teste, comparação entre versões |

---

## 9. Decisões fechadas e pendências

**Fechado:**
- Multi-nicho e multi-canal via packs YAML, sem código por nicho. ✅
- Entrega = pasta com arquivo por bloco, numerado com zero-padding, sem export para editor. ✅
- Buracos de bloco são preservados e listados em `_nao-encontrados.txt`. ✅
- Internet Archive e NARA promovidos para a fase 5. ✅

**Pendente (não bloqueia começar as fases 0 e 1):**
1. **LLM do briefing** — Gemini Flash / GPT-mini (centavos por vídeo, melhor relevância) ou 100% local com Ollama (grátis, relevância menor)? Dá para começar com um e trocar: é uma interface só.
2. **Volume semanal** — define se vale construir o pré-aquecimento de catálogo por tema na fase 8 ou antes.
3. **Resolução mínima por canal** — 720p aceitável em acervo de época (muita coisa boa só existe em SD), 1080p obrigatório em fitness. Confirmar caso a caso nos YAMLs.
