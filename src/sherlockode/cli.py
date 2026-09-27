import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from sherlockode.app import Application
from sherlockode.catalog.catalog import UnknownScopeError
from sherlockode.config.settings import Settings, load_settings
from sherlockode.investigation.models import InvestigationRequest
from sherlockode.investigation.rendering import render_markdown
from sherlockode.investigation.service import InvestigationService
from sherlockode.workspace.layout import Workspace

app = typer.Typer(help="Ask questions about your software repositories.", no_args_is_help=True)
investigations_app = typer.Typer(help="Browse past investigations.", no_args_is_help=True)
app.add_typer(investigations_app, name="investigations")

console = Console()
ScopeOption = Annotated[list[str] | None, typer.Option("--scope", "-s", help="Group or repository; repeatable.")]


class CliState(BaseModel):
    config: Path | None = None


state = CliState()


@app.callback()
def main(
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="TOML configuration file.", envvar="REPO_AGENT_CONFIG")
    ] = None,
) -> None:
    state.config = config


def _settings() -> Settings:
    settings = load_settings(state.config)
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return settings


def _with_app[T](action: Callable[[Application], Awaitable[T]]) -> T:
    async def run() -> T:
        async with Application.open(_settings()) as application:
            return await action(application)

    try:
        return asyncio.run(run())
    except UnknownScopeError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(2) from None


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Natural-language question.")],
    scope: ScopeOption = None,
    plan: Annotated[bool | None, typer.Option("--plan/--no-plan", help="Override the planning phase.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full report as JSON.")] = False,
) -> None:
    """Investigate a question and print an evidence-backed answer."""
    request = InvestigationRequest(question=question, scope=scope or [], planning=plan)

    async def investigate(application: Application) -> None:
        report = await InvestigationService(application).investigate(request)
        if as_json:
            console.print_json(report.model_dump_json())
        else:
            console.print(Markdown(render_markdown(report)))
            console.print(f"[dim]Saved to {application.workspace.investigation(report.manifest.id).root}[/dim]")

    _with_app(investigate)


@app.command()
def repos(scope: ScopeOption = None) -> None:
    """List repositories in the catalog, optionally restricted to groups."""

    async def show(application: Application) -> None:
        catalog = await application.catalog()
        table = Table("name", "provider", "full path", "tags", "cloned")
        for repository in catalog.resolve_scope(scope or ["all"]):
            cloned = "yes" if application.checkouts.is_cloned(repository) else ""
            tags = ", ".join(sorted(repository.tags))
            table.add_row(repository.name, repository.provider, repository.full_path or repository.url, tags, cloned)
        console.print(table)

    _with_app(show)


@app.command()
def groups() -> None:
    """List logical repository groups."""

    async def show(application: Application) -> None:
        table = Table("group", "repositories", "description")
        for group in (await application.catalog()).groups():
            table.add_row(group.name, ", ".join(group.repositories), group.description or "")
        console.print(table)

    _with_app(show)


@app.command()
def sync(scope: ScopeOption = None) -> None:
    """Clone or update repositories into the workspace."""

    async def run(application: Application) -> None:
        catalog = await application.catalog()
        for outcome in await application.checkouts.sync(catalog.resolve_scope(scope or [])):
            status = f"[red]{outcome.error}[/red]" if outcome.error else f"[green]{outcome.path}[/green]"
            console.print(f"{outcome.repository}: {status}")

    _with_app(run)


@app.command("config")
def show_config() -> None:
    """Print the effective configuration with secrets redacted."""
    console.print_json(json.dumps(_settings().redacted()))


@investigations_app.command("list")
def list_investigations() -> None:
    """List stored investigations."""
    workspace = Workspace(_settings().workspace)
    table = Table("id", "status", "question")
    for paths in workspace.list_investigations() if workspace.investigations.is_dir() else []:
        manifest = json.loads(paths.manifest.read_text()) if paths.manifest.is_file() else {}
        table.add_row(paths.id, manifest.get("status", "?"), manifest.get("question", ""))
    console.print(table)


@investigations_app.command("show")
def show_investigation(investigation_id: str) -> None:
    """Print a stored investigation report."""
    paths = Workspace(_settings().workspace).investigation(investigation_id)
    if not paths.report_markdown.is_file():
        console.print(f"[yellow]No report; see {paths.manifest}[/yellow]")
        raise typer.Exit(1)
    console.print(Markdown(paths.report_markdown.read_text()))
