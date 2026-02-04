"""Command executor with security checks."""

import asyncio
import subprocess
import sys
from pathlib import Path

from loguru import logger

from flowly.exec.types import (
    ExecRequest,
    ExecResult,
    ExecConfig,
)
from flowly.exec.safety import analyze_command
from flowly.exec.approvals import (
    ExecApprovalStore,
    check_allowlist,
    requires_approval,
)


async def execute_command(
    request: ExecRequest,
    config: ExecConfig,
    store: ExecApprovalStore,
) -> ExecResult:
    """
    Execute a command with full security checks.

    Security flow:
    1. Check if exec is enabled
    2. Analyze command for safety
    3. Check security mode (deny/allowlist/full)
    4. Check allowlist if in allowlist mode
    5. Request approval if needed
    6. Execute command with timeout
    """
    # Check if enabled
    if not config.enabled:
        return ExecResult(
            success=False,
            denied=True,
            error="Command execution is disabled"
        )

    # Analyze command
    analysis = analyze_command(request.command)

    # Check for dangerous patterns
    if analysis.has_dangerous_chars:
        return ExecResult(
            success=False,
            denied=True,
            error=f"Command rejected: {analysis.reason}"
        )

    # Get store config
    store_config = store.config

    # Security mode check
    if store_config.security == "deny":
        return ExecResult(
            success=False,
            denied=True,
            error="Command execution denied by security policy"
        )

    # Allowlist mode
    if store_config.security == "allowlist":
        allowlist_ok = check_allowlist(store, analysis.resolved_path, analysis.executable)

        # Check if approval is required
        if requires_approval(store_config, analysis.ok, allowlist_ok):
            # Create pending approval
            pending = store.create_pending(request, config.approval_timeout_seconds)

            # Request approval via callback (Telegram)
            decision = await store.request_approval(pending)

            if decision is None:
                # Timeout or no callback
                return ExecResult(
                    success=False,
                    denied=True,
                    error="Approval timed out or not available"
                )

            if decision == "deny":
                store.resolve_pending(pending.id, decision)
                return ExecResult(
                    success=False,
                    denied=True,
                    error="Command denied by user"
                )

            # Allow-once or allow-always
            store.resolve_pending(pending.id, decision)

        elif not allowlist_ok and not analysis.is_safe_bin:
            # Not in allowlist and not a safe bin
            return ExecResult(
                success=False,
                denied=True,
                error=f"Command not in allowlist: {analysis.executable}"
            )

    # Execute the command
    timeout = request.timeout or config.timeout_seconds
    cwd = request.cwd or str(Path.home())

    try:
        # Build environment
        env = None
        if request.env:
            import os
            env = os.environ.copy()
            env.update(request.env)

        # Run command
        process = await asyncio.create_subprocess_shell(
            request.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ExecResult(
                success=False,
                exit_code=-1,
                error=f"Command timed out after {timeout} seconds",
                timed_out=True
            )

        # Decode output
        stdout_str = stdout.decode('utf-8', errors='replace')
        stderr_str = stderr.decode('utf-8', errors='replace')

        # Truncate if too long
        max_output = config.max_output_chars
        if len(stdout_str) > max_output:
            stdout_str = stdout_str[:max_output] + f"\n... (truncated, {len(stdout_str)} total chars)"
        if len(stderr_str) > max_output:
            stderr_str = stderr_str[:max_output] + f"\n... (truncated, {len(stderr_str)} total chars)"

        return ExecResult(
            success=process.returncode == 0,
            exit_code=process.returncode,
            stdout=stdout_str,
            stderr=stderr_str,
        )

    except Exception as e:
        logger.error(f"Command execution error: {e}")
        return ExecResult(
            success=False,
            error=str(e)
        )
