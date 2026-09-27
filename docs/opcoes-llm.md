# Opções de LLM para a camada de briefing (set/2026)

**Carga de trabalho real:** 100 blocos por vídeo, em lotes de 20 blocos por chamada = 5 chamadas.
Por vídeo: **~10k tokens de entrada + ~15k de saída**. Cálculos abaixo usam essa base e USD≈R$5,40.

⚠️ **Aviso de confiabilidade:** preços vêm de agregadores e das páginas dos fornecedores, e o nome dos modelos muda quase mensalmente. Divergências entre fontes existem. Confirme no painel do fornecedor antes de comprometer orçamento.

---

## Custo por vídeo — a conclusão que importa

| # | Modelo | Fornecedor | Entrada / Saída (US$/1M) | **Custo/vídeo** | 20 vídeos/mês |
|---|---|---|---|---|---|
| 1 | **GLM-5.3-Flash** | Z.ai | $0,075–0,08 / $0,25 | **R$ 0,025** | R$ 0,50 |
| 2 | **Amazon Nova Lite** | AWS Bedrock | $0,06 / $0,24 | **R$ 0,023** | R$ 0,46 |
| 3 | **Groq GPT-OSS-20B** | Groq | $0,075 / $0,30 | **R$ 0,028** | R$ 0,57 |
| 4 | **Qwen3.8-Flash** | Alibaba | $0,14–0,15 / $0,42–0,47 | **R$ 0,046** | R$ 0,93 |
| 5 | **Mistral Small 4** | Mistral | $0,15 / $0,60 | **R$ 0,057** | R$ 1,14 |
| 6 | **DeepSeek V4-Flash** | DeepSeek | $0,22 / $0,66 (off-peak) | **R$ 0,065** | R$ 1,31 |
| 7 | **GPT-5.4 nano** | OpenAI | $0,20 / $1,25 | **R$ 0,11** | R$ 2,25 |
| 8 | **Grok 4.3** | xAI | $1,25 / $2,50 | **R$ 0,27** | R$ 5,40 |
| 9 | **GPT-5.4 mini** | OpenAI | $0,75 / $4,50 | **R$ 0,40** | R$ 8,10 |
| 10 | **Claude Haiku 4.5** | Anthropic | $1,00 / $5,00 | **R$ 0,46** | R$ 9,18 |

**O mais caro da lista custa R$ 9/mês. O mais barato, R$ 0,50.** A diferença absoluta é de ~R$ 8,70 por mês — irrelevante. Portanto **preço não é o critério de decisão aqui**. O critério é qualidade do brief: português, aderência a JSON Schema e conhecimento de vocabulário militar/histórico.

---

## Detalhe de cada opção

### 1. GLM-5.3-Flash (Z.ai) — o mais barato credível
$0,075–0,08 in / $0,25 out, cached input $0,015. Contexto de 1M. API compatível com OpenAI.
✅ Preço quase nulo, contexto enorme (cabe a legenda inteira de contexto).
⚠️ Dados trafegam por infra chinesa. Português é bom, não excelente.

### 2. Amazon Nova Lite / Micro (Bedrock) — o piso absoluto
Lite $0,06/$0,24 · Micro $0,035/$0,14. **Bedrock tem batch com 50% de desconto.**
✅ Mais barato do mercado; se você já tem AWS, é zero atrito novo.
⚠️ Modelo mais fraco do lote em nuance e em raciocínio metafórico — justamente o que o brief exige. Setup de IAM/Bedrock é burocrático.

### 3. Groq (GPT-OSS-20B / 120B) — o mais rápido, com free tier
20B $0,075/$0,30 · 120B $0,15/$0,60. **Free tier sem cartão de crédito.**
✅ 800+ tokens/s no hardware LPU: 100 blocos saem em segundos, não minutos. Ótimo para iterar prompt.
✅ Dá pra validar a fase 2 inteira gastando R$ 0.
⚠️ Catálogo limitado a modelos abertos; rate limit no free tier.

