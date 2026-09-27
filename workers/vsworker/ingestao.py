"""Ingestão: item da fonte → clipes cortados, medidos e catalogados.

Função pura de efeito controlado: recebe o que ingerir, devolve o que aconteceu.
Não conhece NATS. É isso que permite testar a ingestão inteira pela linha de
comando, sem subir fila nenhuma.

O gate de licença roda ANTES do download. Baixar 2 GB de um filme que vai ser
recusado por licença é desperdiçar banda e disco.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from videosearcher.core.http import baixar, get_json
from videosearcher.core.licenca import Licenca, classificar_licenca

from . import catalogo, corte
from .config import Config
from .storage import DiscoLocal, chave_de_clipe, chave_de_keyframe

log = logging.getLogger("vsworker.ingestao")

METADATA_IA = "https://archive.org/metadata"
DOWNLOAD_IA = "https://archive.org/download"

FORMATOS_IA = (
    "h.264", "MPEG4", "HiRes MPEG4", "512Kb MPEG4", "MPEG2", "WebM", "Ogg Video",
)


@dataclass
class ResultadoIngestao:
    provider: str
    provider_id: str
    licenca: str = ""
    aceita: bool = False
    motivo: str = ""
    fonte_id: int | None = None
    cenas: int = 0
    segmentos_planejados: int = 0
    clipes_gravados: int = 0
    duplicados: int = 0
    vazios: int = 0
    falhas: list[str] = field(default_factory=list)
    bytes_totais: int = 0


def ingerir_internet_archive(
    identifier: str,
    cfg: Config,
    conexao: psycopg.Connection,
    *,
    limite_clipes: int | None = None,
) -> ResultadoIngestao:
    """Ingere um item do Internet Archive: baixa, corta, mede e cataloga."""
    resultado = ResultadoIngestao(provider="internet_archive", provider_id=identifier)

    meta = get_json(f"{METADATA_IA}/{identifier}")
    metadados = meta.get("metadata") or {}

    # --- gate de licença, antes de gastar banda -------------------------
    licenca: Licenca = classificar_licenca(metadados)
    resultado.licenca = licenca.id
    resultado.motivo = licenca.motivo
    if not licenca.usavel_comercialmente:
        resultado.aceita = False
        log.warning(
            "fonte recusada por licença: %s (%s) — %s",
            identifier, licenca.id, licenca.motivo,
        )
        return resultado
    resultado.aceita = True

    arquivo_meta = _melhor_arquivo(meta.get("files") or [])
    if arquivo_meta is None:
        resultado.falhas.append("nenhum arquivo de vídeo utilizável no item")
        return resultado

    titulo = _texto(metadados.get("title"))
    url = f"{DOWNLOAD_IA}/{identifier}/{arquivo_meta['name'].replace(' ', '%20')}"

    fonte = catalogo.FonteRegistro(
        provider="internet_archive",
        provider_id=identifier,
        titulo=titulo,
        descricao=_texto(metadados.get("description")),
        source_page=f"https://archive.org/details/{identifier}",
        download_url=url,
        duracao_s=None,
        largura=None,
        altura=None,
        data_original=_texto(metadados.get("year") or metadados.get("date")),
        licenca_id=licenca.id,
        licenca_url=licenca.url,
        licenca_verificada=licenca.verificada,
        licenca_motivo=licenca.motivo,
        atribuicao=licenca.atribuicao,
        credito=f"{titulo or identifier} (Internet Archive)",
        metadados={
            "colecoes": metadados.get("collection"),
            "arquivo": arquivo_meta.get("name"),
        },
    )

    return _processar(
        url, fonte, cfg, conexao, resultado,
        palavras_base=_palavras_de(titulo, metadados),
        limite_clipes=limite_clipes,
    )


def ingerir_arquivo_local(
    caminho: Path,
    cfg: Config,
    conexao: psycopg.Connection,
    *,
    provider: str = "local",
    provider_id: str | None = None,
    titulo: str | None = None,
    limite_clipes: int | None = None,
) -> ResultadoIngestao:
    """Ingere material seu, que já está em disco. Licença é sua, então entra
    como verificada — mas explicitamente, não por suposição."""
    identificador = provider_id or caminho.stem
    resultado = ResultadoIngestao(
        provider=provider, provider_id=identificador,
        licenca="proprio", aceita=True, motivo="material próprio declarado pelo operador",
    )
    fonte = catalogo.FonteRegistro(
        provider=provider,
        provider_id=identificador,
        titulo=titulo or caminho.stem,
        descricao=None,
        source_page=None,
        download_url=None,
        duracao_s=None,
        largura=None,
        altura=None,
        data_original=None,
        licenca_id="proprio",
        licenca_url=None,
        licenca_verificada=True,
        licenca_motivo="material próprio declarado pelo operador",
        atribuicao=False,
        credito=None,
        metadados={"origem": str(caminho)},
    )
    return _processar(
        None, fonte, cfg, conexao, resultado,
        palavras_base=[], limite_clipes=limite_clipes, arquivo_pronto=caminho,
    )


# ---------------------------------------------------------------------------


def _processar(
    url: str | None,
    fonte: catalogo.FonteRegistro,
    cfg: Config,
    conexao: psycopg.Connection,
    resultado: ResultadoIngestao,
    *,
    palavras_base: list[str],
    limite_clipes: int | None,
    arquivo_pronto: Path | None = None,
) -> ResultadoIngestao:
    loja = DiscoLocal(cfg.acervo_dir)
    temporario = Path(tempfile.mkdtemp(prefix="vsworker-"))

    try:
        if arquivo_pronto is not None:
            origem = arquivo_pronto
        else:
            origem = temporario / "fonte.mp4"
            log.info("baixando %s", url)
            baixar(str(url), origem, max_bytes=4_000_000_000)

        sonda = corte.sondar(origem)
        fonte.duracao_s = sonda.duracao_s
        fonte.largura = sonda.largura
        fonte.altura = sonda.altura

        cenas = corte.detectar_cenas(origem, limiar=cfg.limiar_cena)
        segmentos = corte.planejar_segmentos(
            sonda, cenas,
            duracao_alvo=cfg.duracao_corte_s,
            duracao_minima=cfg.duracao_minima_s,
        )
        resultado.cenas = len(cenas)
        resultado.segmentos_planejados = len(segmentos)

        teto = limite_clipes or cfg.max_clipes_por_fonte
        if len(segmentos) > teto:
            log.info("limitando %d segmentos a %d", len(segmentos), teto)
            segmentos = segmentos[:teto]

        fonte_id = catalogo.upsert_fonte(conexao, fonte)
        conexao.commit()
        resultado.fonte_id = fonte_id

        for segmento in segmentos:
            try:
                _gravar_segmento(
                    origem, segmento, fonte, fonte_id, cfg, conexao, loja,
                    temporario, resultado, palavras_base,
                )
            except Exception as exc:  # um segmento ruim não aborta o filme
                conexao.rollback()
                resultado.falhas.append(f"segmento {segmento.indice}: {exc}")
                log.warning("segmento %d falhou: %s", segmento.indice, exc)

        return resultado
    finally:
        shutil.rmtree(temporario, ignore_errors=True)


def _gravar_segmento(
    origem: Path,
    segmento: corte.Segmento,
    fonte: catalogo.FonteRegistro,
    fonte_id: int,
    cfg: Config,
    conexao: psycopg.Connection,
    loja: DiscoLocal,
    temporario: Path,
    resultado: ResultadoIngestao,
    palavras_base: list[str],
) -> None:
    bruto = temporario / f"seg_{segmento.indice:04d}.mp4"
    corte.cortar(
        origem, segmento, bruto,
        altura_alvo=cfg.altura_alvo, fps_alvo=cfg.fps_alvo,
    )

    keyframe_tmp = temporario / f"seg_{segmento.indice:04d}.jpg"
    corte.extrair_keyframe(bruto, keyframe_tmp)

    hash_visual = corte.dhash(keyframe_tmp)

    # Quadro chapado (tela preta, fade, cartela de cor sólida) tem zero
    # variação de luminância. Não é duplicata: é clipe sem conteúdo, e detecção
    # de cena produz isso em transição. Descartar aqui evita poluir o acervo e
    # gastar classificação com nada.
    if corte.quadro_chapado(hash_visual):
        resultado.vazios += 1
        bruto.unlink(missing_ok=True)
        keyframe_tmp.unlink(missing_ok=True)
        return

    if catalogo.hash_ja_existe(conexao, hash_visual):
        resultado.duplicados += 1
        bruto.unlink(missing_ok=True)
        keyframe_tmp.unlink(missing_ok=True)
        return

    # A duração que vale é a MEDIDA no arquivo, nunca a planejada: o seek por
    # keyframe não entrega exatamente o pedido, e o ranqueamento depende dessa
    # duração para decidir se o clipe cobre o bloco.
    sonda_clipe = corte.sondar(bruto)
    metricas = corte.metricas_visuais(keyframe_tmp)

    chave = chave_de_clipe(
        fonte.provider, fonte.provider_id, segmento.indice, ".mp4"
    )
    chave_kf = chave_de_keyframe(chave)
    bytes_clipe = bruto.stat().st_size
    loja.put(chave, bruto)
    loja.put(chave_kf, keyframe_tmp)

    registro = catalogo.ClipeRegistro(
        tipo="video",
        objeto=chave,
        keyframe=chave_kf,
        inicio_s=segmento.inicio_s,
        fim_s=segmento.fim_s,
        duracao_s=sonda_clipe.duracao_s,
        largura=sonda_clipe.largura,
        altura=sonda_clipe.altura,
        fps=sonda_clipe.fps,
        bytes=bytes_clipe,
        cena_id=segmento.cena_id,
        hash_visual=hash_visual,
        look=corte.classificar_look(metricas["saturacao"]),
        saturacao=metricas["saturacao"],
        brilho=metricas["brilho"],
    )
    clipe_id = catalogo.inserir_clipe(conexao, fonte_id, registro)

    # Texto de busca provisório: título da fonte. O classify substitui por
    # caption + palavras-chave, que é infinitamente melhor.
    texto = " ".join(filter(None, [fonte.titulo, *palavras_base]))
    if texto.strip():
        catalogo.registrar_texto_busca(conexao, clipe_id, texto)
        catalogo.adicionar_palavras(conexao, clipe_id, palavras_base, origem="provedor")

    conexao.commit()
    resultado.clipes_gravados += 1
    resultado.bytes_totais += bytes_clipe


def _melhor_arquivo(arquivos: list[dict]) -> dict | None:
    candidatos = [
        f for f in arquivos
        if isinstance(f, dict)
        and (f.get("format") in FORMATOS_IA
             or str(f.get("name", "")).lower().endswith((".mp4", ".webm", ".m4v", ".ogv")))
    ]
    if not candidatos:
        return None

    def nota(f: dict) -> tuple[int, int]:
        try:
            pref = FORMATOS_IA.index(f.get("format", ""))
        except ValueError:
            pref = len(FORMATOS_IA)
        return (pref, -int(f.get("size") or 0))

    return min(candidatos, key=nota)


def _texto(valor) -> str | None:
    if isinstance(valor, list):
        valor = " ".join(str(v) for v in valor)
    if valor is None:
        return None
    limpo = " ".join(str(valor).split())
    return limpo[:500] or None


def _palavras_de(titulo: str | None, metadados: dict) -> list[str]:
    """Palavras iniciais vindas do próprio acervo, antes da classificação."""
    from videosearcher.core.text import palavras_chave

    fonte_texto = " ".join(
        filter(None, [titulo, _texto(metadados.get("subject"))])
    )
    return palavras_chave(fonte_texto, maximo=10)
