"""CLI — Typer-based commands for ai_repo."""

import asyncio
import logging
import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="ai-repo",
    help="AI-Aware Repo — index, query, and explore any codebase.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


# ── index ────────────────────────────────────────────────────────────────

@app.command()
def index(
    repo_path: str = typer.Option(default=".", help="Path to repository"),
    repo_id: str = typer.Option(default="default", help="Repository identifier"),
    full: bool = typer.Option(default=False, help="Full re-index (not incremental)"),
    bootstrap: bool = typer.Option(default=False, help="Run auto-bootstrap after indexing"),
    verbose: bool = typer.Option(default=False, help="Verbose logging"),
):
    """Index a repository: scan, parse, chunk, embed, and build graph."""
    _setup_logging(verbose)

    from ai_repo.core.database import Database
    from ai_repo.core.embeddings import EmbeddingClient
    from ai_repo.core.indexer import Indexer

    db = Database()
    indexer = Indexer(db=db)

    console.print(f"[bold]Indexing[/bold] {repo_path} (repo_id={repo_id})...")
    start = time.time()
    stats = indexer.index_repo(repo_path, repo_id=repo_id, incremental=not full)
    elapsed = time.time() - start

    table = Table(title="Indexing Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    for k, v in stats.items():
        table.add_row(k, str(v))
    table.add_row("time", f"{elapsed:.1f}s")
    console.print(table)

    # Generate embeddings for new chunks
    embedder = EmbeddingClient()
    chunks = db.get_chunks_without_embeddings(limit=500)
    if chunks:
        console.print(f"Generating embeddings for {len(chunks)} chunks...")
        texts = [c.content for c in chunks]
        embeddings = embedder.embed_batch_sync(texts)
        updates = [
            (c.id, emb) for c, emb in zip(chunks, embeddings) if emb is not None
        ]
        if updates:
            db.bulk_update_embeddings(updates)
            console.print(f"[green]Embedded {len(updates)} chunks[/green]")

    # Auto-bootstrap memory
    if bootstrap:
        from ai_repo.core.memory import MemoryManager
        mm = MemoryManager(db=db)
        console.print("Running auto-bootstrap...")
        count = asyncio.run(mm.auto_bootstrap(repo_id))
        console.print(f"[green]Stored {count} memory facts[/green]")


# ── query ────────────────────────────────────────────────────────────────

@app.command()
def query(
    question: str = typer.Argument(help="Question to ask about the codebase"),
    repo_id: str = typer.Option(default="default", help="Repository identifier"),
    top_k: int = typer.Option(default=10, help="Number of results"),
    verbose: bool = typer.Option(default=False, help="Verbose logging"),
):
    """Query the codebase using RAG pipeline."""
    _setup_logging(verbose)

    from ai_repo.core.database import Database
    from ai_repo.core.llm import LLMClient
    from ai_repo.core.memory import MemoryManager
    from ai_repo.core.prompt_composer import PromptComposer
    from ai_repo.core.retriever import Retriever

    db = Database()
    retriever = Retriever(db=db)
    composer = PromptComposer(db=db)
    llm = LLMClient()
    memory = MemoryManager(db=db)

    # Retrieve
    console.print(f"[dim]Retrieving context for: {question}[/dim]")
    start = time.time()
    results = retriever.retrieve_sync(question, repo_id=repo_id, top_k=top_k)

    # Get relevant memory facts
    facts = memory.search_facts(query=question)

    # Compose prompt
    system_prompt, user_prompt = composer.compose(question, results, facts)

    # Generate
    console.print("[dim]Generating answer...[/dim]")
    answer = asyncio.run(llm.generate(prompt=user_prompt, system=system_prompt))
    elapsed = time.time() - start

    console.print()
    console.print(answer)
    console.print(f"\n[dim]({len(results)} chunks, {len(facts)} facts, {elapsed:.1f}s)[/dim]")


# ── graph ────────────────────────────────────────────────────────────────

@app.command()
def graph(
    symbol_name: str = typer.Argument(help="Symbol name to explore"),
    depth: int = typer.Option(default=1, help="Traversal depth"),
    repo_id: str = typer.Option(default="", help="Repository identifier (empty=all)"),
    verbose: bool = typer.Option(default=False, help="Verbose logging"),
):
    """Show neighbors of a symbol in the code graph."""
    _setup_logging(verbose)

    from ai_repo.core.database import Database

    db = Database()
    rid = repo_id if repo_id else None
    symbols = db.get_symbol_by_name(symbol_name, repo_id=rid)

    if not symbols:
        console.print(f"[red]Symbol '{symbol_name}' not found[/red]")
        raise typer.Exit(1)

    for sym in symbols:
        console.print(f"\n[bold]{sym.name}[/bold] ({sym.kind}) in `{sym.file_path}:{sym.start_line}`")
        if sym.signature:
            console.print(f"  [dim]{sym.signature}[/dim]")

        neighbors = db.get_neighbors(sym.id, depth=depth)
        if neighbors:
            table = Table(title=f"Neighbors (depth={depth})")
            table.add_column("Name", style="cyan")
            table.add_column("Kind")
            table.add_column("File")
            table.add_column("Edge")
            table.add_column("Depth")
            for n in neighbors:
                table.add_row(
                    n["name"], n["kind"], n["file_path"],
                    n["edge_type"], str(n["depth"]),
                )
            console.print(table)
        else:
            console.print("  [dim]No neighbors found[/dim]")


# ── explain ──────────────────────────────────────────────────────────────

@app.command()
def explain(
    symbol_name: str = typer.Argument(help="Symbol to explain"),
    repo_id: str = typer.Option(default="", help="Repository identifier (empty=all)"),
    verbose: bool = typer.Option(default=False, help="Verbose logging"),
):
    """Explain a symbol using LLM with graph context."""
    _setup_logging(verbose)

    from ai_repo.core.database import Database
    from ai_repo.core.llm import LLMClient

    db = Database()
    llm = LLMClient()
    rid = repo_id if repo_id else None
    symbols = db.get_symbol_by_name(symbol_name, repo_id=rid)

    if not symbols:
        console.print(f"[red]Symbol '{symbol_name}' not found[/red]")
        raise typer.Exit(1)

    sym = symbols[0]
    neighbors = db.get_neighbors(sym.id, depth=2)
    impact = db.get_impact(sym.id, depth=2)

    context_parts = [
        f"Symbol: {sym.name} ({sym.kind})",
        f"File: {sym.file_path}:{sym.start_line}",
    ]
    if sym.signature:
        context_parts.append(f"Signature: {sym.signature}")
    if sym.docstring:
        context_parts.append(f"Docstring: {sym.docstring}")
    if neighbors:
        context_parts.append("\nNeighbors:")
        for n in neighbors[:20]:
            context_parts.append(f"  - {n['name']} ({n['kind']}, {n['edge_type']})")
    if impact:
        context_parts.append("\nDependent symbols (impact):")
        for i in impact[:20]:
            context_parts.append(f"  - {i['name']} ({i['kind']}, {i['edge_type']})")

    context = "\n".join(context_parts)
    prompt = f"Explain what this symbol does, its role in the project, and how it relates to other components:\n\n{context}"

    console.print("[dim]Generating explanation...[/dim]")
    answer = asyncio.run(llm.generate(
        prompt=prompt,
        system="You are a code documentation assistant. Be concise and precise.",
    ))
    console.print()
    console.print(answer)


# ── serve ────────────────────────────────────────────────────────────────

@app.command()
def serve(
    host: str = typer.Option(default="0.0.0.0", help="Bind host"),
    port: int = typer.Option(default=8100, help="Bind port"),
    verbose: bool = typer.Option(default=False, help="Verbose logging"),
):
    """Start the FastAPI server."""
    _setup_logging(verbose)
    import uvicorn
    from ai_repo.api.server import create_app

    app_instance = create_app()
    uvicorn.run(
        app_instance,
        host=host,
        port=port,
        loop="asyncio",
        server_header=False,
    )


# ── plugin ───────────────────────────────────────────────────────────────

plugin_app = typer.Typer(help="Plugin management commands")
app.add_typer(plugin_app, name="plugin")


@plugin_app.command("install")
def plugin_install(
    url: str = typer.Argument(help="Git URL of plugin to install"),
    ref: str = typer.Option(default="main", help="Git ref (branch/tag)"),
):
    """Install a plugin from a git repository."""
    from ai_repo.plugins.installer import PluginInstaller

    installer = PluginInstaller()
    try:
        name = installer.install(url, ref=ref)
        console.print(f"[green]Installed plugin: {name}[/green]")
    except Exception as e:
        console.print(f"[red]Installation failed: {e}[/red]")
        raise typer.Exit(1)


@plugin_app.command("list")
def plugin_list():
    """List installed plugins."""
    from ai_repo.plugins.loader import PluginLoader

    loader = PluginLoader()
    plugins = loader.discover()

    if not plugins:
        console.print("[dim]No plugins found[/dim]")
        return

    table = Table(title="Installed Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Version")
    table.add_column("Description")
    for p in plugins:
        table.add_row(p["name"], p.get("version", "?"), p.get("description", ""))
    console.print(table)


if __name__ == "__main__":
    app()
