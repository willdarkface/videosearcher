# Arquitetura da plataforma

Decisões e o porquê de cada uma. O objetivo é milhares de arquivos, serviços
separados, processamento assíncrono e consumo de recurso baixo.

---

## Escolhas de tecnologia

| Camada | Escolha | Por quê |
|---|---|---|
| Banco | **PostgreSQL 17 + pgvector** | Escala de verdade, busca vetorial no mesmo banco (sem serviço extra), FTS nativo, particionamento quando crescer |
| Fila | **NATS 2 + JetStream** | Binário Go único, ~30 MB de RAM, fila durável com retry e ack. RabbitMQ carrega uma VM Erlang; Kafka é overkill; Redis não dá durabilidade boa de graça |
| BFF e busca | **Go 1.25** | Container de ~20 MB, RAM baixa, concorrência nativa. É onde o front bate, então latência importa |
| Processamento | **Python 3.11** | ffmpeg, PySceneDetect, modelos de visão e embedding vivem aqui. Reaproveita todo o código já escrito |
| Front | **Svelte + Vite, servido por Caddy** | Bundle pequeno, sem runtime Node em produção. Next.js exigiria manter um segundo runtime só para renderizar |
| Storage | Volume agora, **interface S3 desde já** | Passo 2 é storage: o código fala com uma interface, então trocar volume por S3/MinIO não toca regra de negócio |

### Por que não SQLite
Você está certo. SQLite trava em escrita concorrente, não tem busca vetorial
nativa madura, e replicar é gambiarra. Com milhares de clipes e workers
paralelos escrevendo, o gargalo aparece rápido.

### Por que Go e Python juntos, e não um só
Go sozinho significaria reescrever ffmpeg, detecção de cena e embedding — ou
chamar Python por subprocesso, que é pior que separar em serviço. Python sozinho
gastaria 10x mais RAM no BFF e na busca, que são justamente os caminhos quentes.
A fronteira é clara: **Go no que responde rápido, Python no que processa mídia.**

---

## Serviços

```
                        ┌──────────┐
                        │   web    │  Svelte estático + Caddy
                        │  :3000   │
                        └────┬─────┘
                             │ HTTP (só fala com o BFF)
                        ┌────▼─────┐
                        │   bff    │  Go — agrega, valida, autentica depois
                        │  :8080   │
                        └──┬───┬───┘
                 ┌─────────┘   └─────────┐
          ┌──────▼──────┐         ┌──────▼──────┐
          │   catalog   │         │  pipeline   │
          │     Go      │         │   Python    │
          │   :8081     │         │   :8082     │
          │ busca FTS + │         │ legenda →   │
          │  pgvector   │         │ blocos →    │
          └──────┬──────┘         │ briefs →    │
                 │                │ busca →     │
                 │                │ ranqueamento│
                 │                └──┬───────┬──┘
                 │                   │       │ publica jobs
                 │         ┌─────────▼───┐   │
                 │         │  postgres   │   │
                 │         │  17+pgvector│   │
                 │         │    :5432    │   │
                 │         └─────────────┘   │
                 │                           │
                 │                      ┌────▼─────┐
                 └──────────────────────│   nats   │  JetStream
                                        │  :4222   │
                                        └──┬───┬───┘
                            ┌──────────────┘   └─────────────┐
                     ┌──────▼──────┐                  ┌──────▼──────┐
                     │    media    │                  │  classify   │
                     │   Python    │                  │   Python    │
                     │ download,   │                  │ VLM caption,│
                     │ scenedetect,│                  │ palavras,   │
                     │ corte 4/6/8s│                  │ embedding   │
                     └─────────────┘                  └─────────────┘
```

O front **só** conhece o BFF. Isso mantém CORS, autenticação e versionamento num
lugar só, e permite quebrar os serviços internos sem tocar no front.

---

## Filas (NATS JetStream)

| Stream | Assunto | Consumidor | Trabalho |
|---|---|---|---|
| `INGEST` | `ingest.fonte` | media | Baixar item, detectar cena, cortar em 4/6/8s |
| `INGEST` | `ingest.clipe` | classify | Keyframe → caption, palavras-chave, embedding |
| `PROJETO` | `projeto.processar` | pipeline | Legenda → blocos → briefs → busca → ranqueamento |
| `PROJETO` | `projeto.entregar` | media | Baixar escolhidos, renomear, montar pasta |

Configuração dos streams: `WorkQueue`, `AckExplicit`, `MaxDeliver=4`,
`AckWait=30m` (corte de filme é demorado), backoff exponencial. Job que falha 4
vezes vai para `DLQ` e aparece no dashboard com o erro.

A tabela `jobs` no Postgres existe em paralelo à fila, para o front mostrar
progresso e histórico — a fila entrega trabalho, o banco conta a história.

---

## Orçamento de recursos

| Serviço | RAM típica | Imagem |
|---|---|---|
| postgres | 256 MB | ~450 MB |
| nats | 32 MB | ~20 MB |
| bff (Go) | 20 MB | ~25 MB |
| catalog (Go) | 25 MB | ~25 MB |
| pipeline (Python) | 200 MB | ~350 MB |
| media (Python + ffmpeg) | 300 MB | ~450 MB |
| classify (Python + embedding) | 1,2 GB | ~1,5 GB |
| web (Caddy + estático) | 15 MB | ~50 MB |
| **Total sem classify** | **~850 MB** | |
| **Total com classify** | **~2,1 GB** | |

O `classify` é o único pesado, por causa do modelo de embedding em memória.
Duas saídas se incomodar: rodar só quando há fila (`replicas: 0` e subir sob
demanda), ou usar embedding via API. Ele é o serviço que mais se beneficia de
escalar horizontal quando a base crescer.

---

## Escalabilidade

- **Workers são stateless.** Escalar é `docker compose up --scale media=4`. A
  fila distribui, o ack garante que ninguém processa duas vezes.
- **Postgres é o único stateful** nesta fase. Cresce vertical até doer, e aí
  entra réplica de leitura para o `catalog`, que é 90% leitura.
- **Storage sai do banco desde já.** Arquivo nunca vai para dentro do Postgres:
  o banco guarda o caminho, e o caminho hoje é volume, amanhã é bucket.
- **`clipes` vai a milhões.** Índices desenhados para isso: HNSW no vetor, GIN
  no tsvector, BRIN em `criado_em`, e particionamento por `provider` fica
  preparado mas não ativado — ativar antes de precisar só complica.

---

## Passo 2: storage

O código fala com `ObjectStore` (`put`, `get`, `url`, `delete`). Hoje a
implementação é disco no volume compartilhado. Amanhã é MinIO local ou S3/R2,
sem tocar em nenhuma regra. O campo `clipes.arquivo` já guarda chave de objeto,
não caminho absoluto, exatamente para essa troca ser transparente.
