-- =====================================================================
-- videosearcher — schema do catálogo
-- Postgres 17 + pgvector
--
-- Decisões estruturais:
--   * bigint identity como PK interna (menor, mais rápido em índice e join),
--     e uuid público para a API não expor sequência.
--   * arquivo NUNCA entra no banco: guardamos chave de objeto, porque o passo 2
--     troca volume por S3 e isso não pode virar migração de dados.
--   * licença é campo obrigatório com o MOTIVO da classificação gravado, para
--     ser possível reauditar a base inteira com uma query se algo for
--     contestado.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------
-- Tipos
-- ---------------------------------------------------------------------
CREATE TYPE tipo_midia     AS ENUM ('video', 'photo');
CREATE TYPE look_visual    AS ENUM ('any', 'bw_archival', 'painting', 'sepia', 'color_modern');
CREATE TYPE movimento      AS ENUM ('any', 'still', 'slow', 'fast');
CREATE TYPE sensibilidade  AS ENUM ('none', 'sensitive', 'graphic');
CREATE TYPE origem_palavra AS ENUM ('vlm', 'provedor', 'manual');
CREATE TYPE estado_job     AS ENUM ('pendente', 'processando', 'concluido', 'falhou', 'dlq');

-- ---------------------------------------------------------------------
-- fontes — o item original, antes de qualquer corte
-- ---------------------------------------------------------------------
CREATE TABLE fontes (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  uuid            UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
  provider        TEXT NOT NULL,
  provider_id     TEXT NOT NULL,
  titulo          TEXT,
  descricao       TEXT,
  source_page     TEXT,
  download_url    TEXT,
  duracao_s       DOUBLE PRECISION,
  largura         INTEGER,
  altura          INTEGER,
  data_original   TEXT,

  -- Licença. Ver videosearcher/core/licenca.py — livre só quando o metadado
  -- prova. `licenca_verificada = false` significa NÃO USAR comercialmente.
  licenca_id      TEXT NOT NULL,
  licenca_url     TEXT,
  licenca_verificada BOOLEAN NOT NULL,
  licenca_motivo  TEXT NOT NULL,
  atribuicao      BOOLEAN NOT NULL DEFAULT TRUE,
  credito         TEXT,

  metadados       JSONB NOT NULL DEFAULT '{}'::jsonb,
  ingerido_em     TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT fontes_provider_unico UNIQUE (provider, provider_id)
);

CREATE INDEX idx_fontes_licenca ON fontes (licenca_verificada, licenca_id);
CREATE INDEX idx_fontes_provider ON fontes (provider);
CREATE INDEX idx_fontes_ingerido ON fontes USING brin (ingerido_em);

COMMENT ON COLUMN fontes.licenca_motivo IS
  'Por que a licença foi classificada assim. Permite reauditar a base se uma '
  'licença for contestada.';

-- ---------------------------------------------------------------------
-- clipes — o ativo de verdade: pedaço utilizável de 4 a 8 segundos
-- ---------------------------------------------------------------------
CREATE TABLE clipes (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  uuid         UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
  fonte_id     BIGINT NOT NULL REFERENCES fontes(id) ON DELETE CASCADE,
  tipo         tipo_midia NOT NULL,

  -- Chave de objeto, não caminho absoluto: o passo 2 troca volume por bucket.
  objeto       TEXT NOT NULL,
  keyframe     TEXT,

  inicio_s     DOUBLE PRECISION,
  fim_s        DOUBLE PRECISION,
  duracao_s    DOUBLE PRECISION NOT NULL,
  largura      INTEGER NOT NULL,
  altura       INTEGER NOT NULL,
  fps          DOUBLE PRECISION,
  bytes        BIGINT,
  cena_id      INTEGER,

  -- pHash perceptual: impede o mesmo clipe entrar por duas fontes diferentes.
  hash_visual  TEXT,

  criado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT clipes_duracao_positiva CHECK (duracao_s > 0),
  CONSTRAINT clipes_dimensoes CHECK (largura > 0 AND altura > 0),
  CONSTRAINT clipes_intervalo CHECK (
    (inicio_s IS NULL AND fim_s IS NULL) OR (fim_s > inicio_s)
  )
);

