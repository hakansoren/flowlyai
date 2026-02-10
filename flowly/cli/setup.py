"""Interactive setup wizards for Flowly channels and providers."""

import asyncio
import httpx
from rich.console import Console
from rich.prompt import Prompt, Confirm

console = Console()


async def validate_telegram_token(token: str) -> dict | None:
    """Validate a Telegram bot token by calling getMe API."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    return data.get("result")
    except Exception:
        pass
    return None


def setup_telegram() -> bool:
    """
    Interactive Telegram setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]🤖 Telegram Bot Setup[/bold cyan]")
    console.print("─" * 40)

    config = load_config()
    current_token = config.channels.telegram.token

    # Check if already configured
    if current_token:
        bot_info = asyncio.run(validate_telegram_token(current_token))
        if bot_info:
            console.print(f"\n[green]✓[/green] Already configured: @{bot_info.get('username')}")
            if not Confirm.ask("Reconfigure?", default=False):
                return True

    # Show instructions
    console.print("\n[dim]To create a Telegram bot:[/dim]")
    console.print("  1. Open Telegram and search for [cyan]@BotFather[/cyan]")
    console.print("  2. Send [cyan]/newbot[/cyan] and follow the prompts")
    console.print("  3. Copy the token (looks like [dim]123456:ABC-xyz...[/dim])")
    console.print()

    # Get token
    token = Prompt.ask("Enter bot token").strip()

    if not token:
        console.print("[red]No token provided[/red]")
        return False

    # Validate token
    console.print("\n[dim]Validating token...[/dim]")
    bot_info = asyncio.run(validate_telegram_token(token))

    if not bot_info:
        console.print("[red]✗ Invalid token[/red]")
        return False

    bot_username = bot_info.get("username", "unknown")
    console.print(f"[green]✓[/green] Valid! Bot: [cyan]@{bot_username}[/cyan]")

    # Save to config
    config.channels.telegram.enabled = True
    config.channels.telegram.token = token
    save_config(config)
    console.print("[green]✓[/green] Saved to config")

    # Ask about DM policy
    console.print("\n[bold]DM Access Policy:[/bold]")
    console.print("  [cyan]1.[/cyan] pairing  - Users need approval code [dim](recommended)[/dim]")
    console.print("  [cyan]2.[/cyan] open     - Anyone can message")
    console.print("  [cyan]3.[/cyan] allowlist - Only pre-approved users")

    policy_choice = Prompt.ask("Choose policy", choices=["1", "2", "3"], default="1")
    policy_map = {"1": "pairing", "2": "open", "3": "allowlist"}
    dm_policy = policy_map[policy_choice]

    config.channels.telegram.dm_policy = dm_policy
    save_config(config)
    console.print(f"[green]✓[/green] DM policy set to [cyan]{dm_policy}[/cyan]")

    # For allowlist mode, ask for initial user
    if dm_policy == "allowlist":
        console.print("\n[dim]For allowlist mode, you need to add at least one user.[/dim]")
        console.print("[dim]Get your user ID from @userinfobot on Telegram.[/dim]")

        user_id = Prompt.ask("Enter your Telegram user ID (or skip)", default="").strip()
        if user_id:
            config.channels.telegram.allow_from = [user_id]
            save_config(config)
            console.print(f"[green]✓[/green] Added {user_id} to allowlist")

    # Success message
    console.print("\n[green]✓ Telegram setup complete![/green]")
    console.print(f"\nStart the bot with: [cyan]flowly gateway[/cyan]")
    console.print("[dim]Background mode:[/dim] [cyan]flowly service install --start[/cyan]")

    if dm_policy == "pairing":
        console.print(f"\nWhen users message the bot, they'll get a pairing code.")
        console.print(f"Approve with: [cyan]flowly pairing approve telegram <code>[/cyan]")

    return True


