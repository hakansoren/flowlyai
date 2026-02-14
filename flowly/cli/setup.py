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


def setup_x() -> bool:
    """
    Interactive X (Twitter) API setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]X (Twitter) Integration Setup[/bold cyan]")
    console.print("─" * 40)

    config = load_config()
    x_cfg = config.integrations.x

    if x_cfg.bearer_token or x_cfg.api_key:
        console.print(f"\n[green]✓[/green] Already configured")
        if x_cfg.bearer_token:
            console.print(f"  Bearer Token: {x_cfg.bearer_token[:10]}...")
        if x_cfg.api_key:
            console.print(f"  API Key: {x_cfg.api_key[:10]}...")
        if not Confirm.ask("Reconfigure?", default=False):
            return True

    console.print("\n[dim]To get X API credentials:[/dim]")
    console.print("  1. Go to [cyan]https://developer.x.com/en/portal/dashboard[/cyan]")
    console.print("  2. Create a Project and App")
    console.print("  3. In App Settings > [cyan]Keys and Tokens[/cyan]:")
    console.print("     - Generate [cyan]Bearer Token[/cyan] (for reading)")
    console.print("     - Generate [cyan]API Key & Secret[/cyan] (for posting)")
    console.print("     - Generate [cyan]Access Token & Secret[/cyan] (for posting)")
    console.print("  4. Set App permissions to [cyan]Read and Write[/cyan]")
    console.print()

    # Bearer Token (read operations)
    bearer_token = Prompt.ask("Enter Bearer Token (for search/timeline)").strip()
    if not bearer_token:
        console.print("[yellow]Skipped - X integration disabled[/yellow]")
        return True

    config.integrations.x.bearer_token = bearer_token
    save_config(config)
    console.print("[green]✓[/green] Bearer Token saved")

    # OAuth 1.0a (write operations)
    if Confirm.ask("\nSet up posting (OAuth 1.0a)?", default=True):
        api_key = Prompt.ask("  Enter API Key (Consumer Key)").strip()
        api_secret = Prompt.ask("  Enter API Secret (Consumer Secret)").strip()
        access_token = Prompt.ask("  Enter Access Token").strip()
        access_token_secret = Prompt.ask("  Enter Access Token Secret").strip()

        if api_key and api_secret and access_token and access_token_secret:
            config.integrations.x.api_key = api_key
            config.integrations.x.api_secret = api_secret
            config.integrations.x.access_token = access_token
            config.integrations.x.access_token_secret = access_token_secret
            save_config(config)
            console.print("[green]✓[/green] OAuth 1.0a credentials saved (posting enabled)")
        else:
            console.print("[yellow]Incomplete credentials - posting disabled, read-only mode[/yellow]")

    console.print("\n[green]✓ X setup complete![/green]")
    console.print("\n[dim]You can now use X commands with the agent:[/dim]")
    console.print("  • Search X for 'python'")
    console.print("  • Show @elonmusk's recent tweets")
    console.print("  • Post a tweet: Hello world!")

    return True


def setup_exec() -> bool:
    """
    Interactive command execution setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config

    console.print("\n[bold cyan]Command Execution Setup[/bold cyan]")
    console.print("─" * 40)

    config = load_config()
    exec_cfg = config.tools.exec

    if exec_cfg.enabled:
        console.print(f"\n[green]✓[/green] Already enabled")
        console.print(f"  Security: {exec_cfg.security}")
        console.print(f"  Ask mode: {exec_cfg.ask}")
        if not Confirm.ask("Reconfigure?", default=False):
            return True

    console.print("\n[dim]This allows the agent to run shell commands on your machine.[/dim]")
    console.print("[dim]Use with caution — choose an appropriate security level.[/dim]")

    # Enable
    if not Confirm.ask("\nEnable command execution?", default=True):
        config.tools.exec.enabled = False
        save_config(config)
        console.print("[yellow]Command execution disabled[/yellow]")
        return True

    # Security level
    console.print("\n[bold]Security level:[/bold]")
    console.print("  [cyan]1.[/cyan] allowlist - Only approved commands run, new ones are asked [dim](recommended)[/dim]")
    console.print("  [cyan]2.[/cyan] full      - All commands run without restriction [dim](dangerous)[/dim]")

    sec_choice = Prompt.ask("Choose security level", choices=["1", "2"], default="1")
    security = "allowlist" if sec_choice == "1" else "full"

    # Ask mode (only for allowlist)
    ask = "on-miss"
    if security == "allowlist":
        console.print("\n[bold]Approval mode:[/bold]")
        console.print("  [cyan]1.[/cyan] on-miss - Ask via chat when command is not in allowlist [dim](recommended)[/dim]")
        console.print("  [cyan]2.[/cyan] always  - Ask for every command")
        console.print("  [cyan]3.[/cyan] off     - Deny unknown commands silently")

        ask_choice = Prompt.ask("Choose approval mode", choices=["1", "2", "3"], default="1")
        ask_map = {"1": "on-miss", "2": "always", "3": "off"}
        ask = ask_map[ask_choice]

    config.tools.exec.enabled = True
    config.tools.exec.security = security
    config.tools.exec.ask = ask
    save_config(config)

    console.print(f"\n[green]✓[/green] Command execution enabled")
    console.print(f"  Security: [cyan]{security}[/cyan]")
    console.print(f"  Ask mode: [cyan]{ask}[/cyan]")

    if security == "allowlist" and ask == "on-miss":
        console.print("\n[dim]The agent will ask you via chat before running new commands.[/dim]")
        console.print("[dim]Approved commands are remembered for next time.[/dim]")

    return True


