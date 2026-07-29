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
            proxies = await load_all_proxies(store)
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
    table.add_column("Latency (ms)")
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
            f"{p.latency_ms:.0f}" if p.latency_ms else "-",
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
    port: int = typer.Option(8008, "--port", "-p", help="Bind port"),
):
    """Start the API server (alias for 'serve')."""
    return _serve(host, port)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8008, "--port", "-p", help="Bind port"),
):
    """Start the API server (FastAPI + uvicorn)."""
    return _serve(host, port)


def _serve(
    host: str = "0.0.0.0",
    port: int = 8008,
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


@app.command("source")
def source_cmd(
    action: str = typer.Argument(..., help="Action: list, add, remove, enable, disable, seed"),
    url: Optional[str] = typer.Option(None, help="Source URL (for add)"),
    source_id: Optional[str] = typer.Option(None, "--id", help="Source UUID"),
    type_hint: str = typer.Option("http", "--type", "-t", help="Proxy type hint"),
):
    """Manage proxy sources."""
    if action == "list":
        _source_list()
    elif action == "add":
        if not url:
            console.print("[red]--url is required for source add[/red]")
            raise typer.Exit(1)
        _source_add(url, type_hint)
    elif action == "remove":
        if not source_id:
            console.print("[red]--id is required for source remove[/red]")
            raise typer.Exit(1)
        _source_remove(source_id)
    elif action == "enable":
        if not source_id:
            console.print("[red]--id is required for source enable[/red]")
            raise typer.Exit(1)
        _source_enable(source_id)
    elif action == "disable":
        if not source_id:
            console.print("[red]--id is required for source disable[/red]")
            raise typer.Exit(1)
        _source_disable(source_id)
    elif action == "seed":
        _source_seed()
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        raise typer.Exit(1)


def _source_list():
    """List all proxy sources."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)
    sources = store.list_sources()

    if not sources:
        console.print("[yellow]No sources found. Run: hime source seed[/yellow]")
        raise typer.Exit()

    table = Table(title=f"Proxy Sources ({len(sources)})")
    table.add_column("UUID", style="dim", max_width=8)
    table.add_column("URL", style="cyan")
    table.add_column("Type")
    table.add_column("Enabled")
    table.add_column("Last Fetch")

    for s in sources:
        enabled_color = "green" if s.enabled else "red"
        table.add_row(
            s.uuid[:8],
            s.url,
            s.type_hint,
            f"[{enabled_color}]{'yes' if s.enabled else 'no'}[/{enabled_color}]",
            _format_time(s.last_fetch) if s.last_fetch else "-",
        )

    console.print(table)

    enabled_count = sum(1 for s in sources if s.enabled)
    console.print(f"\nTotal: {len(sources)} | Enabled: {enabled_count} | Disabled: {len(sources) - enabled_count}")


def _source_add(url: str, type_hint: str):
    """Add a proxy source."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    # Check for duplicate
    existing = store.get_source_by_url(url)
    if existing:
        console.print(f"[yellow]Source already exists: {existing.uuid[:8]}[/yellow]")
        raise typer.Exit()

    source = store.add_source(url, type_hint)
    console.print(f"[green]Added source: {source.uuid[:8]} — {url}[/green]")


def _source_remove(source_id: str):
    """Remove a proxy source."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    # Find full UUID
    sources = store.list_sources()
    target = None
    for s in sources:
        if s.uuid.startswith(source_id):
            target = s
            break

    if not target:
        console.print(f"[red]Source not found: {source_id}[/red]")
        raise typer.Exit(1)

    store.delete_source(target.uuid)
    console.print(f"[green]Removed source: {target.uuid[:8]} — {target.url}[/green]")


def _source_enable(source_id: str):
    """Enable a proxy source."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    sources = store.list_sources()
    target = None
    for s in sources:
        if s.uuid.startswith(source_id):
            target = s
            break

    if not target:
        console.print(f"[red]Source not found: {source_id}[/red]")
        raise typer.Exit(1)

    store.enable_source(target.uuid)
    console.print(f"[green]Enabled source: {target.uuid[:8]} — {target.url}[/green]")


def _source_disable(source_id: str):
    """Disable a proxy source."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    sources = store.list_sources()
    target = None
    for s in sources:
        if s.uuid.startswith(source_id):
            target = s
            break

    if not target:
        console.print(f"[red]Source not found: {source_id}[/red]")
        raise typer.Exit(1)

    store.disable_source(target.uuid)
    console.print(f"[yellow]Disabled source: {target.uuid[:8]} — {target.url}[/yellow]")


def _source_seed():
    """Seed default sources from config into DB."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    urls = [(url, "http") for url in config.proxy.proxy_sources]
    added = store.seed_sources(urls)
    total = len(store.list_sources())
    console.print(f"[green]Seeded {added} new sources ({total} total in DB)[/green]")


@app.command("service")
def service_cmd(
    action: str = typer.Argument(..., help="Action: list, add, remove, get"),
    name: Optional[str] = typer.Option(None, help="Service name (for add)"),
    url: Optional[str] = typer.Option(None, help="Service URL (for add)"),
    service_id: Optional[str] = typer.Option(None, "--id", help="Service UUID"),
    method: str = typer.Option("GET", "--method", "-m", help="HTTP method"),
    proxy: bool = typer.Option(False, "--proxy", help="Use proxy"),
):
    """Manage services."""
    if action == "list":
        _service_list()
    elif action == "add":
        if not name or not url:
            console.print("[red]--name and --url are required for service add[/red]")
            raise typer.Exit(1)
        _service_add(name, url, method, proxy)
    elif action == "remove":
        if not service_id:
            console.print("[red]--id is required for service remove[/red]")
            raise typer.Exit(1)
        _service_remove(service_id)
    elif action == "get":
        if not service_id:
            console.print("[red]--id is required for service get[/red]")
            raise typer.Exit(1)
        _service_get(service_id)
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        raise typer.Exit(1)


def _service_list():
    """List all services."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)
    services = store.list_services()

    if not services:
        console.print("[yellow]No services found.[/yellow]")
        raise typer.Exit()

    table = Table(title=f"Services ({len(services)})")
    table.add_column("UUID", style="dim", max_width=8)
    table.add_column("Name", style="cyan")
    table.add_column("URL")
    table.add_column("Method")
    table.add_column("Proxy")
    table.add_column("Enabled")
    table.add_column("Cache TTL")

    for s in services:
        proxy_color = "green" if s.proxy else "red"
        enabled_color = "green" if s.enabled else "red"
        table.add_row(
            s.uuid[:8],
            s.name,
            s.url[:40],
            s.method,
            f"[{proxy_color}]{'yes' if s.proxy else 'no'}[/{proxy_color}]",
            f"[{enabled_color}]{'yes' if s.enabled else 'no'}[/{enabled_color}]",
            str(s.cache_ttl),
        )

    console.print(table)


def _service_add(name: str, url: str, method: str, proxy: bool):
    """Add a service."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    if store.service_exists(name):
        console.print(f"[yellow]Service '{name}' already exists[/yellow]")
        raise typer.Exit()

    service = store.create_service(name=name, url=url, method=method, proxy=proxy)
    console.print(f"[green]Added service: {service.uuid[:8]} — {name}[/green]")


def _service_remove(service_id: str):
    """Remove a service."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    services = store.list_services()
    target = None
    for s in services:
        if s.uuid.startswith(service_id):
            target = s
            break

    if not target:
        console.print(f"[red]Service not found: {service_id}[/red]")
        raise typer.Exit(1)

    store.delete_service(target.uuid)
    console.print(f"[green]Removed service: {target.uuid[:8]} — {target.name}[/green]")


def _service_get(service_id: str):
    """Get service details."""
    from hime.config import load_config
    from hime.storage import ProxyStore

    config = load_config()
    store = ProxyStore(config.sqlite_path)

    services = store.list_services()
    target = None
    for s in services:
        if s.uuid.startswith(service_id):
            target = s
            break

    if not target:
        console.print(f"[red]Service not found: {service_id}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Service: {target.name}[/bold]")
    console.print(f"  UUID: {target.uuid}")
    console.print(f"  URL: {target.url}")
    console.print(f"  Method: {target.method}")
    console.print(f"  Headers: {target.headers}")
    console.print(f"  Timeout: {target.timeout}s")
    console.print(f"  Cache TTL: {target.cache_ttl}s")
    console.print(f"  Proxy: {'yes' if target.proxy else 'no'}")
    console.print(f"  Enabled: {'yes' if target.enabled else 'no'}")
    console.print(f"  Created: {target.created_at}")
    console.print(f"  Modified: {target.modified_at}")
