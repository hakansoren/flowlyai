"""Configuration schema using Pydantic."""

from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator
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


class DiscordConfig(BaseModel):
    """Discord channel configuration."""
    enabled: bool = False
    token: str = ""  # Bot token from Discord Developer Portal
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377  # GUILDS + GUILD_MESSAGES + DIRECT_MESSAGES + MESSAGE_CONTENT


class SlackDMConfig(BaseModel):
    """Slack DM policy configuration."""
    enabled: bool = True
    policy: str = "open"  # "open" or "allowlist"
    allow_from: list[str] = Field(default_factory=list)  # Allowed Slack user IDs


class SlackConfig(BaseModel):
    """Slack channel configuration."""
    enabled: bool = False
    mode: str = "socket"  # "socket" supported
    bot_token: str = ""  # xoxb-...
    app_token: str = ""  # xapp-...
    group_policy: str = "mention"  # "mention", "open", "allowlist"
    group_allow_from: list[str] = Field(default_factory=list)  # Allowed channel IDs if allowlist
    dm: SlackDMConfig = Field(default_factory=SlackDMConfig)


class ChannelsConfig(BaseModel):
    """Configuration for chat channels."""
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)


class AgentDefaults(BaseModel):
    """Default agent configuration."""
    workspace: str = "~/.flowly/workspace"
    model: str = "moonshotai/kimi-k2.5"
    max_tokens: int = 8192
    temperature: float = 0.7
    action_temperature: float = 0.1
    action_tool_retries: int = 2
    max_tool_iterations: int = 20
    context_messages: int = 100  # Max messages to include in context
    persona: str = "default"  # Bot persona (default, jarvis, pirate, etc.)
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
    xai: ProviderConfig = Field(default_factory=ProviderConfig)  # xAI Grok models


class GatewayConfig(BaseModel):
    """Gateway/server configuration."""
    host: str = "127.0.0.1"
    port: int = 18790

    @field_validator("port")
    @classmethod
    def _validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"port must be between 1 and 65535, got {v}")
        return v


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
    security: Literal["deny", "allowlist", "full"] = "deny"  # Security mode
    ask: Literal["off", "on-miss", "always"] = "on-miss"  # Approval mode
    timeout_seconds: int = 300  # 5 minutes default
    max_output_chars: int = 200000  # 200KB
    approval_timeout_seconds: int = 120  # 2 minutes to approve

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout(cls, v: int) -> int:
        if not 1 <= v <= 3600:
            raise ValueError(f"timeout_seconds must be between 1 and 3600, got {v}")
        return v


class TrelloConfig(BaseModel):
    """Trello integration configuration."""
    api_key: str = ""  # Get at https://trello.com/app-key
    token: str = ""  # Generate from the same page


class XConfig(BaseModel):
    """X (Twitter) API configuration."""
    bearer_token: str = ""  # App-only Bearer Token (read operations)
    api_key: str = ""  # OAuth 1.0a Consumer Key (write operations)
    api_secret: str = ""  # OAuth 1.0a Consumer Secret
    access_token: str = ""  # OAuth 1.0a Access Token
    access_token_secret: str = ""  # OAuth 1.0a Access Token Secret


class VoiceWebhookSecurityConfig(BaseModel):
    """Voice webhook security configuration."""
    allowed_hosts: list[str] = Field(default_factory=list)
    trust_forwarding_headers: bool = False
    trusted_proxy_ips: list[str] = Field(default_factory=list)


class VoiceLiveCallConfig(BaseModel):
    """Live-call tool sandbox policy."""
    strict_tool_sandbox: bool = True
    allow_tools: list[str] = Field(
        default_factory=lambda: ["voice_call", "message", "screenshot", "system"]
    )


class VoiceBridgeConfig(BaseModel):
    """Integrated voice plugin configuration for Twilio calls."""
    enabled: bool = False
    # Legacy bridge fallback API URL (optional, disabled by default)
    bridge_url: str = "http://localhost:8765"
    legacy_bridge_enabled: bool = False

    # Twilio settings
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Webhook URL (static public URL for Twilio callbacks)
    webhook_base_url: str = ""
    skip_signature_verification: bool = False
    webhook_security: VoiceWebhookSecurityConfig = Field(default_factory=VoiceWebhookSecurityConfig)
    live_call: VoiceLiveCallConfig = Field(default_factory=VoiceLiveCallConfig)

    # Link voice calls to Telegram session (for screenshots, messages etc.)
    telegram_chat_id: str = ""  # Your Telegram chat ID - voice calls will use this session
    default_to_number: str = ""  # Optional default target phone for "beni ara" requests

    # STT/TTS settings
    stt_provider: str = "groq"  # groq, deepgram, openai, or elevenlabs
    tts_provider: str = "elevenlabs"  # openai, deepgram, or elevenlabs
    groq_api_key: str = ""  # For Groq Whisper STT
    deepgram_api_key: str = ""  # For Deepgram STT/TTS
    elevenlabs_api_key: str = ""  # For ElevenLabs STT/TTS
    tts_voice: str = "21m00Tcm4TlvDq8ikWAM"  # TTS voice (provider-specific, default: rachel)
    language: str = "en-US"

    # Ngrok auto-tunnel (alternative to manual webhook_base_url)
    ngrok_authtoken: str = ""  # ngrok authtoken from https://dashboard.ngrok.com


class IntegrationsConfig(BaseModel):
    """External integrations configuration."""
    trello: TrelloConfig = Field(default_factory=TrelloConfig)
    voice: VoiceBridgeConfig = Field(default_factory=VoiceBridgeConfig)
    x: XConfig = Field(default_factory=XConfig)


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
        """Get API key in priority order: OpenRouter > Anthropic > OpenAI > xAI > Gemini > Zhipu > vLLM."""
        return (
            self.providers.openrouter.api_key or
            self.providers.anthropic.api_key or
            self.providers.openai.api_key or
            self.providers.xai.api_key or
            self.providers.gemini.api_key or
            self.providers.zhipu.api_key or
            self.providers.vllm.api_key or
            None
        )
    
    def get_api_base(self) -> str | None:
        """Get API base URL if using OpenRouter, xAI, Zhipu or vLLM."""
        if self.providers.openrouter.api_key:
            return self.providers.openrouter.api_base or "https://openrouter.ai/api/v1"
        if self.providers.xai.api_key:
            return self.providers.xai.api_base or "https://api.x.ai/v1"
        if self.providers.zhipu.api_key:
            return self.providers.zhipu.api_base
        if self.providers.vllm.api_base:
            return self.providers.vllm.api_base
        return None
    
    class Config:
        env_prefix = "FLOWLY_"
        env_nested_delimiter = "__"
