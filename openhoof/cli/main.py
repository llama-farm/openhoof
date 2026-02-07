"""CLI entry point for Atmosphere Agents."""

import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
import uvicorn
import asyncio

app = typer.Typer(name="atmosphere", help="Atmosphere Agents - Extensible AI Agent Platform")
console = Console()


@app.command()
def start(
    port: int = typer.Option(18765, "--port", "-p", help="API port"),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload"),
):
    """Start the Atmosphere Agents server."""
    console.print(f"[bold green]Starting Atmosphere Agents on {host}:{port}[/bold green]")
    console.print(f"[dim]API: http://localhost:{port}/api[/dim]")
    console.print(f"[dim]Health: http://localhost:{port}/api/health[/dim]")
    console.print()
    
    uvicorn.run(
        "openhoof.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def init(
    path: Path = typer.Option(
        Path.home() / ".atmosphere",
        "--path",
        "-p",
        help="Atmosphere home directory"
    ),
):
    """Initialize Atmosphere Agents workspace."""
    console.print(f"[bold]Initializing Atmosphere at {path}[/bold]")
    
    # Create directories
    (path / "agents").mkdir(parents=True, exist_ok=True)
    (path / "plugins" / "tools").mkdir(parents=True, exist_ok=True)
    (path / "plugins" / "triggers").mkdir(parents=True, exist_ok=True)
    (path / "plugins" / "skills").mkdir(parents=True, exist_ok=True)
    (path / "data").mkdir(parents=True, exist_ok=True)
    
    # Create default config
    config_path = path / "config.yaml"
    if not config_path.exists():
        from ..config import Config
        config = Config()
        config.save(config_path)
        console.print(f"[green]Created config: {config_path}[/green]")
    else:
        console.print(f"[yellow]Config exists: {config_path}[/yellow]")
    
    console.print("[bold green]✓ Atmosphere initialized![/bold green]")
    console.print()
    console.print("Next steps:")
    console.print("  1. Create an agent: [bold]atmosphere agents create my-agent[/bold]")
    console.print("  2. Start the server: [bold]atmosphere start[/bold]")


@app.command("agents")
def agents_cmd(
    action: str = typer.Argument("list", help="Action: list, create, delete, start, stop"),
    agent_id: str = typer.Argument(None, help="Agent ID for create/delete/start/stop"),
    name: str = typer.Option(None, "--name", "-n", help="Agent name (for create)"),
):
    """Manage agents."""
    from ..config import get_agents_dir
    
    agents_dir = get_agents_dir()
    
    if action == "list":
        if not agents_dir.exists():
            console.print("[yellow]No agents directory. Run 'atmosphere init' first.[/yellow]")
            return
        
        table = Table(title="Agents")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Status")
        
        for agent_dir in agents_dir.iterdir():
            if agent_dir.is_dir():
                # Try to load name from agent.yaml
                config_path = agent_dir / "agent.yaml"
                name = agent_dir.name
                if config_path.exists():
                    import yaml
                    with open(config_path) as f:
                        data = yaml.safe_load(f) or {}
                        name = data.get("name", agent_dir.name)
                
                table.add_row(agent_dir.name, name, "[dim]stopped[/dim]")
        
        console.print(table)
    
    elif action == "create":
        if not agent_id:
            console.print("[red]Agent ID required[/red]")
            raise typer.Exit(1)
        
        agent_name = name or agent_id
        workspace_dir = agents_dir / agent_id
        
        if workspace_dir.exists():
            console.print(f"[red]Agent already exists: {agent_id}[/red]")
            raise typer.Exit(1)
        
        # Create workspace
        workspace_dir.mkdir(parents=True)
        (workspace_dir / "memory").mkdir()
        (workspace_dir / "skills").mkdir()
        
        # Write agent.yaml
        import yaml
        config_data = {
            "id": agent_id,
            "name": agent_name,
            "description": "",
            "heartbeat": {
                "enabled": True,
                "interval": 1800,
            },
        }
        (workspace_dir / "agent.yaml").write_text(yaml.dump(config_data, default_flow_style=False))
        
        # Write SOUL.md
        soul = f"""# {agent_name}

An AI agent in the Atmosphere platform.

## Identity

You are **{agent_name}**.

## Behavior

- Be helpful and precise
- Use tools when needed
- Write to memory to remember important things
"""
        (workspace_dir / "SOUL.md").write_text(soul)
        
        # Write AGENTS.md
        agents_md = """# Workspace

## Every Session

1. Read SOUL.md - who you are
2. Read memory/ for recent context
3. Check HEARTBEAT.md for tasks
"""
        (workspace_dir / "AGENTS.md").write_text(agents_md)
        
        console.print(f"[green]✓ Created agent: {agent_id}[/green]")
        console.print(f"  Workspace: {workspace_dir}")
    
    elif action == "delete":
        if not agent_id:
            console.print("[red]Agent ID required[/red]")
            raise typer.Exit(1)
        
        workspace_dir = agents_dir / agent_id
        if not workspace_dir.exists():
            console.print(f"[red]Agent not found: {agent_id}[/red]")
            raise typer.Exit(1)
        
        import shutil
        shutil.rmtree(workspace_dir)
        console.print(f"[green]✓ Deleted agent: {agent_id}[/green]")
    
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        console.print("Available: list, create, delete")


@app.command()
def chat(
    agent_id: str = typer.Argument(..., help="Agent ID to chat with"),
    message: str = typer.Argument(None, help="Message to send (interactive if omitted)"),
):
    """Chat with an agent."""
    import httpx
    from ..config import settings
    
    base_url = f"http://localhost:{settings.atmosphere_port}"
    
    if message:
        # Single message mode
        with httpx.Client() as client:
            resp = client.post(
                f"{base_url}/api/agents/{agent_id}/chat",
                json={"message": message},
                timeout=120,
            )
            if resp.status_code != 200:
                console.print(f"[red]Error: {resp.text}[/red]")
                raise typer.Exit(1)
            
            data = resp.json()
            console.print(f"[bold]{agent_id}:[/bold] {data['response']}")
    else:
        # Interactive mode
        console.print(f"[bold]Chatting with {agent_id}[/bold] (Ctrl+C to exit)")
        console.print()
        
        with httpx.Client() as client:
            while True:
                try:
                    msg = console.input("[bold blue]You:[/bold blue] ")
                    if not msg.strip():
                        continue
                    
                    resp = client.post(
                        f"{base_url}/api/agents/{agent_id}/chat",
                        json={"message": msg},
                        timeout=120,
                    )
                    if resp.status_code != 200:
                        console.print(f"[red]Error: {resp.text}[/red]")
                        continue
                    
                    data = resp.json()
                    console.print(f"[bold green]{agent_id}:[/bold green] {data['response']}")
                    console.print()
                
                except KeyboardInterrupt:
                    console.print("\n[dim]Goodbye![/dim]")
                    break


@app.command()
def version():
    """Show version."""
    from openhoof import __version__
    console.print(f"Atmosphere Agents v{__version__}")


if __name__ == "__main__":
    app()
