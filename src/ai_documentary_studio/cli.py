"""CLI entrypoint for ai-documentary-studio."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from .core.orchestrator import Orchestrator, slugify

log = logging.getLogger(__name__)


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config(config_path: str = "config/default.yaml") -> dict:
    import yaml

    path = Path(config_path)
    if not path.exists():
        return {}
    with path.open("r") as f:
        return yaml.safe_load(f) or {}


@click.group()
@click.option("--config", default="config/default.yaml", help="Path to config YAML")
@click.option("--log-level", default="INFO", help="Log level (DEBUG/INFO/WARNING/ERROR)")
@click.pass_context
def cli(ctx, config: str, log_level: str) -> None:
    """ai-documentary-studio — autonomous AI documentary production."""
    setup_logging(log_level)
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config)


@cli.command()
@click.argument("topic")
@click.option("--duration", default="10m", help="Target duration (e.g. 10m, 15m)")
@click.option("--style", default="cinematic", help="Documentary style")
@click.option("--workspace", default=None, help="Project workspace path (default: projects/<slug>)")
@click.pass_context
def produce(ctx, topic: str, duration: str, style: str, workspace: str | None) -> None:
    """Produce a full documentary from a single topic."""
    config = ctx.obj["config"]
    slug = slugify(topic)
    ws = workspace or (Path(config.get("project", {}).get("workspace_root", "projects")) / slug)
    click.echo(f"🎬 Producing documentary: {topic}")
    click.echo(f"   Slug: {slug}")
    click.echo(f"   Workspace: {ws}")
    click.echo(f"   Duration: {duration} | Style: {style}")
    click.echo("")

    orch = Orchestrator(config, slug, ws)
    result = orch.run(topic=topic, duration=duration, style=style)

    if result["status"] == "complete":
        click.echo(click.style("✅ Documentary production complete!", fg="green", bold=True))
        click.echo(f"   Final MP4: {ws}/renders/{slug}.mp4")
        click.echo(f"   QA report: {ws}/qa_report.md")
    else:
        click.echo(click.style(f"❌ Production failed: {result.get('error', 'unknown')}", fg="red", bold=True))
        sys.exit(1)


@cli.command()
@click.argument("topic")
@click.pass_context
def status(ctx, topic: str) -> None:
    """Check the status of a documentary production."""
    config = ctx.obj["config"]
    slug = slugify(topic)
    ws = Path(config.get("project", {}).get("workspace_root", "projects")) / slug
    if not ws.exists():
        click.echo(f"No project found for slug: {slug}")
        sys.exit(1)
    orch = Orchestrator(config, slug, ws)
    status = orch.status()
    click.echo(f"Project: {slug}")
    for stage, st in status["stages"].items():
        color = "green" if st == "complete" else ("yellow" if st == "in_progress" else "red")
        click.echo(click.style(f"  {stage}: {st}", fg=color))


@cli.command(name="download-youtube")
@click.argument("url_or_query")
@click.option("--quality", default="1080p", help="Max quality")
@click.option("--output", default=None, help="Output directory")
@click.pass_context
def download_youtube(ctx, url_or_query: str, quality: str, output: str | None) -> None:
    """Download a YouTube video by URL or search query.

    This is the user's primary feature: download YouTube videos and store them
    in the library for later use by the documentary pipeline.
    """
    from .media.youtube import YouTubeDownloader

    config = ctx.obj["config"]
    cache_dir = output or config.get("media", {}).get("youtube", {}).get("cache_dir", "downloads/youtube")
    dl = YouTubeDownloader(config, cache_dir=cache_dir)

    if url_or_query.startswith("http"):
        click.echo(f"📥 Downloading: {url_or_query}")
        result = dl.download(url_or_query, quality=quality)
    else:
        click.echo(f"🔍 Searching YouTube for: {url_or_query}")
        result = dl.search_and_download(url_or_query, quality=quality)

    if result.get("video_path"):
        click.echo(click.style("✅ Downloaded!", fg="green", bold=True))
        click.echo(f"   Video: {result['video_path']}")
        click.echo(f"   Audio: {result.get('audio_path', 'n/a')}")
        click.echo(f"   Cached: {result.get('cached', False)}")
        click.echo(f"   SHA256: {result.get('sha256', 'n/a')[:16]}...")
    else:
        click.echo(click.style("❌ Download failed", fg="red", bold=True))
        sys.exit(1)


@cli.command()
@click.pass_context
def agents(ctx) -> None:
    """List all available agents and their stages."""
    click.echo("ai-documentary-studio agents:")
    agents_list = [
        ("P1", "Research Planner"),
        ("P2", "Research Collector"),
        ("P3", "Truth (verification)"),
        ("P4", "Story Writer"),
        ("P5", "Documentary Director"),
        ("P6", "Visual Planner"),
        ("P7", "Asset Acquisition"),
        ("P8", "Semantic Clip Selection"),
        ("P9", "Narration Director"),
        ("P10", "Animation Director"),
        ("P11", "Music Director"),
        ("P12", "Video Editing"),
        ("P13", "Rendering"),
        ("P14", "Quality Assurance"),
        ("—", "Orchestrator (manages all)"),
        ("—", "Verifier (validates all)"),
        ("—", "Tester (tests all)"),
    ]
    for stage, name in agents_list:
        click.echo(f"  [{stage}] {name}")


@cli.command()
@click.pass_context
def doctor(ctx) -> None:
    """Check system dependencies and configuration."""
    config = ctx.obj["config"]
    click.echo("🔍 System check:")
    checks = [
        ("Python", sys.version.split()[0]),
        ("FFmpeg", _check_cmd("ffmpeg")),
        ("ffprobe", _check_cmd("ffprobe")),
        ("yt-dlp", _check_cmd("yt-dlp")),
        ("Node.js", _check_cmd("node")),
        ("npx", _check_cmd("npx")),
        ("HyperFrames", _check_npx("hyperframes")),
    ]
    for name, val in checks:
        if val:
            click.echo(click.style(f"  ✅ {name}: {val}", fg="green"))
        else:
            click.echo(click.style(f"  ❌ {name}: not found", fg="red"))

    # API keys
    import os

    click.echo("\n🔑 API keys:")
    for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY"]:
        val = os.environ.get(key)
        if val:
            click.echo(click.style(f"  ✅ {key}: set ({val[:8]}...)", fg="green"))
        else:
            click.echo(click.style(f"  ⚠️  {key}: not set (will use fallback)", fg="yellow"))


def _check_cmd(cmd: str) -> str:
    import shutil

    path = shutil.which(cmd)
    return path or ""


def _check_npx(pkg: str) -> str:
    import subprocess

    try:
        r = subprocess.run(["npx", "--yes", pkg, "--version"], capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
