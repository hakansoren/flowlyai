"""Secure shell execution tool with approval system."""

import asyncio
from typing import Any, Callable, Awaitable

from loguru import logger

from flowly.agent.tools.base import Tool
from flowly.exec import (
    ExecConfig,
    ExecRequest,
    ExecResult,
    ExecApprovalStore,
    ExecApprovalDecision,
    analyze_command,
    execute_command,
)
from flowly.exec.types import PendingApproval


class SecureExecTool(Tool):
    """
    Secure shell command execution tool.

    Features:
    - Security modes: deny, allowlist, full
    - Ask modes: off, on-miss, always
    - Command analysis for dangerous patterns
    - Safe bins (jq, grep, etc.) always allowed
    - Allowlist with glob pattern matching
    - Approval system via callback (Telegram)
    """

    def __init__(
        self,
        config: ExecConfig,
        approval_callback: Callable[[PendingApproval], Awaitable[ExecApprovalDecision | None]] | None = None,
        working_dir: str | None = None,
    ):
        self.config = config
        self.working_dir = working_dir
        self._store = ExecApprovalStore()
        self._store.load()

        if approval_callback:
            self._store.set_approval_callback(approval_callback)

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        if not self.config.enabled:
            return "Execute shell commands. CURRENTLY DISABLED."

        security = self._store.config.security
        ask = self._store.config.ask

        desc = "Execute a shell command and return its output.\n\n"
        desc += f"Security: {security}, Ask: {ask}\n"

        if security == "deny":
            desc += "WARNING: Command execution is currently denied."
        elif security == "allowlist":
            desc += "Only allowlisted commands and safe bins (grep, jq, etc.) are permitted.\n"
            desc += "Other commands require user approval."
        elif security == "full":
            desc += "Full access mode - all commands allowed."

        return desc

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command"
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Optional timeout in seconds (default: {self.config.timeout_seconds})"
                }
            },
            "required": ["command"]
        }

    def set_approval_callback(
        self,
        callback: Callable[[PendingApproval], Awaitable[ExecApprovalDecision | None]]
    ) -> None:
        """Set the approval callback (for Telegram integration)."""
        self._store.set_approval_callback(callback)

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
        session_key: str | None = None,
        **kwargs: Any
    ) -> str:
        """Execute a command with full security checks."""

        # Create request
        request = ExecRequest(
            command=command.strip(),
            cwd=working_dir or self.working_dir,
            timeout=timeout,
            session_key=session_key,
        )

        # Analyze command first (for logging)
        analysis = analyze_command(command)
        logger.info(f"Exec request: {command[:50]}... (safe_bin={analysis.is_safe_bin}, resolved={analysis.resolved_path})")

        # Execute with security checks
        result = await execute_command(request, self.config, self._store)

        # Format result
        if result.denied:
            return f"❌ Command denied: {result.error}"

        if result.timed_out:
            return f"⏰ Command timed out after {timeout or self.config.timeout_seconds} seconds"

        if result.error:
            return f"❌ Error: {result.error}"

        # Build output
        output_parts = []

        if result.stdout:
            output_parts.append(result.stdout)

        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")

        if result.exit_code is not None and result.exit_code != 0:
            output_parts.append(f"\nExit code: {result.exit_code}")

        return "\n".join(output_parts) if output_parts else "(no output)"

    @property
    def store(self) -> ExecApprovalStore:
        """Get the approval store for external management."""
        return self._store


# Keep backward compatibility alias
ExecTool = SecureExecTool