def setup_voice() -> bool:
    """
    Interactive voice transcription (Groq) setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]🎤 Voice Transcription Setup (Groq Whisper)[/bold cyan]")
    console.print("─" * 40)

    config = load_config()
    current_key = config.providers.groq.api_key

    if current_key:
        console.print(f"\n[green]✓[/green] Already configured: {current_key[:10]}...")
        if not Confirm.ask("Reconfigure?", default=False):
            return True

    console.print("\n[dim]To get a Groq API key:[/dim]")
    console.print("  1. Go to [cyan]https://console.groq.com/keys[/cyan]")
    console.print("  2. Create a new API key")
    console.print("  3. Copy the key (starts with [dim]gsk_...[/dim])")
    console.print()

    api_key = Prompt.ask("Enter Groq API key").strip()

    if not api_key:
        console.print("[yellow]Skipped - voice transcription disabled[/yellow]")
        return True

    # Save to config
    config.providers.groq.api_key = api_key
    save_config(config)

    console.print("[green]✓[/green] Groq API key saved")
    console.print("\n[dim]Voice messages in Telegram will now be transcribed automatically.[/dim]")

    return True


def setup_openrouter() -> bool:
    """
    Interactive OpenRouter (LLM) setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]🧠 LLM Provider Setup (OpenRouter)[/bold cyan]")
    console.print("─" * 40)

    config = load_config()
    current_key = config.providers.openrouter.api_key

    if current_key:
        console.print(f"\n[green]✓[/green] Already configured: {current_key[:15]}...")
        if not Confirm.ask("Reconfigure?", default=False):
            return True

    console.print("\n[dim]To get an OpenRouter API key:[/dim]")
    console.print("  1. Go to [cyan]https://openrouter.ai/keys[/cyan]")
    console.print("  2. Create a new API key")
    console.print("  3. Copy the key (starts with [dim]sk-or-...[/dim])")
    console.print()

    api_key = Prompt.ask("Enter OpenRouter API key").strip()

    if not api_key:
        console.print("[red]API key is required[/red]")
        return False

    # Save to config
    config.providers.openrouter.api_key = api_key
    config.providers.openrouter.api_base = "https://openrouter.ai/api/v1"
    save_config(config)

    console.print("[green]✓[/green] OpenRouter API key saved")

    # Ask about model
    console.print("\n[bold]Choose default model:[/bold]")
    console.print("  [cyan]1.[/cyan] claude-sonnet-4-5 [dim](fast, recommended)[/dim]")
    console.print("  [cyan]2.[/cyan] claude-opus-4-5 [dim](smartest)[/dim]")
    console.print("  [cyan]3.[/cyan] gpt-4o [dim](OpenAI)[/dim]")
    console.print("  [cyan]4.[/cyan] custom")

    model_choice = Prompt.ask("Choose model", choices=["1", "2", "3", "4"], default="1")
    model_map = {
        "1": "anthropic/claude-sonnet-4-5",
        "2": "anthropic/claude-opus-4-5",
        "3": "openai/gpt-4o",
    }

    if model_choice == "4":
        model = Prompt.ask("Enter model name").strip()
    else:
        model = model_map[model_choice]

    config.agents.defaults.model = model
    save_config(config)

    console.print(f"[green]✓[/green] Default model set to [cyan]{model}[/cyan]")

    return True


