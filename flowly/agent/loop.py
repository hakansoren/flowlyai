"""Agent loop: the core processing engine."""

import asyncio
import copy
import json
import re
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
        action_model: str | None = None,
        action_temperature: float = 0.1,
        action_tool_retries: int = 2,
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
        self.action_model = action_model
        self.action_temperature = action_temperature
        self.action_tool_retries = max(0, action_tool_retries)
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
                first_msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                batch, dropped = self._coalesce_inbound_batch(first_msg)
                if dropped:
                    logger.warning(f"Inbound coalescing dropped {dropped} stale message(s)")

                # Process coalesced batch
                for msg in batch:
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

    def _extract_action_intent_text(self, content: str) -> str:
        """
        Extract the user utterance from voice-wrapped prompts for intent detection.

        Voice prompts include additional instructions that contain action words
        (e.g. "kapat"). We only want to analyze what the user actually said.
        """
        voice_patterns = (
            r'Kullanıcı şunu söyledi:\s*"(.*?)"',
            r'User said:\s*"(.*?)"',
        )
        for pattern in voice_patterns:
            match = re.search(pattern, content, flags=re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip().lower()
        return content.lower()

    def _is_action_turn(self, channel: str, content: str) -> bool:
        """Detect whether this turn is an action request that should execute tools strictly."""
        lowered = content.lower()
        if "voice_call(" in lowered or "cron(" in lowered:
            return True

        intent_text = self._extract_action_intent_text(content)
        action_patterns = (
            r"\barasana\b",
            r"\barar\s+m[ıi]s[ıi]n\b",
            r"\bara\b",
            r"\baray[ıi]p\b",
            r"\barama\b",
            r"\btelefon(?:la)?\b",
            r"\bcall\b",
            r"\bhat[ıi]rlat\b",
            r"\bremind(?:er)?\b",
            r"\bhaber\s+ver\b",
            r"\bbildir\b",
            r"\bnotify\b",
            r"\bschedule\b",
            r"\bplanla\b",
            r"\bcron\s+olu[şs]tur\b",
            r"\bg[öo]nder\b",
            r"\bsend\b",
            r"\bpayla[şs]\b",
            r"\bekran\s+g[öo]r[üu]nt[üu]s[üu]\b",
            r"\bscreenshot\b",
            r"\bss\b",
            r"\brun\s+tool\b",
        )
        return any(re.search(pattern, intent_text) for pattern in action_patterns)

    def _is_live_call_turn(self, content: str) -> bool:
        """
        Detect active call orchestration prompts.

        In this mode, voice output is already handled by the call pipeline,
        so the model should not use `voice_call(action="speak")`.
        """
        lowered = content.lower()
        return (
            "[aktif telefon görüşmesi]" in lowered
            or "[aktif telefon gorusmesi]" in lowered
            or ("call sid:" in lowered and "kullanıcı şunu söyledi:" in lowered)
            or ("call sid:" in lowered and "user said:" in lowered)
        )

    def _apply_turn_tool_policy(
        self,
        tool_defs: list[dict[str, Any]],
        live_call_turn: bool,
    ) -> list[dict[str, Any]]:
        """Apply per-turn tool constraints for safety and predictability."""
        if not live_call_turn:
            return tool_defs

        filtered_defs: list[dict[str, Any]] = []
        for tool_def in tool_defs:
            fn = tool_def.get("function", {})
            if fn.get("name") != "voice_call":
                filtered_defs.append(tool_def)
                continue

            # During active phone conversation turns, avoid self-referential
            # speak tool calls. The returned assistant text is spoken already.
            patched = copy.deepcopy(tool_def)
            action_prop = (
                patched.get("function", {})
                .get("parameters", {})
                .get("properties", {})
                .get("action")
            )
            if isinstance(action_prop, dict):
                enum_values = action_prop.get("enum")
                if isinstance(enum_values, list):
                    action_prop["enum"] = [
                        value for value in enum_values
                        if value in {"end_call", "list_calls"}
                    ]
            filtered_defs.append(patched)

        return filtered_defs

    def _coalesce_inbound_batch(self, first_msg: InboundMessage) -> tuple[list[InboundMessage], int]:
        """
        Coalesce bursty inbound traffic to reduce stale turn processing.

        Keeps the latest message per interactive session while preserving
        first-seen ordering across sessions.
        """
        interactive_channels = {"telegram", "whatsapp", "cli"}
        batch = [first_msg]

        while True:
            try:
                batch.append(self.bus.inbound.get_nowait())
            except asyncio.QueueEmpty:
                break

        if len(batch) == 1:
            return batch, 0

        coalesced: list[InboundMessage] = []
        session_index: dict[str, int] = {}
        dropped = 0

        for msg in batch:
            if msg.channel in interactive_channels:
                key = msg.session_key
                if key in session_index:
                    coalesced[session_index[key]] = msg
                    dropped += 1
                else:
                    session_index[key] = len(coalesced)
                    coalesced.append(msg)
            else:
                coalesced.append(msg)

        return coalesced, dropped

    async def _run_llm_tool_loop(
        self,
        messages: list[dict[str, Any]],
        action_turn: bool,
        live_call_turn: bool = False,
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        """
        Run iterative LLM + tool execution loop until final response.

        Returns:
            (final_content, accumulated_tool_results, executed_tool_names)
        """
        iteration = 0
        final_content: str | None = None
        accumulated_tool_results: list[dict[str, Any]] = []
        executed_tool_names: list[str] = []
        tools_were_used = False
        no_tool_retry_count = 0

        selected_model = (self.action_model or self.model) if action_turn else self.model
        selected_temperature = self.action_temperature if action_turn else 0.7

        while iteration < self.max_iterations:
            iteration += 1

            tool_defs = self._apply_turn_tool_policy(
                self.tools.get_definitions(),
                live_call_turn=live_call_turn,
            )
            tool_choice = "required" if (action_turn and not tools_were_used) else "auto"
            logger.info(
                "LLM request telemetry: "
                f"model={selected_model}, tool_choice={tool_choice}, tool_count={len(tool_defs)}, "
                f"action_turn={action_turn}, live_call_turn={live_call_turn}, "
                f"iteration={iteration}/{self.max_iterations}"
            )

            response = await self.provider.chat(
                messages=messages,
                tools=tool_defs,
                model=selected_model,
                temperature=selected_temperature,
                tool_choice=tool_choice,
            )

            if response.content and response.content.startswith("Error") and tool_choice == "required":
                logger.warning(f"tool_choice=required failed, retrying with auto: {response.content[:120]}")
                response = await self.provider.chat(
                    messages=messages,
                    tools=tool_defs,
                    model=selected_model,
                    temperature=selected_temperature,
                    tool_choice="auto",
                )

            if response.content and response.content.startswith("Error calling LLM:"):
                lowered_error = response.content.lower()
                schema_rejected = (
                    "input_schema does not support oneof" in lowered_error
                    or "input_schema does not support allof" in lowered_error
                    or "input_schema does not support anyof" in lowered_error
                )
                if schema_rejected:
                    logger.error("Provider rejected tool schema; aborting turn without additional retries.")
                    final_content = (
                        "Tool şeması model sağlayıcısı tarafından reddedildi. "
                        "İşlem çalıştırılmadı."
                    )
                else:
                    logger.error("LLM call failed after fallback; aborting turn without additional retries.")
                    final_content = (
                        "Model sağlayıcısından geçerli yanıt alınamadı. "
                        "İşlem çalıştırılmadı."
                    )
                break

            logger.info(
                "LLM response telemetry: "
                f"has_tool_calls={response.has_tool_calls}, content_len={len(response.content or '')}, "
                f"action_turn={action_turn}, live_call_turn={live_call_turn}, iteration={iteration}"
            )

            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ]

                assistant_content = None
                if response.content:
                    content_lower = response.content.lower()
                    hallucination_phrases = [
                        "yaptım", "gönderdim", "aldım", "açtım", "kapattım",
                        "i did", "i sent", "i took", "i opened", "i closed",
                        "done", "completed", "finished", "tamamlandı",
                    ]
                    if not any(phrase in content_lower for phrase in hallucination_phrases):
                        assistant_content = response.content

                messages = self.context.add_assistant_message(
                    messages, assistant_content, tool_call_dicts
                )

                turn_tools: list[str] = []
                terminal_action_executed = False
                turn_success_count = 0
                for tool_call in response.tool_calls:
                    turn_tools.append(tool_call.name)
                    executed_tool_names.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments)
                    logger.info(f"Executing tool: {tool_call.name}({args_str[:160]}...)")

                    try:
                        result = await self.tools.execute(tool_call.name, tool_call.arguments)
                        accumulated_tool_results.append({
                            "tool": tool_call.name,
                            "success": not result.startswith("Error"),
                            "result": result[:500] if len(result) > 500 else result,
                        })
                    except Exception as e:
                        result = f"Error executing {tool_call.name}: {str(e)}"
                        logger.error(result)
                        accumulated_tool_results.append({
                            "tool": tool_call.name,
                            "success": False,
                            "result": result,
                        })
                    else:
                        if not result.startswith("Error"):
                            turn_success_count += 1

                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )

                    # In strict action turns, stop as soon as a terminal action succeeds.
                    if action_turn and not result.startswith("Error"):
                        if tool_call.name == "voice_call":
                            voice_action = str(tool_call.arguments.get("action", "")).lower()
                            if voice_action in {"call", "end_call", "speak"}:
                                terminal_action_executed = True
                        elif tool_call.name == "cron":
                            cron_action = str(tool_call.arguments.get("action", "")).lower()
                            target_tool = str(tool_call.arguments.get("tool_name", "")).lower()
                            if cron_action == "add" and target_tool == "voice_call":
                                terminal_action_executed = True

                    if terminal_action_executed:
                        logger.info(
                            "Action turn terminal tool executed; skipping remaining tool calls in this batch."
                        )
                        break

                logger.info(f"Tool execution telemetry: executed_tools={turn_tools}")
                tools_were_used = True

                if terminal_action_executed:
                    successful = [t for t in accumulated_tool_results if t.get("success")]
                    if successful:
                        last_ok = successful[-1]
                        final_content = (
                            "İşlem tamamlandı.\n"
                            f"{last_ok['tool']}: {last_ok['result']}"
                        )
                    else:
                        final_content = "İşlem çalıştırıldı."
                    break

                if action_turn and turn_success_count == 0:
                    if no_tool_retry_count < self.action_tool_retries:
                        no_tool_retry_count += 1
                        logger.warning(
                            "Action turn tool calls all failed; retrying with corrective instruction "
                            f"({no_tool_retry_count}/{self.action_tool_retries})"
                        )
                        messages.append({
                            "role": "user",
                            "content": (
                                "Önceki tool çağrısı başarısız oldu. "
                                "Doğru parametrelerle ilgili tool'u tekrar çağır. "
                                "Başarısızsa net hata ver, başka alakasız tool çağırma."
                            ),
                        })
                        continue
                    final_content = "Tool çağrıları başarısız oldu, işlem yapılmadı."
                    break

                continue

            if action_turn and not tools_were_used:
                if no_tool_retry_count < self.action_tool_retries:
                    no_tool_retry_count += 1
                    logger.warning(
                        "Action turn returned no tool call; retrying with corrective instruction "
                        f"({no_tool_retry_count}/{self.action_tool_retries})"
                    )
                    messages.append({
                        "role": "user",
                        "content": (
                            "Bu istek bir aksiyon isteği. Uygun tool'u şimdi çağır. "
                            "Tool çalıştırmadan işlem tamamlandı deme."
                        ),
                    })
                    continue

                final_content = "Tool çağrısı doğrulanamadı, işlem yapılmadı."
                break

            final_content = response.content
            break

        if final_content is None:
            if accumulated_tool_results:
                summary = f"İşlemler tamamlandı ({len(accumulated_tool_results)} tool çalıştırıldı):\n"
                for tr in accumulated_tool_results[-5:]:
                    status = "✓" if tr["success"] else "✗"
                    summary += f"  {status} {tr['tool']}\n"
                final_content = summary
            else:
                final_content = "İşlem tamamlandı ancak yanıt üretilemedi."

        if not final_content or not final_content.strip():
            if action_turn and not tools_were_used:
                final_content = "Tool çağrısı doğrulanamadı, işlem yapılmadı."
            elif accumulated_tool_results:
                final_content = "✓ İşlem tamamlandı."
            else:
                final_content = "İşlem tamamlandı ancak yanıt üretilemedi."

        logger.info(
            "LLM final telemetry: "
            f"final_content_length={len(final_content)}, executed_tools={executed_tool_names}, "
            f"action_turn={action_turn}, live_call_turn={live_call_turn}"
        )

        if action_turn and not executed_tool_names:
            logger.error("Action turn alarm: executed_tools=0")

        return final_content, accumulated_tool_results, executed_tool_names

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

        # Set voice_call tool context for Telegram linking
        voice_tool = self.tools.get("voice_call")
        if voice_tool and hasattr(voice_tool, "set_context"):
            voice_tool.set_context(msg.channel, msg.chat_id)

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

        action_turn = self._is_action_turn(msg.channel, msg.content)
        live_call_turn = self._is_live_call_turn(msg.content)
        final_content, _, _ = await self._run_llm_tool_loop(
            messages=messages,
            action_turn=action_turn,
            live_call_turn=live_call_turn,
        )
        
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

        # Set voice_call tool context for Telegram linking
        voice_tool = self.tools.get("voice_call")
        if voice_tool and hasattr(voice_tool, "set_context"):
            voice_tool.set_context(origin_channel, origin_chat_id)

        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(max_messages=self.context_messages),
            current_message=msg.content
        )
        
        action_turn = self._is_action_turn(origin_channel, msg.content)
        live_call_turn = self._is_live_call_turn(msg.content)
        final_content, _, _ = await self._run_llm_tool_loop(
            messages=messages,
            action_turn=action_turn,
            live_call_turn=live_call_turn,
        )
        
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
