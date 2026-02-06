"""CLI commands for flowly."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from flowly import __version__, __logo__

app = typer.Typer(
    name="flowly",
    help=f"{__logo__} flowly - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} flowly v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """flowly - Personal AI Assistant."""
    pass


# ============================================================================
# Setup Commands
# ============================================================================

setup_app = typer.Typer(help="Interactive setup wizards")
app.add_typer(setup_app, name="setup")


@setup_app.callback(invoke_without_command=True)
def setup_main(ctx: typer.Context):
    """Run the full setup wizard (or use subcommands for specific setups)."""
    if ctx.invoked_subcommand is None:
        from flowly.cli.setup import setup_all
        setup_all()


@setup_app.command("telegram")
def setup_telegram_cmd():
    """Set up Telegram bot."""
    from flowly.cli.setup import setup_telegram
    setup_telegram()


@setup_app.command("voice")
def setup_voice_cmd():
    """Set up voice transcription (Groq Whisper)."""
    from flowly.cli.setup import setup_voice
    setup_voice()


@setup_app.command("voice-calls")
def setup_voice_calls_cmd():
    """Set up voice calls (Twilio)."""
    from flowly.cli.setup import setup_voice_calls
    setup_voice_calls()


@setup_app.command("openrouter")
def setup_openrouter_cmd():
    """Set up OpenRouter LLM provider."""
    from flowly.cli.setup import setup_openrouter
    setup_openrouter()


@setup_app.command("trello")
def setup_trello_cmd():
    """Set up Trello integration."""
    from flowly.cli.setup import setup_trello
    setup_trello()


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize flowly configuration and workspace."""
    from flowly.config.loader import get_config_path, save_config
    from flowly.config.schema import Config
    from flowly.utils.helpers import get_workspace_path

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()

    # Create default config
    config = Config()
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")

    # Create default bootstrap files
    _create_workspace_templates(workspace)

    console.print(f"\n{__logo__} flowly is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.flowly/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]flowly agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? Run: flowly channels login[/dim]")




def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
""",
        "SOUL.md": """# Soul

I am Nanobot, your personal AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }

    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")

    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the flowly gateway."""
    from flowly.config.loader import load_config, get_data_dir
    from flowly.bus.queue import MessageBus
    from flowly.providers.litellm_provider import LiteLLMProvider
    from flowly.agent.loop import AgentLoop
    from flowly.channels.manager import ChannelManager
    from flowly.cron.service import CronService
    from flowly.cron.types import CronJob
    from flowly.heartbeat.service import HeartbeatService
    from flowly.gateway.server import GatewayServer

    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting flowly gateway on port {port}...")

    config = load_config()

    # Create components
    bus = MessageBus()

    # Create provider (supports OpenRouter, Anthropic, OpenAI)
    api_key = config.get_api_key()
    api_base = config.get_api_base()

    if not api_key:
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.flowly/config.json under providers.openrouter.apiKey")
        raise typer.Exit(1)

    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )

    # Create cron service first (agent needs it)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Build compaction config from settings
    from flowly.compaction.types import CompactionConfig, MemoryFlushConfig
    compaction_cfg = config.agents.defaults.compaction
    compaction_config = CompactionConfig(
        mode=compaction_cfg.mode,
        reserve_tokens_floor=compaction_cfg.reserve_tokens_floor,
        max_history_share=compaction_cfg.max_history_share,
        context_window=compaction_cfg.context_window,
        memory_flush=MemoryFlushConfig(
            enabled=compaction_cfg.memory_flush.enabled,
            soft_threshold_tokens=compaction_cfg.memory_flush.soft_threshold_tokens,
            prompt=compaction_cfg.memory_flush.prompt,
            system_prompt=compaction_cfg.memory_flush.system_prompt,
        ),
    )

    # Build exec config
    from flowly.exec.types import ExecConfig
    exec_cfg = config.tools.exec
    exec_config = ExecConfig(
        enabled=exec_cfg.enabled,
        timeout_seconds=exec_cfg.timeout_seconds,
        max_output_chars=exec_cfg.max_output_chars,
        approval_timeout_seconds=exec_cfg.approval_timeout_seconds,
    )

    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None,
        cron_service=cron,
        context_messages=config.agents.defaults.context_messages,
        compaction_config=compaction_config,
        exec_config=exec_config,
        trello_config=config.integrations.trello,
        voice_config=config.integrations.voice,
    )

    # Set cron job callback (needs agent to be created first)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        # Build the prompt - if delivery is requested, tell agent to send message
        prompt = job.payload.message

        if job.payload.deliver:
            channel = job.payload.channel or "telegram"
            if job.payload.to:
                # We have a specific target - send directly after agent processes
                response = await agent.process_direct(prompt, session_key=f"cron:{job.id}")
                from flowly.bus.events import OutboundMessage
                await bus.publish_outbound(OutboundMessage(
                    channel=channel,
                    chat_id=job.payload.to,
                    content=response or ""
                ))
                return response
            else:
                # No specific target - ask agent to use message tool
                prompt = (
                    f"[Scheduled Task: {job.name}]\n"
                    f"{job.payload.message}\n\n"
                    f"After completing the task, send the result to the user using the message tool."
                )

        response = await agent.process_direct(prompt, session_key=f"cron:{job.id}")
        return response

    cron.on_job = on_cron_job

    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")

    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True
    )

    # Create channel manager
    channels = ChannelManager(config, bus)

    # Set up compact callback for channels
    async def on_compact(session_key: str, instructions: str | None = None) -> dict:
        """Handle /compact command from channels."""
        return await agent.compact_session(session_key, instructions)

    channels.set_compact_callback(on_compact)

    # Create gateway API server for voice bridge
    async def on_voice_message(call_sid: str, from_number: str, text: str) -> str:
        """Handle voice message from voice bridge."""
        # Format message with clear voice context
        # This helps the agent understand it's in a voice call and should speak naturally
        prompt = f"""[ACTIVE VOICE CALL - Call ID: {call_sid}]