def setup_agents() -> bool:
    """
    Interactive multi-agent setup wizard.

    Returns True if setup was successful.
    """
    from flowly.config.loader import load_config, save_config
    from flowly.config.schema import MultiAgentConfig, MultiAgentTeamConfig

    try:
        from InquirerPy import inquirer
    except Exception:
        inquirer = None

    console.print("\n[bold cyan]Multi-Agent Setup[/bold cyan]")
    console.print("─" * 40)

    config = load_config()
    existing_agents = config.agents.agents
    existing_teams = config.agents.teams

    if existing_agents:
        console.print(f"\n[green]✓[/green] {len(existing_agents)} agent(s) configured:")
        for aid, acfg in existing_agents.items():
            console.print(f"  • [cyan]@{aid}[/cyan] — {acfg.name or aid} ({acfg.provider}/{acfg.model})")
        if existing_teams:
            console.print(f"\n  {len(existing_teams)} team(s):")
            for tid, tcfg in existing_teams.items():
                console.print(f"  • [cyan]@{tid}[/cyan] — {tcfg.name or tid} (agents: {', '.join(tcfg.agents)})")

    # Main menu loop
    while True:
        console.print()
        actions = [
            ("Add an agent", "add_agent"),
            ("Create a team", "create_team"),
        ]
        if existing_agents:
            actions.append(("Remove an agent", "remove_agent"))
        if existing_teams:
            actions.append(("Remove a team", "remove_team"))
        actions.append(("Done", "done"))

        if inquirer is not None:
            inq_choices = [{"name": label, "value": value} for label, value in actions]
            try:
                action = inquirer.select(
                    message="What would you like to do?",
                    choices=inq_choices,
                    default="add_agent",
                ).execute()
            except (KeyboardInterrupt, EOFError):
                break
        else:
            for idx, (label, _) in enumerate(actions, start=1):
                console.print(f"  [cyan]{idx}.[/cyan] {label}")
            choice = Prompt.ask(
                "Choose action",
                choices=[str(i) for i in range(1, len(actions) + 1)],
                default="1",
            )
            action = actions[int(choice) - 1][1]

        if action == "done":
            break

        elif action == "add_agent":
            _wizard_add_agent(config, inquirer)
            save_config(config)
            existing_agents = config.agents.agents
            existing_teams = config.agents.teams

        elif action == "create_team":
            if len(config.agents.agents) < 2:
                console.print("[yellow]You need at least 2 agents to create a team.[/yellow]")
                continue
            _wizard_create_team(config, inquirer)
            save_config(config)
            existing_agents = config.agents.agents
            existing_teams = config.agents.teams

        elif action == "remove_agent":
            _wizard_remove_agent(config, inquirer)
            save_config(config)
            existing_agents = config.agents.agents
            existing_teams = config.agents.teams

        elif action == "remove_team":
            _wizard_remove_team(config, inquirer)
            save_config(config)
            existing_agents = config.agents.agents
            existing_teams = config.agents.teams

    # Summary
    agent_count = len(config.agents.agents)
    team_count = len(config.agents.teams)
    if agent_count:
        console.print(f"\n[green]✓ Multi-agent setup complete![/green]")
        console.print(f"  {agent_count} agent(s), {team_count} team(s)")
        console.print(f"\n[dim]Usage:[/dim]")
        console.print(f"  • Direct agent: [cyan]@coder fix the login bug[/cyan]")
        if team_count:
            console.print(f"  • Team:         [cyan]@dev fix the login bug[/cyan]")
        console.print(f"  • Default:      Messages without @mention go to Flowly agent")
    else:
        console.print("\n[dim]No agents configured. Single-agent mode (default).[/dim]")

    return True


