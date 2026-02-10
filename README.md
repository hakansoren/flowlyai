<div align="center">
  <img src="flowly_logo.svg" alt="Flowly" width="150">
  <h1>Flowly AI</h1>
  <p><strong>Your personal AI that runs locally, talks everywhere.</strong></p>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.11-3776AB?logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/platform-macOS%20·%20Linux%20·%20Windows-lightgrey" alt="Platform">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

---

Flowly is a personal AI assistant that lives on your machine. Connect it to Telegram, WhatsApp, Discord, or Slack — then talk to it from anywhere. It can browse the web, manage files, run shell commands, take screenshots, schedule tasks, make phone calls, and more.

```
You (Telegram) → Flowly (your Mac/PC) → tools, files, APIs → response
```

## Why Flowly?

- **Runs on your machine** — your data stays local, your tools stay private
- **Always on** — install as a background service, survives terminal close and reboot
- **Multi-channel** — one agent, reachable from Telegram, WhatsApp, Discord, Slack
- **Voice calls** — answer phone calls with Twilio, talk with real-time STT/TTS
- **Extensible** — add tools, skills, personas, or entire channel adapters
- **Cross-platform** — macOS (launchd), Linux (systemd), Windows (Task Scheduler)

## Quick Start

```bash
# Install
git clone https://github.com/hakansoren/flowlyai.git && cd flowlyai
uv sync

# Setup
uv run flowly onboard

# Chat
uv run flowly agent -m "What can you do?"
```