[Caller: {from_number}]
[User said]: {text}

Remember: You are speaking on a phone call. The user can ONLY hear your text response.
If you use any tools, verbally explain what you're doing and the results."""
        response = await agent.process_direct(prompt, session_key=f"voice:{call_sid}")
        return response or "Üzgünüm, bunu işleyemedim. Lütfen tekrar deneyin."

    gateway_server = GatewayServer(
        host=config.gateway.host,
        port=port,
        on_voice_message=on_voice_message,
    )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every 30m")

    if config.integrations.voice.enabled:
        console.print(f"[green]✓[/green] Voice calls: enabled (bridge: {config.integrations.voice.bridge_url})")

    console.print(f"[green]✓[/green] API: http://{config.gateway.host}:{port}")

    async def run():
        try:
            await gateway_server.start()
            await cron.start()
            await heartbeat.start()
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            await gateway_server.stop()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
):
    """Interact with the agent directly."""
    from flowly.config.loader import load_config, get_data_dir
    from flowly.bus.queue import MessageBus
    from flowly.providers.litellm_provider import LiteLLMProvider
    from flowly.agent.loop import AgentLoop
    from flowly.cron.service import CronService

    config = load_config()

    api_key = config.get_api_key()
    api_base = config.get_api_base()

    if not api_key:
        console.print("[red]Error: No API key configured.[/red]")
        raise typer.Exit(1)

    bus = MessageBus()
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )

    # Create cron service for agent CLI
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Build compaction config
    from flowly.compaction.types import CompactionConfig, MemoryFlushConfig
    compaction_cfg = config.agents.defaults.compaction
    compaction_config = CompactionConfig(
        mode=compaction_cfg.mode,
        reserve_tokens_floor=compaction_cfg.reserve_tokens_floor,
        max_history_share=compaction_cfg.max_history_share,
        context_window=compaction_cfg.context_window,
        memory_flush=MemoryFlushConfig(
            enabled=compaction_cfg.memory_flush.enabled,
            soft_threshold_tokens=compaction_cfg.memory_flush.soft_threshold_tokens,
            prompt=compaction_cfg.memory_flush.prompt,
            system_prompt=compaction_cfg.memory_flush.system_prompt,
        ),
    )

    # Build exec config
    from flowly.exec.types import ExecConfig
    exec_cfg = config.tools.exec
    exec_config = ExecConfig(
        enabled=exec_cfg.enabled,
        timeout_seconds=exec_cfg.timeout_seconds,
        max_output_chars=exec_cfg.max_output_chars,
        approval_timeout_seconds=exec_cfg.approval_timeout_seconds,
    )

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        brave_api_key=config.tools.web.search.api_key or None,
        cron_service=cron,
        context_messages=config.agents.defaults.context_messages,
        compaction_config=compaction_config,
        exec_config=exec_config,
        trello_config=config.integrations.trello,
        voice_config=config.integrations.voice,
    )

    async def handle_compact(instructions: str | None = None) -> None:
        """Handle /compact command."""
        console.print("[cyan]⚙️ Compacting conversation history...[/cyan]")
        result = await agent_loop.compact_session(session_id, instructions)
        if result["success"]:
            console.print(
                f"[green]✓[/green] {result['message']} "
                f"({result['tokens_before']} → {result['tokens_after']} tokens)"
            )
            console.print(f"\n[dim]Summary preview:[/dim]\n{result['summary_preview']}")
        else:
            console.print(f"[yellow]{result['message']}[/yellow]")

    if message:
        # Single message mode - check for /compact
        if message.strip().startswith("/compact"):
            parts = message.strip().split(" ", 1)
            instructions = parts[1] if len(parts) > 1 else None
            asyncio.run(handle_compact(instructions))
        else:
            async def run_once():
                response = await agent_loop.process_direct(message, session_id)
                console.print(f"\n{__logo__} {response}")
            asyncio.run(run_once())
    else:
        # Interactive mode
        console.print(f"{__logo__} Interactive mode (Ctrl+C to exit)")
        console.print("[dim]Commands: /compact [instructions], /clear, /quit[/dim]\n")

        async def run_interactive():
            while True:
                try:
                    user_input = console.input("[bold blue]You:[/bold blue] ")
                    if not user_input.strip():
                        continue

                    # Handle slash commands
                    if user_input.strip().startswith("/"):
                        cmd_parts = user_input.strip().split(" ", 1)
                        cmd = cmd_parts[0].lower()
                        args = cmd_parts[1] if len(cmd_parts) > 1 else None

                        if cmd == "/compact":
                            await handle_compact(args)
                            continue
                        elif cmd == "/clear":
                            session = agent_loop.sessions.get_or_create(session_id)
                            session.clear()
                            agent_loop.sessions.save(session)
                            console.print("[green]✓[/green] Session cleared")
                            continue
                        elif cmd in ("/quit", "/exit", "/q"):
                            console.print("Goodbye!")
                            break
                        elif cmd == "/help":
                            console.print("\n[bold]Available commands:[/bold]")
                            console.print("  /compact [instructions] - Summarize conversation history")
                            console.print("  /clear                  - Clear session history")
                            console.print("  /quit                   - Exit interactive mode")
                            console.print("  /help                   - Show this help\n")
                            continue

                    response = await agent_loop.process_direct(user_input, session_id)
                    console.print(f"\n{__logo__} {response}\n")
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break

        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from flowly.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Bridge URL", style="yellow")

    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    user_bridge = Path.home() / ".flowly" / "bridge"

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent / "bridge"  # flowly/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall flowly-ai")
        raise typer.Exit(1)

    console.print(f"{__logo__} Setting up bridge...")

    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess

    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from flowly.config.loader import get_data_dir
    from flowly.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    jobs = service.list_jobs(include_disabled=all)

    if not jobs:
        console.print("No scheduled jobs.")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")

    import time
    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"

        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000))
            next_run = next_time

        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"

        table.add_row(job.id, job.name, sched, status, next_run)

    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
):
    """Add a scheduled job."""
    from flowly.config.loader import get_data_dir
    from flowly.cron.service import CronService
    from flowly.cron.types import CronSchedule

    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime
        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )

    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from flowly.config.loader import get_data_dir
    from flowly.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from flowly.config.loader import get_data_dir
    from flowly.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from flowly.config.loader import get_data_dir
    from flowly.cron.service import CronService

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    async def run():
        return await service.run_job(job_id, force=force)

    if asyncio.run(run()):
        console.print(f"[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Skills Commands (shortcuts to flowly-hub)
# ============================================================================

skills_app = typer.Typer(help="Manage skills (alias for flowly-hub)")
app.add_typer(skills_app, name="skills")


@skills_app.command("list")
def skills_list(
    all_skills: bool = typer.Option(False, "--all", "-a", help="Include workspace skills"),
):
    """List installed skills."""
    from flowly.hub.manager import SkillManager
    from flowly.utils.helpers import get_workspace_path

    workspace = get_workspace_path()
    with SkillManager(workspace_dir=workspace) as manager:
        skills = manager.list_installed(include_workspace=all_skills)

    if not skills:
        console.print("[yellow]No skills installed[/yellow]")
        console.print("\n[dim]Install skills with: flowly skills install <skill-name>[/dim]")
        return

    table = Table(title="Installed Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Version")
    table.add_column("Source", style="dim")

    for skill in skills:
        source_short = skill.source[:30] + "..." if len(skill.source) > 30 else skill.source
        table.add_row(skill.slug, skill.version, source_short)

    console.print(table)


@skills_app.command("install")
def skills_install(
    source: str = typer.Argument(..., help="Skill source"),
    force: bool = typer.Option(False, "--force", "-f", help="Force reinstall"),
):
    """Install a skill."""
    from flowly.hub.manager import SkillManager
    from flowly.utils.helpers import get_workspace_path

    workspace = get_workspace_path()
    with SkillManager(workspace_dir=workspace) as manager:
        console.print(f"[cyan]Installing {source}...[/cyan]")
        skill = manager.install(source, force=force)

        if skill:
            console.print(f"[green]✓[/green] Installed [cyan]{skill.name}[/cyan] v{skill.version}")
        else:
            console.print(f"[red]✗[/red] Failed to install {source}")
            raise typer.Exit(1)


@skills_app.command("remove")
def skills_remove(
    skill: str = typer.Argument(..., help="Skill to remove"),
):
    """Remove an installed skill."""
    from flowly.hub.manager import SkillManager
    from flowly.utils.helpers import get_workspace_path

    workspace = get_workspace_path()
    with SkillManager(workspace_dir=workspace) as manager:
        if manager.remove(skill):
            console.print(f"[green]✓[/green] Removed [cyan]{skill}[/cyan]")
        else:
            console.print(f"[red]✗[/red] Skill {skill} not found")
            raise typer.Exit(1)


@skills_app.command("search")
def skills_search(
    query: str = typer.Argument(..., help="Search query"),
):
    """Search for skills in the registry."""
    from flowly.hub.manager import SkillManager
    from flowly.utils.helpers import get_workspace_path

    workspace = get_workspace_path()
    with SkillManager(workspace_dir=workspace) as manager:
        results = manager.search(query)

    if not results:
        console.print(f"[yellow]No skills found for '{query}'[/yellow]")
        return

    table = Table(title=f"Skills matching '{query}'")
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    for skill in results[:10]:
        desc = skill.description[:50] + "..." if len(skill.description) > 50 else skill.description
        table.add_row(skill.slug, desc)

    console.print(table)


# ============================================================================
# Exec Approvals Commands
# ============================================================================

approvals_app = typer.Typer(help="Manage command execution approvals")
app.add_typer(approvals_app, name="approvals")


@approvals_app.command("status")
def approvals_status():
    """Show exec approvals configuration."""
    from flowly.exec.approvals import ExecApprovalStore

    store = ExecApprovalStore()
    config = store.load()

    console.print("\n[bold cyan]Exec Approvals Configuration[/bold cyan]")
    console.print("─" * 40)
    console.print(f"Security: [cyan]{config.security}[/cyan]")
    console.print(f"Ask mode: [cyan]{config.ask}[/cyan]")
    console.print(f"Ask fallback: [cyan]{config.ask_fallback}[/cyan]")
    console.print(f"Allowlist entries: [cyan]{len(config.allowlist)}[/cyan]")

    if config.security == "deny":
        console.print("\n[yellow]⚠️  Command execution is currently DENIED[/yellow]")
        console.print("[dim]Run 'flowly approvals set --security allowlist' to enable[/dim]")


@approvals_app.command("set")
def approvals_set(
    security: str = typer.Option(None, "--security", "-s", help="Security mode: deny, allowlist, full"),
    ask: str = typer.Option(None, "--ask", "-a", help="Ask mode: off, on-miss, always"),
):
    """Update exec approvals configuration."""
    from flowly.exec.approvals import ExecApprovalStore

    store = ExecApprovalStore()
    config = store.load()

    if security:
        if security not in ("deny", "allowlist", "full"):
            console.print(f"[red]Invalid security mode: {security}[/red]")
            raise typer.Exit(1)
        config.security = security
        console.print(f"[green]✓[/green] Security set to [cyan]{security}[/cyan]")

    if ask:
        if ask not in ("off", "on-miss", "always"):
            console.print(f"[red]Invalid ask mode: {ask}[/red]")
            raise typer.Exit(1)
        config.ask = ask
        console.print(f"[green]✓[/green] Ask mode set to [cyan]{ask}[/cyan]")

    store.save()


@approvals_app.command("list")
def approvals_list():
    """List allowlist entries."""
    from flowly.exec.approvals import ExecApprovalStore

    store = ExecApprovalStore()
    config = store.load()

    if not config.allowlist:
        console.print("[dim]No allowlist entries.[/dim]")
        console.print("[dim]Commands will require approval (if ask mode is on-miss or always)[/dim]")
        return

    table = Table(title="Exec Allowlist")
    table.add_column("Pattern", style="cyan")
    table.add_column("Last Used")
    table.add_column("Command")

    import time
    for entry in config.allowlist:
        last_used = ""
        if entry.last_used_at:
            last_used = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.last_used_at / 1000))
        cmd = entry.last_used_command or ""
        if len(cmd) > 40:
            cmd = cmd[:40] + "..."
        table.add_row(entry.pattern, last_used, cmd)

    console.print(table)


@approvals_app.command("add")
def approvals_add(
    pattern: str = typer.Argument(..., help="Path pattern to allow (supports glob)"),
):
    """Add a pattern to the allowlist."""
    from flowly.exec.approvals import ExecApprovalStore

    store = ExecApprovalStore()
    store.load()
    store.add_to_allowlist(pattern)

    console.print(f"[green]✓[/green] Added [cyan]{pattern}[/cyan] to allowlist")


@approvals_app.command("remove")
def approvals_remove(
    pattern: str = typer.Argument(..., help="Pattern to remove"),
):
    """Remove a pattern from the allowlist."""
    from flowly.exec.approvals import ExecApprovalStore

    store = ExecApprovalStore()
    store.load()

    if store.remove_from_allowlist(pattern):
        console.print(f"[green]✓[/green] Removed [cyan]{pattern}[/cyan] from allowlist")
    else:
        console.print(f"[yellow]Pattern not found: {pattern}[/yellow]")


@approvals_app.command("safe-bins")
def approvals_safe_bins():
    """List safe bins that are always allowed."""
    from flowly.exec.safety import DEFAULT_SAFE_BINS

    console.print("\n[bold]Safe Bins (always allowed for stdin operations):[/bold]")
    for bin_name in sorted(DEFAULT_SAFE_BINS):
        console.print(f"  • {bin_name}")
    console.print("\n[dim]These commands are allowed without explicit allowlist entry[/dim]")
    console.print("[dim]when they don't reference files as arguments.[/dim]")


# ============================================================================
# Pairing Commands
# ============================================================================

pairing_app = typer.Typer(help="Secure channel pairing")
app.add_typer(pairing_app, name="pairing")


@pairing_app.command("list")
def pairing_list(
    channel: str = typer.Argument(..., help="Channel (telegram, whatsapp)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List pending pairing requests."""
    from flowly.pairing import list_pairing_requests

    if channel not in ("telegram", "whatsapp"):
        console.print(f"[red]Invalid channel: {channel}. Use 'telegram' or 'whatsapp'[/red]")
        raise typer.Exit(1)

    requests = list_pairing_requests(channel)

    if json_output:
        import json
        data = [
            {
                "id": r.id,
                "code": r.code,
                "created_at": r.created_at,
                "meta": r.meta,
            }
            for r in requests
        ]
        console.print(json.dumps({"channel": channel, "requests": data}, indent=2))
        return

    if not requests:
        console.print(f"[dim]No pending {channel} pairing requests.[/dim]")
        return

    table = Table(title=f"Pending {channel.title()} Pairing Requests")
    table.add_column("Code", style="cyan")
    table.add_column("User ID")
    table.add_column("Meta")
    table.add_column("Requested")

    for r in requests:
        meta_str = ", ".join(f"{k}={v}" for k, v in r.meta.items()) if r.meta else ""
        table.add_row(r.code, r.id, meta_str, r.created_at[:19])

    console.print(table)


@pairing_app.command("approve")
def pairing_approve(
    channel: str = typer.Argument(..., help="Channel (telegram, whatsapp)"),
    code: str = typer.Argument(..., help="Pairing code"),
    notify: bool = typer.Option(False, "--notify", "-n", help="Notify user on approval"),
):
    """Approve a pairing code."""
    from flowly.pairing import approve_pairing_code
    from flowly.config.loader import load_config

    if channel not in ("telegram", "whatsapp"):
        console.print(f"[red]Invalid channel: {channel}. Use 'telegram' or 'whatsapp'[/red]")
        raise typer.Exit(1)

    approved = approve_pairing_code(channel, code)

    if not approved:
        console.print(f"[red]No pending pairing request found for code: {code}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Approved {channel} sender [cyan]{approved.id}[/cyan]")

    if approved.meta:
        meta_str = ", ".join(f"{k}={v}" for k, v in approved.meta.items())
        console.print(f"  [dim]({meta_str})[/dim]")

    # Notify user if requested
    if notify and channel == "telegram":
        config = load_config()
        if config.channels.telegram.token:
            async def send_notification():
                import httpx
                token = config.channels.telegram.token
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(url, json={
                            "chat_id": approved.id,
                            "text": "✅ Access approved! Send a message to start chatting.",
                        })
                    console.print(f"[green]✓[/green] Notification sent")
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not notify user: {e}[/yellow]")

            asyncio.run(send_notification())


@pairing_app.command("revoke")
def pairing_revoke(
    channel: str = typer.Argument(..., help="Channel (telegram, whatsapp)"),
    user_id: str = typer.Argument(..., help="User ID to revoke"),
):
    """Revoke access for a user."""
    from flowly.pairing import remove_allow_from_entry

    if channel not in ("telegram", "whatsapp"):
        console.print(f"[red]Invalid channel: {channel}. Use 'telegram' or 'whatsapp'[/red]")
        raise typer.Exit(1)

    if remove_allow_from_entry(channel, user_id):
        console.print(f"[green]✓[/green] Revoked access for {user_id}")
    else:
        console.print(f"[yellow]User {user_id} was not in the allow list[/yellow]")


@pairing_app.command("allowed")
def pairing_allowed(
    channel: str = typer.Argument(..., help="Channel (telegram, whatsapp)"),
):
    """List allowed users from pairing store."""
    from flowly.pairing import read_allow_from_store

    if channel not in ("telegram", "whatsapp"):
        console.print(f"[red]Invalid channel: {channel}. Use 'telegram' or 'whatsapp'[/red]")
        raise typer.Exit(1)

    allowed = read_allow_from_store(channel)

    if not allowed:
        console.print(f"[dim]No users in {channel} pairing store.[/dim]")
        console.print("[dim]Users can also be allowed via config.json allow_from list.[/dim]")
        return

    console.print(f"[bold]{channel.title()} Allowed Users (from pairing):[/bold]")
    for user_id in allowed:
        console.print(f"  • {user_id}")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show flowly status."""
    from flowly.config.loader import load_config, get_config_path
    from flowly.utils.helpers import get_workspace_path

    config_path = get_config_path()
    workspace = get_workspace_path()

    console.print(f"{__logo__} Nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        config = load_config()
        console.print(f"Model: {config.agents.defaults.model}")

        # Check API keys
        has_openrouter = bool(config.providers.openrouter.api_key)
        has_anthropic = bool(config.providers.anthropic.api_key)
        has_openai = bool(config.providers.openai.api_key)
        has_gemini = bool(config.providers.gemini.api_key)
        has_vllm = bool(config.providers.vllm.api_base)

        console.print(f"OpenRouter API: {'[green]✓[/green]' if has_openrouter else '[dim]not set[/dim]'}")
        console.print(f"Anthropic API: {'[green]✓[/green]' if has_anthropic else '[dim]not set[/dim]'}")
        console.print(f"OpenAI API: {'[green]✓[/green]' if has_openai else '[dim]not set[/dim]'}")
        console.print(f"Gemini API: {'[green]✓[/green]' if has_gemini else '[dim]not set[/dim]'}")
        vllm_status = f"[green]✓ {config.providers.vllm.api_base}[/green]" if has_vllm else "[dim]not set[/dim]"
        console.print(f"vLLM/Local: {vllm_status}")


if __name__ == "__main__":
    app()
