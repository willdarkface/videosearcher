"""CLI do videosearcher."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from . import __version__
from .core import registry
from .core.cache import RespostaCache
from .core.config import list_channels, load_channel
from .core.models import Sensitivity
from .llm.base import LLMError
from .llm.chain import LLMChain
from .llm.providers.specs import list_specs
from .script.blocker import build_blocks, summarize
from .script.briefing import BriefingEngine
from .script.parser import SubtitleParseError, parse_subtitles

load_dotenv()

_COR_INTENT = {
    "arquivo": "yellow",
    "metaforico": "magenta",
    "literal": "cyan",
    "retrato": "green",
    "grafico": "blue",
}

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Encontra e baixa a mídia ideal para cada bloco de um roteiro.",
)
llm_app = typer.Typer(no_args_is_help=True, help="Diagnóstico e cadastro das LLMs.")
app.add_typer(llm_app, name="llm")

console = Console()

OK = "[green]✓[/green]"
FAIL = "[red]✗[/red]"


@app.command()
def version() -> None:
    """Mostra a versão."""
    console.print(f"videosearcher {__version__}")


# ---------------------------------------------------------------------------
# Provedores de mídia
# ---------------------------------------------------------------------------


@app.command()
def providers() -> None:
    """Lista os provedores de mídia registrados e suas capabilities."""
    rows = registry.status()
    if not rows:
        console.print("[yellow]nenhum provedor registrado[/yellow]")
        return

    table = Table(title="Provedores de mídia", show_lines=False)
    table.add_column("provedor", style="bold")
    table.add_column("mídia")
    table.add_column("tipo")
    table.add_column("licença")
    table.add_column("cota/h", justify="right")
    table.add_column("subclip", justify="center")
    table.add_column("chave", justify="center")
    table.add_column("busca", justify="center")

    for row in rows:
        caps = row.capabilities
        media = "+".join(sorted(m.value for m in caps.media_types))
        kind = "+".join(sorted(k.value for k in caps.content_kind))
        quota = str(caps.max_requests_per_hour) if caps.max_requests_per_hour else "—"
        key = "n/a" if not caps.requires_api_key else (OK if row.api_key_present else FAIL)
        table.add_row(
            row.name,
            media,
            kind,
            caps.license_default,
            quota,
            "sim" if caps.needs_subclip else "—",
            key,
            OK if row.implemented else "[yellow]fase 3+[/yellow]",
        )

    console.print(table)
    console.print(
        "\n[dim]chave ✗ = variável de ambiente ausente (ver .env.example) · "
        "busca 'fase 3+' = capabilities prontas, integração pendente[/dim]"
    )


# ---------------------------------------------------------------------------
# Canais
# ---------------------------------------------------------------------------


@app.command()
def channels() -> None:
    """Lista os packs de canal disponíveis."""
    slugs = list_channels()
    if not slugs:
        console.print("[yellow]nenhum canal em channels/ — rode a partir da raiz do repo[/yellow]")
        return

    table = Table(title="Packs de canal")
    table.add_column("slug", style="bold")
    table.add_column("nome")
    table.add_column("look")
    table.add_column("bloco (s)")
    table.add_column("res. mín.", justify="right")
    table.add_column("prioridade de provedores")

    for slug in slugs:
        cfg = load_channel(slug)
        entrega = cfg.entrega
        table.add_row(
            slug,
            cfg.nome,
            cfg.estetica.look_padrao.value,
            f"{entrega.min_duracao:g}–{entrega.max_duracao:g}",
            str(entrega.resolucao_minima),
            ", ".join(cfg.provedores.prioridade[:4]) or "—",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Blocos
# ---------------------------------------------------------------------------


@app.command()
def blocks(
    legenda: Path = typer.Argument(..., help="Arquivo .srt ou .vtt"),
    canal: str = typer.Option("_base", "--canal", "-c", help="Slug do pack de canal"),
    limite: int = typer.Option(0, "--limite", "-n", help="Mostrar apenas os N primeiros"),
    saida_json: Path | None = typer.Option(None, "--json", help="Grava os blocos em JSON"),
) -> None:
    """Segmenta uma legenda em blocos visuais numerados."""
    try:
        cfg = load_channel(canal)
    except FileNotFoundError:
        console.print(f"[red]canal '{canal}' não encontrado.[/red] Veja `videosearcher channels`.")
        raise typer.Exit(code=1) from None

    try:
        cues = parse_subtitles(legenda)
    except FileNotFoundError:
        console.print(f"[red]legenda não encontrada:[/red] {legenda}")
        raise typer.Exit(code=1) from None
    except SubtitleParseError as exc:
        console.print(f"[red]legenda inválida:[/red] {exc}")
        raise typer.Exit(code=1) from None

    result = build_blocks(cues, cfg.entrega)

    console.print(
        f"\n[bold]{legenda.name}[/bold] · canal [cyan]{cfg.nome}[/cyan] · "
        f"{len(cues)} cues → [bold green]{len(result)} blocos[/bold green]\n"
    )

    table = Table(show_lines=False)
    table.add_column("#", justify="right", style="bold")
    table.add_column("início")
    table.add_column("fim")
    table.add_column("dur", justify="right")
    table.add_column("texto")

    width = len(str(len(result)))
    shown = result[:limite] if limite > 0 else result
    for block in shown:
        text = block.text if len(block.text) <= 88 else block.text[:85] + "..."
        duration = f"{block.duration_s:.1f}s"
        style = "yellow" if block.duration_s > cfg.entrega.max_duracao + 0.01 else None
        table.add_row(
            str(block.number).zfill(width),
            f"{block.start_s:.1f}",
            f"{block.end_s:.1f}",
            f"[yellow]{duration}[/yellow]" if style else duration,
            text,
        )

    console.print(table)
    if limite > 0 and len(result) > limite:
        console.print(f"[dim]... e mais {len(result) - limite} blocos[/dim]")

    stats = summarize(result)
    console.print(
        "\n[bold]Estatísticas:[/bold] "
        + " · ".join(f"{k}={v}" for k, v in stats.items())
    )
    console.print(
        f"[dim]alvo do canal: {cfg.entrega.min_duracao:g}–{cfg.entrega.max_duracao:g}s "
        f"(alvo {cfg.entrega.alvo:g}s)[/dim]"
    )

    if saida_json:
        payload = {
            "legenda": str(legenda),
            "canal": cfg.slug,
            "estatisticas": stats,
            "blocos": [b.model_dump() for b in result],
        }
        saida_json.parent.mkdir(parents=True, exist_ok=True)
        saida_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"\n[green]JSON gravado em {saida_json}[/green]")


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@llm_app.command("list")
def llm_list() -> None:
    """Lista os provedores de LLM suportados e onde cadastrar cada um."""
    import os

    table = Table(title="Provedores de LLM suportados", show_lines=True)
    table.add_column("provedor", style="bold")
    table.add_column("chave", justify="center")
    table.add_column("variável")
    table.add_column("modelo padrão")
    table.add_column("cadastro")

    for spec in list_specs():
        present = bool(os.getenv(spec.api_key_env, "").strip())
        table.add_row(
            spec.name,
            OK if present else FAIL,
            spec.api_key_env,
            spec.default_model,
            spec.signup_url,
        )

    console.print(table)
    console.print("\n[bold]Tier gratuito de cada um:[/bold]")
    for spec in list_specs():
        if spec.free_tier:
            console.print(f"  [bold]{spec.name}[/bold]: {spec.free_tier}")


@llm_app.command("check")
def llm_check(
    canal: str = typer.Option("_base", "--canal", "-c", help="Slug do pack de canal"),
    ping: bool = typer.Option(
        True, "--ping/--no-ping", help="Faz uma chamada real de teste em cada elo"
    ),
) -> None:
    """Testa a corrente de LLM do canal, elo por elo."""
    try:
        cfg = load_channel(canal)
    except FileNotFoundError:
        console.print(f"[red]canal '{canal}' não encontrado.[/red]")
        raise typer.Exit(code=1) from None

    try:
        chain = LLMChain(cfg.llm)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(f"\nCorrente de LLM do canal [cyan]{cfg.nome}[/cyan]:\n")

    table = Table()
    table.add_column("ordem", justify="right")
    table.add_column("provedor", style="bold")
    table.add_column("modelo")
    table.add_column("tier")
    table.add_column("estado", justify="center")
    table.add_column("detalhe")

    if not ping:
        for i, link in enumerate(chain.links(), start=1):
            client = chain.client_for(link)
            has_key = client.has_key()
            table.add_row(
                str(i),
                link.provider,
                link.model,
                link.tier,
                OK if has_key else FAIL,
                "chave presente" if has_key else f"{client.api_key_env} vazia",
            )
        console.print(table)
        return

    results = chain.check()
    for i, attempt in enumerate(results, start=1):
        table.add_row(
            str(i),
            attempt.provider,
            attempt.model,
            attempt.tier,
            OK if attempt.ok else FAIL,
            attempt.detail[:90],
        )
    console.print(table)

    working = [a for a in results if a.ok]
    if working:
        first = working[0]
        console.print(
            f"\n{OK} [bold green]Pronto.[/bold green] O briefing vai usar "
            f"[bold]{first.provider}/{first.model}[/bold], "
            f"com {len(working) - 1} elo(s) de reserva."
        )
    else:
        console.print(
            "\n[red]Nenhum elo funcionando.[/red] Rode `videosearcher llm list` para ver "
            "onde cadastrar, ou leia a seção 'Cadastro das LLMs' do README."
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Briefing
# ---------------------------------------------------------------------------


@app.command()
def briefs(
    legenda: Path = typer.Argument(..., help="Arquivo .srt ou .vtt"),
    canal: str = typer.Option(..., "--canal", "-c", help="Slug do pack de canal"),
    tema: str | None = typer.Option(None, "--tema", help="Tema do vídeo (padrão: infere)"),
    limite: int = typer.Option(0, "--limite", "-n", help="Processar apenas os N primeiros blocos"),
    sem_cache: bool = typer.Option(False, "--sem-cache", help="Ignora o cache de respostas"),
    saida_json: Path | None = typer.Option(None, "--json", help="Grava os briefs em JSON"),
) -> None:
    """Gera o briefing visual de cada bloco via LLM."""
    try:
        cfg = load_channel(canal)
    except FileNotFoundError:
        console.print(f"[red]canal '{canal}' não encontrado.[/red] Veja `videosearcher channels`.")
        raise typer.Exit(code=1) from None

    try:
        cues = parse_subtitles(legenda)
    except (FileNotFoundError, SubtitleParseError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    blocos = build_blocks(cues, cfg.entrega)
    if limite > 0:
        blocos = blocos[:limite]

    try:
        chain = LLMChain(cfg.llm)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    engine = BriefingEngine(cfg, chain, RespostaCache(ativo=not sem_cache))

    console.print(
        f"\n[bold]{legenda.name}[/bold] · canal [cyan]{cfg.nome}[/cyan] · "
        f"{len(blocos)} blocos em lotes de {cfg.llm.batch_size}\n"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total} lotes"),
        console=console,
        transient=True,
    ) as progress:
        tarefa = progress.add_task("briefing", total=max(1, -(-len(blocos) // cfg.llm.batch_size)))

        def avancar(feito: int, total: int) -> None:
            progress.update(tarefa, completed=feito, total=total)

        try:
            resultado = engine.processar(blocos, tema=tema, progresso=avancar)
        except LLMError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from None

    table = Table(show_lines=False, pad_edge=False, box=None)
    table.add_column("#", justify="right", style="bold")
    table.add_column("dur", justify="right", no_wrap=True)
    table.add_column("intenção", no_wrap=True)
    table.add_column("era", no_wrap=True)
    table.add_column("look", no_wrap=True)
    table.add_column("md", no_wrap=True)
    table.add_column("query principal", no_wrap=True, overflow="ellipsis", max_width=42)
    table.add_column("slug", no_wrap=True, overflow="ellipsis", max_width=34)

    por_bloco = {b.number: b for b in blocos}
    largura = len(str(len(blocos)))
    for brief in resultado.briefs:
        bloco = por_bloco.get(brief.block_number)
        cor = _COR_INTENT.get(brief.intent.value, "white")
        look = brief.look.value.replace("bw_archival", "bw").replace("color_modern", "cor")
        table.add_row(
            str(brief.block_number).zfill(largura),
            f"{bloco.duration_s:.1f}s" if bloco else "—",
            f"[{cor}]{brief.intent.value[:10]}[/{cor}]",
            brief.era or "—",
            look,
            "+".join(m.value[0] for m in brief.media_preference),
            (brief.queries.primary[0] if brief.queries.primary else "[red]— nenhuma —[/red]"),
            brief.slug,
        )

    console.print(table)

    # ---- resumo ----
    intents: dict[str, int] = {}
    for brief in resultado.briefs:
        intents[brief.intent.value] = intents.get(brief.intent.value, 0) + 1
    com_era = sum(1 for b in resultado.briefs if b.era)
    com_archival = sum(1 for b in resultado.briefs if b.queries.archival)
    sem_query = sum(1 for b in resultado.briefs if not b.queries.primary)
    sensiveis = sum(1 for b in resultado.briefs if b.sensitivity is not Sensitivity.NONE)

    console.print("\n[bold]Resumo[/bold]")
    console.print(
        "  intenções: "
        + " · ".join(f"{k}={v}" for k, v in sorted(intents.items(), key=lambda x: -x[1]))
    )
    console.print(
        f"  com era histórica: {com_era}/{len(resultado.briefs)}"
        f" · com query de arquivo: {com_archival}"
        f" · sensíveis: {sensiveis}"
    )
    if sem_query:
        console.print(f"  [red]sem query primária: {sem_query}[/red]")
    if resultado.emergencia:
        console.print(f"  [yellow]briefs de emergência: {resultado.emergencia}[/yellow]")
    console.print(
        f"  lotes: {resultado.lotes} · {resultado.cache} · provedores: "
        + (", ".join(f"{k} ({v}x)" for k, v in resultado.provedores_usados.items()) or "só cache")
    )

    if resultado.avisos:
        console.print(f"\n[yellow]Avisos ({len(resultado.avisos)}):[/yellow]")
        for aviso in resultado.avisos[:12]:
            console.print(f"  • {aviso}")
        if len(resultado.avisos) > 12:
            console.print(f"  [dim]... e mais {len(resultado.avisos) - 12}[/dim]")

    if saida_json:
        payload = {
            "legenda": str(legenda),
            "canal": cfg.slug,
            "tema": tema,
            "avisos": resultado.avisos,
            "briefs": [b.model_dump(mode="json") for b in resultado.briefs],
        }
        saida_json.parent.mkdir(parents=True, exist_ok=True)
        saida_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"\n[green]JSON gravado em {saida_json}[/green]")


# ---------------------------------------------------------------------------
# Pipeline completo
# ---------------------------------------------------------------------------


@app.command()
def run(
    legenda: Path = typer.Argument(..., help="Arquivo .srt ou .vtt"),
    canal: str = typer.Option(..., "--canal", "-c", help="Slug do pack de canal"),
    saida: Path | None = typer.Option(None, "--saida", "-o", help="Pasta de entrega"),
    limite: int = typer.Option(0, "--limite", "-n", help="Processar só os N primeiros blocos"),
    so_links: bool = typer.Option(
        False, "--so-links", help="Não baixa nada: só gera o relatório de links"
    ),
    sem_alternativas: bool = typer.Option(
        False, "--sem-alternativas", help="Baixa apenas o escolhido de cada bloco"
    ),
    baixar_filmes: bool = typer.Option(
        False, "--baixar-filmes", help="Baixa também filmes de arquivo inteiros (GB)"
    ),
    tema: str | None = typer.Option(None, "--tema", help="Tema do vídeo"),
) -> None:
    """Executa o pipeline: legenda → blocos → briefs → busca → entrega."""
    from .output.deliver import entregar, escrever_relatorio
    from .pipeline import Pipeline

    try:
        cfg = load_channel(canal)
    except FileNotFoundError:
        console.print(f"[red]canal '{canal}' não encontrado.[/red]")
        raise typer.Exit(code=1) from None

    pasta = saida or Path("saida") / f"{datetime.now():%Y-%m-%d}_{cfg.slug}"
    pipeline = Pipeline(cfg)

    console.print(f"\n[bold]{legenda.name}[/bold] · canal [cyan]{cfg.nome}[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
        transient=True,
    ) as progress:
        tarefas: dict[str, Any] = {}

        def avancar(etapa: str, feito: int, total: int) -> None:
            if etapa not in tarefas:
                tarefas[etapa] = progress.add_task(etapa, total=total)
            progress.update(tarefas[etapa], completed=feito, total=total)

        try:
            resultado = pipeline.executar(
                legenda, limite_blocos=limite, tema=tema, progresso=avancar
            )
        except (FileNotFoundError, SubtitleParseError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from None
        except LLMError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from None

    total = len(resultado.blocos)
    com = resultado.com_resultado
    sem = resultado.sem_resultado
    videos = sum(1 for r in com if r.escolhido[0].media_type.value == "video")

    table = Table(show_lines=False, box=None, pad_edge=False)
    table.add_column("#", justify="right", style="bold")
    table.add_column("dur", justify="right", no_wrap=True)
    table.add_column("res", justify="center", no_wrap=True)
    table.add_column("tipo", no_wrap=True)
    table.add_column("asset", justify="right", no_wrap=True)
    table.add_column("provedor", no_wrap=True)
    table.add_column("query", no_wrap=True, overflow="ellipsis", max_width=38)

    largura = len(str(total))
    for r in resultado.resultados:
        if not r.encontrou:
            table.add_row(
                str(r.block.number).zfill(largura),
                f"{r.block.duration_s:.1f}s",
                "[red]✗[/red]",
                "—", "—", "—",
                (r.brief.queries.primary[0] if r.brief.queries.primary else "—"),
            )
            continue
        asset, _ = r.escolhido
        tipo = "vídeo" if asset.media_type.value == "video" else "imagem"
        table.add_row(
            str(r.block.number).zfill(largura),
            f"{r.block.duration_s:.1f}s",
            "[green]✓[/green]",
            tipo,
            f"{asset.duration_s:.1f}s" if asset.duration_s else f"{asset.width}x{asset.height}",
            asset.provider,
            (r.brief.queries.primary[0] if r.brief.queries.primary else "—"),
        )

    console.print(table)
    console.print("\n[bold]Resumo da busca[/bold]")
    console.print(
        f"  blocos: {total} · com resultado: [green]{len(com)}[/green]"
        f" ({len(com) / total:.0%})" if total else "  sem blocos"
    )
    console.print(
        f"  vídeo: {videos} · imagem: {len(com) - videos} · "
        f"sem nada: [red]{len(sem)}[/red]"
    )
    console.print(f"  cache de busca: {resultado.cache_busca}")
    if resultado.briefing:
        extra = ""
        if resultado.briefing.emergencia:
            extra = f" · emergência: {resultado.briefing.emergencia}"
        console.print(f"  briefing: {resultado.briefing.cache}{extra}")

    erros = [e for r in resultado.resultados for e in r.erros]
    if erros:
        console.print(f"\n[yellow]Erros de provedor ({len(erros)}):[/yellow]")
        for erro in list(dict.fromkeys(erros))[:8]:
            console.print(f"  • {erro}")

    relatorio = escrever_relatorio(resultado, pasta / "_RELATORIO.md")
    console.print(f"\n[green]Relatório: {relatorio}[/green]")

    if so_links:
        console.print("[dim]--so-links: nada foi baixado[/dim]")
        return

    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("baixando"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
        transient=True,
    ) as progress:
        tarefa = progress.add_task("download", total=max(1, len(com)))
        entrega = entregar(
            resultado,
            pasta,
            alternativas=not sem_alternativas,
            baixar_filmes_inteiros=baixar_filmes,
            progresso=lambda f, t: progress.update(tarefa, completed=f, total=t),
        )

    console.print(
        f"[green]{entrega.baixados} arquivos[/green] em [bold]{entrega.pasta}[/bold]"
        f" · {entrega.bytes_totais / 1e6:.1f} MB"
    )
    if entrega.pendentes:
        console.print(
            f"[yellow]{len(entrega.pendentes)} blocos pendentes[/yellow] — filmes de "
            f"arquivo inteiros, aguardam corte por cena (fase 5). "
            f"Ver _PENDENTES-CORTE-POR-CENA.txt"
        )
    if entrega.falhas:
        console.print(f"[yellow]falhas de download ({len(entrega.falhas)}):[/yellow]")
        for falha in entrega.falhas[:6]:
            console.print(f"  • {falha}")


if __name__ == "__main__":  # pragma: no cover
    app()
