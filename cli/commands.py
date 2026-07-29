"""CLI commands for Hime."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from hime.app import App
from hime.proxy import ProxyType

logger = logging.getLogger(__name__)

app = typer.Typer(help="Hime — Mass Google Scraper with Proxy Rotation")
console = Console()


def _run(coro):
    """Run async function from sync CLI."""
    return asyncio.run(coro)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    lang: str = typer.Option("ru", "--lang", "-l", help="Search language"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
):
    """Search Google via proxy rotation."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Searching: {query}...", total=None)

        async def _run_search():
            app_inst = App()
            try:
                await app_inst.init()
                results = await app_inst.search(query, lang, page)
                return results
            finally:
                await app_inst.close()

        results = _run(_run_search())
        progress.update(task, description=f"Found {len(results)} results")

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        raise typer.Exit()

    table = Table(title=f"Results for: {query} (page {page})")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="bold")
    table.add_column("URL", style="cyan")
    table.add_column("Snippet", max_width=60)

    for r in results:
        table.add_row(str(r.position), r.title, r.url, r.snippet[:80])

    console.print(table)


@app.command()
def load(
    check: bool = typer.Option(False, "--check", "-c", help="Run health check after loading"),
):
    """Load proxies from GitHub sources (auto)."""
    from hime.config import load_config
    from hime.storage import ProxyStore
    from hime.proxy.loader import load_all_proxies

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    async def _load():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Loading proxies from GitHub...", total=None)
            proxies = await load_all_proxies()
            progress.update(task, description=f"Loaded {len(proxies)} proxies, saving to DB...")
            if proxies:
                store.bulk_upsert(proxies)
            return proxies

    proxies = _run(_load())
    counts = store.count()
    console.print(f"\n[green]Loaded {len(proxies)} proxies from GitHub.[/green]")
    for status, count in counts.items():
        console.print(f"  {status}: {count}")

    if check and proxies:
        console.print("\n[yellow]Running health check...[/yellow]")
        _proxy_check()


