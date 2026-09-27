# Mapeamento de fontes de vídeo para pipeline faceless (set/2026)

Levantamento feito antes de desenhar a automação de casamento "trecho do roteiro ↔ clipe".
Conteúdo reescrito/resumido a partir das fontes citadas, para conformidade com licenciamento.

---

## 1. Bancos gratuitos COM API (base da automação)

| Fonte | Acervo | API | Limite | Licença | Observação |
|---|---|---|---|---|---|
| **Pexels** | ~150 mil vídeos, até 4K | Sim, oficial e gratuita | 200 req/hora e 20.000 req/mês; limite pode ser **removido de graça** se o caso de uso for aprovado e houver atribuição | Uso comercial livre, sem atribuição obrigatória | Melhor relação qualidade/API do mercado grátis |
| **Pixabay** | 5,8 M+ imagens e vídeos | Sim, oficial e gratuita | ~100 req/60s; **exige cache de 24h dos resultados** | Licença própria, comercial ok | Headers de rate limit e 429 padrão |
| **Coverr** | Curado, "não parece stock" + mídia gerada por IA | Sim, oficial (e servidor MCP) | Chave grátis: 50 req/hora | Grátis para uso comercial | Acervo pequeno, mas estético |
| **Mixkit** (Envato) | Clipes, música, SFX, templates | Não | — | Licença própria grátis, sem watermark | Só download manual |
| **Videvo** | 50 mil+ clipes grátis p/ usuário free | Não pública | — | ⚠️ Parte do acervo grátis **exige atribuição**; plano Premium converte para royalty-free | Cuidado em pipeline automático |
| **Videezy / Vecteezy** | Médio | Não | — | ⚠️ Coleção "Free" **exige atribuição** obrigatória | Só usar se o pipeline gerar os créditos |
| **Openverse** | CC/domínio público | Sim | Generoso | CC variadas | ❌ **Busca só imagens e áudio**; vídeo apenas via "External Sources" — não serve |
| **Pond5 Free + Public Domain Project** | Coleção grátis + acervo marcado como domínio público | Não | — | Free Collection + PD | Bom para arquivo histórico |