### 4. Qwen3.8-Flash (Alibaba) — o melhor custo-benefício estrutural ⭐
~$0,14–0,15 in / $0,42–0,47 out, contexto 1M, **aceita texto, imagem e vídeo**.
✅ **O grande diferencial:** é multimodal. O mesmo fornecedor e a mesma chave servem para o briefing (texto) **e** para a legendagem de keyframes na indexação do catálogo (visão) — que é um passo obrigatório da fase 5/6 do seu pipeline. Um vendor, dois trabalhos.
✅ Qwen tem histórico forte em multilíngue.
⚠️ Infra chinesa; documentação às vezes confusa entre regiões.

### 5. Mistral Small 4 — a aposta europeia em português
$0,15/$0,60, batch ~$0,08/$0,30.
✅ Modelo europeu com treino forte em línguas latinas — português tende a sair mais natural que em modelos anglo-centrados ou chineses.
✅ GDPR, infra na UE, sem ressalva geopolítica.
⚠️ Menos "esperto" que nano/Haiku em raciocínio de intenção metafórica.

### 6. DeepSeek V4-Flash — o rei do desconto noturno
~$0,15–0,22 in / $0,60–0,66 out **off-peak**, dobrando no horário de pico. **Cache hit a $0,007/1M** — praticamente grátis para prompt repetido. 17h do dia têm 50% de desconto.
✅ Seu caso é batch assíncrono: rodar o briefing de madrugada corta metade do custo sem nenhum prejuízo.
✅ O cache hit quase zero casa perfeitamente com o seu padrão (prompt de sistema + vocabulário do canal são fixos).
⚠️ Preço mudou várias vezes em 2026; infra chinesa.

### 7. GPT-5.4 nano — melhor structured output do tier barato
$0,20 in / $1,25 out, **cached input $0,02** (10x mais barato).
✅ JSON Schema estrito é recurso de primeira classe na OpenAI — menos retrabalho de parse, que é exatamente o risco da camada de briefing.
✅ Ecossistema, SDK, docs e tooling maduros.
⚠️ Output 5x mais caro que os chineses (mas ainda R$ 0,11/vídeo).

### 8. Grok 4.3 (xAI) — forte em português
$1,25 in / $2,50 out, cached input $0,20. Output baratíssimo para o nível do modelo.
✅ O índice multilíngue da Artificial Analysis coloca Grok 4 entre os melhores em **português**.
✅ Razão output/input favorável para geração de JSON longo.
⚠️ Não é o barato; é o "bom em PT por preço médio".

### 9. GPT-5.4 mini — o degrau acima do nano
$0,75 in / $4,50 out (fontes divergem: há relato de $0,55/$2,20).
✅ Onde o nano erra intenção, o mini acerta. Ainda R$ 0,40/vídeo.
⚠️ Só vale se o nano demonstrar erro real nos seus testes. Não compre antes de medir.

### 10. Claude Haiku 4.5 (Anthropic) — o mais caro da lista, e ainda barato
$1,00 in / $5,00 out.
✅ Melhor aderência a schema complexo e melhor leitura de **tom** (`tone`, `look`, `sensitivity` são campos subjetivos do seu brief — é aí que modelo bom se paga).
✅ Prompt caching e batch API reduzem bem.
⚠️ 18x o preço do GLM Flash — o que em valor absoluto significa R$ 9/mês contra R$ 0,50.

---

## Bônus: a camada que torna a decisão reversível

**OpenRouter** — não é um LLM, é um roteador: uma chave, uma API compatível com OpenAI, 400+ modelos de 70+ fornecedores, com **structured outputs por JSON Schema**, fallback automático entre provedores e roteamento por preço. Cobra um spread pequeno sobre o preço do fornecedor.

Para o seu caso é a escolha arquitetural certa: você testa 5 modelos trocando **uma string** e nunca fica preso a um fornecedor. Se um cair no meio de um lote, o fallback assume.