def setup_trello() -> bool:
    """
    Interactive Trello integration setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]📋 Trello Integration Setup[/bold cyan]")
    console.print("─" * 40)

    config = load_config()
    current_key = config.integrations.trello.api_key
    current_token = config.integrations.trello.token

    if current_key and current_token:
        console.print(f"\n[green]✓[/green] Already configured")
        console.print(f"  API Key: {current_key[:10]}...")
        console.print(f"  Token: {current_token[:10]}...")
        if not Confirm.ask("Reconfigure?", default=False):
            return True

    console.print("\n[dim]To get Trello credentials:[/dim]")
    console.print("  1. Go to [cyan]https://trello.com/app-key[/cyan]")
    console.print("  2. Copy the API key shown at the top")
    console.print("  3. Click the 'Token' link to generate a token")
    console.print("  4. Authorize the app and copy the token")
    console.print()

    # Get API key
    api_key = Prompt.ask("Enter Trello API key").strip()

    if not api_key:
        console.print("[yellow]Skipped - Trello integration disabled[/yellow]")
        return True

    # Get token
    token = Prompt.ask("Enter Trello token").strip()

    if not token:
        console.print("[yellow]Skipped - Trello integration disabled[/yellow]")
        return True

    # Save to config
    config.integrations.trello.api_key = api_key
    config.integrations.trello.token = token
    save_config(config)

    console.print("[green]✓[/green] Trello credentials saved")
    console.print("\n[dim]You can now use Trello commands with the agent:[/dim]")
    console.print("  • List my Trello boards")
    console.print("  • Create a card in [board name]")
    console.print("  • Show cards in [list name]")

    return True


def setup_voice_calls() -> bool:
    """
    Interactive voice calls (Twilio) setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]📞 Voice Calls Setup (Twilio)[/bold cyan]")
    console.print("─" * 40)

    config = load_config()
    voice_cfg = config.integrations.voice

    if voice_cfg.enabled and voice_cfg.twilio_account_sid:
        console.print(f"\n[green]✓[/green] Already configured")
        console.print(f"  Account SID: {voice_cfg.twilio_account_sid[:10]}...")
        console.print(f"  Phone: {voice_cfg.twilio_phone_number}")
        if not Confirm.ask("Reconfigure?", default=False):
            return True

    console.print("\n[dim]To get Twilio credentials:[/dim]")
    console.print("  1. Sign up at [cyan]https://www.twilio.com[/cyan]")
    console.print("  2. Go to Console → Account Info")
    console.print("  3. Copy Account SID and Auth Token")
    console.print("  4. Buy or verify a phone number")
    console.print()

    # Account SID
    account_sid = Prompt.ask("Enter Twilio Account SID").strip()
    if not account_sid:
        console.print("[yellow]Skipped - voice calls disabled[/yellow]")
        return True

    # Auth Token
    auth_token = Prompt.ask("Enter Twilio Auth Token", password=True).strip()
    if not auth_token:
        console.print("[yellow]Skipped - voice calls disabled[/yellow]")
        return True

    # Phone Number
    phone_number = Prompt.ask("Enter Twilio Phone Number (e.g., +1234567890)").strip()
    if not phone_number:
        console.print("[yellow]Skipped - voice calls disabled[/yellow]")
        return True

    # Webhook URL
    console.print("\n[dim]Voice calls require a static public webhook URL for Twilio.[/dim]")
    console.print("[dim]Production recommendation: fixed domain + TLS + reverse proxy.[/dim]")
    webhook_url = Prompt.ask("Enter webhook base URL (e.g., https://your-domain.com)").strip()

    # STT Provider
    console.print("\n[bold]Choose STT (Speech-to-Text) provider:[/bold]")
    console.print("  [cyan]1.[/cyan] Groq Whisper [dim](recommended, fast, free tier)[/dim]")
    console.print("  [cyan]2.[/cyan] Deepgram [dim](real-time streaming)[/dim]")
    console.print("  [cyan]3.[/cyan] OpenAI Whisper [dim](batch processing)[/dim]")
    console.print("  [cyan]4.[/cyan] ElevenLabs [dim](high quality, streaming)[/dim]")

    stt_choice = Prompt.ask("Choose STT", choices=["1", "2", "3", "4"], default="1")
    stt_map = {"1": "groq", "2": "deepgram", "3": "openai", "4": "elevenlabs"}
    stt_provider = stt_map[stt_choice]

    # API key based on provider
    deepgram_key = ""
    groq_key = ""
    elevenlabs_key = ""
    if stt_provider == "groq":
        console.print("\n[dim]Get Groq API key at: https://console.groq.com/keys[/dim]")
        groq_key = Prompt.ask("Enter Groq API key").strip()
    elif stt_provider == "deepgram":
        console.print("\n[dim]Get Deepgram API key at: https://console.deepgram.com[/dim]")
        deepgram_key = Prompt.ask("Enter Deepgram API key").strip()
    elif stt_provider == "elevenlabs":
        console.print("\n[dim]Get ElevenLabs API key at: https://elevenlabs.io/app/settings/api-keys[/dim]")
        elevenlabs_key = Prompt.ask("Enter ElevenLabs API key").strip()

    # TTS Provider
    console.print("\n[bold]Choose TTS (Text-to-Speech) provider:[/bold]")
    console.print("  [cyan]1.[/cyan] ElevenLabs [dim](best quality, 5000+ voices)[/dim]")
    console.print("  [cyan]2.[/cyan] OpenAI [dim](high quality)[/dim]")
    console.print("  [cyan]3.[/cyan] Deepgram [dim](fast, Aura voices)[/dim]")

    tts_choice = Prompt.ask("Choose TTS", choices=["1", "2", "3"], default="1")
    tts_map = {"1": "elevenlabs", "2": "openai", "3": "deepgram"}
    tts_provider = tts_map[tts_choice]

    # TTS Voice based on provider
    if tts_provider == "elevenlabs":
        # Get ElevenLabs API key if not already set for STT
        if not elevenlabs_key:
            console.print("\n[dim]Get ElevenLabs API key at: https://elevenlabs.io/app/settings/api-keys[/dim]")
            elevenlabs_key = Prompt.ask("Enter ElevenLabs API key").strip()

        console.print("\n[bold]Choose ElevenLabs voice:[/bold]")
        console.print("  [cyan]1.[/cyan] rachel [dim](female, American, calm)[/dim]")
        console.print("  [cyan]2.[/cyan] bella [dim](female, American, soft)[/dim]")
        console.print("  [cyan]3.[/cyan] elli [dim](female, American, young)[/dim]")
        console.print("  [cyan]4.[/cyan] josh [dim](male, American, deep)[/dim]")
        console.print("  [cyan]5.[/cyan] adam [dim](male, American, deep)[/dim]")
        console.print("  [cyan]6.[/cyan] sam [dim](male, American, raspy)[/dim]")

        voice_choice = Prompt.ask("Choose voice", choices=["1", "2", "3", "4", "5", "6"], default="1")
        voice_map = {
            "1": "21m00Tcm4TlvDq8ikWAM",  # rachel
            "2": "EXAVITQu4vr4xnSDxMaL",  # bella
            "3": "MF3mGyEYCl7XYWbV9V6O",  # elli
            "4": "TxGEqnHWrfWFTfGW9XjX",  # josh
            "5": "pNInz6obpgDQGcFmaJgB",  # adam
            "6": "yoZ06aMxZJJ28mfd3POQ",  # sam
        }
        tts_voice = voice_map[voice_choice]
    elif tts_provider == "openai":
        console.print("\n[bold]Choose OpenAI voice:[/bold]")
        console.print("  [cyan]1.[/cyan] nova [dim](neutral, natural)[/dim]")
        console.print("  [cyan]2.[/cyan] alloy [dim](neutral)[/dim]")
        console.print("  [cyan]3.[/cyan] shimmer [dim](soft, warm)[/dim]")
        console.print("  [cyan]4.[/cyan] echo [dim](deep)[/dim]")
        console.print("  [cyan]5.[/cyan] fable [dim](British)[/dim]")
        console.print("  [cyan]6.[/cyan] onyx [dim](authoritative)[/dim]")

        voice_choice = Prompt.ask("Choose voice", choices=["1", "2", "3", "4", "5", "6"], default="1")
        voice_map = {"1": "nova", "2": "alloy", "3": "shimmer", "4": "echo", "5": "fable", "6": "onyx"}
        tts_voice = voice_map[voice_choice]
    else:
        console.print("\n[bold]Choose Deepgram Aura voice:[/bold]")
        console.print("  [cyan]1.[/cyan] aura-asteria-en [dim](female, American)[/dim]")
        console.print("  [cyan]2.[/cyan] aura-luna-en [dim](female, American)[/dim]")
        console.print("  [cyan]3.[/cyan] aura-orion-en [dim](male, American)[/dim]")
        console.print("  [cyan]4.[/cyan] aura-arcas-en [dim](male, American)[/dim]")
        console.print("  [cyan]5.[/cyan] aura-athena-en [dim](female, British)[/dim]")
        console.print("  [cyan]6.[/cyan] aura-helios-en [dim](male, British)[/dim]")

        voice_choice = Prompt.ask("Choose voice", choices=["1", "2", "3", "4", "5", "6"], default="1")
        voice_map = {
            "1": "aura-asteria-en", "2": "aura-luna-en", "3": "aura-orion-en",
            "4": "aura-arcas-en", "5": "aura-athena-en", "6": "aura-helios-en"
        }
        tts_voice = voice_map[voice_choice]

    # Language
    language = Prompt.ask("Enter language code", default="en-US").strip()

    # Save to config
    config.integrations.voice.enabled = True
    config.integrations.voice.twilio_account_sid = account_sid
    config.integrations.voice.twilio_auth_token = auth_token
    config.integrations.voice.twilio_phone_number = phone_number
    config.integrations.voice.webhook_base_url = webhook_url
    config.integrations.voice.legacy_bridge_enabled = False
    config.integrations.voice.skip_signature_verification = False
    from urllib.parse import urlparse
    parsed_host = urlparse(webhook_url).hostname or ""
    config.integrations.voice.webhook_security.allowed_hosts = [parsed_host] if parsed_host else []
    config.integrations.voice.webhook_security.trust_forwarding_headers = False
    config.integrations.voice.webhook_security.trusted_proxy_ips = []
    config.integrations.voice.live_call.strict_tool_sandbox = True
    config.integrations.voice.stt_provider = stt_provider
    config.integrations.voice.tts_provider = tts_provider
    config.integrations.voice.groq_api_key = groq_key
    config.integrations.voice.deepgram_api_key = deepgram_key
    config.integrations.voice.elevenlabs_api_key = elevenlabs_key
    config.integrations.voice.tts_voice = tts_voice
    config.integrations.voice.language = language
    save_config(config)

    console.print("\n[green]✓[/green] Voice calls configuration saved")
    console.print("\n[dim]Next steps:[/dim]")
    console.print("  1. Start Flowly gateway: [cyan]flowly gateway[/cyan]")
    console.print("     or background mode: [cyan]flowly service install --start[/cyan]")
    console.print("  2. Set Twilio Voice webhook to: [cyan]{}/incoming[/cyan]".format(webhook_url.rstrip("/")))
    console.print("  3. Set Twilio Status callback to: [cyan]{}/status[/cyan]".format(webhook_url.rstrip("/")))
    console.print("\n[dim]The agent can now make calls with:[/dim]")
    console.print("  • Call +1234567890 and say hello")
    console.print("  • Make a voice call to [phone number]")

    return True


