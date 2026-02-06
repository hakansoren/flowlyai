"""Configuration schema using Pydantic."""

from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class MemoryFlushConfig(BaseModel):
    """Pre-compaction memory flush configuration."""
    enabled: bool = True
    soft_threshold_tokens: int = 4000
    prompt: str = (
        "Pre-compaction memory flush. "
        "Store durable memories now (use memory/YYYY-MM-DD.md). "
        "If nothing to store, reply with NO_REPLY."
    )
    system_prompt: str = (
        "Pre-compaction memory flush turn. "
        "The session is near auto-compaction; capture durable memories to disk."
    )


class CompactionConfig(BaseModel):
    """Context compaction configuration."""
    mode: Literal["default", "safeguard"] = "safeguard"
    reserve_tokens_floor: int = 20000
    max_history_share: float = 0.5  # 0.1-0.9
    context_window: int = 128000
    memory_flush: MemoryFlushConfig = Field(default_factory=MemoryFlushConfig)


class WhatsAppConfig(BaseModel):
    """WhatsApp channel configuration."""
    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers


class TelegramConfig(BaseModel):
    """Telegram channel configuration."""
    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames
    dm_policy: Literal["open", "pairing", "allowlist"] = "pairing"  # DM access policy


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class AgentDefaults(BaseModel):
    """Default agent configuration."""
    workspace: str = "~/.flowly/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.7
    max_tool_iterations: int = 20
    context_messages: int = 100  # Max messages to include in context
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)


class AgentsConfig(BaseModel):
    """Agent configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(BaseModel):
    """LLM provider configuration."""
    api_key: str = ""
    api_base: str | None = None


class ProvidersConfig(BaseModel):
    """Configuration for LLM providers."""
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)  # For voice transcription


class GatewayConfig(BaseModel):
    """Gateway/server configuration."""
    host: str = "0.0.0.0"
    port: int = 18790


class WebSearchConfig(BaseModel):
    """Web search tool configuration."""
    api_key: str = ""  # Brave Search API key
    max_results: int = 5


class WebToolsConfig(BaseModel):
    """Web tools configuration."""
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(BaseModel):
    """Command execution tool configuration."""
    enabled: bool = False  # Disabled by default for security
    timeout_seconds: int = 300  # 5 minutes default
    max_output_chars: int = 200000  # 200KB
    approval_timeout_seconds: int = 120  # 2 minutes to approve


class TrelloConfig(BaseModel):
    """Trello integration configuration."""
    api_key: str = ""  # Get at https://trello.com/app-key
    token: str = ""  # Generate from the same page


class VoiceBridgeConfig(BaseModel):
    """Voice bridge configuration for Twilio calls."""
    enabled: bool = False
    bridge_url: str = "http://localhost:8765"  # Voice bridge API URL

    # Twilio settings (used by voice-bridge, stored here for setup wizard)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Webhook URL (public URL for Twilio callbacks)
    webhook_base_url: str = ""

    # STT/TTS settings
    stt_provider: str = "deepgram"  # deepgram or openai
    deepgram_api_key: str = ""
    tts_voice: str = "nova"  # OpenAI TTS voice
    language: str = "en-US"


class IntegrationsConfig(BaseModel):
    """External integrations configuration."""
    trello: TrelloConfig = Field(default_factory=TrelloConfig)
    voice: VoiceBridgeConfig = Field(default_factory=VoiceBridgeConfig)


class ToolsConfig(BaseModel):
    """Tools configuration."""
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)


class Config(BaseSettings):
    """Root configuration for flowly."""
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    
    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()
    
    def get_api_key(self) -> str | None:
        """Get API key in priority order: OpenRouter > Anthropic > OpenAI > Gemini > Zhipu > vLLM."""
        return (
            self.providers.openrouter.api_key or
            self.providers.anthropic.api_key or
            self.providers.openai.api_key or
            self.providers.gemini.api_key or
            self.providers.zhipu.api_key or
            self.providers.vllm.api_key or
            None
        )
    
    def get_api_base(self) -> str | None:
        """Get API base URL if using OpenRouter, Zhipu or vLLM."""
        if self.providers.openrouter.api_key:
            return self.providers.openrouter.api_base or "https://openrouter.ai/api/v1"
        if self.providers.zhipu.api_key:
            return self.providers.zhipu.api_base
        if self.providers.vllm.api_base:
            return self.providers.vllm.api_base
        return None
    
    class Config:
        env_prefix = "NANOBOT_"
        env_nested_delimiter = "__"
