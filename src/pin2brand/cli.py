"""Pin2Brand CLI powered by Typer and Rich."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .exporter import run_pin2brand_pipeline
from .scraper import BoardAccessError

app = typer.Typer(
    name="pin2brand",
    help="Compile a public Pinterest board or local image folder into an Agent-Ready Visual Identity Kit.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main_callback() -> None:
    """Pin2Brand CLI root."""


@app.command()
def analyze(
    board_url: str = typer.Argument(..., help="Pinterest board URL or path to a local image folder"),
    max_pins: int = typer.Option(24, "--max-pins", "-n", min=1, max=60, help="Max images to extract"),
    provider: str = typer.Option(
        "auto",
        "--provider",
        "-p",
        help="Vision provider: auto | gemini | openai | ollama | offline",
    ),
    model: str = typer.Option("gemini-2.5-flash", "--model", "-m", help="Vision model name"),
    offline: bool = typer.Option(False, "--offline", help="Force deterministic heuristic synthesis"),
    cookies: Optional[Path] = typer.Option(None, "--cookies", "-c", help="Optional cookies.json or cookies.txt"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir", "-o", help="Root output directory"),
) -> None:
    """Analyze a Pinterest board or local folder and export JSON, AGENTS.md, Cursor .mdc, W3C tokens, CSS, Prompts, and HTML Studio."""
    console.print(
        Panel.fit(
            f"[bold cyan]Pin2Brand[/bold cyan]  |  Target: [white]{board_url}[/white]\n"
            f"Max pins: {max_pins}  |  Provider: {provider}  |  Model: {model}  |  Offline: {offline}",
            border_style="cyan",
        )
    )

    try:
        with console.status("[bold green]Extracting references, computing CIELAB + texture metrics & compiling identity..."):
            result = asyncio.run(
                run_pin2brand_pipeline(
                    board_url=board_url,
                    output_root=output_dir,
                    max_pins=max_pins,
                    model_name=model,
                    force_offline=offline,
                    provider=provider,
                    cookies_path=cookies,
                )
            )
    except BoardAccessError as exc:
        console.print(f"\n[bold red]Pinterest Access Error:[/bold red] {exc}")
        raise typer.Exit(code=2)
    except Exception as exc:
        console.print(f"\n[bold red]Pipeline Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    board = result["board"]
    math_report = result["math_report"]
    manifest = result["manifest"]
    artifacts = result["artifacts"]
    mode = result["synthesis_mode"]

    console.print(
        f"\n[bold green]Done![/bold green] Extracted [bold]{len(board.pins)}[/bold] pins via "
        f"[cyan]{board.source_method}[/cyan] | Synthesis: [magenta]{mode}[/magenta]\n"
        f"Archetype: [bold yellow]{manifest.frontend_ui_rules.aesthetic_archetype}[/bold yellow]\n"
        f"Surface: [white]{math_report.surface_character}[/white] (Grain={math_report.texture_grain_score}, Earth={math_report.earth_tone_ratio}%) | "
        f"Keywords: [dim]{', '.join(manifest.mood_keywords)}[/dim]"
    )

    # Color Palette Table
    color_table = Table(title=f"Extracted Color System — {manifest.project_name}")
    color_table.add_column("Role", style="bold")
    color_table.add_column("Swatch")
    color_table.add_column("HEX", style="cyan")
    color_table.add_column("Name")
    color_table.add_column("Contrast Ink")

    tokens = [
        ("BG Primary", manifest.color_system.background_primary),
        ("BG Secondary", manifest.color_system.background_secondary),
        ("Surface Card", manifest.color_system.surface_card),
        ("Text Primary", manifest.color_system.text_primary),
        ("Text Secondary", manifest.color_system.text_secondary),
        ("Accent Primary", manifest.color_system.accent_primary),
        ("Accent Secondary", manifest.color_system.accent_secondary),
    ]
    for label, tok in tokens:
        color_table.add_row(
            label,
            f"[{tok.hex}]██████[/{tok.hex}]",
            tok.hex,
            tok.name,
            tok.contrast_text_hex,
        )
    console.print(color_table)

    # Generated Artifacts Table
    art_table = Table(title="Generated Multi-Agent Artifacts")
    art_table.add_column("Artifact", style="bold green")
    art_table.add_column("Path")
    for key, path in artifacts.items():
        art_table.add_row(key, str(path.resolve()))
    console.print(art_table)


if __name__ == "__main__":
    app()
