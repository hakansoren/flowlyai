"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from flowly.bus.events import InboundMessage, OutboundMessage
from flowly.bus.queue import MessageBus
from flowly.providers.base import LLMProvider
from flowly.agent.context import ContextBuilder
from flowly.agent.tools.registry import ToolRegistry
from flowly.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from flowly.agent.tools.shell import ExecTool
from flowly.agent.tools.web import WebSearchTool, WebFetchTool
from flowly.agent.tools.message import MessageTool
from flowly.agent.tools.screenshot import ScreenshotTool
from flowly.agent.tools.spawn import SpawnTool
from flowly.agent.tools.cron import CronTool
from flowly.agent.tools.trello import TrelloTool
from flowly.agent.tools.docker import DockerTool
from flowly.agent.tools.system import SystemTool
from flowly.agent.tools.voice import VoiceCallTool
from flowly.agent.subagent import SubagentManager
from flowly.session.manager import SessionManager
from flowly.cron.service import CronService
from flowly.compaction.service import CompactionService
from flowly.compaction.types import CompactionConfig, MemoryFlushConfig
from flowly.compaction.estimator import estimate_messages_tokens
from flowly.exec.types import ExecConfig
from flowly.config.schema import TrelloConfig, VoiceBridgeConfig


class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        cron_service: CronService | None = None,
        context_messages: int = 100,
        compaction_config: CompactionConfig | None = None,
        exec_config: ExecConfig | None = None,
        trello_config: TrelloConfig | None = None,
        voice_config: VoiceBridgeConfig | None = None,
    ):
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.cron_service = cron_service
        self.context_messages = context_messages

        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
        )

        # Compaction service
        self.compaction = CompactionService(
            provider=provider,
            model=self.model,
            config=compaction_config,
        )

        # Exec config
        self.exec_config = exec_config or ExecConfig()

        # Trello config
        self.trello_config = trello_config

        # Voice config
        self.voice_config = voice_config

        self._running = False
        self._register_default_tools()
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(EditFileTool())
        self.tools.register(ListDirTool())
        
        # Shell tool (secure)
        from flowly.agent.tools.shell import SecureExecTool
        self.tools.register(SecureExecTool(
            config=self.exec_config,
            working_dir=str(self.workspace),
        ))
        
        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        
        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)

        # Screenshot tool
        self.tools.register(ScreenshotTool())

        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)

        # Cron tool (for scheduling)
        cron_tool = CronTool(cron_service=self.cron_service)
        self.tools.register(cron_tool)

        # Trello tool (if configured)
        if self.trello_config and self.trello_config.api_key and self.trello_config.token:
            self.tools.register(TrelloTool(
                api_key=self.trello_config.api_key,
                token=self.trello_config.token,
            ))

        # Docker tool (always available, will error if Docker not installed)
        self.tools.register(DockerTool())

        # System monitoring tool
        self.tools.register(SystemTool())

        # Voice call tool (if configured)
        # Note: The voice plugin is set later via set_voice_plugin() after the plugin is created
        if self.voice_config and self.voice_config.enabled:
            self._voice_tool = VoiceCallTool()
            self.tools.register(self._voice_tool)
        else:
            self._voice_tool = None

    def set_voice_plugin(self, voice_plugin) -> None:
        """Set the voice plugin for voice call tool integration.

        This must be called after the VoicePlugin is created to enable
        integrated voice call handling with full tool access.
        """
        if self._voice_tool:
            self._voice_tool.set_voice_plugin(voice_plugin)
            logger.info("Voice plugin connected to agent")

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")
        
        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    def set_cron_service(self, cron_service: CronService) -> None:
        """Set the cron service for the cron tool."""
        self.cron_service = cron_service
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_cron_service(cron_service)

    async def _run_memory_flush(
        self,
        session: Any,
        channel: str,
        chat_id: str,
    ) -> None:
        """
        Run a pre-compaction memory flush turn.

        This gives the agent a chance to save important information
        to disk before context gets compacted.
        """
        user_prompt, system_prompt = self.compaction.get_memory_flush_prompt()

        # Build messages with flush prompt
        messages = self.context.build_messages(
            history=session.get_history(max_messages=self.context_messages),
            current_message=user_prompt,
        )

        # Add system prompt for flush context
        messages[0]["content"] += f"\n\n{system_prompt}"

        # Run a single turn with tools available
        try:
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )

            # Execute any tool calls (agent might want to write to memory)
            if response.has_tool_calls:
                for tool_call in response.tool_calls:
                    logger.debug(f"Memory flush tool: {tool_call.name}")
                    await self.tools.execute(tool_call.name, tool_call.arguments)

            # Check if response should be silent
            content = response.content or ""
            if not self.compaction.is_silent_reply(content):
                # Agent wants to communicate something
                stripped = self.compaction.strip_silent_token(content)
                if stripped:
                    logger.info(f"Memory flush response: {stripped[:100]}...")
                    # Optionally send to user
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=channel,
                        chat_id=chat_id,
                        content=f"📝 {stripped}"
                    ))

            # Save flush interaction to session
            session.add_message("user", f"[System: Memory Flush] {user_prompt}")
            session.add_message("assistant", content)
            self.sessions.save(session)

        except Exception as e:
            logger.warning(f"Memory flush failed: {e}")
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.
        
        Args:
            msg: The inbound message to process.
        
        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")
        
        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)
        
        # Get history and check for compaction
        history = session.get_history(max_messages=self.context_messages)

        # Check if memory flush is needed before potential compaction
        total_tokens = estimate_messages_tokens(history)
        if self.compaction.should_memory_flush(total_tokens):
            logger.info("Running pre-compaction memory flush")
            await self._run_memory_flush(session, msg.channel, msg.chat_id)
            self.compaction.mark_memory_flush_done()
            # Reload history after flush
            history = session.get_history(max_messages=self.context_messages)
            total_tokens = estimate_messages_tokens(history)

        # Check if compaction is needed
        if self.compaction.should_compact(total_tokens):
            logger.info(f"Compacting context: {total_tokens} tokens exceeds threshold")
            result = await self.compaction.compact(history)
            logger.info(
                f"Compaction complete: {result.tokens_before} -> {result.tokens_after} tokens, "
                f"removed {result.messages_removed} messages"
            )
            # Replace history with summary
            history = [{"role": "system", "content": f"[Previous conversation summary]\n\n{result.summary}"}]
            # Update session with compacted history
            session.metadata["last_compaction_summary"] = result.summary

        # Build initial messages
        messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
        )

        # Agent loop
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "I've completed processing but have no response to give."
        
        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content
        )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)
        
        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(max_messages=self.context_messages),
            current_message=msg.content
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(self, content: str, session_key: str = "cli:direct") -> str:
        """
        Process a message directly (for CLI usage or voice calls).

        Args:
            content: The message content.
            session_key: Session identifier in format "channel:chat_id".

        Returns:
            The agent's response.
        """
        # Parse session_key to extract channel and chat_id
        if ":" in session_key:
            channel, chat_id = session_key.split(":", 1)
        else:
            channel, chat_id = "cli", session_key

        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )

        response = await self._process_message(msg)
        return response.content if response else ""

    async def compact_session(
        self,
        session_key: str,
        custom_instructions: str | None = None,
    ) -> dict[str, Any]:
        """
        Manually compact a session's history.

        Args:
            session_key: Session identifier.
            custom_instructions: Optional instructions for summarization.

        Returns:
            Dict with compaction results.
        """
        session = self.sessions.get_or_create(session_key)
        history = session.get_history(max_messages=self.context_messages)

        if not history:
            return {
                "success": False,
                "message": "No history to compact.",
                "tokens_before": 0,
                "tokens_after": 0,
            }

        tokens_before = estimate_messages_tokens(history)

        # Check if already compacted (first message is a compaction summary)
        is_already_compacted = (
            len(history) == 1
            and history[0].get("role") == "system"
            and "[Compacted conversation summary]" in history[0].get("content", "")
        )

        if is_already_compacted:
            return {
                "success": False,
                "message": "Already compacted. Send more messages first.",
                "tokens_before": tokens_before,
                "tokens_after": tokens_before,
            }

        # Check if too few messages to compact (need at least 3 messages)
        # Filter out system messages for this count
        user_assistant_messages = [m for m in history if m.get("role") in ("user", "assistant")]
        if len(user_assistant_messages) < 3:
            return {
                "success": False,
                "message": f"Not enough messages to compact ({len(user_assistant_messages)} messages). Need at least 3.",
                "tokens_before": tokens_before,
                "tokens_after": tokens_before,
            }

        # Check if token count is too low to bother compacting (< 1000 tokens)
        if tokens_before < 1000:
            return {
                "success": False,
                "message": f"History too small to compact ({tokens_before} tokens). Need at least 1000.",
                "tokens_before": tokens_before,
                "tokens_after": tokens_before,
            }

        # Run compaction
        result = await self.compaction.compact(
            history,
            custom_instructions=custom_instructions,
        )

        # Clear session and add summary as first message
        session.clear()
        session.add_message(
            "system",
            f"[Compacted conversation summary]\n\n{result.summary}"
        )
        session.metadata["last_compaction_summary"] = result.summary
        session.metadata["compaction_count"] = session.metadata.get("compaction_count", 0) + 1
        self.sessions.save(session)

        return {
            "success": True,
            "message": f"Compacted {result.messages_removed} messages",
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "summary_preview": result.summary[:200] + "..." if len(result.summary) > 200 else result.summary,
        }