> **API keys:** Set your [OpenRouter](https://openrouter.ai/keys) key in `~/.flowly/config.json`. Optional: [Groq](https://console.groq.com/keys) (voice), [Brave Search](https://brave.com/search/api/) (web search).

## Architecture

```
┌─────────────────────────────────────────────┐
│                  Gateway                     │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│  │ Telegram │  │ WhatsApp │  │  Discord   │  │
│  │  Slack   │  │  Voice   │  │   CLI      │  │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘  │
│       └──────────────┼──────────────┘        │
│                      ▼                       │
│              ┌──────────────┐                │
│              │  Agent Loop  │                │
│              │   (LiteLLM)  │                │
│              └──────┬───────┘                │
│                     ▼                        │
│  ┌─────┐ ┌──────┐ ┌─────┐ ┌──────┐ ┌─────┐ │
│  │Shell│ │ Web  │ │File │ │ Cron │ │ ... │ │
│  └─────┘ └──────┘ └─────┘ └──────┘ └─────┘ │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │  Skills · Personas · Hub · Memory    │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

## Built-in Tools

| Tool | What it does |
|------|-------------|
| **Shell** | Run commands on your machine |
| **Filesystem** | Read, write, edit, list files |
| **Web** | Fetch URLs, search with Brave |
| **Screenshot** | Capture your screen |
| **Cron** | Schedule recurring tasks |
| **Docker** | Manage containers and images |
| **Trello** | Create/manage boards and cards |
| **System** | CPU, memory, disk, process info |
| **Voice** | Make and receive phone calls |
| **Spawn** | Run background sub-agents |

## Channels

Connect Flowly to your favorite chat apps. Each channel runs simultaneously through the gateway.

<details>
<summary><b>Telegram</b> — easiest setup</summary>

1. Create a bot via `@BotFather` on Telegram
2. Add to config:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

3. `uv run flowly gateway`

> Get your user ID from `@userinfobot`.

</details>

<details>
<summary><b>WhatsApp</b> — scan QR</summary>

```bash
uv run flowly channels login    # Scan QR code
uv run flowly gateway           # Start (in another terminal)
```

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

Requires Node.js ≥18.

</details>

<details>
<summary><b>Discord</b></summary>

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

</details>

<details>
<summary><b>Slack</b></summary>

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "allowFrom": ["U1234567890"]
    }
  }
}
```

</details>

## Background Service

Run Flowly as a persistent service — survives terminal close and auto-starts on boot:

```bash
flowly service install --start    # Install and start
flowly service status             # Health check
flowly service logs -f            # Follow logs
flowly service restart            # Restart
flowly service stop               # Stop
flowly service uninstall          # Remove
```

| Platform | Backend |
|----------|---------|
| macOS | launchd (LaunchAgents) |
| Linux | systemd (user service) |
| Windows | Task Scheduler |

## Personas

Switch how Flowly talks without changing functionality:

```bash
flowly persona list              # See all
flowly persona set jarvis        # Switch persona
flowly service restart           # Apply
```

| Persona | Style |
|---------|-------|
| `default` | Helpful and friendly |
| `jarvis` | J.A.R.V.I.S. — British AI, dry wit |
| `friday` | F.R.I.D.A.Y. — warm, professional |
| `pirate` | "Aye aye, Captain!" |
| `samurai` | Brief and wise |
| `casual` | Your best buddy |
| `professor` | Step-by-step explanations |
| `butler` | Distinguished, ultra-polite |

Create your own: drop a `.md` file in `~/.flowly/workspace/personas/`.

## Voice Calls

Flowly can answer and make phone calls with real-time speech:

```bash
flowly setup voice-calls         # Configure Twilio + STT/TTS
flowly gateway                   # Start with voice enabled
```

**Supported providers:**
- **STT:** Groq Whisper, Deepgram, ElevenLabs
- **TTS:** ElevenLabs, Deepgram, OpenAI
- **Telephony:** Twilio

## CLI Reference

```
flowly onboard                   Initialize config & workspace
flowly agent -m "..."            Send a message
flowly agent                     Interactive chat
flowly gateway                   Start the gateway (all channels)
flowly gateway --persona jarvis  Start with a persona
flowly service install --start   Install background service
flowly service status            Service health check
flowly service logs -f           Follow logs
flowly persona list              List personas
flowly persona set <name>        Switch persona
flowly setup voice-calls         Configure voice
flowly channels login            Link WhatsApp
flowly channels status           Channel status
flowly status                    Overall status
```

## Configuration

All config lives in `~/.flowly/config.json`:

```json
{
  "providers": {
    "openrouter": { "apiKey": "sk-or-v1-..." }
  },
  "agents": {
    "defaults": { "model": "anthropic/claude-sonnet-4-5" }
  },
  "channels": {
    "telegram": { "enabled": true, "token": "..." }
  }
}
```

## Requirements

| | Minimum |
|---|---|
| **Python** | ≥ 3.11 |
| **uv** | Any recent version |
| **Node.js** | ≥ 18 (only for WhatsApp bridge) |
| **OS** | macOS, Linux, or Windows |

## Desktop App

[Flowly Desktop](https://github.com/hakansoren/flowly-desktop) — Electron app with guided setup, one-click install, and visual management.

---

## Changelog

<details>
<summary><strong>2026-02-10</strong> — Discord & Slack channels, setup wizard</summary>

- Discord and Slack channel implementations
- Interactive CLI setup wizard (`flowly setup`)
- Multi-channel manager support

</details>

<details>
<summary><strong>2026-02-09</strong> — Service mode, personas, screenshot delegation</summary>

- Background service mode (launchd/systemd/schtasks)
- 8 built-in personas (Jarvis, Friday, Pirate, etc.)
- Electron-delegated screenshot system
- Voice call improvements

</details>

<details>
<summary><strong>2026-02-06</strong> — Integrated voice system, new tools</summary>

- Twilio voice bridge with real-time audio streaming
- ElevenLabs, Deepgram, Groq Whisper STT/TTS providers
- Agentic voice call state machine
- System monitoring, Docker, Trello integration tools
- Cross-platform support (Windows/macOS/Linux)

</details>

<details>
<summary><strong>2026-02-04</strong> — Secure execution, pairing system</summary>

- Secure command execution sandbox
- Device pairing system
- Interactive setup CLI wizard

</details>

<details>
<summary><strong>2026-02-03</strong> — Initial release</summary>

- Core agent loop with LiteLLM provider
- Telegram and WhatsApp channels
- Cron scheduling, context compaction
- Groq Whisper voice transcription
- Flowly Hub skill management

</details>

---

<p align="center">
  <sub>MIT License</sub>
</p>