@app.command("proxy")
def proxy_cmd(
    action: str = typer.Argument(..., help="Action: add, list, check"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="Proxy file path"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type: http, https, socks5"),
):
    """Manage proxies."""
    if action == "add":
        if not file:
            console.print("[red]--file is required for proxy add[/red]")
            raise typer.Exit(1)
        _proxy_add(file)
    elif action == "list":
        _proxy_list(status, type)
    elif action == "check":
        _proxy_check()
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        raise typer.Exit(1)


def _proxy_add(file_path: str):
    """Load proxies from file."""
    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    lines = path.read_text().strip().splitlines()
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    from hime.proxy import ProxyData

    proxies = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        proxy = _parse_proxy_line(line)
        if proxy:
            proxies.append(proxy)

    if not proxies:
        console.print("[yellow]No valid proxies found in file.[/yellow]")
        raise typer.Exit()

    store.bulk_upsert(proxies)
    console.print(f"[green]Added {len(proxies)} proxies.[/green]")


def _parse_proxy_line(line: str):
    """Parse proxy line like host:port or protocol://host:port."""
    from hime.proxy import ProxyData, ProxyType

    for proto in ("socks5://", "https://", "http://"):
        if line.startswith(proto):
            rest = line[len(proto) :]
            parts = rest.split(":")
            if len(parts) == 2:
                return ProxyData(
                    ip=parts[0],
                    port=int(parts[1]),
                    type=ProxyType(proto.rstrip("://")),
                )
            return None

    parts = line.split(":")
    if len(parts) == 2:
        return ProxyData(ip=parts[0], port=int(parts[1]), type=ProxyType.HTTP)
    return None


def _proxy_list(status_filter: Optional[str], type_filter: Optional[str]):
    """List proxies."""
    from hime.config import load_config
    from hime.storage import ProxyStore
    from hime.proxy import ProxyStatus

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    if status_filter:
        try:
            ps = ProxyStatus(status_filter)
        except ValueError:
            console.print(f"[red]Invalid status: {status_filter}[/red]")
            raise typer.Exit(1)
        proxies = store.get_by_status(ps)
    else:
        proxies = store.get_all()

    if type_filter:
        try:
            from hime.proxy import ProxyType
            tf = ProxyType(type_filter)
            proxies = [p for p in proxies if p.type == tf]
        except ValueError:
            console.print(f"[red]Invalid type: {type_filter}[/red]")
            raise typer.Exit(1)

    if not proxies:
        console.print("[yellow]No proxies found.[/yellow]")
        raise typer.Exit()

    table = Table(title=f"Proxies ({len(proxies)})")
    table.add_column("UUID", style="dim", max_width=8)
    table.add_column("IP", style="cyan")
    table.add_column("Port")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Source")
    table.add_column("Failures")
    table.add_column("Resp (ms)")
    table.add_column("Last Check")

    status_colors = {
        "active": "green",
        "dead": "red",
        "unknown": "yellow",
    }

    for p in proxies:
        color = status_colors.get(p.status.value, "white")
        table.add_row(
            p.uuid[:8],
            p.ip,
            str(p.port),
            p.type.value,
            f"[{color}]{p.status.value}[/{color}]",
            p.source or "-",
            str(p.failure_count),
            f"{p.response_time:.0f}" if p.response_time else "-",
            _format_time(p.last_check),
        )

    console.print(table)

    counts = store.count()
    console.print(f"\nTotal: {sum(counts.values())} | ", end="")
    for status, count in counts.items():
        console.print(f"{status}: {count} | ", end="")
    console.print()


def _format_time(ts: float) -> str:
    """Format timestamp to human-readable string."""
    if not ts:
        return "-"
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _proxy_check():
    """Check all proxies health."""
    from hime.config import load_config
    from hime.storage import ProxyStore
    from hime.proxy.manager import ProxyChecker

    config = load_config()
    store = ProxyStore(config.sqlite_path)
    proxies = store.get_all()

    if not proxies:
        console.print("[yellow]No proxies to check.[/yellow]")
        raise typer.Exit()

    checker = ProxyChecker(
        timeout=config.proxy.health_check_timeout,
        test_url=config.proxy.health_check_url,
    )

    async def _check_all():
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Checking {len(proxies)} proxies...", total=len(proxies))

            for p in proxies:
                alive, resp_time = await checker.check(p)
                p.mark_checked(alive, resp_time)
                store.upsert(p)
                progress.advance(task)

    _run(_check_all())

    counts = store.count()
    active = counts.get("active", 0)
    dead = counts.get("dead", 0)
    console.print(f"\n[green]Active: {active}[/green] | [red]Dead: {dead}[/red]")


@app.command()
def stats():
    """Show statistics."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)
    counts = store.count()

    table = Table(title="Hime Statistics")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Total proxies", str(sum(counts.values())))
    for status, count in counts.items():
        table.add_row(f"  {status}", str(count))

    console.print(table)


@app.command()
def api(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
):
    """Start the API server (alias for 'serve')."""
    return _serve(host, port)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
):
    """Start the API server (FastAPI + uvicorn)."""
    return _serve(host, port)


def _serve(
    host: str = "0.0.0.0",
    port: int = 8000,
):
    """Start the API server (FastAPI + uvicorn)."""
    from hime.api.app import create_app

    console.print(f"[green]Starting Hime API on {host}:{port}[/green]")
    try:
        import uvicorn

        fastapi_app = create_app()
        config = uvicorn.Config(
            fastapi_app,
            host=host,
            port=port,
            log_level="info",
            access_log=True,
        )
        server = uvicorn.Server(config)
        server.run()
    except ImportError:
        console.print("[red]uvicorn not installed. Run: pip install uvicorn[/red]")
        raise typer.Exit(1)
