"""Repositório do catálogo: é a única parte que escreve no Postgres.

Concentrar o SQL aqui evita o pior defeito de arquitetura de worker: cada
serviço inventando seu próprio jeito de gravar, e o schema virando terra de
ninguém.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row


@dataclass
class FonteRegistro:
    provider: str
    provider_id: str
    titulo: str | None
    descricao: str | None
    source_page: str | None
    download_url: str | None
    duracao_s: float | None
    largura: int | None
    altura: int | None
    data_original: str | None
    licenca_id: str
    licenca_url: str | None
    licenca_verificada: bool
    licenca_motivo: str
    atribuicao: bool
    credito: str | None
    metadados: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClipeRegistro:
    tipo: str
    objeto: str
    keyframe: str | None
    inicio_s: float | None
    fim_s: float | None
    duracao_s: float
    largura: int
    altura: int
    fps: float | None
    bytes: int
    cena_id: int | None
    hash_visual: str | None
    look: str = "any"
    saturacao: float | None = None
    brilho: float | None = None
    movimento: str = "any"


def conectar(dsn: str) -> psycopg.Connection:
    conexao = psycopg.connect(dsn, autocommit=False, row_factory=dict_row)
    return conexao


def upsert_fonte(conexao: psycopg.Connection, fonte: FonteRegistro) -> int:
    """Grava a fonte e devolve o id. Reprocessar a mesma fonte atualiza em vez
    de duplicar — a chave natural é (provider, provider_id)."""
    sql = """
        INSERT INTO fontes (
            provider, provider_id, titulo, descricao, source_page, download_url,
            duracao_s, largura, altura, data_original,
            licenca_id, licenca_url, licenca_verificada, licenca_motivo,
            atribuicao, credito, metadados
        ) VALUES (
            %(provider)s, %(provider_id)s, %(titulo)s, %(descricao)s,
            %(source_page)s, %(download_url)s, %(duracao_s)s, %(largura)s,
            %(altura)s, %(data_original)s, %(licenca_id)s, %(licenca_url)s,
            %(licenca_verificada)s, %(licenca_motivo)s, %(atribuicao)s,
            %(credito)s, %(metadados)s
        )
        ON CONFLICT (provider, provider_id) DO UPDATE SET
            titulo = EXCLUDED.titulo,
            duracao_s = EXCLUDED.duracao_s,
            largura = EXCLUDED.largura,
            altura = EXCLUDED.altura,
            licenca_id = EXCLUDED.licenca_id,
            licenca_url = EXCLUDED.licenca_url,
            licenca_verificada = EXCLUDED.licenca_verificada,
            licenca_motivo = EXCLUDED.licenca_motivo,
            atribuicao = EXCLUDED.atribuicao,
            credito = EXCLUDED.credito,
            metadados = EXCLUDED.metadados
        RETURNING id
    """
    from psycopg.types.json import Jsonb

    dados = fonte.__dict__ | {"metadados": Jsonb(fonte.metadados)}
    with conexao.cursor() as cur:
        cur.execute(sql, dados)
        return cur.fetchone()["id"]


def hash_ja_existe(conexao: psycopg.Connection, hash_visual: str) -> bool:
    """Deduplicação: o mesmo clipe pode chegar por fontes diferentes."""
    if not hash_visual:
        return False
    with conexao.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM clipes WHERE hash_visual = %s LIMIT 1", (hash_visual,)
        )
        return cur.fetchone() is not None


def inserir_clipe(
    conexao: psycopg.Connection, fonte_id: int, clipe: ClipeRegistro
) -> int:
    """Insere clipe, atributos e o texto de busca inicial, numa transação só."""
    sql_clipe = """
        INSERT INTO clipes (
            fonte_id, tipo, objeto, keyframe, inicio_s, fim_s, duracao_s,
            largura, altura, fps, bytes, cena_id, hash_visual
        ) VALUES (
            %(fonte_id)s, %(tipo)s, %(objeto)s, %(keyframe)s, %(inicio_s)s,
            %(fim_s)s, %(duracao_s)s, %(largura)s, %(altura)s, %(fps)s,
            %(bytes)s, %(cena_id)s, %(hash_visual)s
        )
        RETURNING id
    """
    sql_atributos = """
        INSERT INTO atributos (clipe_id, look, saturacao, brilho, movimento)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (clipe_id) DO UPDATE SET
            look = EXCLUDED.look,
            saturacao = EXCLUDED.saturacao,
            brilho = EXCLUDED.brilho,
            movimento = EXCLUDED.movimento
    """
    with conexao.cursor() as cur:
        cur.execute(sql_clipe, {"fonte_id": fonte_id, **clipe.__dict__})
        clipe_id = cur.fetchone()["id"]
        cur.execute(
            sql_atributos,
            (clipe_id, clipe.look, clipe.saturacao, clipe.brilho, clipe.movimento),
        )
    return clipe_id


def registrar_texto_busca(
    conexao: psycopg.Connection, clipe_id: int, conteudo: str
) -> None:
    """Materializa o tsvector. Chamado de novo pelo classify quando a caption
    chega, porque aí o texto de busca fica muito melhor."""
    sql = """
        INSERT INTO busca_texto (clipe_id, conteudo, vetor)
        VALUES (%s, %s, to_tsvector('simple', %s))
        ON CONFLICT (clipe_id) DO UPDATE SET
            conteudo = EXCLUDED.conteudo,
            vetor = EXCLUDED.vetor
    """
    with conexao.cursor() as cur:
        cur.execute(sql, (clipe_id, conteudo, conteudo))


def adicionar_palavras(
    conexao: psycopg.Connection,
    clipe_id: int,
    termos: list[str],
    origem: str = "provedor",
    peso: float = 1.0,
) -> int:
    """Associa palavras-chave ao clipe, criando os termos que faltarem."""
    limpos = sorted({t.strip().lower() for t in termos if t and t.strip()})
    if not limpos:
        return 0
    with conexao.cursor() as cur:
        cur.executemany(
            "INSERT INTO palavras (termo) VALUES (%s) ON CONFLICT (termo) DO NOTHING",
            [(t,) for t in limpos],
        )
        cur.execute("SELECT id, termo FROM palavras WHERE termo = ANY(%s)", (limpos,))
        ids = [linha["id"] for linha in cur.fetchall()]
        cur.executemany(
            """INSERT INTO clipe_palavras (clipe_id, palavra_id, origem, peso)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (clipe_id, palavra_id, origem) DO UPDATE
               SET peso = EXCLUDED.peso""",
            [(clipe_id, pid, origem, peso) for pid in ids],
        )
    return len(ids)


def salvar_descricao(
    conexao: psycopg.Connection, clipe_id: int, caption: str, modelo: str
) -> None:
    sql = """
        INSERT INTO descricoes (clipe_id, caption, modelo)
        VALUES (%s, %s, %s)
        ON CONFLICT (clipe_id) DO UPDATE SET
            caption = EXCLUDED.caption,
            modelo = EXCLUDED.modelo,
            criado_em = now()
    """
    with conexao.cursor() as cur:
        cur.execute(sql, (clipe_id, caption, modelo))


def salvar_embedding(
    conexao: psycopg.Connection, clipe_id: int, vetor: list[float], modelo: str
) -> None:
    """Grava o vetor. O literal do pgvector é montado como texto porque evita
    depender do pacote `pgvector` no worker só para um cast."""
    from .embedding import para_literal_pgvector

    sql = """
        INSERT INTO embeddings (clipe_id, modelo, vetor)
        VALUES (%s, %s, %s::vector)
        ON CONFLICT (clipe_id) DO UPDATE SET
            vetor = EXCLUDED.vetor,
            modelo = EXCLUDED.modelo,
            criado_em = now()
    """
    with conexao.cursor() as cur:
        cur.execute(sql, (clipe_id, modelo, para_literal_pgvector(vetor)))


def atualizar_sensibilidade(
    conexao: psycopg.Connection, clipe_id: int, sensibilidade: str
) -> None:
    with conexao.cursor() as cur:
        cur.execute(
            """INSERT INTO atributos (clipe_id, sensibilidade)
               VALUES (%s, %s::sensibilidade)
               ON CONFLICT (clipe_id) DO UPDATE
               SET sensibilidade = EXCLUDED.sensibilidade""",
            (clipe_id, sensibilidade),
        )


def clipes_sem_classificacao(
    conexao: psycopg.Connection, limite: int = 50
) -> list[dict]:
    """Clipes que ainda não têm caption ou embedding.

    Serve de rede de segurança e de backfill: se a fila perder mensagem ou o
    worker cair no meio, isso reencontra o trabalho pendente sem depender de
    nada além do estado do banco.
    """
    sql = """
        SELECT c.id, c.objeto, c.keyframe, f.titulo, f.provider
        FROM clipes c
        JOIN fontes f ON f.id = c.fonte_id
        LEFT JOIN descricoes d ON d.clipe_id = c.id
        LEFT JOIN embeddings e ON e.clipe_id = c.id
        WHERE c.keyframe IS NOT NULL
          AND (d.clipe_id IS NULL OR e.clipe_id IS NULL)
        ORDER BY c.id
        LIMIT %s
    """
    with conexao.cursor() as cur:
        cur.execute(sql, (limite,))
        return [dict(linha) for linha in cur.fetchall()]


def remover_clipe(conexao: psycopg.Connection, clipe_id: int) -> str | None:
    """Remove o clipe e devolve a chave do objeto, para o chamador apagar o
    arquivo. Usado quando o modelo de visão confirma que o quadro é inútil."""
    with conexao.cursor() as cur:
        cur.execute("DELETE FROM clipes WHERE id = %s RETURNING objeto", (clipe_id,))
        linha = cur.fetchone()
        return linha["objeto"] if linha else None


def estatisticas(conexao: psycopg.Connection) -> dict[str, int]:
    sql = """
        SELECT
          (SELECT count(*) FROM fontes) AS fontes,
          (SELECT count(*) FROM fontes WHERE licenca_verificada) AS fontes_livres,
          (SELECT count(*) FROM clipes) AS clipes,
          (SELECT count(*) FROM clipes_usaveis) AS clipes_usaveis,
          (SELECT count(*) FROM descricoes) AS classificados,
          (SELECT count(*) FROM embeddings) AS com_embedding,
          (SELECT count(*) FROM palavras) AS palavras,
          (SELECT COALESCE(sum(bytes), 0) FROM clipes) AS bytes
    """
    with conexao.cursor() as cur:
        cur.execute(sql)
        # sum() do Postgres volta como Decimal, que não serializa em JSON.
        return {chave: int(valor) for chave, valor in cur.fetchone().items()}