CREATE INDEX idx_clipes_fonte ON clipes (fonte_id);
CREATE INDEX idx_clipes_tipo_duracao ON clipes (tipo, duracao_s);
CREATE INDEX idx_clipes_hash ON clipes (hash_visual) WHERE hash_visual IS NOT NULL;
CREATE INDEX idx_clipes_criado ON clipes USING brin (criado_em);

-- Aspecto como coluna gerada: a regra de 16:9 consulta isso direto.
ALTER TABLE clipes ADD COLUMN aspecto DOUBLE PRECISION
  GENERATED ALWAYS AS (largura::double precision / NULLIF(altura, 0)) STORED;
CREATE INDEX idx_clipes_aspecto ON clipes (aspecto);

-- ---------------------------------------------------------------------
-- descricoes — caption gerada por modelo de visão
-- ---------------------------------------------------------------------
CREATE TABLE descricoes (
  clipe_id   BIGINT PRIMARY KEY REFERENCES clipes(id) ON DELETE CASCADE,
  caption    TEXT NOT NULL,
  idioma     TEXT NOT NULL DEFAULT 'en',
  modelo     TEXT NOT NULL,
  criado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- palavras-chave, com origem rastreável
-- ---------------------------------------------------------------------
CREATE TABLE palavras (
  id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  termo TEXT NOT NULL UNIQUE
);
CREATE INDEX idx_palavras_trgm ON palavras USING gin (termo gin_trgm_ops);

CREATE TABLE clipe_palavras (
  clipe_id   BIGINT NOT NULL REFERENCES clipes(id) ON DELETE CASCADE,
  palavra_id BIGINT NOT NULL REFERENCES palavras(id) ON DELETE CASCADE,
  origem     origem_palavra NOT NULL,
  peso       REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (clipe_id, palavra_id, origem)
);
CREATE INDEX idx_clipe_palavras_palavra ON clipe_palavras (palavra_id);

COMMENT ON TABLE clipe_palavras IS
  'origem=manual vence automática no ranqueamento: correção sua nunca é '
  'sobrescrita por reclassificação.';

-- ---------------------------------------------------------------------
-- atributos — derivados por medição, não por adivinhação
-- ---------------------------------------------------------------------
CREATE TABLE atributos (
  clipe_id      BIGINT PRIMARY KEY REFERENCES clipes(id) ON DELETE CASCADE,
  look          look_visual NOT NULL DEFAULT 'any',
  saturacao     REAL,
  brilho        REAL,
  movimento     movimento NOT NULL DEFAULT 'any',
  sensibilidade sensibilidade NOT NULL DEFAULT 'none',
  tem_rosto     BOOLEAN,
  tem_texto     BOOLEAN,
  nitidez       REAL
);
CREATE INDEX idx_atributos_look ON atributos (look, sensibilidade);

COMMENT ON COLUMN atributos.saturacao IS
  'Medida no keyframe. É o que define look=bw_archival de verdade, em vez de '
  'confiar no palpite do LLM.';

-- ---------------------------------------------------------------------
-- busca textual — tsvector materializado
-- ---------------------------------------------------------------------
CREATE TABLE busca_texto (
  clipe_id BIGINT PRIMARY KEY REFERENCES clipes(id) ON DELETE CASCADE,
  conteudo TEXT NOT NULL,
  vetor    TSVECTOR NOT NULL
);
CREATE INDEX idx_busca_vetor ON busca_texto USING gin (vetor);

-- ---------------------------------------------------------------------
-- busca semântica — pgvector com HNSW
-- 768 dimensões = SigLIP base. Mudar de modelo exige nova coluna, não
-- alteração desta: embedding de modelos diferentes não é comparável.
-- ---------------------------------------------------------------------
CREATE TABLE embeddings (
  clipe_id  BIGINT PRIMARY KEY REFERENCES clipes(id) ON DELETE CASCADE,
  modelo    TEXT NOT NULL,
  vetor     vector(768) NOT NULL,
  criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_embeddings_hnsw ON embeddings
  USING hnsw (vetor vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- ---------------------------------------------------------------------
-- usos — histórico que impede repetir clipe no mesmo canal
-- ---------------------------------------------------------------------
CREATE TABLE usos (
  id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  clipe_id  BIGINT NOT NULL REFERENCES clipes(id) ON DELETE CASCADE,
  canal     TEXT NOT NULL,
  projeto   TEXT NOT NULL,
  bloco     INTEGER NOT NULL,
  aprovado  BOOLEAN,
  usado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_usos_canal_clipe ON usos (canal, clipe_id);
CREATE INDEX idx_usos_projeto ON usos (projeto);

COMMENT ON COLUMN usos.aprovado IS
  'NULL = ainda não revisado. false = você trocou por outro no dashboard, e '
  'isso é o sinal de treino do ranqueamento.';

-- ---------------------------------------------------------------------
-- projetos e blocos — o que o dashboard mostra
-- ---------------------------------------------------------------------
CREATE TABLE projetos (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  uuid          UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
  nome          TEXT NOT NULL,
  canal         TEXT NOT NULL,
  legenda_nome  TEXT,
  legenda_texto TEXT,
  config        JSONB NOT NULL DEFAULT '{}'::jsonb,
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
  atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_projetos_canal ON projetos (canal, criado_em DESC);

COMMENT ON COLUMN projetos.config IS
  'Inclui proporcao_video, duracao_bloco e resolucao_minima — os controles do '
  'dashboard. Guardado por projeto para a execução ser reproduzível.';

CREATE TABLE blocos (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  projeto_id  BIGINT NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
  numero      INTEGER NOT NULL,
  inicio_s    DOUBLE PRECISION NOT NULL,
  fim_s       DOUBLE PRECISION NOT NULL,
  texto       TEXT NOT NULL,
  brief       JSONB,
  clipe_id    BIGINT REFERENCES clipes(id) ON DELETE SET NULL,
  nota        REAL,
  motivo      TEXT,
  arquivo     TEXT,
  CONSTRAINT blocos_numero_unico UNIQUE (projeto_id, numero)
);
CREATE INDEX idx_blocos_projeto ON blocos (projeto_id, numero);
CREATE INDEX idx_blocos_sem_clipe ON blocos (projeto_id) WHERE clipe_id IS NULL;

-- Candidatos alternativos por bloco, para o botão de trocar no dashboard
CREATE TABLE bloco_candidatos (
  bloco_id  BIGINT NOT NULL REFERENCES blocos(id) ON DELETE CASCADE,
  clipe_id  BIGINT NOT NULL REFERENCES clipes(id) ON DELETE CASCADE,
  posicao   SMALLINT NOT NULL,
  nota      REAL NOT NULL,
  motivo    TEXT,
  PRIMARY KEY (bloco_id, clipe_id)
);
CREATE INDEX idx_candidatos_bloco ON bloco_candidatos (bloco_id, posicao);

-- ---------------------------------------------------------------------
-- jobs — a fila entrega trabalho, o banco conta a história
-- ---------------------------------------------------------------------
CREATE TABLE jobs (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  uuid         UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
  tipo         TEXT NOT NULL,
  assunto      TEXT NOT NULL,
  payload      JSONB NOT NULL,
  estado       estado_job NOT NULL DEFAULT 'pendente',
  tentativas   SMALLINT NOT NULL DEFAULT 0,
  erro         TEXT,
  progresso    SMALLINT NOT NULL DEFAULT 0,
  projeto_id   BIGINT REFERENCES projetos(id) ON DELETE CASCADE,
  criado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
  iniciado_em  TIMESTAMPTZ,
  concluido_em TIMESTAMPTZ
);
CREATE INDEX idx_jobs_estado ON jobs (estado, criado_em);
CREATE INDEX idx_jobs_projeto ON jobs (projeto_id, criado_em DESC);

-- ---------------------------------------------------------------------
-- Visão de conveniência: só clipe seguro para uso comercial
-- ---------------------------------------------------------------------
CREATE VIEW clipes_usaveis AS
SELECT c.*, f.provider, f.licenca_id, f.credito, f.atribuicao, f.source_page,
       f.data_original, a.look, a.movimento, a.sensibilidade, a.saturacao
FROM clipes c
JOIN fontes f ON f.id = c.fonte_id
LEFT JOIN atributos a ON a.clipe_id = c.id
WHERE f.licenca_verificada = TRUE
  AND f.licenca_id NOT IN ('unknown', 'nao-comercial', 'declarado-nao-verificado');

COMMENT ON VIEW clipes_usaveis IS
  'Toda busca do catálogo passa por aqui. Material de licença não comprovada '
  'fica no banco para auditoria, mas nunca chega ao ranqueamento.';
