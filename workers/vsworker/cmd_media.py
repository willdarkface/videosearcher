"""Worker de mídia.

Dois modos, de propósito:

  * **fila** (produção): consome `ingest.fonte` do NATS JetStream.
  * **CLI** (operação e teste): ingere na hora, sem fila.

O modo CLI não é conveniência descartável: é o que permite testar a ingestão
inteira sem subir infraestrutura, e é o que você usa para ingerir um item
pontual sem passar pelo dashboard.

    python -m vsworker.cmd_media --ia usgovfilms-item-id
    python -m vsworker.cmd_media --arquivo /caminho/video.mp4 --corte 4
    python -m vsworker.cmd_media --fila
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path

from . import catalogo
from .config import Config
from .ingestao import ingerir_arquivo_local, ingerir_internet_archive

log = logging.getLogger("vsworker.media")


def configurar_log() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def _relatar(resultado) -> None:
    dados = asdict(resultado)
    print(json.dumps(dados, ensure_ascii=False, indent=2))


def executar_cli(args: argparse.Namespace) -> int:
    cfg = Config.do_ambiente()
    if args.corte:
        cfg = Config(**{**cfg.__dict__, "duracao_corte_s": float(args.corte)})

    conexao = catalogo.conectar(cfg.dsn)
    try:
        if args.ia:
            resultado = ingerir_internet_archive(
                args.ia, cfg, conexao, limite_clipes=args.limite
            )
        else:
            caminho = Path(args.arquivo)
            if not caminho.exists():
                log.error("arquivo não encontrado: %s", caminho)
                return 1
            resultado = ingerir_arquivo_local(
                caminho, cfg, conexao, limite_clipes=args.limite
            )

        _relatar(resultado)
        if args.estatisticas:
            print("\nacervo:", json.dumps(catalogo.estatisticas(conexao), indent=2))

        # Licença recusada não é erro de execução: é o sistema funcionando.
        # Falha de segmento individual também não aborta — está no relatório.
        return 0
    finally:
        conexao.close()


async def executar_fila() -> int:
    """Consome a fila de ingestão. Cada mensagem é um item para cortar.

    O trabalho pesado roda em thread separada para não travar o loop de
    heartbeat do NATS — corte de filme leva minutos, e sem isso o servidor
    consideraria o consumidor morto e reentregaria a mensagem.
    """
    import asyncio

    import nats

    cfg = Config.do_ambiente()
    conexao_nats = await nats.connect(cfg.nats_url, name="media-worker")
    js = conexao_nats.jetstream()

    await js.add_stream(name="INGEST", subjects=["ingest.>"], max_age=7 * 24 * 3600)
    assinatura = await js.pull_subscribe("ingest.fonte", durable="media")
    log.info("worker de mídia ouvindo ingest.fonte em %s", cfg.nats_url)

    while True:
        try:
            mensagens = await assinatura.fetch(1, timeout=30)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            break

        for mensagem in mensagens:
            try:
                payload = json.loads(mensagem.data)
            except json.JSONDecodeError:
                log.error("payload inválido, descartando")
                await mensagem.term()
                continue

            # in_progress periódico enquanto o corte roda: é o que evita
            # reentrega de um job que está saudável, só demorado.
            parar = asyncio.Event()

            async def batendo(msg=mensagem, evento=parar) -> None:
                while not evento.is_set():
                    await asyncio.sleep(25)
                    if not evento.is_set():
                        await msg.in_progress()

            batida = asyncio.create_task(batendo())
            try:
                resultado = await asyncio.to_thread(_processar_payload, payload, cfg)
                log.info(
                    "ingestão concluída: %s clipes=%d duplicados=%d",
                    resultado.provider_id, resultado.clipes_gravados,
                    resultado.duplicados,
                )
                await mensagem.ack()
            except Exception as exc:
                log.exception("ingestão falhou: %s", exc)
                await mensagem.nak(delay=60)
            finally:
                parar.set()
                batida.cancel()

    await conexao_nats.drain()
    return 0


def _processar_payload(payload: dict, cfg: Config):
    conexao = catalogo.conectar(cfg.dsn)
    try:
        if identificador := payload.get("internet_archive"):
            return ingerir_internet_archive(
                identificador, cfg, conexao, limite_clipes=payload.get("limite")
            )
        if caminho := payload.get("arquivo"):
            return ingerir_arquivo_local(
                Path(caminho), cfg, conexao, limite_clipes=payload.get("limite")
            )
        raise ValueError("payload sem `internet_archive` nem `arquivo`")
    finally:
        conexao.close()


def main(argv: list[str] | None = None) -> int:
    configurar_log()
    parser = argparse.ArgumentParser(description="Worker de ingestão de mídia")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--ia", metavar="IDENTIFIER", help="item do Internet Archive")
    grupo.add_argument("--arquivo", metavar="CAMINHO", help="vídeo local")
    grupo.add_argument("--fila", action="store_true", help="consome a fila NATS")
    parser.add_argument("--corte", type=float, help="duração do pedaço (4, 6 ou 8)")
    parser.add_argument("--limite", type=int, help="máximo de clipes desta fonte")
    parser.add_argument("--estatisticas", action="store_true", help="imprime o acervo ao fim")
    args = parser.parse_args(argv)

    if args.fila:
        import asyncio

        return asyncio.run(executar_fila())
    return executar_cli(args)


if __name__ == "__main__":
    sys.exit(main())
