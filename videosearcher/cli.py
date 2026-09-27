"""CLI do videosearcher."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from . import __version__
from .core import registry
from .core.config import list_channels, load_channel
from .llm.chain import LLMChain
from .llm.providers.specs import list_specs
from .script.blocker import build_blocks, summarize
from .script.parser import SubtitleParseError, parse_subtitles

load_dotenv()

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


if __name__ == "__main__":  # pragma: no cover
    app()