def _wizard_add_agent(config, inquirer) -> None:
    """Sub-wizard: add a new agent."""
    from flowly.config.schema import MultiAgentConfig

    console.print("\n[bold]Add Agent[/bold]")

    # Agent ID
    while True:
        agent_id = Prompt.ask("  Agent ID (e.g., coder, reviewer)").strip().lower()
        if not agent_id:
            console.print("  [red]Agent ID is required[/red]")
            continue
        if not agent_id.isidentifier() and not agent_id.replace("-", "_").isidentifier():
            console.print("  [red]Agent ID must be alphanumeric (a-z, 0-9, -, _)[/red]")
            continue
        if agent_id in config.agents.agents:
            console.print(f"  [yellow]Agent '{agent_id}' already exists[/yellow]")
            if not Confirm.ask("  Overwrite?", default=False):
                return
        break

    # Display name
    name = Prompt.ask("  Display name", default=agent_id.replace("-", " ").replace("_", " ").title()).strip()

    # Provider
    console.print("\n  [bold]Provider:[/bold]")
    console.print("    [cyan]1.[/cyan] Anthropic (Claude Code) [dim](recommended)[/dim]")
    console.print("    [cyan]2.[/cyan] OpenAI (Codex)")
    console.print("    [cyan]3.[/cyan] Google (Gemini CLI)")
    console.print("    [cyan]4.[/cyan] OpenCode")
    console.print("    [cyan]5.[/cyan] Factory (Droid)")

    provider_choice = Prompt.ask("  Choose provider", choices=["1", "2", "3", "4", "5"], default="1")
    provider_map = {"1": "anthropic", "2": "openai", "3": "gemini", "4": "opencode", "5": "droid"}
    provider = provider_map[provider_choice]

    # Model
    if provider == "anthropic":
        console.print("\n  [bold]Claude model:[/bold]")
        console.print("    [cyan]1.[/cyan] sonnet [dim](fast, recommended)[/dim]")
        console.print("    [cyan]2.[/cyan] opus   [dim](smartest)[/dim]")
        console.print("    [cyan]3.[/cyan] haiku  [dim](fastest, cheapest)[/dim]")
        console.print("    [cyan]4.[/cyan] custom")

        model_choice = Prompt.ask("  Choose model", choices=["1", "2", "3", "4"], default="1")
        model_map = {"1": "sonnet", "2": "opus", "3": "haiku"}
        if model_choice == "4":
            model = Prompt.ask("  Enter model name").strip()
        else:
            model = model_map[model_choice]
    elif provider == "openai":
        console.print("\n  [bold]Codex model:[/bold]")
        console.print("    [cyan]1.[/cyan] gpt-5.3-codex [dim](recommended)[/dim]")
        console.print("    [cyan]2.[/cyan] gpt-5.2")
        console.print("    [cyan]3.[/cyan] custom")

        model_choice = Prompt.ask("  Choose model", choices=["1", "2", "3"], default="1")
        model_map = {"1": "gpt-5.3-codex", "2": "gpt-5.2"}
        if model_choice == "3":
            model = Prompt.ask("  Enter model name").strip()
        else:
            model = model_map[model_choice]
    elif provider == "gemini":
        console.print("\n  [bold]Gemini model:[/bold]")
        console.print("    [cyan]1.[/cyan] gemini-3-pro   [dim](recommended)[/dim]")
        console.print("    [cyan]2.[/cyan] gemini-3-flash [dim](fast)[/dim]")
        console.print("    [cyan]3.[/cyan] gemini-2.5-pro")
        console.print("    [cyan]4.[/cyan] gemini-2.5-flash")
        console.print("    [cyan]5.[/cyan] custom")

        model_choice = Prompt.ask("  Choose model", choices=["1", "2", "3", "4", "5"], default="1")
        model_map = {"1": "gemini-3-pro", "2": "gemini-3-flash", "3": "gemini-2.5-pro", "4": "gemini-2.5-flash"}
        if model_choice == "5":
            model = Prompt.ask("  Enter model name").strip()
        else:
            model = model_map[model_choice]
    elif provider == "opencode":
        console.print("\n  [bold]OpenCode model:[/bold] [dim](provider/model format)[/dim]")
        console.print("    [cyan]1.[/cyan] anthropic/claude-sonnet-4-5 [dim](recommended)[/dim]")
        console.print("    [cyan]2.[/cyan] openai/gpt-4o")
        console.print("    [cyan]3.[/cyan] custom")

        model_choice = Prompt.ask("  Choose model", choices=["1", "2", "3"], default="1")
        model_map = {"1": "anthropic/claude-sonnet-4-5", "2": "openai/gpt-4o"}
        if model_choice == "3":
            model = Prompt.ask("  Enter model name (provider/model)").strip()
        else:
            model = model_map[model_choice]
    elif provider == "droid":
        console.print("\n  [bold]Droid model:[/bold]")
        console.print("    [cyan]1.[/cyan] opus   [dim](recommended)[/dim]")
        console.print("    [cyan]2.[/cyan] sonnet")
        console.print("    [cyan]3.[/cyan] gpt-5")
        console.print("    [cyan]4.[/cyan] custom")

        model_choice = Prompt.ask("  Choose model", choices=["1", "2", "3", "4"], default="1")
        model_map = {"1": "opus", "2": "sonnet", "3": "gpt-5"}
        if model_choice == "4":
            model = Prompt.ask("  Enter model name").strip()
        else:
            model = model_map[model_choice]
    else:
        model = Prompt.ask("  Enter model name").strip()

    # Working directory (optional)
    default_dir = f"~/.flowly/agents/{agent_id}"
    working_dir = Prompt.ask("  Working directory", default=default_dir).strip()
    if working_dir == default_dir:
        working_dir = ""  # Use default

    # Create and save
    agent_cfg = MultiAgentConfig(
        name=name,
        provider=provider,
        model=model,
        working_directory=working_dir,
    )
    config.agents.agents[agent_id] = agent_cfg
    console.print(f"\n  [green]✓[/green] Agent [cyan]@{agent_id}[/cyan] added ({provider}/{model})")


