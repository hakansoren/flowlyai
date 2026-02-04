"""Command safety analysis and validation."""

import re
import shlex
import shutil
from pathlib import Path

from flowly.exec.types import CommandAnalysis

# Safe binaries that only operate on stdin (no file args)
DEFAULT_SAFE_BINS = frozenset([
    "jq", "grep", "cut", "sort", "uniq", "head", "tail", "tr", "wc",
    "cat", "echo", "date", "whoami", "pwd", "hostname", "uname",
])

# Dangerous shell metacharacters
SHELL_METACHARS = re.compile(r'[;&|`$<>]')
CONTROL_CHARS = re.compile(r'[\r\n\x00]')
QUOTE_CHARS = re.compile(r'["\']')

# Patterns for dangerous commands
DANGEROUS_PATTERNS = [
    re.compile(r'\brm\s+(-[rf]+\s+)*/', re.IGNORECASE),  # rm -rf /
    re.compile(r'\bsudo\b', re.IGNORECASE),
    re.compile(r'\bchmod\s+777', re.IGNORECASE),
    re.compile(r'\bchown\b.*root', re.IGNORECASE),
    re.compile(r'\bmkfs\b', re.IGNORECASE),
    re.compile(r'\bdd\b.*of=/', re.IGNORECASE),
    re.compile(r'>\s*/dev/', re.IGNORECASE),
    re.compile(r'\bcurl\b.*\|\s*(ba)?sh', re.IGNORECASE),  # curl | sh
    re.compile(r'\bwget\b.*\|\s*(ba)?sh', re.IGNORECASE),  # wget | sh
    re.compile(r':(){.*};:', re.IGNORECASE),  # Fork bomb
]

# Pipeline operators that are not allowed in allowlist mode
DISALLOWED_PIPELINE_OPS = {'||', '|&', '`', '$(', '\n', '\r', '(', ')'}


def is_safe_executable(value: str | None) -> bool:
    """Check if a string is safe to use as an executable name."""
    if not value:
        return False

    trimmed = value.strip()
    if not trimmed:
        return False

    # Check for dangerous characters
    if '\0' in trimmed:
        return False
    if CONTROL_CHARS.search(trimmed):
        return False
    if SHELL_METACHARS.search(trimmed):
        return False

    return True


def resolve_executable(name: str) -> str | None:
    """Resolve an executable name to its full path."""
    # If it's already a path
    if '/' in name:
        path = Path(name).expanduser().resolve()
        if path.exists() and path.is_file():
            return str(path)
        return None

    # Use shutil.which to find in PATH
    return shutil.which(name)


def is_safe_bin(executable: str, args: list[str]) -> bool:
    """Check if command is a safe stdin-only binary with safe args."""
    # Get basename
    name = Path(executable).name if '/' in executable else executable

    if name not in DEFAULT_SAFE_BINS:
        return False

    # Check args don't reference files
    for arg in args:
        # Skip flags
        if arg.startswith('-'):
            continue
        # Check if arg looks like a path
        if '/' in arg or arg.startswith('~'):
            return False
        # Check if arg is an existing file
        if Path(arg).exists():
            return False

    return True


def has_dangerous_pattern(command: str) -> bool:
    """Check if command matches any dangerous patterns."""
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(command):
            return True
    return False


def split_pipeline(command: str) -> tuple[bool, str | None, list[str]]:
    """
    Split a command into pipeline segments.

    Returns (ok, reason, segments).
    """
    # Check for disallowed operators
    for op in DISALLOWED_PIPELINE_OPS:
        if op in command:
            return False, f"Disallowed operator: {op}", []

    # Check for command substitution
    if '$(' in command or '`' in command:
        return False, "Command substitution not allowed", []

    # Check for redirection
    if re.search(r'[<>]', command):
        return False, "Redirection not allowed in allowlist mode", []

    # Split by pipe
    segments = [s.strip() for s in command.split('|')]

    # Validate each segment
    for seg in segments:
        if not seg:
            return False, "Empty pipeline segment", []

    return True, None, segments


def parse_command(command: str) -> tuple[str | None, list[str]]:
    """Parse a command into executable and arguments."""
    try:
        parts = shlex.split(command)
        if not parts:
            return None, []
        return parts[0], parts[1:]
    except ValueError:
        return None, []


def analyze_command(command: str) -> CommandAnalysis:
    """
    Analyze a shell command for safety.

    Returns a CommandAnalysis with details about the command.
    """
    command = command.strip()

    if not command:
        return CommandAnalysis(ok=False, reason="Empty command")

    # Check for control characters
    if CONTROL_CHARS.search(command):
        return CommandAnalysis(
            ok=False,
            reason="Control characters not allowed",
            has_dangerous_chars=True
        )

    # Check for dangerous patterns
    if has_dangerous_pattern(command):
        return CommandAnalysis(
            ok=False,
            reason="Command matches dangerous pattern",
            has_dangerous_chars=True
        )

    # Check if it's a pipeline
    is_pipeline = '|' in command and '||' not in command

    if is_pipeline:
        ok, reason, segments = split_pipeline(command)
        if not ok:
            return CommandAnalysis(
                ok=False,
                reason=reason,
                is_pipeline=True,
                has_dangerous_chars=True
            )

        # For pipelines, analyze the first segment
        executable, args = parse_command(segments[0])
        resolved = resolve_executable(executable) if executable else None

        return CommandAnalysis(
            ok=True,
            executable=executable,
            resolved_path=resolved,
            args=args,
            is_pipeline=True,
            segments=segments,
            is_safe_bin=is_safe_bin(executable, args) if executable else False
        )

    # Single command
    executable, args = parse_command(command)

    if not executable:
        return CommandAnalysis(ok=False, reason="Could not parse command")

    # Check for shell metachars in the executable
    if SHELL_METACHARS.search(executable):
        return CommandAnalysis(
            ok=False,
            reason="Shell metacharacters in executable",
            has_dangerous_chars=True
        )

    # Resolve the executable path
    resolved = resolve_executable(executable)

    return CommandAnalysis(
        ok=True,
        executable=executable,
        resolved_path=resolved,
        args=args,
        is_pipeline=False,
        is_safe_bin=is_safe_bin(executable, args)
    )
