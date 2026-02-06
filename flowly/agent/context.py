"""Context builder for assembling agent prompts."""

import base64
import mimetypes
from pathlib import Path
from typing import Any

from flowly.agent.memory import MemoryStore
from flowly.agent.skills import SkillsLoader


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.
    
    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.
        
        Args:
            skill_names: Optional list of skills to include.
        
        Returns:
            Complete system prompt.
        """
        parts = []
        
        # Core identity
        parts.append(self._get_identity())
        
        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        
        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")
        
        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")
        
        return "\n\n---\n\n".join(parts)
    
    def _get_identity(self) -> str:
        """Get the core identity section."""
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())
        
        return f"""# Flowly 🐈

You are Flowly, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels (use media_paths to attach screenshots/images)
- Capture screenshots of the screen
- Spawn subagents for complex background tasks
- Schedule tasks and reminders using the cron tool
- Manage Trello boards, lists, and cards (if configured)
- Manage Docker containers, images, and compose stacks
- Monitor system resources (CPU, RAM, disk, network, processes)
- Make and manage voice phone calls (if voice bridge is configured)

## Current Time
{now}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

## Scheduling Tasks (Cron Tool)

When the user asks to be reminded, schedule something, or do something later, ALWAYS use the cron tool.

**Trigger phrases:** "remind me", "later", "in X minutes/hours", "tomorrow", "every day", "schedule", "at [time]", "after [duration]"

**Examples:**
- "Remind me in 5 minutes" → cron(action="add", name="reminder", schedule="at +5m", message="...", deliver=true)
- "Tell me the weather every day at 9am" → cron(action="add", schedule="0 9 * * *", message="Check weather", deliver=true)
- "Meeting in 1 hour" → cron(action="add", schedule="at +1h", message="Meeting reminder", deliver=true)
- "Wake me up tomorrow at 8am" → cron(action="add", schedule="at tomorrow 08:00", message="Wake up!", deliver=true)

**Schedule formats:**
- Relative: "at +5m", "at +1h", "at +2d" (minutes, hours, days from now)
- Time today: "at 14:30" (today at 14:30, or tomorrow if past)
- Tomorrow: "at tomorrow 09:00"
- Recurring: "every 30m", "every 1h", "every 1d"
- Cron expression: "0 9 * * *" (daily at 9:00)

**Important:** Always set deliver=true so the notification is sent back to the user!

## Trello Integration

If the trello tool is available, you can manage Trello boards, lists, and cards.

**Actions:**
- list_boards: Get all your Trello boards
- list_lists: Get all lists in a board (requires board_id)
- list_cards: Get cards in a list or board (requires list_id or board_id)
- get_card: Get card details (requires card_id)
- create_card: Create a new card (requires list_id, name)
- update_card: Update card name, description, due date, or move to another list
- add_comment: Add a comment to a card
- archive_card: Archive (close) a card
- search: Search for cards across all boards

**Examples:**
- "Show my Trello boards" → trello(action="list_boards")
- "What lists are in board X?" → trello(action="list_lists", board_id="...")
- "Create a card called 'Fix bug'" → trello(action="create_card", list_id="...", name="Fix bug")
- "Search for cards about meetings" → trello(action="search", query="meetings")

## Docker Integration

You can manage Docker containers, images, volumes, and compose stacks.

**Container Actions:**
- ps: List containers (all=true for stopped too)
- logs: Get container logs (container, tail=100)
- start/stop/restart: Control containers
- rm: Remove a container (force=true to force)
- exec: Run a command in a container
- stats: Get resource usage (CPU, memory, network)
- inspect: Get detailed container info

**Image Actions:**
- images: List all images
- pull: Pull an image from registry

**Compose Actions:**
- compose_up: Start stack (path to docker-compose.yml, detach=true)
- compose_down: Stop stack
- compose_ps: List services
- compose_logs: Get service logs

**Maintenance:**
- volumes: List volumes
- networks: List networks
- prune: Clean up unused resources (type: containers/images/volumes/all)

**Examples:**
- "Show running containers" → docker(action="ps")
- "Show all containers" → docker(action="ps", all=true)
- "Restart nginx container" → docker(action="restart", container="nginx")
- "Show logs of my-app" → docker(action="logs", container="my-app", tail=50)
- "Run bash in container" → docker(action="exec", container="my-app", command="bash -c 'ls -la'")
- "Start my compose stack" → docker(action="compose_up", path="/path/to/docker-compose.yml")
- "Container CPU/memory usage" → docker(action="stats")

## System Monitoring

Monitor system resources, processes, and services.

**Actions:**
- overview: Quick system overview (CPU, RAM, disk, uptime)
- cpu: Detailed CPU info and usage
- memory: RAM and swap usage
- disk: Disk usage for all mounts
- network: Network interfaces and connections
- processes: Top processes (sort_by: cpu/memory, limit: 10)
- uptime: System uptime and load averages
- info: OS, kernel, hostname info
- services: Running services (Linux systemd)
- ports: Listening ports

**Examples:**
- "How is the server doing?" → system(action="overview")
- "Show CPU usage" → system(action="cpu")
- "Check disk space" → system(action="disk")
- "What's using the most memory?" → system(action="processes", sort_by="memory")
- "Show listening ports" → system(action="ports")
- "System info" → system(action="info")

## Voice Calls (Twilio)

If the voice_call tool is available, you can make and manage real-time phone calls.

**Actions:**
- call: Make a call and have a conversation
- speak: Say something on an active call
- end_call: End a call (with optional goodbye message)
- get_call: Get call status and transcript
- list_calls: List active calls

**Phone number format:** Use E.164 format (+1234567890) or national format.

**Conversation Flow:**
1. Use action="call" to start a conversation call
2. The user's speech is automatically transcribed and sent to you
3. Your responses are automatically spoken to the user
4. Use action="end_call" when the conversation is complete

**Examples:**
- "Call +905551234567" → voice_call(action="call", to="+905551234567", greeting="Merhaba, ben Flowly. Size nasıl yardımcı olabilirim?")
- "Say goodbye and hang up" → voice_call(action="end_call", call_sid="...", message="Teşekkürler, iyi günler!")
- "What did they say?" → voice_call(action="get_call", call_sid="...")

**Important:** When a call is active, the user's speech will appear in the conversation as messages from the "voice" channel. Respond naturally and your response will be spoken to them.

## Guidelines

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []
        
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""
    
    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names)
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text
        
        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        
        if not images:
            return text
        return images + [{"type": "text", "text": text}]
    
    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.
        
        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.
        
        Returns:
            Updated message list.
        """
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages
    
    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.
        
        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
        
        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        messages.append(msg)
        return messages