def _wizard_create_team(config, inquirer) -> None:
    """Sub-wizard: create a team from existing agents."""
    from flowly.config.schema import MultiAgentTeamConfig

    console.print("\n[bold]Create Team[/bold]")

    agent_ids = list(config.agents.agents.keys())
    if len(agent_ids) < 2:
        console.print("  [yellow]Need at least 2 agents to create a team.[/yellow]")
        return

    # Team ID
    while True:
        team_id = Prompt.ask("  Team ID (e.g., dev, qa)").strip().lower()
        if not team_id:
            console.print("  [red]Team ID is required[/red]")
            continue
        if team_id in config.agents.teams:
            console.print(f"  [yellow]Team '{team_id}' already exists[/yellow]")
            if not Confirm.ask("  Overwrite?", default=False):
                return
        break

    # Display name
    name = Prompt.ask("  Team name", default=team_id.replace("-", " ").replace("_", " ").title()).strip()

    # Select agents
    console.print(f"\n  [bold]Select team members:[/bold]")
    if inquirer is not None:
        agent_choices = [
            {"name": f"@{aid} — {config.agents.agents[aid].name or aid} ({config.agents.agents[aid].provider}/{config.agents.agents[aid].model})", "value": aid}
            for aid in agent_ids
        ]
        try:
            selected_agents = inquirer.checkbox(
                message="Select agents (Space to toggle, Enter to confirm):",
                choices=agent_choices,
            ).execute()
        except (KeyboardInterrupt, EOFError):
            return
    else:
        for idx, aid in enumerate(agent_ids, start=1):
            acfg = config.agents.agents[aid]
            console.print(f"    [cyan]{idx}.[/cyan] @{aid} — {acfg.name or aid} ({acfg.provider}/{acfg.model})")
        console.print(f"\n  [dim]Enter agent numbers separated by commas (e.g., 1,2)[/dim]")
        selection = Prompt.ask("  Select agents").strip()
        try:
            indices = [int(x.strip()) - 1 for x in selection.split(",")]
            selected_agents = [agent_ids[i] for i in indices if 0 <= i < len(agent_ids)]
        except (ValueError, IndexError):
            console.print("  [red]Invalid selection[/red]")
            return

    if len(selected_agents) < 2:
        console.print("  [yellow]A team needs at least 2 agents[/yellow]")
        return

    # Leader agent
    console.print(f"\n  [bold]Choose team leader[/bold] [dim](receives @{team_id} messages first)[/dim]")
    if inquirer is not None:
        leader_choices = [
            {"name": f"@{aid}", "value": aid}
            for aid in selected_agents
        ]
        try:
            leader = inquirer.select(
                message="Select leader:",
                choices=leader_choices,
                default=selected_agents[0],
            ).execute()
        except (KeyboardInterrupt, EOFError):
            return
    else:
        for idx, aid in enumerate(selected_agents, start=1):
            console.print(f"    [cyan]{idx}.[/cyan] @{aid}")
        leader_choice = Prompt.ask(
            "  Choose leader",
            choices=[str(i) for i in range(1, len(selected_agents) + 1)],
            default="1",
        )
        leader = selected_agents[int(leader_choice) - 1]

    # Create and save
    team_cfg = MultiAgentTeamConfig(
        name=name,
        agents=selected_agents,
        leader_agent=leader,
    )
    config.agents.teams[team_id] = team_cfg
    console.print(f"\n  [green]✓[/green] Team [cyan]@{team_id}[/cyan] created")
    console.print(f"    Members: {', '.join(f'@{a}' for a in selected_agents)}")
    console.print(f"    Leader: @{leader}")


