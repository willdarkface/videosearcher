"""Entrega: relatório de links, download e pasta numerada."""

from __future__ import annotations

import csv
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..core.models import MediaType
from ..pipeline import ResultadoBloco, ResultadoPipeline
from .naming import caminho_sem_colisao, nome_arquivo


@dataclass
class ResultadoEntrega:
    pasta: Path
    baixados: int = 0
    falhas: list[str] = field(default_factory=list)
    pendentes: list[str] = field(default_factory=list)
    bytes_totais: int = 0


# Acima desta razão, o asset é um filme inteiro e não um clipe: usar do jeito
# que está significa pegar os primeiros segundos, que quase nunca servem.
RAZAO_FILME_INTEIRO = 20.0


def _aviso_de_uso(r: ResultadoBloco) -> str | None:
    """Avisa quando o asset escolhido não é utilizável como está."""
    asset, _ = r.escolhido
    if not asset.duration_s or r.block.duration_s <= 0:
        return None
    razao = asset.duration_s / r.block.duration_s
    if razao < RAZAO_FILME_INTEIRO:
        return None
    return (
        f"> ⚠️ **NÃO USE DIRETO.** Este asset tem {asset.duration_s / 60:.0f} minutos "
        f"para um bloco de {r.block.duration_s:.1f}s ({razao:.0f}x). É um filme "
        f"inteiro, não um clipe. Sem detecção de cena (fase 5) o corte pegaria os "
        f"primeiros segundos, que quase nunca servem. Além disso, o ranqueamento "
        f"atual não mede relevância semântica: este item pode não ter relação "
        f"nenhuma com o bloco."
    )


# ---------------------------------------------------------------------------
# Relatório de links — não baixa nada, serve para conferir calibragem
# ---------------------------------------------------------------------------


def escrever_relatorio(resultado: ResultadoPipeline, destino: Path) -> Path:
    total = len(resultado.blocos)
    com = resultado.com_resultado
    sem = resultado.sem_resultado

    linhas: list[str] = []
    linhas.append(f"# Relatório de busca — {resultado.legenda.name}")
    linhas.append("")
    linhas.append(f"- **Canal:** {resultado.canal.nome} (`{resultado.canal.slug}`)")
    linhas.append(f"- **Blocos:** {total}")
    linhas.append(
        f"- **Com resultado:** {len(com)} ({len(com) / total:.0%})"
        if total
        else "- **Com resultado:** 0"
    )
    linhas.append(f"- **Sem resultado:** {len(sem)}")

    videos = sum(1 for r in com if r.escolhido[0].media_type is MediaType.VIDEO)
    fotos = len(com) - videos
    linhas.append(f"- **Vídeo escolhido:** {videos} · **Imagem escolhida:** {fotos}")
    precisam_corte = sum(1 for r in com if _aviso_de_uso(r))
    if precisam_corte:
        linhas.append(
            f"- **⚠️ Precisam de corte por cena (fase 5):** {precisam_corte} — "
            f"são filmes inteiros, não clipes, e não devem ser usados como estão"
        )
    faltam_chaves = [
        nome
        for nome, env in (("Pexels", "PEXELS_API_KEY"), ("Pixabay", "PIXABAY_API_KEY"))
        if not os.getenv(env, "").strip()
    ]
    if faltam_chaves:
        linhas.append(
            f"- **Chaves ausentes:** {', '.join(faltam_chaves)} — estes provedores "
            f"não foram consultados, e são justamente os que cobrem bloco moderno "
            f"e metafórico"
        )
    por_provedor: dict[str, int] = {}
    for r in com:
        p = r.escolhido[0].provider
        por_provedor[p] = por_provedor.get(p, 0) + 1
    if por_provedor:
        linhas.append(
            "- **Provedores:** "
            + ", ".join(f"{k} ({v})" for k, v in sorted(por_provedor.items(), key=lambda x: -x[1]))
        )
    linhas.append("")
    linhas.append("> Confira a coluna **query** contra o **texto do bloco**: é ali que se vê")
    linhas.append("> se o briefing está calibrado. O link abre a página do asset.")
    linhas.append("")
    linhas.append("---")
    linhas.append("")

    for r in resultado.resultados:
        b, brief = r.block, r.brief
        linhas.append(f"## Bloco {b.number:03d} · {b.timecode} · {b.duration_s:.1f}s")
        linhas.append("")
        linhas.append(f"> {b.text}")
        linhas.append("")
        linhas.append(
            f"`intent: {brief.intent.value}` · `era: {brief.era or '—'}` · "
            f"`look: {brief.look.value}` · `motion: {brief.motion.value}` · "
            f"`midia: {'+'.join(m.value for m in brief.media_preference)}`"
        )
        linhas.append("")
        linhas.append(f"- **query:** `{'` · `'.join(brief.queries.primary) or '—'}`")
        if brief.queries.secondary:
            linhas.append(f"- alternativas: `{'` · `'.join(brief.queries.secondary)}`")
        if brief.queries.archival:
            linhas.append(f"- arquivo: `{'` · `'.join(brief.queries.archival)}`")
        linhas.append(
            f"- provedores consultados: {', '.join(r.provedores_consultados) or '—'} "
            f"· candidatos: {r.candidatos}"
        )
        linhas.append("")

        if not r.encontrou:
            linhas.append("**❌ SEM RESULTADO**")
            if r.selecao.recusados:
                linhas.append("")
                linhas.append("Recusados:")
                for asset, veredito in r.selecao.recusados[:4]:
                    linhas.append(f"- `{asset.uid}` — {veredito.motivo}")
            for erro in r.erros:
                linhas.append(f"- ⚠️ {erro}")
            linhas.append("")
            linhas.append("---")
            linhas.append("")
            continue

        asset, veredito = r.escolhido
        tipo = "🎬 vídeo" if asset.media_type is MediaType.VIDEO else "🖼️ imagem"
        dur = f"{asset.duration_s:.1f}s" if asset.duration_s else "—"
        linhas.append(
            f"**✅ ESCOLHIDO** · {tipo} · {asset.width}x{asset.height} · {dur} · "
            f"`{asset.provider}` · nota {veredito.bonus:.2f}"
        )
        linhas.append("")
        aviso = _aviso_de_uso(r)
        if aviso:
            linhas.append(aviso)
            linhas.append("")
        linhas.append(f"- motivo: {veredito.motivo}")
        if veredito.ajustes:
            linhas.append(f"- ajustes: `{'`, `'.join(veredito.ajustes)}`")
        linhas.append(f"- página: {asset.source_page or '—'}")
        linhas.append(f"- download: {asset.download_url}")
        if asset.preview_url:
            linhas.append(f"- preview: {asset.preview_url}")
        linhas.append(f"- licença: `{asset.license_id}`")

        if r.selecao.alternativas:
            linhas.append("")
            linhas.append("Alternativas:")
            for asset_alt, ver_alt in r.selecao.alternativas[:3]:
                t = "vídeo" if asset_alt.media_type is MediaType.VIDEO else "imagem"
                d = f"{asset_alt.duration_s:.1f}s" if asset_alt.duration_s else "—"
                linhas.append(
                    f"- {t} · {d} · `{asset_alt.provider}` · nota {ver_alt.bonus:.2f} · "
                    f"{asset_alt.source_page or asset_alt.download_url}"
                )
        linhas.append("")
        linhas.append("---")
        linhas.append("")

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino


# ---------------------------------------------------------------------------
# Download + pasta numerada
# ---------------------------------------------------------------------------


def entregar(
    resultado: ResultadoPipeline,
    pasta: Path,
    *,
    alternativas: bool = True,
    baixar_filmes_inteiros: bool = False,
    progresso: Callable[[int, int], None] | None = None,
) -> ResultadoEntrega:
    from ..core.registry import get_provider

    entrega = ResultadoEntrega(pasta=pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    pasta_alt = pasta / "_alternativas"

    total_blocos = len(resultado.blocos)
    com = resultado.com_resultado

    for i, r in enumerate(com):
        asset, _ = r.escolhido

        # Filme de arquivo tem horas de duração: baixar significa gigabytes para
        # um bloco de segundos, e o arquivo não é utilizável antes da detecção
        # de cena. Fica registrado como pendente em vez de entupir o disco.
        if not baixar_filmes_inteiros and _aviso_de_uso(r):
            entrega.pendentes.append(
                f"bloco {r.block.number:03d}: {asset.duration_s / 60:.0f} min "
                f"({asset.provider}) — aguarda corte por cena · {asset.source_page}"
            )
            if progresso:
                progresso(i + 1, len(com))
            continue

        nome = nome_arquivo(r.block.number, asset, r.brief.slug, total_blocos=total_blocos)
        destino = caminho_sem_colisao(pasta, nome)
        try:
            provedor = get_provider(asset.provider)
            caminho = provedor.download(asset, destino)
            r.arquivo = caminho
            entrega.baixados += 1
            entrega.bytes_totais += caminho.stat().st_size
        except Exception as exc:
            entrega.falhas.append(f"bloco {r.block.number} ({asset.uid}): {exc}")

        if alternativas and resultado.canal.entrega.alternativas_por_bloco:
            limite = resultado.canal.entrega.alternativas_por_bloco
            for n, (asset_alt, _) in enumerate(r.selecao.alternativas[:limite]):
                sufixo = chr(ord("b") + n)
                nome_alt = nome_arquivo(
                    r.block.number,
                    asset_alt,
                    r.brief.slug,
                    total_blocos=total_blocos,
                    sufixo=sufixo,
                )
                try:
                    provedor = get_provider(asset_alt.provider)
                    caminho = provedor.download(
                        asset_alt, caminho_sem_colisao(pasta_alt, nome_alt)
                    )
                    r.alternativas_baixadas.append(caminho)
                    entrega.bytes_totais += caminho.stat().st_size
                except Exception as exc:
                    entrega.falhas.append(
                        f"bloco {r.block.number} alternativa {sufixo}: {exc}"
                    )

        if progresso:
            progresso(i + 1, len(com))

    escrever_manifest(resultado, pasta / "_manifest.csv")
    escrever_nao_encontrados(resultado, pasta / "_nao-encontrados.txt")
    escrever_creditos(resultado, pasta / "_CREDITOS.md")
    if entrega.pendentes:
        (pasta / "_PENDENTES-CORTE-POR-CENA.txt").write_text(
            "Estes blocos acharam material de arquivo, mas o item é um filme\n"
            "inteiro de dezenas de minutos. Baixar não resolve: o arquivo só\n"
            "vira utilizável depois da detecção de cena (fase 5), que corta o\n"
            "filme em sub-clipes e indexa cada cena.\n\n"
            "Para baixar de qualquer forma, rode com --baixar-filmes.\n\n"
            + "\n".join(entrega.pendentes),
            encoding="utf-8",
        )
    return entrega


def escrever_manifest(resultado: ResultadoPipeline, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "bloco", "inicio_s", "fim_s", "duracao_s", "texto", "intent", "era", "look",
            "query", "arquivo", "tipo", "provedor", "duracao_asset_s", "resolucao",
            "licenca", "atribuicao", "credito", "nota", "motivo", "ajustes", "pagina",
        ])
        for r in resultado.resultados:
            if not r.encontrou:
                w.writerow([
                    r.block.number, f"{r.block.start_s:.2f}", f"{r.block.end_s:.2f}",
                    f"{r.block.duration_s:.2f}", r.block.text, r.brief.intent.value,
                    r.brief.era or "", r.brief.look.value,
                    " | ".join(r.brief.queries.primary),
                    "", "", "", "", "", "", "", "", "", "SEM RESULTADO", "", "",
                ])
                continue
            asset, veredito = r.escolhido
            w.writerow([
                r.block.number, f"{r.block.start_s:.2f}", f"{r.block.end_s:.2f}",
                f"{r.block.duration_s:.2f}", r.block.text, r.brief.intent.value,
                r.brief.era or "", r.brief.look.value,
                " | ".join(r.brief.queries.primary),
                r.arquivo.name if r.arquivo else "", asset.media_type.value,
                asset.provider,
                f"{asset.duration_s:.2f}" if asset.duration_s else "",
                f"{asset.width}x{asset.height}", asset.license_id,
                "sim" if asset.attribution_required else "nao",
                asset.credit_string or "", f"{veredito.bonus:.3f}", veredito.motivo,
                "+".join(veredito.ajustes), asset.source_page or "",
            ])
    return destino