**DeepInfra / Fireworks / Cerebras / Together** — hosts de modelos abertos. O mesmo peso pode variar ~9x de preço entre hosts (Llama 70B vai de ~$0,12 a ~$1,05/M). Se algum dia você padronizar num modelo aberto, é onde se compra barato.

---

## Recomendação

**Arquitetura (fecha agora):** o LLM entra como **adapter plugável**, igual aos provedores de mídia. Interface única `LLMProvider.brief(blocks, channel_config) -> list[VisualBrief]`, e o modelo é declarado no YAML do canal:

```yaml
# channels/guerra-ww2.yaml
llm:
  provider: openrouter
  model: anthropic/claude-haiku-4.5    # canal que exige nuance de tom
  batch_size: 20
  cache_prompt: true
```
```yaml
# channels/fitness.yaml
llm:
  provider: openrouter
  model: z-ai/glm-5.3-flash            # canal literal, não precisa de nuance
```

Consequência: **canal diferente pode usar modelo diferente**, e trocar é uma linha de config. Nenhuma decisão de modelo fica presa no código.

**Escolha prática (3 passos):**
1. **Desenvolver e iterar prompt no Groq free tier** — R$ 0, respostas em segundos, ciclo de tuning rapidíssimo.
2. **Bancada A/B na mesma legenda** com 3 candidatos: `GLM-5.3-Flash` (piso de preço), `Qwen3.8-Flash` (multimodal, serve pro captioning depois) e `Claude Haiku 4.5` (teto de qualidade). Comparar briefs lado a lado num canal de guerra (metáfora + vocabulário militar) e num de fitness (literal).
3. **Rodar o vencedor por canal.** Se o Haiku ganhar nos canais de guerra e espiritual, rode Haiku lá — R$ 9/mês não muda sua vida, e brief ruim custa horas de retrabalho manual.

**O que NÃO fazer:** otimizar por preço nesta camada. Economizar R$ 8/mês num brief pior significa dezenas de blocos errados por vídeo, e cada bloco errado é você caçando clipe na mão.

---

## Fontes
Preços e disponibilidade conferidos em: [OpenAI pricing](https://developers.openai.com/api/docs/pricing) · [anúncio GPT-5.4 mini/nano](https://community.openai.com/t/introducing-gpt-5-4-mini-and-nano-our-most-capable-small-models-yet/1377015) · [Anthropic/Claude](https://markaicode.com/pricing/anthropic-api-pricing/) · [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) · [DeepSeek off-peak](https://www.morphllm.com/deepseek-api) · [Z.ai pricing](https://docs.z.ai/guides/overview/pricing) · [GLM-5.3-Flash](https://www.eesel.ai/blog/glm-5-3-flash-pricing) · [Qwen pricing](https://developer.puter.com/tutorials/qwen-api-pricing/) · [Mistral pricing](https://docs.mistral.ai/inference/pricing) · [Mistral Small 4](https://www.cloudzero.com/blog/mistral-api-pricing/) · [Groq pricing](https://markaicode.com/pricing/groq-pricing/) · [Bedrock/Nova](https://www.cloudzero.com/blog/amazon-bedrock-pricing/) · [xAI pricing](https://docs.x.ai/developers/pricing) · [Grok rates](https://www.cloudzero.com/blog/grok-pricing/) · [OpenRouter structured outputs](https://www.openrouter.ai/docs/features/structured-outputs) · [Artificial Analysis — português](https://artificialanalysis.ai/models/multilingual/portuguese) · [comparativo de hosts](https://saturncloud.io/reports/inference-provider-comparison-report/)

Conteúdo parafraseado e resumido para conformidade com restrições de licenciamento.


---

# Anexo — Opções 100% gratuitas (set/2026)

**Sua necessidade real:** 100 blocos = 5 requisições e ~25k tokens por vídeo. Mesmo produzindo 3 vídeos por dia, são **15 requisições e 75k tokens/dia**. Isso cabe folgado em quase todo free tier do mercado.

| Opção | O que é grátis | Limite | Sua capacidade |
|---|---|---|---|
| **Mistral La Plateforme — tier Experiment** ⭐ | **Todos os modelos**, incluindo Mistral Large, a $0 | ~**1 bilhão de tokens/mês**, com RPS/TPM baixos | ~**40.000 vídeos/mês** |
| **Z.ai — modelos Flash gratuitos** ⭐ | `GLM-4.7-Flash`, `GLM-4.5-Flash` e **`GLM-4.6V-Flash` (visão)** são grátis na API, sem trial | Rate limit do fornecedor | Uso contínuo |
| **Groq free tier** | Todos os modelos, **sem cartão de crédito** | 30 req/min; por modelo: GPT-OSS ~200k tokens/dia · llama-3.1-8b 14.400 req e 500k tokens/dia · llama-3.3-70b 1.000 req e 100k tokens/dia | ~**8 vídeos/dia** no GPT-OSS |
| **NVIDIA NIM** | 100+ modelos (DeepSeek, Llama, Qwen, Nemotron, GLM), sem cartão, API compatível com OpenAI | Cotas de avaliação | Prototipagem e volume moderado |
| **Cerebras free** | Modelos abertos em hardware ultrarrápido | Fontes divergem: ~5 req/min e **1M tokens/dia** em 2 modelos, ou 30 RPM / 14.400 RPD | ~**40 vídeos/dia** |
| **Alibaba Model Studio (Qwen)** | Cota gratuita para conta nova | ~1M tokens por modelo por 90 dias; uma página oficial cita cota bem maior para novos usuários | Avaliação, não produção perpétua |
| **OpenRouter — modelos `:free`** | Catálogo rotativo de modelos gratuitos | 20 req/min e **50 req/dia**; sobe para **1.000 req/dia** após compra única de US$10 em créditos | 10 vídeos/dia → **200 vídeos/dia** com os US$10 |
| **Cloudflare Workers AI** | ~84 modelos hospedados | 10.000 "neurons"/dia, no plano Free e no Paid | Volume leve/moderado |
| **GitHub Models** | Modelos variados com sua conta GitHub | ~10–15 req/min, ~50–150 req/dia | Prototipagem |
| **Hugging Face Inference Providers** | Centenas de modelos, 18 provedores | US$ 0,10/mês de crédito na conta free | Só teste |

## As duas que resolvem de fato

**1. Mistral tier Experiment — a resposta mais direta.** Um bilhão de tokens por mês, de graça, com acesso a todos os modelos. Sua demanda é 25 mil tokens por vídeo. Você usaria 0,0025% da cota por vídeo. Os limites apertados são de **taxa** (requisições por segundo e tokens por minuto), não de volume — e o seu briefing é batch assíncrono rodando em background, então taxa baixa não incomoda. Bônus: Mistral é modelo europeu com bom desempenho em línguas latinas, o que ajuda no português.

**2. Z.ai Flash gratuitos — incluindo visão.** `GLM-4.7-Flash` e `GLM-4.5-Flash` são gratuitos de forma permanente (não é trial), e existe **`GLM-4.6V-Flash`, um modelo de visão também gratuito**. Isso importa muito mais do que parece: a etapa que realmente consome tokens no seu pipeline não é o briefing, é a **legendagem de keyframes na indexação do catálogo** — um filme do Internet Archive rende ~150 sub-clipes, cada um pedindo uma caption. Ter modelo de visão grátis muda o custo dessa fase de "centavos por filme" para zero.

## Arquitetura: pool de free tiers com fallback

O `LLMProvider` que já está no plano resolve isso sem gambiarra. Mesma lógica do `quota.py` dos provedores de mídia:

```yaml
# channels/_base.yaml
llm:
  chain:                                  # ordem de tentativa
    - { provider: mistral,  model: mistral-small-latest, tier: free }
    - { provider: zai,      model: glm-4.7-flash,        tier: free }
    - { provider: groq,     model: openai/gpt-oss-20b,   tier: free }
    - { provider: openrouter, model: z-ai/glm-5.3-flash, tier: paid }   # rede de segurança
  batch_size: 20
  on_rate_limit: next_in_chain            # 429 → próximo da fila
  on_quota_exhausted: next_in_chain
```

Consequências práticas: o pipeline nunca para por 429, o custo tende a **R$ 0**, e o provedor pago existe só como rede de segurança que quase nunca é acionada. E trocar qualquer elo é editar YAML.

## Ressalvas honestas

1. **Free tier costuma treinar em cima do seu dado.** No seu caso isso é irrelevante — são roteiros de vídeo que vão ser publicados no YouTube de qualquer forma. Não há dado sensível. Só não use free tier se um dia o pipeline passar a processar algo confidencial.
2. **Free tiers morrem.** Exemplo concreto: o free tier do Qwen OAuth foi **descontinuado em 15/04/2026**. É por isso que a corrente de fallback com um elo pago no fim não é paranoia, é engenharia.
3. **Não crie múltiplas contas para furar limite.** Viola os termos de todos eles, e a OpenRouter afirma explicitamente que governa capacidade globalmente — chaves extras não aumentam nada. Existem repositórios ensinando rotação multi-conta; ignore, é caminho de banimento.
4. **Qualidade do tier grátis é menor** nos modelos pequenos. Vale medir: se `GLM-4.7-Flash` gratuito produzir brief tão bom quanto `Claude Haiku` nos seus canais, você economizou 100% do custo. Se não produzir, R$ 9/mês resolve. A bancada A/B da fase 2 responde isso com dado, não com palpite.

## Recomendação revisada

**Comece 100% grátis, e provavelmente fique.** A corrente:

1. **Mistral free (Experiment)** como principal — cota absurda para sua escala, bom em português.
2. **Z.ai GLM Flash grátis** como segundo, e o **GLM-4.6V-Flash grátis** para a legendagem de keyframes da fase 5/6.
3. **Groq free** como terceiro, e como bancada de iteração de prompt (respostas em segundos).
4. **US$ 10 únicos em crédito na OpenRouter** como seguro permanente — não é mensalidade, é saldo que destrava 1.000 req/dia nos modelos gratuitos e dá acesso a qualquer modelo pago se você precisar comparar.

Custo total esperado da camada de LLM: **R$ 0/mês**, com um único aporte opcional de ~R$ 55 uma vez na vida.

### Fontes do anexo
[Mistral free tier — anúncio](https://mistral.ai/news/september-24-release/) · [limites Mistral](https://help.mistral.ai/en/articles/698531-why-am-i-hitting-api-rate-limits-and-how-do-i-increase-them) · [cota do tier Experiment](https://pricepertoken.com/endpoints/mistral/free) · [GLM Flash gratuitos](https://felloai.com/glm-pricing/) · [detalhe dos modelos Z.ai](https://developer.puter.com/tutorials/zai-glm-api-pricing/) · [Groq free tier real](https://localaimaster.com/blog/groq-api-free-guide) · [docs de rate limit Groq](https://console.groq.com/docs/rate-limits) · [OpenRouter rate limits](https://openrouter.zendesk.com/hc/en-us/articles/39501163636379-OpenRouter-Rate-Limits-What-You-Need-to-Know) · [comparativo de free tiers](https://blogs.novita.ai/free-llm-api-comparison-2026/) · [NVIDIA NIM gratuito](https://sidsaladi.substack.com/p/free-llm-api-nvidia-nim) · [Cerebras rate limits](https://inference-docs.cerebras.ai/support/rate-limits) · [cota gratuita Qwen](https://markaicode.com/pricing/qwen-25-pricing/) · [descontinuação do free tier Qwen OAuth](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/)