def _wizard_remove_agent(config, inquirer) -> None:
    """Sub-wizard: remove an existing agent."""
    agent_ids = list(config.agents.agents.keys())
    if not agent_ids:
        console.print("  [dim]No agents to remove.[/dim]")
        return

    console.print("\n[bold]Remove Agent[/bold]")

    if inquirer is not None:
        choices = [{"name": f"@{aid} — {config.agents.agents[aid].name or aid}", "value": aid} for aid in agent_ids]
        try:
            agent_id = inquirer.select(
                message="Select agent to remove:",
                choices=choices,
            ).execute()
        except (KeyboardInterrupt, EOFError):
            return
    else:
        for idx, aid in enumerate(agent_ids, start=1):
            console.print(f"  [cyan]{idx}.[/cyan] @{aid} — {config.agents.agents[aid].name or aid}")
        choice = Prompt.ask(
            "  Choose agent",
            choices=[str(i) for i in range(1, len(agent_ids) + 1)],
        )
        agent_id = agent_ids[int(choice) - 1]

    if not Confirm.ask(f"  Remove @{agent_id}?", default=False):
        return

    del config.agents.agents[agent_id]

    # Remove from any teams
    teams_to_remove = []
    for tid, team in config.agents.teams.items():
        if agent_id in team.agents:
            team.agents.remove(agent_id)
            if team.leader_agent == agent_id:
                team.leader_agent = team.agents[0] if team.agents else ""
            if len(team.agents) < 2:
                teams_to_remove.append(tid)

    for tid in teams_to_remove:
        del config.agents.teams[tid]
        console.print(f"  [yellow]Team @{tid} removed (not enough members)[/yellow]")

    console.print(f"  [green]✓[/green] Agent @{agent_id} removed")


