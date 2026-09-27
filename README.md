# videosearcher

Recebe uma **legenda** (`.srt` ou `.vtt`), divide o roteiro em **blocos visuais** e, para cada bloco, encontra e baixa a mídia que faz sentido ali — **vídeo ou foto** — em bancos gratuitos e acervos de domínio público.

A entrega é uma pasta com um arquivo por bloco, nomeado pelo número do bloco:

```
saida/2026-09-26_guerra/
├── 001 - video soldados marchando na neve.mp4
├── 002 - imagem tanque panzer em campo aberto.jpg
├── 004 - video comboio de caminhoes militares.mp4
├── 007 - imagem retrato piloto cabine aviao.jpg
├── _alternativas/
├── _manifest.csv
├── _nao-encontrados.txt
└── _CREDITOS.md
```

Bloco sem resultado simplesmente não gera arquivo, e a numeração **não é reordenada** — o buraco fica visível e os números continuam batendo com a legenda.

---

## Índice

- [Estado atual](#estado-atual)
- [Instalação](#instalação)
- [Cadastro das LLMs](#cadastro-das-llms) ← **comece aqui**
- [Como funciona a corrente de fallback](#como-funciona-a-corrente-de-fallback)
- [OpenRouter: quando e como usar](#openrouter-quando-e-como-usar)
- [Uso](#uso)
- [Packs de canal](#packs-de-canal)
- [Adicionar um provedor de LLM](#adicionar-um-provedor-de-llm)
- [Adicionar um provedor de mídia](#adicionar-um-provedor-de-mídia)
- [Arquitetura](#arquitetura)
- [Roadmap](#roadmap)

---

## Estado atual

| Fase | O que entrega | Estado |
|---|---|---|
| **0** | Esqueleto, modelos, registry de provedores, packs de canal, camada de LLM com fallback, CLI | ✅ **pronto** |
| **1** | Parser SRT/VTT + segmentação em blocos visuais | ✅ **pronto** |
| **2** | Briefing visual por LLM (intenção, era, queries, estética) | ✅ **pronto** |
| 3 | Pexels + Pixabay + ranqueamento + entrega em pasta numerada | ⏳ |
| 4 | Download, normalização ffmpeg, Ken Burns em foto, 4:3 | ⏳ |
| 5 | Internet Archive + NARA + detecção de cena | ⏳ |
| 6 | Library of Congress, Wikimedia, Openverse, NASA, Coverr | ⏳ |
| 7 | Re-rank visual (SigLIP), filtro de estética, dedupe por canal | ⏳ |
| 8 | UI de revisão, créditos automáticos, pré-aquecimento de catálogo | ⏳ |

O planejamento completo está em [`docs/plano-desenvolvimento.md`](docs/plano-desenvolvimento.md).

---

## Instalação

Requer **Python 3.11+** e `git`.

```bash
git clone https://github.com/willdarkface/videosearcher.git
cd videosearcher

python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e .
```

Confirme:

```bash
videosearcher version
videosearcher providers
videosearcher channels
```

Depois copie o arquivo de variáveis:

```bash
cp .env.example .env
```

---

## Cadastro das LLMs

A LLM é usada numa etapa só: transformar cada bloco do roteiro num **briefing visual** (intenção, era, estética, e as consultas de busca já traduzidas para o vocabulário de banco de mídia).

### Quanto isso custa

Um vídeo de 100 blocos consome **~25 mil tokens**. Mesmo produzindo 3 vídeos por dia, são ~75 mil tokens/dia. Isso cabe folgado em free tier — **a expectativa é gastar R$ 0**.

### Você não precisa cadastrar tudo

**Uma chave já faz o sistema rodar.** Se quiser o mínimo de esforço, cadastre só a primeira da lista abaixo e pule o resto.

### 1. Mistral — recomendado como principal

Tier **Experiment** gratuito, com cota alta. Melhor qualidade de briefing entre os provedores gratuitos testados.

1. Acesse **<https://console.mistral.ai>** e crie a conta
2. Menu lateral → **API Keys** → **Create new key**
3. Copie a chave e cole no `.env`:

```bash
MISTRAL_API_KEY=sua-chave-aqui
```

Modelo usado por padrão: **`ministral-14b-2512`**.

> ⚠️ **Pegadinha verificada na prática.** A família `mistral-small`, `mistral-medium` e `mistral-large` devolve **429 Rate limit exceeded** em conta gratuita, mesmo com a chave válida e a página de limites mostrando cota. O limite efetivo dessas variantes é zero no tier grátis.
>
> Os que funcionam de fato: `ministral-14b-2512`, `ministral-8b-2512`, `ministral-3b-2512` e `open-mistral-nemo`. Confira os seus em <https://admin.mistral.ai/plateforme/limits>.
>
> Como distinguir chave inválida de conta sem cota: `GET /v1/models` responde **200** quando a chave é boa. Se a inferência devolve 429 mas o `/v1/models` responde 200, o problema é cota de modelo, não autenticação.

### 2. Z.ai (GLM) — recomendado como segundo

`GLM-4.7-Flash` e `GLM-4.5-Flash` são **gratuitos na API de forma permanente**, não é trial. E existe o `GLM-4.6V-Flash`, um modelo de **visão** também gratuito — que vai ser usado na fase 5 para legendar keyframes do acervo histórico.

1. Acesse **<https://z.ai>**, crie a conta
2. Vá ao painel de API → gere a chave
3. No `.env`:

```bash
ZAI_API_KEY=sua-chave-aqui
```

### 3. Groq — o mais rápido, ótimo para testar

Free tier **sem cartão de crédito**, ~30 requisições/minuto, com teto diário por modelo. Roda a centenas de tokens por segundo: 100 blocos saem em segundos. É onde você deve iterar prompt.

1. Acesse **<https://console.groq.com/keys>**
2. Faça login (Google/GitHub serve) → **Create API Key**
3. No `.env`:

```bash
GROQ_API_KEY=sua-chave-aqui
```

Modelos: **`openai/gpt-oss-120b`** (melhor) e **`openai/gpt-oss-20b`** (mais rápido). São modelos de raciocínio, então precisam de folga de `max_tokens` — com orçamento apertado eles gastam tudo pensando e devolvem conteúdo vazio.

### 4. OpenRouter — a rede de segurança

Uma chave, 400+ modelos de 70+ fornecedores, API compatível com OpenAI. Modelos com sufixo **`:free`** custam zero. Detalhes na [seção própria](#openrouter-quando-e-como-usar).

1. Acesse **<https://openrouter.ai/settings/keys>**
2. Faça login → **Create Key**
3. No `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

### Opcionais

| Provedor | Onde cadastrar | Variável | Observação |
|---|---|---|---|
| **NVIDIA NIM** | <https://build.nvidia.com> | `NVIDIA_API_KEY` | 100+ modelos, sem cartão, cota de avaliação |
| **Cerebras** | <https://cloud.cerebras.ai> | `CEREBRAS_API_KEY` | Free tier, inferência muito rápida |
| **OpenAI** | <https://platform.openai.com/api-keys> | `OPENAI_API_KEY` | Pago. Melhor suporte a JSON Schema estrito |
| **Anthropic** | <https://console.anthropic.com/settings/keys> | `ANTHROPIC_API_KEY` | Pago. Melhor leitura de tom |

### Conferindo o cadastro

Dois comandos resolvem qualquer dúvida:

```bash
# quem existe, qual variável usa, onde cadastrar, e qual o tier grátis
videosearcher llm list

# testa de verdade cada elo da corrente, com chamada HTTP real
videosearcher llm check --canal guerra
```

O `llm check` faz um ping em cada provedor e mostra elo por elo:

```
┏━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ ordem ┃ provedor   ┃ modelo            ┃ tier ┃ estado ┃ detalhe           ┃
┡━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│     1 │ mistral    │ mistral-small-... │ free │   ✓    │ OK                │
│     2 │ zai        │ glm-4.7-flash     │ free │   ✗    │ ZAI_API_KEY não   │
│       │            │                   │      │        │ preenchida —      │
│       │            │                   │      │        │ cadastre em ...   │
└───────┴────────────┴───────────────────┴──────┴────────┴───────────────────┘

✓ Pronto. O briefing vai usar mistral/mistral-small-latest, com 0 elo(s) de reserva.
```

Quando a chave está errada, ele diz exatamente isso — inclusive a mensagem que o
provedor devolveu:

```
│  1 │ mistral │ ... │ free │ ✗ │ mistral: 401 — chave inválida em MISTRAL_API_KEY │
```

Use `--no-ping` para checar apenas se as variáveis estão preenchidas, sem gastar requisição.

### Qualidade medida com roteiro real

Comparação no mesmo trecho de um roteiro de história militar, pedindo briefing estruturado para 4 blocos:

| Provedor / modelo | Tempo | Qualidade observada |
|---|---|---|
| **mistral / ministral-14b-2512** | 4,6s | **Melhor.** Era histórica precisa (`1803-1815`), queries específicas do domínio (`baker rifle mechanism close up`, `rifle barrel spiral grooves historical`) |
| groq / gpt-oss-120b | 2,4s | Boa classificação de intenção, mas perdeu a era em um bloco e queries mais genéricas |
| groq / gpt-oss-20b | 1,4s | **3x mais rápido.** Queries rasas (`napoleonic troops`, `red lines`), errou uma intenção e trocou a cor de uma jaqueta no slug |

Por isso a corrente padrão é `ministral-14b` → `gpt-oss-120b` → `gpt-oss-20b`: qualidade primeiro, velocidade como reserva.

### Por que JSON Schema estrito não é opcional

O mesmo modelo, no mesmo prompt, com e sem `response_format: json_schema`:

```
COM schema estrito:  bloco 7  · bloco 10 · bloco 40 · bloco 95   ← números preservados
SEM schema (json_object):  bloco None · None · None · None        ← números perdidos
```

Sem o schema, o modelo devolveu uma lista na raiz em vez do objeto esperado e **descartou o `block_number` de todos os blocos**. O número do bloco é exatamente o que dá nome ao arquivo entregue (`004 - video ....mp4`), então perdê-lo inviabiliza a entrega.

É por isso que `ProviderSpec.supports_json_schema` existe: provedores que não aceitam schema estrito caem para `json_object` e precisam de validação e reparo no consumidor.

### Ressalvas honestas

1. **Free tier normalmente treina no seu dado.** No seu caso é irrelevante: são roteiros que vão ser publicados de qualquer forma. Só evite se o pipeline passar a processar algo confidencial.
2. **Free tiers morrem.** É por isso que a corrente tem vários elos: quando um cai, a produção continua.
3. **Não crie múltiplas contas para furar limite.** Viola os termos de todos, e a OpenRouter afirma governar capacidade globalmente — chave extra não aumenta nada.

---

## Como funciona a corrente de fallback

A LLM não é uma escolha fixa no código. Cada canal declara uma **corrente**, tentada em ordem:

```yaml
# channels/_base.yaml
llm:
  chain:
    - { provider: mistral,    model: mistral-small-latest,  tier: free }
    - { provider: zai,        model: glm-4.7-flash,         tier: free }
    - { provider: groq,       model: openai/gpt-oss-20b,    tier: free }
    - { provider: openrouter, model: z-ai/glm-4.5-air:free, tier: free }
  batch_size: 20
  cache_prompt: true
  temperature: 0.2
  on_rate_limit: next_in_chain
  on_quota_exhausted: next_in_chain
```

Qualquer um destes eventos faz o próximo elo assumir, sem interromper a produção:

| Situação | HTTP | Ação |
|---|---|---|
| Variável de ambiente vazia | — | pula |
| Chave inválida | 401 | pula |
| Limite de taxa | 429 | pula |
| Cota/crédito esgotado | 402, 403 | pula |
| Provedor fora do ar ou timeout | 5xx | pula |

Só quando **todos** falham o pipeline para — e aí ele imprime o motivo de cada elo.

**Canal diferente pode usar modelo diferente.** Basta sobrescrever `llm` no YAML do canal:

```yaml
# channels/guerra.yaml — canal que exige nuance de tom
llm:
  chain:
    - { provider: openrouter, model: anthropic/claude-haiku-4.5, tier: paid }
    - { provider: mistral,    model: mistral-small-latest,        tier: free }
```

---

## OpenRouter: quando e como usar

### Você precisa dele?

**Não é obrigatório.** Mistral ou Z.ai sozinhos já rodam o sistema. Mas o OpenRouter resolve três problemas de uma vez, e por isso é o elo final recomendado.

### O que ele resolve

1. **Acesso a modelo que não tem free tier.** Claude e GPT não dão nada de graça. Pelo OpenRouter você usa os dois com a mesma chave, sem abrir conta na Anthropic nem na OpenAI.
2. **Comparar modelos trocando uma string.** `anthropic/claude-haiku-4.5`, `openai/gpt-5.4-nano`, `z-ai/glm-5.3-flash` — mesmo endpoint, mesmo código.
3. **Fallback quando um fornecedor cai.** Ele roteia entre provedores do mesmo modelo automaticamente.

### Configurando

```bash
# .env
OPENROUTER_API_KEY=sk-or-v1-...

# opcional: identifica seu app nos rankings públicos deles
OPENROUTER_APP_URL=https://github.com/willdarkface/videosearcher
OPENROUTER_APP_TITLE=videosearcher
```

### Formato do nome do modelo

Sempre `fornecedor/modelo`, e o sufixo `:free` indica a variante gratuita:

```yaml
- { provider: openrouter, model: z-ai/glm-4.5-air:free,       tier: free }  # R$ 0
- { provider: openrouter, model: anthropic/claude-haiku-4.5,  tier: paid }
- { provider: openrouter, model: openai/gpt-5.4-nano,         tier: paid }
```

O catálogo de modelos `:free` muda com frequência. Confira em <https://openrouter.ai/models?max_price=0> e ajuste o YAML.

### Os limites dos modelos gratuitos

| Condição | Limite |
|---|---|
| Conta sem nenhuma compra | 20 req/min e **50 req/dia** |
| Depois de comprar **US$ 10 em créditos, uma vez** | 20 req/min e **1.000 req/dia** |

Um vídeo de 100 blocos = 5 requisições. Então: **10 vídeos/dia de graça**, ou **200 vídeos/dia** depois do aporte único de US$ 10.

> Esses US$ 10 não são mensalidade, são saldo. Eles destravam o limite dos modelos gratuitos **e** ficam disponíveis para você testar qualquer modelo pago. É o melhor investimento único do projeto — e continua opcional.

---

## Uso

### Segmentar uma legenda em blocos

```bash
videosearcher blocks examples/exemplo-guerra.srt --canal guerra
```

```
exemplo-guerra.srt · canal Guerra · 13 cues → 5 blocos

┏━━━┳━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ # ┃ início ┃ fim  ┃  dur ┃ texto                                           ┃
┡━━━╇━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1 │ 0.0    │ 8.6  │ 8.6s │ No inverno de 1942, o exército alemão avançava…  │
│ 2 │ 9.2    │ 18.3 │ 9.1s │ As temperaturas caíram para quarenta graus…      │
│ 3 │ 19.0   │ 28.9 │ 9.9s │ A logística havia falhado. Os comboios de…       │
│ 4 │ 29.5   │ 39.4 │ 9.9s │ Era uma ordem impossível de cumprir. E a…        │
│ 5 │ 40.0   │ 43.8 │ 3.8s │ O que aconteceu nos meses seguintes mudaria o…   │
└───┴────────┴──────┴──────┴─────────────────────────────────────────────────┘

Estatísticas: blocos=5 · duracao_media_s=8.26 · duracao_min_s=3.8 · duracao_max_s=9.9
```

O **mesmo arquivo** em outro canal produz outra segmentação, porque a duração de bloco é configurável por canal:

```bash
videosearcher blocks examples/exemplo-guerra.srt --canal fitness      # 3–7s  → 8 blocos
videosearcher blocks examples/exemplo-guerra.srt --canal espiritual   # 6–12s → 4 blocos
```

Há também um exemplo em VTT, que exercita as partes chatas do formato:

```bash
videosearcher blocks examples/exemplo-fitness.vtt --canal fitness
```

Opções:

| Flag | Efeito |
|---|---|
| `--canal`, `-c` | Slug do pack de canal (padrão: `_base`) |
| `--limite`, `-n` | Mostra só os N primeiros blocos |
| `--json ARQUIVO` | Grava blocos e estatísticas em JSON |

### Gerar o briefing visual de cada bloco

```bash
videosearcher briefs examples/baker-rifle.srt --canal armas
```

```
 #   dur   intenção   era        look  query principal                    slug
003  9.0s  arquivo    1809-1809  bw    Baker rifle single shot kill       rifle-baker-tiro-unico
004  6.9s  arquivo    1815-1815  bw    Waterloo farmhouse British sol…    fazenda-waterloo-defesa
005  6.9s  metaforico —          cor   genius vs mistake military dec…    genialidade-ou-erro

Resumo
  intenções: metaforico=69 · literal=28 · arquivo=11 · retrato=4 · grafico=2
  com era histórica: 38/114 · com query de arquivo: 81 · sensíveis: 17
  lotes: 6 · 6/6 do cache (100%) · provedores: só cache
```

| Flag | Efeito |
|---|---|
| `--canal`, `-c` | Pack de canal (obrigatório: define vocabulário e estética) |
| `--tema` | Tema do vídeo. Por padrão infere da abertura do roteiro |
| `--limite`, `-n` | Processa só os N primeiros blocos — use ao ajustar o prompt |
| `--sem-cache` | Ignora o cache e força chamada nova |
| `--json ARQUIVO` | Grava todos os briefs em JSON |

**Cache:** a resposta é gravada em `.cache/llm/` com chave por hash de prompt + modelo. Reprocessar o mesmo roteiro custa **0,3s e zero cota**. Mudar o prompt invalida o cache automaticamente, então não há risco de continuar servindo resposta velha.

**Robustez:** o pipeline nunca deixa bloco órfão. Se o lote volta incompleto, os blocos faltantes são reprocessados isoladamente. Se a corrente de LLM falha, o lote é dividido ao meio e tentado de novo. Em último caso, um brief de emergência é montado a partir do texto do bloco, e o aviso aparece no relatório.

### Onde ficam prompt e schema

`videosearcher/script/prompt.py` — separado do motor de propósito, porque ajustar prompt é a atividade mais frequente e não deveria exigir mexer em rede, cache ou validação.

Ao mudar o prompt de forma incompatível, incremente `VERSAO_PROMPT` no mesmo arquivo: isso invalida o cache de todo mundo.

Como o prompt é medido contra roteiro real — números de uma iteração que melhorou duas regras:

| Métrica | Antes | Depois |
|---|---|---|
| `era` preenchida mas `intent: metaforico` (contradição) | 48 (42%) | **2 (2%)** |
| Blocos marcados só como foto, sem vídeo | 100 (88%) | **19 (17%)** |
| Blocos que aceitam vídeo | 14 (12%) | **95 (83%)** |
| `look: painting` (época pré-fotografia) | 0 | **17** |
| `motion: still` | 88 | 24 |

As duas correções foram: (1) regra de coerência dizendo que `era` preenchida implica fato histórico concreto, logo `intent` não deveria ser metáfora; (2) aviso explícito de que **época antiga não significa foto** — existe vídeo moderno de reconstituição, close de mecanismo, neve, fumaça e paisagem.

### Todos os comandos

```bash
videosearcher version              # versão
videosearcher providers            # provedores de mídia + capabilities + chaves
videosearcher channels             # packs de canal disponíveis
videosearcher blocks LEGENDA       # fase 1: legenda → blocos
videosearcher briefs LEGENDA -c X  # fase 2: blocos → briefing visual por LLM
videosearcher llm list             # provedores de LLM, variáveis e onde cadastrar
videosearcher llm check            # testa a corrente de LLM elo por elo
```

### Formatos de legenda aceitos

`.srt` e `.vtt`. O parser é tolerante a BOM, CRLF, arquivo em Latin-1, índice ausente, blocos `NOTE`/`STYLE` do VTT, timestamps sem hora (`MM:SS.mmm`), tags inline (`<i>`, `<c.yellow>`), overrides de estilo (`{\an8}`), entidades HTML (`&amp;`) e travessão de diálogo.

---

## Packs de canal

Você tem vários nichos e vai criar mais. Nenhuma regra de nicho vive no código: **um canal é um arquivo YAML**. Criar canal novo = copiar um arquivo.

Já vêm prontos: `guerra`, `armas`, `militar`, `fitness`, `saude`, `religioso`, `espiritual`.

```yaml
# channels/guerra.yaml
extends: _base
nome: "Guerra"

provedores:
  prioridade: [internet_archive, pexels, pixabay]   # arquivo primeiro
  pesos:
    internet_archive: 1.4
    pexels: 0.6

estetica:
  look_padrao: bw_archival    # preto e branco de época como padrão
  aceita_4x3: true            # acervo de época vem em 4:3 e aqui isso é desejável
  grao_permitido: true

briefing:
  intent_padrao: arquivo
  vocabulario: |
    newsreel, war footage, troops marching, armored column, panzer,
    artillery barrage, trench warfare, supply convoy, bomber formation.
    Nomes de operação, unidade e cidade aumentam muito a precisão.

politica:
  sensitivity_maxima: sensitive   # material forte, sem corpos ou ferimentos
  licencas_proibidas: [cc-by-sa]  # evita licença viral

entrega:
  duracao_bloco: [4, 10]
  resolucao_minima: 480           # muito acervo de época só existe em SD
  dividir_por_frase: true         # quebra cue longa em frases antes de agrupar
  duracao_minima_unidade_s: 0.6   # funde fragmento curto ("Right?") no vizinho
```

> **Sobre `dividir_por_frase`:** a cue da legenda não é a unidade visual. Uma cue
> de 8 segundos pode conter sete beats ("Long red lines. Men shoulder to
> shoulder. Smoke everywhere. Right?"). Sem a divisão, o blocker é obrigado a
> cortar na fronteira da legenda e às vezes estoura a duração máxima do canal.
> Com ela, o corte cai na fronteira de ideia e o teto é respeitado. O timecode de
> cada frase é interpolado proporcionalmente ao número de caracteres.

### Regra de duração: o asset se adapta ao bloco

Os blocos têm **duração variável** — é a legenda que manda, e o sistema se adapta a ela. Não existe tentativa de forçar o bloco a caber num clipe.

```yaml
midia:
  video_deve_cobrir_bloco: true      # vídeo precisa durar ≥ o bloco
  tolerancia_cobertura_s: 0.0        # nenhuma folga negativa aceita
  fallback_para_imagem: true         # sem vídeo longo o bastante → imagem
  folga_relativa_maxima: 4.0         # clipe 4x mais longo perde nota, não é eliminado
  imagem_aspecto: "16:9"
  imagem_tolerancia_aspecto: 0.12    # desvio aceito sem crop
  permitir_crop_para_aspecto: true   # fora da tolerância, crop central
```

A lógica, em ordem:

| Situação | Decisão |
|---|---|
| Existe vídeo com duração **≥** o bloco | **Vídeo ganha**, com `trim`. Sempre preferido |
| Entre vídeos válidos | Vence o de **encaixe mais justo** — menos folga, menos arbitrariedade na escolha do trecho |
| Vídeo mais curto que o bloco | **Recusado**, sem exceção. Esticar degrada e loop aparece |
| Nenhum vídeo cobre o bloco | **Cai para imagem**, com `kenburns` — pan/zoom cobre qualquer duração |
| Imagem dentro da tolerância de 16:9 | Entra direto |
| Imagem fora de 16:9 | Entra por **crop central**, com nota proporcional à área mantida |
| Crop derrubaria a resolução abaixo do mínimo do canal | **Recusada** |
| Nada aprovado | Bloco vai para `_nao-encontrados.txt` |

Exemplos reais da regra rodando num bloco de 6,2s:

```
ESCOLHIDO  video  video-6.5s   nota 0.99  [trim]      cobre o bloco: 6.5s ≥ 6.2s (folga 0.3s)
alt 1      video  video-8s     nota 0.93  [trim]      cobre o bloco: 8.0s ≥ 6.2s (folga 1.8s)
alt 2      photo  foto-16x9    nota 1.00  [kenburns]  aspecto 1.78 dentro da tolerância
```

E num bloco de 9,0s onde nenhum vídeo alcança:

```
ESCOLHIDO  photo  foto-16x9    nota 1.00  [kenburns]  aspecto 1.78 dentro da tolerância
RECUSADO   video  video-8.9s               vídeo curto: 8.9s para bloco de 9.0s (faltam 0.1s)
RECUSADO   video  video-4s                 vídeo curto: 4.0s para bloco de 9.0s (faltam 5.0s)
```

Todo veredito carrega o motivo em texto, e o motivo vai para o `_manifest.csv` da entrega — é o que permite auditar por que um bloco recebeu foto em vez de vídeo.

O que cada seção controla:

| Seção | Efeito |
|---|---|
| `provedores` | Ordem e peso dos bancos. Canal militar joga Internet Archive na frente; fitness joga Pexels |
| `estetica` | `look_padrao` (`bw_archival`, `color_modern`, `sepia`, `any`), aceitar 4:3, permitir grão |
| `briefing` | **Vocabulário injetado no prompt** — o ativo que faz o LLM gerar query de stock boa em vez de tradução literal |
| `politica` | Teto de sensibilidade (filtro de desmonetização) e licenças banidas |
| `midia` | Cobertura de duração do vídeo, fallback para imagem, aspecto 16:9 e crop |
| `entrega` | Duração de bloco, resolução mínima, quantas alternativas por bloco |
| `llm` | Corrente de LLM específica daquele canal |

`extends: _base` herda tudo de `channels/_base.yaml` e você sobrescreve só o que muda. A herança é recursiva e faz merge profundo.

### Criar um canal novo

```bash
cp channels/fitness.yaml channels/meu-canal.yaml
# edite nome, vocabulário e prioridade de provedores
videosearcher channels                                  # aparece na lista
videosearcher blocks legenda.srt --canal meu-canal
```

### Deduplicação é por canal

O histórico de uso é filtrado por canal: o mesmo clipe de tanque pode aparecer em dois canais diferentes, mas nunca duas vezes no mesmo. É isso que torna N canais viável sem esgotar acervo.

---

## Adicionar um provedor de LLM

Todos os provedores suportados falam a API `/chat/completions` compatível com OpenAI, então **nenhum código novo é preciso**. Basta uma entrada em `videosearcher/llm/providers/specs.py`:

```python
SPECS["meuprovedor"] = ProviderSpec(
    name="meuprovedor",
    base_url="https://api.meuprovedor.com/v1",
    api_key_env="MEUPROVEDOR_API_KEY",
    default_model="modelo-rapido",
    signup_url="https://meuprovedor.com/signup",
    docs_url="https://meuprovedor.com/docs",
    free_tier="Descreva aqui o tier gratuito — aparece no `llm list`.",
    supports_json_schema=True,     # False se só aceitar {"type":"json_object"}
)
```

Depois use no YAML:

```yaml
llm:
  chain:
    - { provider: meuprovedor, model: modelo-rapido, tier: free }
```

`videosearcher llm check` já testa o novo elo, sem nenhuma outra alteração.

---

## Adicionar um provedor de mídia

Mesma filosofia: **um arquivo = um provedor**. O registry descobre sozinho.

```bash
cp videosearcher/providers/_template.py videosearcher/providers/storyblocks.py
```

```python
@register
class StoryblocksProvider(BaseProvider):
    name = "storyblocks"

    capabilities = Capabilities(
        media_types={MediaType.VIDEO, MediaType.PHOTO},
        content_kind={ContentKind.BROLL},
        license_default="storyblocks-individual",
        attribution_required=False,
        needs_subclip=False,
        cost_per_asset=0.0,
        api_key_env="STORYBLOCKS_API_KEY",
    )

    def accepts(self, brief: VisualBrief) -> bool:
        """Decide se vale gastar cota com este brief. É aqui que o roteamento acontece."""
        if brief.intent is Intent.ARQUIVO:
            return False
        return super().accepts(brief)

    def search(self, brief, limit=20): ...
    def normalize(self, raw): ...
    def download(self, asset, dest): ...
```

Pronto — aparece em `videosearcher providers` e entra no roteamento. Nada mais no sistema muda.

O `accepts()` é o coração do plug-and-play. Exemplo real: `PexelsProvider.accepts()` devolve `False` quando `brief.intent == "arquivo"` ou há `era` definida, então um bloco sobre 1943 nunca gasta cota no Pexels.

---

## Arquitetura

```
legenda.srt
   │
① INGESTÃO          parse SRT/VTT → cues com timecode          ✅ fase 1
② SEGMENTAÇÃO       cues → blocos visuais de N segundos        ✅ fase 1
③ BRIEFING (LLM)    bloco → intenção, era, estética, queries   ⏳ fase 2
④ PROVEDORES        brief → adaptadores compatíveis, paralelo  🔌 plug-and-play
⑤ NORMALIZAÇÃO      respostas heterogêneas → schema Asset      ✅ modelo pronto
⑥ RANQUEAMENTO      metadados (barato) → visual (caro)         ⏳ fases 3 e 7
⑦ AQUISIÇÃO         download, sub-clipe, ffmpeg, Ken Burns     ⏳ fases 4 e 5
⑧ ENTREGA           pasta numerada + manifest + créditos       ⏳ fase 3
```

```
videosearcher/
├── core/
│   ├── models.py       Cue, Block, VisualBrief, Asset, Match
│   ├── provider.py     Protocol + Capabilities + BaseProvider
│   ├── registry.py     descoberta automática e roteamento por accepts()
│   ├── config.py       packs de canal com herança (extends)
│   └── quota.py        rate limit por provedor, com persistência
├── llm/
│   ├── base.py         cliente compatível com OpenAI + taxonomia de erros
│   ├── chain.py        corrente de fallback
│   └── providers/
│       └── specs.py    catálogo de LLMs — adicionar = 1 entrada
├── script/
│   ├── parser.py       SRT/VTT tolerante
│   └── blocker.py      segmentação em blocos visuais
├── providers/          1 arquivo = 1 banco de mídia
│   ├── pexels.py  pixabay.py  internet_archive.py
│   └── _template.py    esqueleto comentado para o próximo
└── cli.py
channels/               1 arquivo = 1 canal/nicho
docs/                   pesquisa de fontes e plano de desenvolvimento
```

### Por que catálogo local

A partir da fase 3, toda busca alimenta um banco SQLite local. Na segunda vez o sistema consulta o **seu** acervo antes de bater em qualquer API. Isso resolve de graça a exigência de cache de 24h do Pixabay, guarda o histórico que impede repetir clipe, e tem efeito composto: no vídeo 30 a maioria dos blocos resolve offline, sem gastar cota.

---

## Roadmap

Próximo passo é a **fase 2**: o briefing visual. O prompt é o ativo mais valioso do projeto — é o que decide se o bloco "a economia entrou em colapso" vira um gráfico genérico ou uma fila de pão dos anos 30.

Documentação de apoio:

- [`docs/mapeamento-fontes-video.md`](docs/mapeamento-fontes-video.md) — todos os bancos gratuitos, acervos de domínio público, assinaturas ilimitadas e IAs de geração, com licença, API e custo
- [`docs/plano-desenvolvimento.md`](docs/plano-desenvolvimento.md) — arquitetura completa das 8 camadas e das 8 fases
- [`docs/opcoes-llm.md`](docs/opcoes-llm.md) — comparativo de 10 LLMs com custo por vídeo, e o anexo de opções 100% gratuitas

---

## Licença

MIT