Fontes: [Pexels API](https://www.pexels.com/api/) · [limites Pexels](https://pexels.com/api/documentation) · [Pixabay API docs](https://pixabay.com/api/docs/) · [Coverr developers](https://www.coverr.co/developers) · [Coverr API start](https://api.coverr.co/docs/start/) · [Videvo](https://www.videvo.net/) · [Videezy license](https://support.videezy.com/en_us/videezy-standard-license-and-usage-HylDtxsDK) · [Vecteezy licensing](https://www.vecteezy.com/licensing) · [Openverse about](https://openverse.org/lug/about) · [Pond5 PD Project](https://help.pond5.com/hc/en-us/articles/203320459-What-Is-The-Pond5-Public-Domain-Project-)

---

## 2. Acervos de arquivo / domínio público — **essencial para guerra, história, ciência**

Este é o ponto crítico: Pexels e Pixabay **não têm** imagens reais de guerra, conflito, eventos históricos ou registros de época. Quem tem são os arquivos públicos, e quase todos são programáveis.

| Fonte | O que tem | Acesso programático | Licença |
|---|---|---|---|
| **Internet Archive** | Milhões de itens: `usgovfilms`, `Fedflix`, `wwii-nat-archives-videos`, `wwIIarchive`, Prelinger, coleções de notícias (inclui Iraque/Oriente Médio) | **Advanced Search API** + **Metadata API** + CLI `ia` + lib Python `internetarchive` (search/download) | Maioria domínio público; conferir item por item |
| **NARA — National Archives Catalog** | Filmes militares dos EUA, WWII, D-Day, treinamento, newsreels | **API v2 pública** + dataset completo no **AWS Open Data (S3)** | Obra do governo dos EUA → domínio público nos EUA |
| **Library of Congress** | Paper Print, George Kleine, Theodore Roosevelt collections, filmes do início do século | `loc.gov` com `?fo=json` | Grande parte PD |
| **Wikimedia Commons** | WebM/OGV, filmes PD (ex.: WWI 1918, Paris 1896-1900, Londres 1903) | API MediaWiki (search + imageinfo) | CC0/PD/CC-BY/CC-BY-SA → ⚠️ **rastrear licença e atribuição por arquivo** |
| **NASA Image & Video Library** | Espaço, ciência, Terra | `images-api.nasa.gov` | PD (com exceções de logotipo) |
| British Pathé / AP Archive / CriticalPast / Getty | Arquivo premium de guerra e notícias | Licenciamento pago por clipe | ❌ Fora do ilimitado |

Fontes: [IA Advanced Search](https://archive.org/help/aboutsearch.htm) · [IA Metadata API](https://archive.org/developers/metadata.html) · [lib Python IA](https://archive.org/developers/internetarchive/python-lib.html) · [NARA Catalog API](https://www.archives.gov/research/catalog/help/api) · [NARA dataset no AWS](https://www.archives.gov/developer/national-archives-catalog-dataset) · [NARA filmes WWII](https://www.archives.gov/research/motion-pictures/ww2) · [Commons:Video](https://commons.wikimedia.org/wiki/Commons:Video)

**Nota prática:** material de arquivo vem em 4:3, com grão, 24/25fps e telecine. Para shorts 9:16 isso vira vantagem estética (enquadramento com blur nas bordas, grão, letterbox), mas precisa de um passo de normalização no pipeline.

---

## 3. Assinaturas com **download ilimitado** (pago, sem contagem)

| Plataforma | Preço | O que entrega | API |
|---|---|---|---|
| **Storyblocks** | Essentials **US$21/mês** (anual) · **Unlimited All Access US$30/mês** · Small Business US$40 | Downloads ilimitados, 8K/4K, templates, música e SFX (do All Access pra cima), + AI Toolkit com 3.000/4.500/6.000 créditos/mês e **busca conversacional por IA** | Tem portal de developers/API, mas via parceria — não self-serve |
| **Envato Elements** | **Core US$16,50/mês** (anual, US$198/ano) | Stock ilimitado sujeito a *Fair Use Policy*, 29M+ assets, + 20 créditos IA/mês | ⚠️ A API oficial é do Envato **Market**, não do Elements; o fórum oficial indica que **automatizar downloads não é permitido**. APIs de terceiros "Envato downloader" são área cinza/violação |
| **Artgrid** | ~US$19,99–25/mês, **só cobrança anual** (custo adiantado alto) | Footage ilimitado, foco exclusivo em vídeo; Pro inclui RAW/LOG | Não |
| **Artlist Max** | ~US$33/mês | Footage + música + SFX + templates + ferramentas IA | Não |
| **Videvo Premium / Videezy Pro** | Barato | Remove atribuição e libera acervo premium | Não |

Fontes: [Storyblocks pricing](https://www.storyblocks.com/pricing) · [Storyblocks busca conversacional](https://www.storyblocks.com/ai/conv-search) · [Envato novos planos](https://elements.envato.com/learn/envato-new-plans-pricing-changes-explained) · [Envato fair use / AI Hub](https://elements.envato.com/ai/) · [Envato fórum sobre automação](https://forums.envato.com/t/using-envato-api-to-purchase-and-or-products/464296) · [review Artgrid](https://photutorial.com/artgrid-review/) · [Envato vs Storyblocks](https://photutorial.com/envato-vs-storyblocks/)

**Melhor custo/benefício desta categoria: Storyblocks Unlimited All Access (US$30/mês)** — ilimitado de verdade, acervo grande, busca semântica nativa e licença limpa para YouTube monetizado.

---

## 4. IAs de vídeo com plano "ilimitado" — estado em setembro/2026

Resumo do levantamento de planos (revisão de 11/set/2026). **"Ilimitado" nunca é ilimitado**: o limite muda de lugar — fila lenta, lista fechada de modelos, teto de resolução, janela de tempo ou só o 1º ano.

| Plataforma | O que chamam de ilimitado | Limite real | Preço |
|---|---|---|---|
| **Magnific / Freepik** ⭐ | Ilimitado o ano todo na cobrança anual | Lista nomeada (Kling 2.5, Hailuo 2.3 Fast, Wan 2.2, Nano Banana 2, Seedream); resolução por tier | **Premium+ ~€25,50/mês** anual |
| **Higgsfield** | Set de 365 dias + janelas de 7 dias nos modelos novos + passes de marketplace | Fila padrão, **1 vídeo por vez**, só no site (MCP/CLI gastam crédito) | Plus US$49/mês (US$39 anual) |
| **Midjourney** | Relax mode sem data de fim | Fila lenta, 3 jobs simultâneos, **vídeo em SD**; HD consome Fast hours | Pro/Mega US$60 / US$120 (vídeo); Standard US$30 só imagem |
| **Hailuo (MiniMax)** | Vídeo ilimitado no plano Max | Só modelos Hailuo 1.0/2.0/2.3 (**não** o H3 novo), fila padrão | Max ~US$184/mês anual |
| **Adobe Firefly** | Ilimitado no **primeiro ano** | Depois de 12 meses cai para créditos; só web/mobile app | Pro US$19,99/mês |
| **Vidu** | Ilimitado off-peak no Max | Só na faixa fora de pico; pico consome crédito | Max US$79/mês anual |
| **Runway** | ❌ Plano Unlimited **aposentado** | Fechou para novos em 01/jun/2026, legado até 30/nov/2026; hoje só upscale 4K é ilimitado | Max US$76/mês anual |
| **Luma** | ❌ Nenhum | Tudo por segundo em crédito | Plus US$25/mês |

Fonte: [comparativo de planos ilimitados](https://higgsfield.ai/blog/best-unlimited-ai-video-generators) (blog de fornecedor — tratar preços como indicativos e confirmar no checkout) · [Freepik pricing](https://www.freepik.com/pricing) · [Hailuo/MiniMax pricing](https://felloai.com/fr/minimax-pricing/) · [Luma pricing](https://www.eesel.ai/blog/luma-ai-pricing)

### ⚠️ O furo fatal para automação
Em **praticamente todas** essas plataformas, o ilimitado vale **só dentro do site (web app)**. Via API, tudo volta a ser cobrado por segundo. Ou seja: nenhum desses planos ilimitados é automatizável de forma legítima. Servem para geração manual pontual, não para pipeline.

---

## 5. Self-host — o único "ilimitado" que é de fato automatizável

| Item | Dado |
|---|---|
| **Wan 2.2** (Alibaba) | Open source **Apache 2.0**, arquitetura MoE, 720p/24fps, T2V e I2V, roda em GPU de consumo, integra com ComfyUI |
| Custo em GPU alugada | RunPod ~US$0,30–1,00/hora (RTX 4090 ~US$0,69/h, A6000 ~US$0,89/h) |
| Custo por clipe | Vídeo de 10s leva 8–15 min → **~US$0,10–0,25 por clipe** |
| Pronto para API | RunPod tem **endpoints públicos serverless** para `wan-2-2-t2v` e `wan-2-2-i2v`; há repos Docker/serverless prontos |
| Alternativas | Wan 2.7, LTX-Video, e derivados no ComfyUI |

Fontes: [Wan2.2 no GitHub](https://github.com/Wan-Video/Wan2.2) · [RunPod Wan 2.2 T2V endpoint](https://docs.runpod.io/public-endpoints/models/wan-2-2-t2v) · [guia RunPod + ComfyUI](https://www.runpod.io/articles/guides/comfyui-wan-2-2) · [análise de custos](https://apatero.com/blog/wan-ai-server-costs-runpod-complete-analysis-2025)

Vantagem: custo por **hora de GPU**, não por geração. Sem fila, sem lista de modelos, chamável pela sua própria API, sem termo proibindo automação. É o substituto estrutural do Veo 3 no lower-priority lite.

---

## 6. Arquitetura de fontes recomendada (cascata de fallback)

```
Trecho do roteiro
  │
  ├─ Nível 1 (grátis, API, volume): Pexels → Pixabay → Coverr
  │     b-roll genérico: natureza, cidade, pessoas, tecnologia, abstrato
  │
  ├─ Nível 2 (grátis, API, arquivo): Internet Archive → NARA → LoC → Commons → NASA
  │     guerra, história, política, ciência, época, newsreel
  │
  ├─ Nível 3 (US$30/mês, ilimitado): Storyblocks
  │     quando o grátis não tem qualidade/especificidade, + música e SFX
  │
  └─ Nível 4 (~US$0,15/clipe): Wan 2.2 self-host na RunPod
        quando o clipe simplesmente não existe em nenhum acervo
```

**Custo de entrada: R$ 0.** Níveis 1 e 2 cobrem a maior parte do trabalho. Nível 3 entra quando o volume justificar; nível 4 entra quando a especificidade justificar.

---

## 7. Pontos de licenciamento a respeitar no pipeline

1. **Pixabay exige cache de 24h** dos resultados da API — o cache local já resolve isso por design.
2. **Pexels** não exige atribuição no vídeo final, mas o termo da API pede crédito visível na aplicação; para conseguir o limite ilimitado grátis, a atribuição é requisito.
3. **Videvo free, Videezy free e Vecteezy free exigem atribuição** — ou o pipeline gera automaticamente os créditos na descrição, ou essas fontes ficam fora.
4. **Wikimedia Commons** mistura CC0, PD, CC-BY e CC-BY-SA. A licença precisa ser gravada como metadado por clipe, e o pipeline deve emitir os créditos.
5. **Envato Elements**: automatizar download contraria os termos. Se assinar, usar manualmente.
6. **Marcas, pessoas e direitos de imagem** continuam valendo mesmo em conteúdo "grátis" — relevante em clipes com rostos e logos.
7. **Material de arquivo de guerra**: domínio público quanto a copyright ≠ aprovado para monetização no YouTube. Conteúdo gráfico gera desmonetização por diretriz de anunciante, independente da licença. Precisa de um filtro de sensibilidade no pipeline.

---

## 8. Prévia do problema real: o casamento trecho ↔ clipe

O gargalo não é achar fonte, é relevância. Busca por palavra-chave direto no trecho do roteiro (o que ferramentas tipo MoneyPrinterTurbo fazem) entrega clipe literal e errado — "a economia entrou em colapso" devolve vídeo de gráfico genérico.

O desenho que proponho, e que detalho no plano se você aprovar:

- **Catálogo local próprio** (não buscar ao vivo): ingestão das APIs → keyframes → caption por VLM barato → embedding → índice vetorial. O acervo vira *seu*, buscável por significado e cada vez melhor.
- **Decomposição do roteiro** em unidades visuais com intenção (literal / metafórica / arquivo / gráfico), não em palavras-chave.
- **Scorer híbrido**: similaridade semântica + regras duras (duração do trecho, orientação, movimento de câmera, tom/paleta, não repetir clipe no mesmo vídeo, banir clipes já usados nos últimos N vídeos).
- **Roteamento por tipo de trecho**: trecho histórico vai para o índice de arquivo; trecho abstrato vai para b-roll ou para geração.
- **Loop de aprendizado**: o que você aprova/rejeita realimenta o ranking.