def escrever_nao_encontrados(resultado: ResultadoPipeline, destino: Path) -> Path:
    sem = resultado.sem_resultado
    linhas = [
        f"Blocos sem resultado: {len(sem)} de {len(resultado.blocos)}",
        "",
        "Cada entrada traz o texto do bloco, as queries tentadas e por que os",
        "candidatos foram recusados. É o mapa do seu retrabalho manual — e do que",
        "a geração por IA vai cobrir no futuro.",
        "",
        "=" * 74,
        "",
    ]
    for r in sem:
        linhas.append(f"BLOCO {r.block.number:03d}  {r.block.timecode}  {r.block.duration_s:.1f}s")
        linhas.append(f"  texto:  {r.block.text}")
        linhas.append(f"  intent: {r.brief.intent.value}   era: {r.brief.era or '—'}")
        linhas.append(f"  query:  {' | '.join(r.brief.queries.primary) or '—'}")
        if r.brief.queries.secondary:
            linhas.append(f"  alt:    {' | '.join(r.brief.queries.secondary)}")
        linhas.append(f"  provedores: {', '.join(r.provedores_consultados) or '—'}"
                      f"   candidatos: {r.candidatos}")
        for asset, veredito in r.selecao.recusados[:5]:
            linhas.append(f"    recusado {asset.uid}: {veredito.motivo}")
        for erro in r.erros:
            linhas.append(f"    ERRO {erro}")
        linhas.append("")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino


def escrever_creditos(resultado: ResultadoPipeline, destino: Path) -> Path:
    exigem = [
        r for r in resultado.com_resultado if r.escolhido[0].attribution_required
    ]
    linhas = [f"# Créditos — {resultado.legenda.name}", ""]
    if not exigem:
        linhas.append("Nenhum asset usado exige atribuição obrigatória.")
        linhas.append("")
        linhas.append("Ainda assim, creditar é boa prática. Fontes usadas:")
        fontes = sorted({r.escolhido[0].provider for r in resultado.com_resultado})
        for fonte in fontes:
            linhas.append(f"- {fonte}")
    else:
        linhas.append("Cole na descrição do vídeo:")
        linhas.append("")
        for r in exigem:
            asset = r.escolhido[0]
            linhas.append(f"- {asset.credit_string or asset.uid} — {asset.source_page or ''}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino
