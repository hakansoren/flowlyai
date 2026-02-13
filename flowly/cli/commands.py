"""CLI commands for flowly."""

import asyncio
import os
import platform
import plistlib
import shlex
import shutil
import signal
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from flowly import __version__, __logo__

# Windows needs SelectorEventLoop for uvicorn/aiohttp compatibility
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def get_npm_command() -> str:
    """Get the correct npm command for the current platform."""
    if platform.system() == "Windows":
        # On Windows, npm might be npm.cmd
        npm_cmd = shutil.which("npm.cmd") or shutil.which("npm")
        if npm_cmd:
            return npm_cmd
        return "npm.cmd"
    return "npm"

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


@setup_app.command("discord")
def setup_discord_cmd():
    """Set up Discord bot."""
    from flowly.cli.setup import setup_discord
    setup_discord()


@setup_app.command("slack")
def setup_slack_cmd():
    """Set up Slack bot."""
    from flowly.cli.setup import setup_slack
    setup_slack()


@setup_app.command("agents")
def setup_agents_cmd():
    """Set up multi-agent orchestration."""
    from flowly.cli.setup import setup_agents
    setup_agents()


# ============================================================================
# Persona Commands
# ============================================================================

persona_app = typer.Typer(help="Manage bot persona")
app.add_typer(persona_app, name="persona")

BUILTIN_PERSONAS = ["default", "jarvis", "friday", "pirate", "samurai", "casual", "professor", "butler"]


def _get_personas_dir() -> Path:
    """Get the personas directory from workspace config."""
    from flowly.config.loader import load_config
    config = load_config()
    return config.workspace_path / "personas"


def _ensure_personas(workspace: Path) -> Path:
    """Ensure personas directory exists, copying builtins if needed."""
    personas_dir = workspace / "personas"
    if not personas_dir.exists() or not any(personas_dir.glob("*.md")):
        _install_persona_files(workspace)
    return personas_dir


@persona_app.command("list")
def persona_list():
    """List available personas."""
    from flowly.config.loader import load_config
    config = load_config()
    personas_dir = _ensure_personas(config.workspace_path)
    active = config.agents.defaults.persona

    if not any(personas_dir.glob("*.md")):
        console.print("[yellow]No persona files found.[/yellow]")
        raise typer.Exit(1)

    table = Table(title="Available Personas")
    table.add_column("Name", style="cyan")
    table.add_column("Active", justify="center")
    table.add_column("Description", style="dim")

    for md_file in sorted(personas_dir.glob("*.md")):
        name = md_file.stem
        is_active = "[green]✓[/green]" if name == active else ""
        # Read first non-header line as description
        desc = ""
        for line in md_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                desc = line[:60]
                break
        table.add_row(name, is_active, desc)

    console.print(table)


@persona_app.command("set")
def persona_set(
    name: str = typer.Argument(help="Persona name to activate"),
):
    """Set the active persona."""
    from flowly.config.loader import load_config, save_config
    config = load_config()
    personas_dir = config.workspace_path / "personas"
    persona_file = personas_dir / f"{name}.md"

    if not persona_file.exists():
        console.print(f"[red]Persona not found: {name}[/red]")
        available = [f.stem for f in personas_dir.glob("*.md")] if personas_dir.exists() else BUILTIN_PERSONAS
        console.print(f"[dim]Available: {', '.join(available)}[/dim]")
        raise typer.Exit(1)

    config.agents.defaults.persona = name
    save_config(config)
    console.print(f"[green]✓[/green] Persona set to: [cyan]{name}[/cyan]")

    # Auto-restart if gateway is running
    ok, _ = _service_health(config.gateway.port)
    if ok:
        console.print("[dim]Restarting gateway...[/dim]")
        try:
            service_restart(label=DEFAULT_SERVICE_LABEL)
        except (SystemExit, Exception):
            console.print("[yellow]Could not auto-restart. Run: flowly service restart[/yellow]")


@persona_app.command("show")
def persona_show(
    name: str = typer.Argument(help="Persona name to display"),
):
    """Show persona details."""
    from flowly.config.loader import load_config
    config = load_config()
    persona_file = config.workspace_path / "personas" / f"{name}.md"

    if not persona_file.exists():
        console.print(f"[red]Persona not found: {name}[/red]")
        raise typer.Exit(1)

    content = persona_file.read_text(encoding="utf-8")
    from rich.markdown import Markdown
    console.print(Markdown(content))


# ============================================================================
# Service Commands
# ============================================================================

service_app = typer.Typer(help="Manage background gateway service")
app.add_typer(service_app, name="service")

DEFAULT_SERVICE_LABEL = "ai.flowly.gateway"


def _resolve_flowly_exec_argv() -> list[str]:
    """Resolve the executable argv prefix used for service definitions."""
    flowly_bin = shutil.which("flowly")
    if flowly_bin:
        return [str(Path(flowly_bin).expanduser())]

    argv0 = Path(sys.argv[0]).expanduser()
    if argv0.exists() and argv0.name == "flowly":
        return [str(argv0)]

    local_bin = (Path.home() / ".local" / "bin" / "flowly").expanduser()
    if local_bin.exists():
        return [str(local_bin)]

    uv_bin = shutil.which("uv")
    if uv_bin:
        return [str(Path(uv_bin).expanduser()), "run", "flowly"]

    return ["flowly"]


def _service_paths(label: str) -> tuple[Path | None, Path | None, Path | None]:
    """Return service file paths for macOS/Linux/Windows."""
    system = platform.system().lower()
    if system == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist", None, None
    if system == "linux":
        return None, Path.home() / ".config" / "systemd" / "user" / f"{label}.service", None
    if system == "windows":
        return None, None, Path.home() / "AppData" / "Local" / "flowly" / f"{label}.xml"
    return None, None, None


def _get_log_dir() -> Path:
    """Return platform-appropriate log directory for gateway."""
    system = platform.system().lower()
    if system == "darwin":
        return Path("/tmp")
    if system == "windows":
        log_dir = Path.home() / "AppData" / "Local" / "flowly" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir
    # Linux uses journalctl, but provide a fallback path
    return Path("/tmp")


def _run_cmd(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run command and return completed process with text output."""
    proc = subprocess.run(args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"{' '.join(args)} failed: {stderr}")
    return proc


def _service_health(port: int) -> tuple[bool, str]:
    """Check local gateway health endpoint."""
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            if 200 <= int(resp.status) < 300:
                return True, f"{url} OK"
            return False, f"{url} HTTP {resp.status}"
    except urllib.error.URLError as e:
        return False, f"{url} unavailable ({e.reason})"
    except Exception as e:
        return False, f"{url} unavailable ({e})"


def _kill_gateway_on_port(port: int, wait: float = 2.0) -> bool:
    """Kill any process listening on the gateway port. Returns True if killed."""
    system = platform.system().lower()
    try:
        if system == "darwin" or system == "linux":
            result = subprocess.run(
                ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5,
            )
            pids = [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if pids:
                import time
                time.sleep(wait)
                # SIGKILL any survivors
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                return True
        elif system == "windows":
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = int(line.strip().split()[-1])
                    subprocess.run(
                        ["taskkill", "/pid", str(pid), "/T", "/F"],
                        capture_output=True, timeout=5,
                    )
                    return True
    except Exception:
        pass
    return False


def _extract_port_from_plist(plist_path: Path) -> int:
    if not plist_path.exists():
        return 18790
    try:
        raw = plist_path.read_bytes()
        data = plistlib.loads(raw)
        args = data.get("ProgramArguments", [])
        if "--port" in args:
            idx = args.index("--port")
            if idx + 1 < len(args):
                return int(args[idx + 1])
    except Exception:
        pass
    return 18790


def _extract_port_from_unit(unit_path: Path) -> int:
    if not unit_path.exists():
        return 18790
    try:
        content = unit_path.read_text(encoding="utf-8")
    except Exception:
        return 18790
    marker = "--port"
    if marker not in content:
        return 18790
    try:
        after = content.split(marker, 1)[1].strip()
        return int(after.split()[0])
    except Exception:
        return 18790


def _extract_port_from_win_xml(xml_path: Path) -> int:
    """Extract --port value from Windows Task Scheduler XML."""
    if not xml_path.exists():
        return 18790
    try:
        content = xml_path.read_text(encoding="utf-16")
    except Exception:
        return 18790
    marker = "--port"
    if marker not in content:
        return 18790
    try:
        after = content.split(marker, 1)[1].strip()
        return int(after.split()[0].strip('"').strip("'"))
    except Exception:
        return 18790


@service_app.command("install")
def service_install(
    label: str = typer.Option(DEFAULT_SERVICE_LABEL, "--label", help="Service label"),
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable gateway verbose mode"),
    start: bool = typer.Option(True, "--start/--no-start", help="Start service after install"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing service file"),
    persona: str = typer.Option("", "--persona", help="Bot persona (default, jarvis, pirate, samurai, casual, professor, butler, friday)"),
):
    """Install background service for flowly gateway."""
    mac_plist, linux_unit, win_xml = _service_paths(label)
    exec_argv = _resolve_flowly_exec_argv()
    system = platform.system().lower()

    if system == "darwin" and mac_plist:
        mac_plist.parent.mkdir(parents=True, exist_ok=True)
        if mac_plist.exists() and not force:
            console.print(f"[yellow]Service file exists: {mac_plist}[/yellow]")
            console.print("[dim]Use --force to overwrite.[/dim]")
            raise typer.Exit(1)

        argv = exec_argv + ["gateway", "--port", str(port)]
        if verbose:
            argv.append("--verbose")
        if persona:
            argv.extend(["--persona", persona])
        plist_obj = {
            "Label": label,
            "ProgramArguments": argv,
            "RunAtLoad": True,
            "KeepAlive": True,
            "LimitLoadToSessionType": "Aqua",
            "ProcessType": "Interactive",
            "WorkingDirectory": str(Path.cwd()),
            "StandardOutPath": str(_get_log_dir() / "flowly-gateway.out.log"),
            "StandardErrorPath": str(_get_log_dir() / "flowly-gateway.err.log"),
            "EnvironmentVariables": {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONUNBUFFERED": "1",
            },
        }
        mac_plist.write_bytes(plistlib.dumps(plist_obj, fmt=plistlib.FMT_XML, sort_keys=False))

        try:
            _run_cmd(["launchctl", "unload", str(mac_plist)], check=False)
            _run_cmd(["launchctl", "load", str(mac_plist)])
            if start:
                _run_cmd(["launchctl", "start", label], check=False)
        except Exception as e:
            console.print(f"[red]Service install failed: {e}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]✓[/green] Installed launchd service: {label}")
        console.print(f"[dim]File: {mac_plist}[/dim]")
        return

    if system == "linux" and linux_unit:
        linux_unit.parent.mkdir(parents=True, exist_ok=True)
        if linux_unit.exists() and not force:
            console.print(f"[yellow]Service file exists: {linux_unit}[/yellow]")
            console.print("[dim]Use --force to overwrite.[/dim]")
            raise typer.Exit(1)

        argv = exec_argv + ["gateway", "--port", str(port)]
        if verbose:
            argv.append("--verbose")
        if persona:
            argv.extend(["--persona", persona])
        exec_line = shlex.join(argv)
        unit_content = textwrap.dedent(
            f"""\
            [Unit]
            Description=Flowly Gateway Service
            After=network.target

            [Service]
            Type=simple
            ExecStart={exec_line}
            Restart=always
            RestartSec=3
            WorkingDirectory={Path.cwd()}
            Environment=PYTHONUNBUFFERED=1

            [Install]
            WantedBy=default.target
            """
        )
        linux_unit.write_text(unit_content, encoding="utf-8")

        try:
            _run_cmd(["systemctl", "--user", "daemon-reload"])
            _run_cmd(["systemctl", "--user", "enable", label])
            if start:
                _run_cmd(["systemctl", "--user", "restart", label])
        except Exception as e:
            console.print(f"[red]Service install failed: {e}[/red]")
            console.print("[dim]Tip: Ensure user systemd is available (login session).[/dim]")
            raise typer.Exit(1)

        console.print(f"[green]✓[/green] Installed systemd user service: {label}")
        console.print(f"[dim]File: {linux_unit}[/dim]")
        return

    if system == "windows" and win_xml:
        win_xml.parent.mkdir(parents=True, exist_ok=True)
        if win_xml.exists() and not force:
            console.print(f"[yellow]Service file exists: {win_xml}[/yellow]")
            console.print("[dim]Use --force to overwrite.[/dim]")
            raise typer.Exit(1)

        log_dir = _get_log_dir()
        argv = exec_argv + ["gateway", "--port", str(port)]
        if verbose:
            argv.append("--verbose")
        if persona:
            argv.extend(["--persona", persona])

        command = argv[0]
        arguments = " ".join(argv[1:]) if len(argv) > 1 else ""
        out_log = str(log_dir / "flowly-gateway.out.log")
        err_log = str(log_dir / "flowly-gateway.err.log")

        # Escape XML special characters in dynamic values
        def _xml_escape(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        # Use cmd /c wrapper to redirect stdout/stderr to log files
        wrapper_args = f'/c "{command}" {arguments} > "{out_log}" 2> "{err_log}"'
        working_dir = str(Path.cwd())

        task_xml = textwrap.dedent(
            f"""\
            <?xml version="1.0" encoding="UTF-16"?>
            <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
              <RegistrationInfo>
                <Description>Flowly Gateway Service</Description>
              </RegistrationInfo>
              <Triggers>
                <LogonTrigger>
                  <Enabled>true</Enabled>
                </LogonTrigger>
              </Triggers>
              <Principals>
                <Principal id="Author">
                  <LogonType>InteractiveToken</LogonType>
                  <RunLevel>LeastPrivilege</RunLevel>
                </Principal>
              </Principals>
              <Settings>
                <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
                <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
                <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
                <AllowHardTerminate>true</AllowHardTerminate>
                <StartWhenAvailable>true</StartWhenAvailable>
                <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
                <AllowStartOnDemand>true</AllowStartOnDemand>
                <Enabled>true</Enabled>
                <Hidden>false</Hidden>
                <RestartOnFailure>
                  <Interval>PT1M</Interval>
                  <Count>10</Count>
                </RestartOnFailure>
                <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
              </Settings>
              <Actions Context="Author">
                <Exec>
                  <Command>cmd.exe</Command>
                  <Arguments>{_xml_escape(wrapper_args)}</Arguments>
                  <WorkingDirectory>{_xml_escape(working_dir)}</WorkingDirectory>
                </Exec>
              </Actions>
            </Task>
            """
        )
        win_xml.write_text(task_xml, encoding="utf-16")

        try:
            _run_cmd(["schtasks", "/create", "/tn", label, "/xml", str(win_xml), "/f"])
            if start:
                _run_cmd(["schtasks", "/run", "/tn", label], check=False)
        except Exception as e:
            console.print(f"[red]Service install failed: {e}[/red]")
            console.print("[dim]Tip: You may need to run as Administrator.[/dim]")
            raise typer.Exit(1)

        console.print(f"[green]✓[/green] Installed Windows Task Scheduler service: {label}")
        console.print(f"[dim]File: {win_xml}[/dim]")
        return

    console.print(f"[red]Unsupported platform for service install: {platform.system()}[/red]")
    raise typer.Exit(1)


@service_app.command("start")
def service_start(
    label: str = typer.Option(DEFAULT_SERVICE_LABEL, "--label", help="Service label"),
):
    """Start installed background service."""
    mac_plist, linux_unit, win_xml = _service_paths(label)
    system = platform.system().lower()
    try:
        if system == "darwin" and mac_plist:
            if not mac_plist.exists():
                console.print(f"[red]Service not installed: {mac_plist}[/red]")
                raise typer.Exit(1)
            _run_cmd(["launchctl", "load", str(mac_plist)], check=False)
            _run_cmd(["launchctl", "start", label], check=False)
            console.print(f"[green]✓[/green] Started service {label}")
            return
        if system == "linux":
            _run_cmd(["systemctl", "--user", "start", label])
            console.print(f"[green]✓[/green] Started service {label}")
            return
        if system == "windows":
            if win_xml and not win_xml.exists():
                console.print("[red]Service not installed. Run 'flowly service install' first.[/red]")
                raise typer.Exit(1)
            _run_cmd(["schtasks", "/run", "/tn", label])
            console.print(f"[green]✓[/green] Started service {label}")
            return
    except Exception as e:
        console.print(f"[red]Failed to start service: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[red]Unsupported platform: {platform.system()}[/red]")
    raise typer.Exit(1)


@service_app.command("stop")
def service_stop(
    label: str = typer.Option(DEFAULT_SERVICE_LABEL, "--label", help="Service label"),
):
    """Stop background service."""
    mac_plist, linux_unit, win_xml = _service_paths(label)
    system = platform.system().lower()

    # Determine the port so we can force-kill if needed
    port = 18790
    if system == "darwin" and mac_plist:
        port = _extract_port_from_plist(mac_plist)
    elif system == "linux" and linux_unit:
        port = _extract_port_from_unit(linux_unit)
    elif system == "windows" and win_xml:
        port = _extract_port_from_win_xml(win_xml)

    try:
        if system == "darwin" and mac_plist:
            _run_cmd(["launchctl", "stop", label], check=False)
            _run_cmd(["launchctl", "unload", str(mac_plist)], check=False)
        elif system == "linux":
            _run_cmd(["systemctl", "--user", "stop", label], check=False)
        elif system == "windows":
            _run_cmd(["schtasks", "/end", "/tn", label], check=False)
        else:
            console.print(f"[red]Unsupported platform: {platform.system()}[/red]")
            raise typer.Exit(1)

        # Force-kill any remaining process on the port
        _kill_gateway_on_port(port)
        console.print(f"[green]✓[/green] Stopped service {label}")
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Failed to stop service: {e}[/red]")
        raise typer.Exit(1)


@service_app.command("restart")
def service_restart(
    label: str = typer.Option(DEFAULT_SERVICE_LABEL, "--label", help="Service label"),
):
    """Restart background service."""
    system = platform.system().lower()
    try:
        if system == "darwin":
            service_stop(label=label)
            service_start(label=label)
            return
        if system == "linux":
            _run_cmd(["systemctl", "--user", "restart", label])
            console.print(f"[green]✓[/green] Restarted service {label}")
            return
        if system == "windows":
            service_stop(label=label)
            service_start(label=label)
            return
    except Exception as e:
        console.print(f"[red]Failed to restart service: {e}[/red]")
        raise typer.Exit(1)
    console.print(f"[red]Unsupported platform: {platform.system()}[/red]")
    raise typer.Exit(1)


@service_app.command("status")
def service_status(
    label: str = typer.Option(DEFAULT_SERVICE_LABEL, "--label", help="Service label"),
):
    """Show service state and local health."""
    mac_plist, linux_unit, win_xml = _service_paths(label)
    system = platform.system().lower()

    if system == "darwin" and mac_plist:
        installed = mac_plist.exists()
        loaded = False
        pid = ""
        try:
            proc = _run_cmd(["launchctl", "list", label], check=False)
            loaded = proc.returncode == 0
            output = proc.stdout or ""
            for line in output.splitlines():
                if "pid" in line.lower():
                    pid = line.strip()
                    break
        except Exception:
            loaded = False
        port = _extract_port_from_plist(mac_plist)
        ok, health = _service_health(port)
        console.print(f"Service: [cyan]{label}[/cyan]")
        console.print(f"Installed: {'[green]yes[/green]' if installed else '[red]no[/red]'}")
        console.print(f"Loaded: {'[green]yes[/green]' if loaded else '[red]no[/red]'}")
        if pid:
            console.print(f"PID info: [dim]{pid}[/dim]")
        console.print(f"Health: {'[green]ok[/green]' if ok else '[yellow]down[/yellow]'} - {health}")
        if installed:
            console.print(f"[dim]File: {mac_plist}[/dim]")
        return

    if system == "linux" and linux_unit:
        installed = linux_unit.exists()
        enabled = False
        active = False
        try:
            enabled = _run_cmd(["systemctl", "--user", "is-enabled", label], check=False).returncode == 0
            active = _run_cmd(["systemctl", "--user", "is-active", label], check=False).returncode == 0
        except Exception:
            pass
        port = _extract_port_from_unit(linux_unit)
        ok, health = _service_health(port)
        console.print(f"Service: [cyan]{label}[/cyan]")
        console.print(f"Installed: {'[green]yes[/green]' if installed else '[red]no[/red]'}")
        console.print(f"Enabled: {'[green]yes[/green]' if enabled else '[red]no[/red]'}")
        console.print(f"Active: {'[green]yes[/green]' if active else '[red]no[/red]'}")
        console.print(f"Health: {'[green]ok[/green]' if ok else '[yellow]down[/yellow]'} - {health}")
        if installed:
            console.print(f"[dim]File: {linux_unit}[/dim]")
        return

    if system == "windows" and win_xml:
        installed = win_xml.exists()
        running = False
        status_text = "Unknown"
        try:
            proc = _run_cmd(
                ["schtasks", "/query", "/tn", label, "/fo", "CSV", "/nh"],
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                # CSV format: "task_name","Next Run","Status"
                parts = proc.stdout.strip().split(",")
                if len(parts) >= 3:
                    status_text = parts[2].strip().strip('"')
                    running = status_text.lower() == "running"
        except Exception:
            pass
        port = _extract_port_from_win_xml(win_xml)
        ok, health = _service_health(port)
        console.print(f"Service: [cyan]{label}[/cyan]")
        console.print(f"Installed: {'[green]yes[/green]' if installed else '[red]no[/red]'}")
        console.print(f"Status: {'[green]Running[/green]' if running else f'[yellow]{status_text}[/yellow]'}")
        console.print(f"Health: {'[green]ok[/green]' if ok else '[yellow]down[/yellow]'} - {health}")
        if installed:
            console.print(f"[dim]File: {win_xml}[/dim]")
        return

    console.print(f"[red]Unsupported platform: {platform.system()}[/red]")
    raise typer.Exit(1)


@service_app.command("logs")
def service_logs(
    label: str = typer.Option(DEFAULT_SERVICE_LABEL, "--label", help="Service label"),
    follow: bool = typer.Option(True, "--follow/--no-follow", "-f", help="Follow logs in real time"),
    lines: int = typer.Option(200, "--lines", "-n", min=1, help="Number of lines to show"),
    stream: str = typer.Option(
        "both",
        "--stream",
        help="Log stream (macOS launchd logs only): out|err|both",
    ),
):
    """Show background service logs (real-time by default)."""
    system = platform.system().lower()

    if system == "darwin":
        stream = stream.lower().strip()
        if stream not in {"out", "err", "both"}:
            console.print("[red]Invalid --stream value. Use out, err, or both.[/red]")
            raise typer.Exit(1)

        log_dir = _get_log_dir()
        out_log = log_dir / "flowly-gateway.out.log"
        err_log = log_dir / "flowly-gateway.err.log"
        selected_files: list[Path] = []
        if stream in {"out", "both"}:
            selected_files.append(out_log)
        if stream in {"err", "both"}:
            selected_files.append(err_log)

        existing_files = [p for p in selected_files if p.exists()]
        missing_files = [p for p in selected_files if not p.exists()]
        for missing in missing_files:
            console.print(f"[yellow]Log file not found yet:[/yellow] {missing}")

        if not existing_files:
            console.print("[red]No log file available yet.[/red]")
            raise typer.Exit(1)

        if follow:
            console.print(
                f"[dim]Following logs ({', '.join(str(p) for p in existing_files)}). "
                "Press Ctrl+C to stop.[/dim]"
            )
            try:
                subprocess.run(
                    ["tail", "-n", str(lines), "-F", *[str(p) for p in existing_files]],
                    check=False,
                )
            except KeyboardInterrupt:
                return
            return

        for file_path in existing_files:
            console.print(f"\n[bold]{file_path}[/bold]")
            proc = _run_cmd(["tail", "-n", str(lines), str(file_path)], check=False)
            if proc.stdout:
                console.print(proc.stdout.rstrip("\n"))
        return

    if system == "linux":
        args = ["journalctl", "--user", "-u", label, "-n", str(lines), "--no-pager"]
        if follow:
            args.append("-f")
            console.print(f"[dim]Following journal logs for {label}. Press Ctrl+C to stop.[/dim]")
        proc = _run_cmd(args, check=False)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            console.print(f"[red]Failed to read logs: {err}[/red]")
            raise typer.Exit(1)
        if proc.stdout:
            console.print(proc.stdout.rstrip("\n"))
        return

    if system == "windows":
        log_dir = _get_log_dir()
        out_log = log_dir / "flowly-gateway.out.log"
        err_log = log_dir / "flowly-gateway.err.log"
        selected_files: list[Path] = []
        if stream in {"out", "both"}:
            selected_files.append(out_log)
        if stream in {"err", "both"}:
            selected_files.append(err_log)

        existing_files = [p for p in selected_files if p.exists()]
        missing_files = [p for p in selected_files if not p.exists()]
        for missing in missing_files:
            console.print(f"[yellow]Log file not found yet:[/yellow] {missing}")

        if not existing_files:
            console.print("[red]No log file available yet.[/red]")
            raise typer.Exit(1)

        if follow:
            console.print(
                f"[dim]Following logs ({', '.join(str(p) for p in existing_files)}). "
                "Press Ctrl+C to stop.[/dim]"
            )
            # Use PowerShell Get-Content -Wait for tail -f equivalent on Windows
            ps_files = ", ".join(f'"{p}"' for p in existing_files)
            ps_cmd = f"Get-Content -Path {ps_files} -Tail {lines} -Wait"
            try:
                subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    check=False,
                )
            except KeyboardInterrupt:
                return
            return

        # Read last N lines using PowerShell
        for file_path in existing_files:
            console.print(f"\n[bold]{file_path}[/bold]")
            ps_cmd = f'Get-Content -Path "{file_path}" -Tail {lines}'
            proc = _run_cmd(["powershell", "-Command", ps_cmd], check=False)
            if proc.stdout:
                console.print(proc.stdout.rstrip("\n"))
        return

    console.print(f"[red]Unsupported platform: {platform.system()}[/red]")
    raise typer.Exit(1)


@service_app.command("uninstall")
def service_uninstall(
    label: str = typer.Option(DEFAULT_SERVICE_LABEL, "--label", help="Service label"),
):
    """Uninstall background service definition."""
    mac_plist, linux_unit, win_xml = _service_paths(label)
    system = platform.system().lower()

    try:
        if system == "darwin" and mac_plist:
            _run_cmd(["launchctl", "stop", label], check=False)
            _run_cmd(["launchctl", "unload", str(mac_plist)], check=False)
            if mac_plist.exists():
                mac_plist.unlink()
            console.print(f"[green]✓[/green] Uninstalled service {label}")
            return
        if system == "linux" and linux_unit:
            _run_cmd(["systemctl", "--user", "stop", label], check=False)
            _run_cmd(["systemctl", "--user", "disable", label], check=False)
            if linux_unit.exists():
                linux_unit.unlink()
            _run_cmd(["systemctl", "--user", "daemon-reload"], check=False)
            console.print(f"[green]✓[/green] Uninstalled service {label}")
            return
        if system == "windows" and win_xml:
            _run_cmd(["schtasks", "/end", "/tn", label], check=False)
            _run_cmd(["schtasks", "/delete", "/tn", label, "/f"], check=False)
            if win_xml.exists():
                win_xml.unlink()
            console.print(f"[green]✓[/green] Uninstalled service {label}")
            return
    except Exception as e:
        console.print(f"[red]Failed to uninstall service: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[red]Unsupported platform: {platform.system()}[/red]")
    raise typer.Exit(1)


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

    # Copy builtin persona files to workspace
    _install_persona_files(workspace)

    # Persona selection
    console.print("\n[bold cyan]Choose a persona for your bot:[/bold cyan]")
    personas_dir = workspace / "personas"
    if personas_dir.exists():
        choices = [f.stem for f in sorted(personas_dir.glob("*.md"))]
        for i, name in enumerate(choices, 1):
            marker = " [green](default)[/green]" if name == "default" else ""
            console.print(f"  {i}. [cyan]{name}[/cyan]{marker}")
        choice = typer.prompt("Select persona number", default="1")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(choices):
                selected = choices[idx]
                config.agents.defaults.persona = selected
                save_config(config)
                console.print(f"[green]✓[/green] Persona set to: [cyan]{selected}[/cyan]")
            else:
                console.print("[dim]Using default persona.[/dim]")
        except ValueError:
            console.print("[dim]Using default persona.[/dim]")

    console.print(f"\n{__logo__} flowly is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.flowly/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]flowly agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? Run: flowly channels login[/dim]")
    console.print("[dim]Change persona later: flowly persona set <name>[/dim]")




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
            file_path.write_text(content, encoding="utf-8")
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
""", encoding="utf-8")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")


def _install_persona_files(workspace: Path):
    """Copy builtin persona files to workspace/personas/ directory."""
    personas_dir = workspace / "personas"
    personas_dir.mkdir(exist_ok=True)

    # Builtin personas are shipped in the package's workspace/personas/ directory
    builtin_dir = Path(__file__).parent.parent.parent / "workspace" / "personas"
    if builtin_dir.exists():
        for src in builtin_dir.glob("*.md"):
            dst = personas_dir / src.name
            if not dst.exists():
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                console.print(f"  [dim]Created personas/{src.name}[/dim]")
    else:
        # Fallback: create a minimal default persona
        default_file = personas_dir / "default.md"
        if not default_file.exists():
            default_file.write_text(
                "# Persona: Flowly\n\n"
                "You are Flowly, a helpful AI assistant.\n\n"
                "## Personality\n\n"
                "- Helpful and friendly\n"
                "- Concise and to the point\n"
                "- Curious and eager to learn\n",
                encoding="utf-8",
            )
            console.print("  [dim]Created personas/default.md[/dim]")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    persona: str = typer.Option("", "--persona", help="Bot persona (default, jarvis, pirate, samurai, casual, professor, butler, friday)"),
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

    import logging
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    from flowly import __banner__
    console.print(f"[cyan]{__banner__.format(version=__version__)}[/cyan]")
    console.print(f"Starting gateway on port {port}...")

    config = load_config()

    # Resolve persona: CLI flag overrides config
    active_persona = persona if persona else config.agents.defaults.persona
    if active_persona:
        console.print(f"[dim]Persona: {active_persona}[/dim]")

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
        security=exec_cfg.security,
        ask=exec_cfg.ask,
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
        action_temperature=config.agents.defaults.action_temperature,
        action_tool_retries=config.agents.defaults.action_tool_retries,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None,
        cron_service=cron,
        context_messages=config.agents.defaults.context_messages,
        compaction_config=compaction_config,
        exec_config=exec_config,
        trello_config=config.integrations.trello,
        voice_config=config.integrations.voice,
        x_config=config.integrations.x,
        persona=active_persona,
    )

    # Multi-agent setup (if agents are configured in config.json)
    multi_agents = config.agents.agents
    multi_teams = config.agents.teams

    if multi_agents:
        from flowly.multiagent.router import AgentRouter
        from flowly.multiagent.orchestrator import TeamOrchestrator
        from flowly.multiagent.setup import ensure_agent_directory
        from flowly.agent.tools.delegate import DelegateTool

        ma_router = AgentRouter(multi_agents, multi_teams)
        ma_orchestrator = TeamOrchestrator(ma_router)

        # Setup agent working directories
        agents_workspace = config.workspace_path / "agents"
        for aid, acfg in multi_agents.items():
            agent_dir = agents_workspace / aid
            ensure_agent_directory(agent_dir, aid, multi_agents, multi_teams)

        # Register delegate_to tool on main agent
        delegate_tool = DelegateTool(multi_agents, multi_teams, agents_workspace, bus)
        agent.tools.register(delegate_tool)

        # Wrap _process_message with multi-agent routing
        _original_process = agent._process_message

        async def _routed_process(msg):
            from flowly.bus.events import InboundMessage as _IB, OutboundMessage as _OB

            # Update delegate tool context so background results go to the right chat
            delegate_tool.set_context(msg.channel, msg.chat_id)

            # System messages bypass routing
            if msg.channel == "system":
                return await _original_process(msg)

            # Route @mentions
            routing = ma_router.route(msg.content)

            if routing.agent_id == "default" or routing.agent_id not in multi_agents:
                return await _original_process(msg)

            # @mention detected — rewrite message so the main agent uses delegate_to tool
            # This way the model responds naturally AND the task runs in background
            msg.content = (
                f"[SYSTEM: User wants to talk to @{routing.agent_id}. "
                f"Use the delegate_to tool with agent_id=\"{routing.agent_id}\" "
                f"and the following message.]\n\n{routing.message}"
            )
            return await _original_process(msg)

        agent._process_message = _routed_process

        agent_names = [f"@{aid} ({acfg.name})" for aid, acfg in multi_agents.items()]
        console.print(f"[green]✓[/green] Multi-agent: {', '.join(agent_names)}")
        if multi_teams:
            team_names = [f"@{tid} ({tcfg.name})" for tid, tcfg in multi_teams.items()]
            console.print(f"[green]✓[/green] Teams: {', '.join(team_names)}")

    # Set cron job callback (needs agent to be created first)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""

        def _inject_cron_result_to_session(
            job: CronJob, result: str, *, is_error: bool = False
        ) -> None:
            """Inject cron job result into the user's original session so the
            agent is aware of what happened when the user continues chatting."""
            channel = job.payload.channel or "telegram"
            chat_id = job.payload.to
            if not chat_id:
                return
            session_key = f"{channel}:{chat_id}"
            session = agent.sessions.get_or_create(session_key)
            status = "ERROR" if is_error else "COMPLETED"
            session.add_message(
                "system",
                f"[Cron Job {status}: {job.name}]\n{result}",
            )
            agent.sessions.save(session)

        if job.payload.kind == "tool_call":
            tool_name = job.payload.tool_name
            if not tool_name:
                raise ValueError(f"Cron job '{job.id}' is tool_call but tool_name is missing")

            delivery_channel = job.payload.channel or "telegram"
            delivery_to = job.payload.to

            # Rehydrate tool contexts for direct cron-triggered tool execution.
            if delivery_to:
                for context_tool_name in ("message", "spawn", "cron", "voice_call"):
                    context_tool = agent.tools.get(context_tool_name)
                    if context_tool and hasattr(context_tool, "set_context"):
                        context_tool.set_context(delivery_channel, delivery_to)

            result = await agent.tools.execute(tool_name, job.payload.tool_args or {})
            is_error = bool(result and result.startswith("Error"))

            # Inject result into user's session so agent knows what happened
            _inject_cron_result_to_session(job, result or "✓ Done.", is_error=is_error)

            if job.payload.deliver and delivery_to:
                from flowly.bus.events import OutboundMessage
                await bus.publish_outbound(OutboundMessage(
                    channel=delivery_channel,
                    chat_id=delivery_to,
                    content=result or "✓ Done.",
                ))

            return result

        # Build the prompt - if delivery is requested, tell agent to send message
        prompt = job.payload.message

        if job.payload.deliver:
            channel = job.payload.channel or "telegram"
            if job.payload.to:
                # We have a specific target - send directly after agent processes
                response = await agent.process_direct(prompt, session_key=f"cron:{job.id}")

                # Inject result into user's session
                _inject_cron_result_to_session(
                    job,
                    response or "(no response)",
                    is_error=not response,
                )

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

        # Inject result into user's session even for non-deliver jobs
        _inject_cron_result_to_session(
            job,
            response or "(no response)",
            is_error=not response,
        )

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

    # Legacy bridge fallback (disabled by default; integrated Python plugin is official path)
    legacy_voice_bridge_enabled = bool(config.integrations.voice.legacy_bridge_enabled)

    # Create gateway API callback for legacy voice bridge
    async def on_voice_message(call_sid: str, from_number: str, text: str) -> str:
        """Handle voice message from voice bridge."""
        # Use Telegram session if configured, otherwise use voice-specific session
        telegram_chat_id = config.integrations.voice.telegram_chat_id
        if telegram_chat_id:
            session_key = f"telegram:{telegram_chat_id}"
        else:
            session_key = f"voice:{call_sid}"

        # Format message with clear voice context
        prompt = f"""[ACTIVE PHONE CALL]
Call SID: {call_sid}
Caller: {from_number}

User said: "{text}"

IMPORTANT RULES:
1. This is a phone call — the user can only hear what you say.
2. Only use safe tools if needed (voice_call end/list, screenshot, message, system).
3. If you take a screenshot, it goes to Telegram automatically — tell the user "I sent the screenshot to Telegram".
4. To hang up: voice_call(action="end_call", call_sid="{call_sid}", message="Goodbye!")
5. Keep it short and clear — long sentences are hard to understand on the phone.

Respond to the user now:"""
        response = await agent.process_direct(prompt, session_key=session_key)
        return response or "Sorry, something went wrong. Could you say that again?"

    gateway_server = GatewayServer(
        host=config.gateway.host,
        port=port,
        on_voice_message=on_voice_message if legacy_voice_bridge_enabled else None,
    )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every 30m")
    if legacy_voice_bridge_enabled:
        console.print("[yellow]⚠[/yellow] Legacy voice bridge fallback enabled")

    # Initialize voice plugin if enabled
    voice_plugin = None
    if config.integrations.voice.enabled:
        voice_cfg = config.integrations.voice
        if voice_cfg.twilio_account_sid and voice_cfg.twilio_auth_token:
            try:
                from flowly.voice.plugin import VoicePlugin
                voice_plugin = VoicePlugin(config, agent)
                # Connect voice plugin to agent's voice tool
                agent.set_voice_plugin(voice_plugin)
                console.print(f"[green]✓[/green] Voice calls: initializing...")
            except Exception as e:
                console.print(f"[yellow]Warning: Voice plugin failed to initialize: {e}[/yellow]")
        else:
            console.print(f"[yellow]Warning: Voice enabled but Twilio credentials not configured[/yellow]")

    console.print(f"[green]✓[/green] API: http://{config.gateway.host}:{port}")

    async def run():
        shutdown_event = asyncio.Event()

        def signal_handler():
            console.print("\n[yellow]Shutting down...[/yellow]")
            shutdown_event.set()

        if platform.system() == "Windows":
            # Windows asyncio doesn't support loop.add_signal_handler
            signal.signal(signal.SIGINT, lambda s, f: signal_handler())
            signal.signal(signal.SIGTERM, lambda s, f: signal_handler())
        else:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, signal_handler)

        try:
            await gateway_server.start()
            await cron.start()
            await heartbeat.start()

            # Start voice plugin if available
            if voice_plugin:
                await voice_plugin.start(host="0.0.0.0", port=8765)
                if voice_plugin._ngrok_tunnel:
                    console.print(f"[green]✓[/green] Voice calls: ngrok tunnel ({voice_plugin._webhook_base_url})")
                else:
                    console.print(f"[green]✓[/green] Voice calls: integrated ({voice_plugin._webhook_base_url})")

            # Run until shutdown signal
            async def run_until_shutdown():
                await asyncio.gather(
                    agent.run(),
                    channels.start_all(),
                )

            # Create main task
            main_task = asyncio.create_task(run_until_shutdown())

            # Wait for either shutdown signal or task completion
            done, pending = await asyncio.wait(
                [main_task, asyncio.create_task(shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        finally:
            # Graceful shutdown
            console.print("[dim]Cleaning up...[/dim]")
            if voice_plugin:
                await voice_plugin.stop()
            await gateway_server.stop()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
            console.print("[green]✓[/green] Shutdown complete")

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
        security=exec_cfg.security,
        ask=exec_cfg.ask,
        timeout_seconds=exec_cfg.timeout_seconds,
        max_output_chars=exec_cfg.max_output_chars,
        approval_timeout_seconds=exec_cfg.approval_timeout_seconds,
    )

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        action_temperature=config.agents.defaults.action_temperature,
        action_tool_retries=config.agents.defaults.action_tool_retries,
        brave_api_key=config.tools.web.search.api_key or None,
        cron_service=cron,
        context_messages=config.agents.defaults.context_messages,
        compaction_config=compaction_config,
        exec_config=exec_config,
        trello_config=config.integrations.trello,
        voice_config=config.integrations.voice,
        x_config=config.integrations.x,
        persona=config.agents.defaults.persona,
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
        npm = get_npm_command()
        use_shell = platform.system() == "Windows"
        console.print("  Installing dependencies...")
        subprocess.run(f'"{npm}" install' if use_shell else [npm, "install"], cwd=user_bridge, check=True, capture_output=True, shell=use_shell)

        console.print("  Building...")
        subprocess.run(f'"{npm}" run build' if use_shell else [npm, "run", "build"], cwd=user_bridge, check=True, capture_output=True, shell=use_shell)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js from https://nodejs.org[/red]")
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
        npm = get_npm_command()
        use_shell = platform.system() == "Windows"
        subprocess.run(f'"{npm}" start' if use_shell else [npm, "start"], cwd=bridge_dir, check=True, shell=use_shell)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js from https://nodejs.org[/red]")


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

    if channel not in ("telegram", "whatsapp", "discord", "slack"):
        console.print(f"[red]Invalid channel: {channel}. Use 'telegram', 'whatsapp', 'discord', or 'slack'[/red]")
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

    if channel not in ("telegram", "whatsapp", "discord", "slack"):
        console.print(f"[red]Invalid channel: {channel}. Use 'telegram', 'whatsapp', 'discord', or 'slack'[/red]")
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

    if channel not in ("telegram", "whatsapp", "discord", "slack"):
        console.print(f"[red]Invalid channel: {channel}. Use 'telegram', 'whatsapp', 'discord', or 'slack'[/red]")
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

    if channel not in ("telegram", "whatsapp", "discord", "slack"):
        console.print(f"[red]Invalid channel: {channel}. Use 'telegram', 'whatsapp', 'discord', or 'slack'[/red]")
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