async def validate_discord_token(token: str) -> dict | None:
    """Validate a Discord bot token by calling /users/@me."""
    url = "https://discord.com/api/v10/users/@me"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Authorization": f"Bot {token}"}, timeout=10
            )
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return None


def setup_discord() -> bool:
    """
    Interactive Discord bot setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]Discord Bot Setup[/bold cyan]")
    console.print("-" * 40)

    config = load_config()
    current_token = config.channels.discord.token

    if current_token:
        bot_info = asyncio.run(validate_discord_token(current_token))
        if bot_info:
            console.print(f"\n[green]✓[/green] Already configured: {bot_info.get('username')}")
            if not Confirm.ask("Reconfigure?", default=False):
                return True

    console.print("\n[dim]To create a Discord bot:[/dim]")
    console.print("  1. Go to [cyan]https://discord.com/developers/applications[/cyan]")
    console.print("  2. Click [cyan]New Application[/cyan], give it a name")
    console.print("  3. Go to [cyan]Bot[/cyan] tab, click [cyan]Reset Token[/cyan] and copy it")
    console.print("  4. Enable [cyan]Message Content Intent[/cyan] under Privileged Gateway Intents")
    console.print("  5. Go to [cyan]OAuth2 > URL Generator[/cyan], select [cyan]bot[/cyan] scope")
    console.print("     and [cyan]Send Messages + Read Message History[/cyan] permissions")
    console.print("  6. Copy the generated URL and open it to invite the bot to your server")
    console.print()

    token = Prompt.ask("Enter bot token").strip()

    if not token:
        console.print("[red]No token provided[/red]")
        return False

    console.print("\n[dim]Validating token...[/dim]")
    bot_info = asyncio.run(validate_discord_token(token))

    if not bot_info:
        console.print("[red]✗ Invalid token[/red]")
        return False

    bot_username = bot_info.get("username", "unknown")
    console.print(f"[green]✓[/green] Valid! Bot: [cyan]{bot_username}[/cyan]")

    config.channels.discord.enabled = True
    config.channels.discord.token = token
    save_config(config)
    console.print("[green]✓[/green] Saved to config")

    console.print("\n[green]✓ Discord setup complete![/green]")
    console.print(f"\nStart the bot with: [cyan]flowly gateway[/cyan]")

    return True


async def validate_slack_tokens(bot_token: str) -> dict | None:
    """Validate Slack bot token via auth.test."""
    url = "https://slack.com/api/auth.test"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {bot_token}"},
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    return data
    except Exception:
        pass
    return None


def setup_slack() -> bool:
    """
    Interactive Slack bot setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]Slack Bot Setup[/bold cyan]")
    console.print("-" * 40)

    config = load_config()
    current_bot_token = config.channels.slack.bot_token

    if current_bot_token:
        auth_info = asyncio.run(validate_slack_tokens(current_bot_token))
        if auth_info:
            console.print(f"\n[green]✓[/green] Already configured: {auth_info.get('user', 'bot')}")
            if not Confirm.ask("Reconfigure?", default=False):
                return True

    console.print("\n[dim]To create a Slack app:[/dim]")
    console.print("  1. Go to [cyan]https://api.slack.com/apps[/cyan]")
    console.print("  2. Click [cyan]Create New App > From scratch[/cyan]")
    console.print("  3. Under [cyan]Socket Mode[/cyan], enable it and create an app token (xapp-)")
    console.print("  4. Under [cyan]OAuth & Permissions[/cyan], add bot scopes:")
    console.print("     [dim]chat:write, app_mentions:read, im:history, channels:history, reactions:write[/dim]")
    console.print("  5. Install to workspace and copy the [cyan]Bot User OAuth Token[/cyan] (xoxb-)")
    console.print("  6. Under [cyan]Event Subscriptions[/cyan], subscribe to:")
    console.print("     [dim]message.im, app_mention[/dim]")
    console.print()

    bot_token = Prompt.ask("Enter Bot User OAuth Token (xoxb-)").strip()
    if not bot_token:
        console.print("[yellow]Skipped - Slack disabled[/yellow]")
        return True

    console.print("\n[dim]Validating bot token...[/dim]")
    auth_info = asyncio.run(validate_slack_tokens(bot_token))
    if not auth_info:
        console.print("[red]✗ Invalid bot token[/red]")
        return False

    bot_name = auth_info.get("user", "unknown")
    console.print(f"[green]✓[/green] Valid! Bot: [cyan]{bot_name}[/cyan]")

    app_token = Prompt.ask("Enter App-Level Token (xapp-)").strip()
    if not app_token:
        console.print("[red]App token is required for Socket Mode[/red]")
        return False

    # Group policy
    console.print("\n[bold]Group/Channel Response Policy:[/bold]")
    console.print("  [cyan]1.[/cyan] mention   - Respond only when @mentioned [dim](recommended)[/dim]")
    console.print("  [cyan]2.[/cyan] open      - Respond to all messages in channels")
    console.print("  [cyan]3.[/cyan] allowlist - Only respond in specific channels")

    policy_choice = Prompt.ask("Choose policy", choices=["1", "2", "3"], default="1")
    policy_map = {"1": "mention", "2": "open", "3": "allowlist"}
    group_policy = policy_map[policy_choice]

    config.channels.slack.enabled = True
    config.channels.slack.bot_token = bot_token
    config.channels.slack.app_token = app_token
    config.channels.slack.group_policy = group_policy
    save_config(config)
    console.print("[green]✓[/green] Saved to config")

    console.print("\n[green]✓ Slack setup complete![/green]")
    console.print(f"\nStart the bot with: [cyan]flowly gateway[/cyan]")
    console.print("[dim]No public URL needed - Socket Mode connects outbound.[/dim]")

    return True


