"""Worker de classificação.

Transforma clipe cru em clipe **buscável**: caption em linguagem natural,
palavras-chave e embedding no mesmo espaço vetorial de texto e imagem.

Sem esta etapa o acervo existe mas não serve para nada — é pasta de arquivo sem
índice. Com ela, o ranqueamento passa a saber do que a imagem é, que é o
problema que sobrou das fases anteriores.

    python -m vsworker.cmd_classify --pendentes 50
    python -m vsworker.cmd_classify --fila
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field

import psycopg

from . import catalogo, vlm
from .ambiente import carregar_env
from .config import Config
from .embedding import Embedder
from .storage import DiscoLocal

log = logging.getLogger("vsworker.classify")


@dataclass
class ResultadoClassificacao:
    processados: int = 0
    classificados: int = 0
    descartados: int = 0
    falhas: list[str] = field(default_factory=list)

    def resumo(self) -> dict:
        return {
            "processados": self.processados,
            "classificados": self.classificados,
            "descartados_por_quadro_inutil": self.descartados,
            "falhas": self.falhas[:10],
        }


def classificar_clipe(
    clipe: dict,
    cfg: Config,
    conexao: psycopg.Connection,
    loja: DiscoLocal,
    embedder: Embedder,
    resultado: ResultadoClassificacao,
) -> None:
    """Classifica um clipe: visão, palavras, embedding e texto de busca."""
    clipe_id = clipe["id"]
    keyframe = loja.caminho_local(clipe["keyframe"])
    if not keyframe.exists():
        resultado.falhas.append(f"clipe {clipe_id}: keyframe ausente ({clipe['keyframe']})")
        return

    classificacao = vlm.classificar(
        keyframe, modelo=cfg.modelo_vlm or None
    )

    # O modelo confirma o que o dHash não pega: quadro borrado ou de transição,
    # que tem variação de pixel mas nenhum conteúdo aproveitável.
    if vlm.quadro_inutil(classificacao):
        objeto = catalogo.remover_clipe(conexao, clipe_id)
        conexao.commit()
        if objeto:
            loja.remover(objeto)
            loja.remover(clipe["keyframe"])
        resultado.descartados += 1
        log.info("clipe %d descartado: %s", clipe_id, classificacao.caption[:60])
        return

    vetor = embedder.de_imagem(keyframe)

    catalogo.salvar_descricao(conexao, clipe_id, classificacao.caption, classificacao.modelo)
    catalogo.adicionar_palavras(
        conexao, clipe_id, classificacao.palavras, origem="vlm", peso=1.0
    )
    catalogo.salvar_embedding(conexao, clipe_id, vetor, embedder.modelo)
    catalogo.atualizar_sensibilidade(conexao, clipe_id, classificacao.sensibilidade)

    # O texto de busca agora vem da caption e das palavras, não mais do título
    # da fonte. É a diferença entre buscar "soldiers marching snow" e só
    # conseguir achar pelo nome do arquivo original.
    texto = " ".join(filter(None, [classificacao.texto_busca, clipe.get("titulo")]))
    catalogo.registrar_texto_busca(conexao, clipe_id, texto)

    conexao.commit()
    resultado.classificados += 1
    log.info("clipe %d: %s", clipe_id, classificacao.caption[:70])


def processar_pendentes(limite: int, cfg: Config) -> ResultadoClassificacao:
    resultado = ResultadoClassificacao()
    loja = DiscoLocal(cfg.acervo_dir)
    embedder = Embedder(cfg.modelo_embedding)
    conexao = catalogo.conectar(cfg.dsn)
    try:
        pendentes = catalogo.clipes_sem_classificacao(conexao, limite)
        log.info("%d clipes pendentes de classificação", len(pendentes))
        for clipe in pendentes:
            resultado.processados += 1
            try:
                classificar_clipe(clipe, cfg, conexao, loja, embedder, resultado)
            except Exception as exc:
                conexao.rollback()
                resultado.falhas.append(f"clipe {clipe['id']}: {exc}")
                log.warning("clipe %d falhou: %s", clipe["id"], exc)
        return resultado
    finally:
        conexao.close()


async def executar_fila() -> int:
    """Consome `ingest.clipe`. Carrega o modelo uma vez e reaproveita entre
    mensagens — recarregar por clipe transformaria segundos em minutos."""
    import asyncio

    import nats

    cfg = Config.do_ambiente()
    loja = DiscoLocal(cfg.acervo_dir)
    embedder = Embedder(cfg.modelo_embedding)

    conexao_nats = await nats.connect(cfg.nats_url, name="classify-worker")
    js = conexao_nats.jetstream()
    await js.add_stream(name="INGEST", subjects=["ingest.>"], max_age=7 * 24 * 3600)
    assinatura = await js.pull_subscribe("ingest.clipe", durable="classify")
    log.info("worker de classificação ouvindo ingest.clipe em %s", cfg.nats_url)

    while True:
        try:
            mensagens = await assinatura.fetch(8, timeout=30)
        except TimeoutError:
            # Sem fila, aproveita para varrer pendência: mensagem perdida ou
            # worker que caiu no meio não deixa clipe órfão para sempre.
            await asyncio.to_thread(processar_pendentes, 20, cfg)
            continue
        except asyncio.CancelledError:
            break

        for mensagem in mensagens:
            try:
                payload = json.loads(mensagem.data)
                clipe_id = int(payload["clipe_id"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                log.error("payload inválido em ingest.clipe, descartando")
                await mensagem.term()
                continue

            try:
                await asyncio.to_thread(
                    _classificar_por_id, clipe_id, cfg, loja, embedder
                )
                await mensagem.ack()
            except Exception as exc:
                log.exception("classificação do clipe %d falhou: %s", clipe_id, exc)
                await mensagem.nak(delay=60)

    await conexao_nats.drain()
    return 0


def _classificar_por_id(
    clipe_id: int, cfg: Config, loja: DiscoLocal, embedder: Embedder
) -> None:
    conexao = catalogo.conectar(cfg.dsn)
    try:
        with conexao.cursor() as cur:
            cur.execute(
                """SELECT c.id, c.objeto, c.keyframe, f.titulo, f.provider
                   FROM clipes c JOIN fontes f ON f.id = c.fonte_id
                   WHERE c.id = %s""",
                (clipe_id,),
            )
            linha = cur.fetchone()
        if linha is None:
            log.warning("clipe %d não existe mais, ignorando", clipe_id)
            return
        resultado = ResultadoClassificacao()
        classificar_clipe(dict(linha), cfg, conexao, loja, embedder, resultado)
        if resultado.falhas:
            raise RuntimeError(resultado.falhas[0])
    finally:
        conexao.close()


def main(argv: list[str] | None = None) -> int:
    carregar_env()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Worker de classificação de acervo")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--pendentes", type=int, metavar="N", help="classifica N pendentes")
    grupo.add_argument("--fila", action="store_true", help="consome a fila NATS")
    parser.add_argument("--buscar", metavar="TEXTO", help="testa busca semântica")
    args = parser.parse_args(argv)

    cfg = Config.do_ambiente()

    if args.fila:
        import asyncio

        return asyncio.run(executar_fila())

    resultado = processar_pendentes(args.pendentes, cfg)
    print(json.dumps(resultado.resumo(), ensure_ascii=False, indent=2))

    if args.buscar:
        _demonstrar_busca(args.buscar, cfg)
    return 0


def _demonstrar_busca(consulta: str, cfg: Config) -> None:
    """Busca semântica no acervo, para conferir que o embedding serve de fato."""
    from .embedding import para_literal_pgvector

    embedder = Embedder(cfg.modelo_embedding)
    vetor = embedder.de_texto(consulta)
    conexao = catalogo.conectar(cfg.dsn)
    try:
        with conexao.cursor() as cur:
            cur.execute(
                """SELECT c.id, d.caption, 1 - (e.vetor <=> %s::vector) AS similaridade
                   FROM embeddings e
                   JOIN clipes c ON c.id = e.clipe_id
                   LEFT JOIN descricoes d ON d.clipe_id = c.id
                   ORDER BY e.vetor <=> %s::vector
                   LIMIT 5""",
                (para_literal_pgvector(vetor), para_literal_pgvector(vetor)),
            )
            print(f"\nbusca semântica: {consulta!r}")
            for linha in cur.fetchall():
                print(
                    f"  {linha['similaridade']:.3f}  clipe {linha['id']}  "
                    f"{(linha['caption'] or '')[:64]}"
                )
    finally:
        conexao.close()


if __name__ == "__main__":
    sys.exit(main())