def _wizard_remove_team(config, inquirer) -> None:
    """Sub-wizard: remove an existing team."""
    team_ids = list(config.agents.teams.keys())
    if not team_ids:
        console.print("  [dim]No teams to remove.[/dim]")
        return

    console.print("\n[bold]Remove Team[/bold]")

    if inquirer is not None:
        choices = [{"name": f"@{tid} — {config.agents.teams[tid].name or tid}", "value": tid} for tid in team_ids]
        try:
            team_id = inquirer.select(
                message="Select team to remove:",
                choices=choices,
            ).execute()
        except (KeyboardInterrupt, EOFError):
            return
    else:
        for idx, tid in enumerate(team_ids, start=1):
            console.print(f"  [cyan]{idx}.[/cyan] @{tid} — {config.agents.teams[tid].name or tid}")
        choice = Prompt.ask(
            "  Choose team",
            choices=[str(i) for i in range(1, len(team_ids) + 1)],
        )
        team_id = team_ids[int(choice) - 1]

    if not Confirm.ask(f"  Remove team @{team_id}?", default=False):
        return

    del config.agents.teams[team_id]
    console.print(f"  [green]✓[/green] Team @{team_id} removed")
    console.print(f"  [dim]Agents are not deleted — only the team is removed.[/dim]")


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

    # 6. X (Twitter)
    x_cfg = config.integrations.x
    if x_cfg.bearer_token or x_cfg.api_key:
        has_post = "read+write" if x_cfg.api_key else "read-only"
        statuses.append(("X (Twitter)", "[green]✓[/green]", f"[dim]{has_post}[/dim]"))
    else:
        statuses.append(("X (Twitter)", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 7. Discord Bot
    discord_token = config.channels.discord.token
    if discord_token:
        masked = discord_token[:8] + "..."
        statuses.append(("Discord Bot", "[green]✓[/green]", f"[dim]{masked}[/dim]"))
    else:
        statuses.append(("Discord Bot", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 8. Slack Bot
    slack_token = config.channels.slack.bot_token
    if slack_token and config.channels.slack.app_token:
        statuses.append(("Slack Bot", "[green]✓[/green]", f"[dim]{config.channels.slack.group_policy}[/dim]"))
    else:
        statuses.append(("Slack Bot", "[red]✗[/red]", "[dim]not configured[/dim]"))

    # 9. Command Execution
    exec_cfg = config.tools.exec
    if exec_cfg.enabled:
        detail = f"{exec_cfg.security}, ask={exec_cfg.ask}"
        statuses.append(("Command Execution", "[green]✓[/green]", f"[dim]{detail}[/dim]"))
    else:
        statuses.append(("Command Execution", "[red]✗[/red]", "[dim]disabled[/dim]"))

    # 10. Multi-Agent
    ma_agents = config.agents.agents
    ma_teams = config.agents.teams
    if ma_agents:
        detail = f"{len(ma_agents)} agent(s), {len(ma_teams)} team(s)"
        statuses.append(("Multi-Agent", "[green]✓[/green]", f"[dim]{detail}[/dim]"))
    else:
        statuses.append(("Multi-Agent", "[yellow]○[/yellow]", "[dim]single-agent mode[/dim]"))

    return statuses


def setup_all() -> None:
    """Run the interactive setup wizard with arrow-key module selection."""
    from flowly import __banner__, __version__
    try:
        from InquirerPy import inquirer
    except Exception:
        inquirer = None

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
        ("X (Twitter)", setup_x),
        ("Discord Bot", setup_discord),
        ("Slack Bot", setup_slack),
        ("Command Execution", setup_exec),
        ("Multi-Agent", setup_agents),
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
        menu_entries.append(f"{label:<22} {icon} {detail}".strip())

    all_idx = len(modules)
    quit_idx = len(modules) + 1

    selected: int | None
    if inquirer is None:
        console.print(
            "[yellow]Interactive menu backend unavailable; using numbered prompts.[/yellow]"
        )
        numbered_entries = menu_entries + ["Run all (full setup)", "Quit"]
        for idx, entry in enumerate(numbered_entries, start=1):
            console.print(f"  [cyan]{idx}.[/cyan] {entry}")

        choice = Prompt.ask(
            "Select a module to configure",
            choices=[str(i) for i in range(1, len(numbered_entries) + 1)],
            default=str(all_idx + 1),
        )
        selected = int(choice) - 1
    else:
        inquirer_choices = [{"name": entry, "value": idx} for idx, entry in enumerate(menu_entries)]
        inquirer_choices.append({"name": "Run all (full setup)", "value": all_idx})
        inquirer_choices.append({"name": "Quit", "value": quit_idx})

        try:
            selected = inquirer.select(
                message="Select a module to configure:",
                instruction="Use arrow keys to navigate, Enter to select",
                choices=inquirer_choices,
                default=all_idx,
            ).execute()
        except (KeyboardInterrupt, EOFError):
            console.print("[dim]Setup cancelled.[/dim]")
            return

    if selected is None:
        console.print("[dim]Setup cancelled.[/dim]")
        return

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