def _get_module_statuses() -> list[tuple[str, str, str]]:
    """Get configuration status for each setup module.

    Returns list of (label, status_icon, detail) tuples.
    """
    from flowly.config.loader import load_config

    config = load_config()
    statuses = []

    # 1. LLM Provider
    api_key = config.providers.openrouter.api_key
    if api_key:
        model = config.agents.defaults.model or "default"
        statuses.append(("LLM Provider", "[green]✓[/green]", f"[dim]{model}[/dim]"))
    else:
        statuses.append(("LLM Provider", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 2. Telegram Bot
    token = config.channels.telegram.token
    if token:
        # Quick check without async validation
        masked = token[:8] + "..."
        statuses.append(("Telegram Bot", "[green]✓[/green]", f"[dim]{masked}[/dim]"))
    else:
        statuses.append(("Telegram Bot", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 3. Voice Transcription
    groq_key = config.providers.groq.api_key
    if groq_key:
        statuses.append(("Voice Transcription", "[green]✓[/green]", "[dim]groq[/dim]"))
    else:
        statuses.append(("Voice Transcription", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 4. Voice Calls
    voice_cfg = config.integrations.voice
    if voice_cfg.enabled and voice_cfg.twilio_account_sid:
        phone = voice_cfg.twilio_phone_number or "?"
        statuses.append(("Voice Calls", "[green]✓[/green]", f"[dim]{phone}[/dim]"))
    else:
        statuses.append(("Voice Calls", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 5. Trello
    trello = config.integrations.trello
    if trello.api_key and trello.token:
        statuses.append(("Trello", "[green]✓[/green]", "[dim]connected[/dim]"))
    else:
        statuses.append(("Trello", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 6. Discord Bot
    discord_token = config.channels.discord.token
    if discord_token:
        masked = discord_token[:8] + "..."
        statuses.append(("Discord Bot", "[green]✓[/green]", f"[dim]{masked}[/dim]"))
    else:
        statuses.append(("Discord Bot", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 7. Slack Bot
    slack_token = config.channels.slack.bot_token
    if slack_token and config.channels.slack.app_token:
        statuses.append(("Slack Bot", "[green]✓[/green]", f"[dim]{config.channels.slack.group_policy}[/dim]"))
    else:
        statuses.append(("Slack Bot", "[red]✗[/red]", "[dim]not configured[/dim]"))

    return statuses


def setup_all() -> None:
    """Run the interactive setup wizard with arrow-key module selection."""
    from flowly import __banner__, __version__
    from simple_term_menu import TerminalMenu

    console.print(f"[cyan]{__banner__.format(version=__version__)}[/cyan]")
    console.print("[bold]Setup Wizard[/bold]")
    console.print("[dim]Use arrow keys to navigate, Enter to select[/dim]\n")

    # Module registry: (label, setup_function)
    modules = [
        ("LLM Provider", setup_openrouter),
        ("Telegram Bot", setup_telegram),
        ("Voice Transcription", setup_voice),
        ("Voice Calls", setup_voice_calls),
        ("Trello", setup_trello),
        ("Discord Bot", setup_discord),
        ("Slack Bot", setup_slack),
    ]

    # Build menu entries with status indicators
    statuses = _get_module_statuses()
    menu_entries = []
    for label, icon_rich, detail_rich in statuses:
        # Strip rich markup for terminal menu
        is_configured = "✓" in icon_rich
        icon = "✓" if is_configured else "✗"
        # Extract detail text from rich markup
        detail = detail_rich.replace("[dim]", "").replace("[/dim]", "")
        menu_entries.append(f"{label:<22} {icon} {detail}")

    menu_entries.append("Run all (full setup)")
    menu_entries.append("Quit")

    menu = TerminalMenu(
        menu_entries,
        title="Select a module to configure:",
    )

    selected = menu.show()

    if selected is None:
        console.print("[dim]Setup cancelled.[/dim]")
        return

    quit_idx = len(modules) + 1
    all_idx = len(modules)

    if selected == quit_idx:
        console.print("[dim]Setup cancelled.[/dim]")
        return

    if selected == all_idx:
        for label, setup_fn in modules:
            console.print(f"\n{'─' * 40}")
            console.print(f"[bold]Setting up: {label}[/bold]")
            setup_fn()
    else:
        label, setup_fn = modules[selected]
        console.print(f"\n{'─' * 40}")
        console.print(f"[bold]Setting up: {label}[/bold]")
        setup_fn()

    # Done
    console.print(f"\n{'─' * 40}")
    console.print("[bold green]✓ Setup complete![/bold green]\n")
    console.print("Start Flowly with: [cyan]flowly gateway[/cyan]")
    console.print("Background mode: [cyan]flowly service install --start[/cyan]")
    console.print()
