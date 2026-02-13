<div align="center">
  <img src="flowly_logo.svg" alt="Flowly" width="150">
  <h1>Flowly AI</h1>
  <p><strong>Your personal AI that runs locally, talks everywhere.</strong></p>
  <p>
    <a href="https://pypi.org/project/flowly-ai/"><img src="https://img.shields.io/pypi/v/flowly-ai" alt="PyPI"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-3776AB?logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/platform-macOS%20·%20Linux%20·%20Windows-lightgrey" alt="Platform">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
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
- **Multi-agent** — create custom agents backed by Claude Code or Codex, build teams, delegate tasks
- **Multi-channel** — one agent, reachable from Telegram, WhatsApp, Discord, Slack
- **Voice calls** — answer phone calls with Twilio, talk with real-time STT/TTS
- **Extensible** — add tools, skills, personas, or entire channel adapters
- **Cross-platform** — macOS (launchd), Linux (systemd), Windows (Task Scheduler)
- **Multi-provider** — OpenRouter, Anthropic, OpenAI, xAI/Grok, Gemini, and more via LiteLLM

## Quick Start

### 1. Install

**With [uv](https://github.com/astral-sh/uv)** (recommended)

```bash
uv tool install flowly-ai
```

**From PyPI**

```bash
pip install flowly-ai
```

**From source** (development)

```bash
git clone https://github.com/hakansoren/flowlyai.git && cd flowlyai
pip install -e .
```

### 2. Setup

```bash
flowly onboard          # Initialize config & workspace
flowly setup            # Interactive setup wizard (API keys, channels, tools)
```

### 3. Run

```bash
flowly agent -m "What can you do?"   # Single message
flowly agent                          # Interactive chat
flowly gateway                        # Start all channels
```

> **API keys:** Get your [OpenRouter](https://openrouter.ai/keys) key, then run `flowly setup` or edit `~/.flowly/config.json` directly. Optional: [Groq](https://console.groq.com/keys) (voice), [Brave Search](https://brave.com/search/api/) (web search).

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

## Multi-Agent

Flowly can delegate tasks to external AI agents like [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or [Codex](https://github.com/openai/codex). Each agent runs as a CLI subprocess in the background — Flowly sends the task, responds to you immediately, and delivers the result when the agent finishes.

### Setup

```bash
flowly setup agents    # Interactive wizard — add agents, create teams
```

Or edit `~/.flowly/config.json` directly:

```json
{
  "agents": {
    "defaults": { "model": "anthropic/claude-sonnet-4-5" },
    "agents": {
      "coder": {
        "name": "Code Assistant",
        "provider": "anthropic",
        "model": "sonnet"
      },
      "reviewer": {
        "name": "Code Reviewer",
        "provider": "openai",
        "model": "gpt-5.3-codex"
      }
    },
    "teams": {
      "dev": {
        "name": "Development Team",
        "agents": ["coder", "reviewer"],
        "leaderAgent": "coder"
      }
    }
  }
}
```

**Requirements:** Install the CLI tool for each provider:

| Provider | CLI Required | Short model names |
|----------|-------------|-------------------|
| `anthropic` | [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`) | `sonnet`, `opus`, `haiku` |
| `openai` | [Codex](https://github.com/openai/codex) (`codex`) | `gpt-5.3-codex`, `gpt-5.2` |

### Usage

**`@mention`** — prefix your message with `@agent_id` to talk to a specific agent:

```
@coder fix the login bug in auth.py
@reviewer review the last PR
```

**`@team`** — mention a team name to reach its leader agent:

```
@dev fix the auth bug       → routes to "coder" (team leader)
```

**Natural language** — or just ask Flowly, and it decides whether to delegate:

```
You: build me a todo app with Flask
Flowly: I'll delegate this to @coder...
         [coder works in the background — you can keep chatting]
Flowly: @coder finished! Here's what was built: ...
```

### How It Works

1. **Routing**: `@mention` messages are rewritten so the main Flowly agent calls the `delegate_to` tool. Messages without `@` go to the default Flowly agent, which can also choose to delegate on its own.
2. **Fire-and-forget**: The `delegate_to` tool starts a CLI subprocess in the background and returns immediately — you can keep chatting while the agent works.
3. **Result delivery**: When the subprocess finishes, the result is sent back through the main agent (via the message bus), which summarizes it for you.
4. **Loop prevention**: Delegate results are marked with `[DELEGATE_RESULT:]` — when processing these, the `delegate_to` tool is temporarily removed to prevent infinite re-delegation.
5. **Working directory**: Agents run in your home directory by default (or a custom `workingDirectory` from config), with teammate info injected via `--append-system-prompt`.

## Built-in Tools

| Tool | What it does |
|------|-------------|
| **Shell** | Run commands on your machine (sandboxed) |
| **Filesystem** | Read, write, edit, list files and directories |
| **Web Search** | Search the web with Brave Search API |
| **Web Fetch** | Fetch and extract content from URLs |
| **Screenshot** | Capture your screen |
| **Cron** | Schedule recurring or one-time tasks |
| **Docker** | Manage containers and images |
| **Trello** | Create and manage boards, lists, cards |
| **X (Twitter)** | Post tweets, search, read timelines, get profiles |
| **System** | CPU, memory, disk, process monitoring |
| **Voice** | Make and receive phone calls via Twilio |
| **Message** | Send messages across channels |
| **Delegate** | Delegate tasks to other agents (Claude Code, Codex, etc.) |
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

3. `flowly gateway`

> Get your user ID from `@userinfobot`.

</details>

<details>
<summary><b>WhatsApp</b> — scan QR</summary>

```bash
flowly channels login    # Scan QR code
flowly gateway           # Start (in another terminal)
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

1. Create app at [Discord Developer Portal](https://discord.com/developers/applications)
2. Enable **Message Content Intent** under Privileged Gateway Intents
3. Generate invite URL with `bot` scope + `Send Messages` + `Read Message History`

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

1. Create app at [api.slack.com/apps](https://api.slack.com/apps)
2. Enable Socket Mode, add bot scopes: `chat:write`, `app_mentions:read`, `im:history`
3. Subscribe to events: `message.im`, `app_mention`

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "groupPolicy": "mention"
    }
  }
}
```

No public URL needed — Socket Mode connects outbound.

</details>

## Providers

Flowly uses [LiteLLM](https://github.com/BerriAI/litellm) under the hood, giving you access to 100+ LLM models. Configure your preferred provider:

| Provider | Model prefix | Config key |
|----------|-------------|------------|
| [OpenRouter](https://openrouter.ai) | `anthropic/claude-*`, `openai/gpt-*`, ... | `providers.openrouter.apiKey` |
| [Anthropic](https://console.anthropic.com) | `claude-*` | `providers.anthropic.apiKey` |
| [OpenAI](https://platform.openai.com) | `gpt-*`, `o1-*` | `providers.openai.apiKey` |
| [xAI](https://docs.x.ai) | `xai/grok-*` | `providers.xai.apiKey` |
| [Google Gemini](https://aistudio.google.com) | `gemini/*` | `providers.gemini.apiKey` |
| [Zhipu](https://open.bigmodel.cn) | `zhipu/*` | `providers.zhipu.apiKey` |
| [vLLM](https://docs.vllm.ai) (self-hosted) | any | `providers.vllm.apiBase` |
| [Groq](https://console.groq.com) (voice STT) | — | `providers.groq.apiKey` |

**Example: Switch to Grok**

```json
{
  "providers": {
    "xai": { "apiKey": "xai-..." }
  },
  "agents": {
    "defaults": { "model": "xai/grok-4" }
  }
}
```

## Skills

Skills are plug-and-play capability packs. Install from the hub or create your own:

```bash
flowly skills list                   # List installed
flowly skills search weather         # Search hub
flowly skills install weather        # Install
```

| Skill | What it does |
|-------|-------------|
| **github** | Interact with GitHub via `gh` CLI |
| **weather** | Weather forecasts (wttr.in + Open-Meteo) |
| **summarize** | Summarize URLs, files, YouTube videos |
| **tmux** | Remote control tmux sessions |
| **skill-creator** | Generate new skills from description |

Create your own: drop a `SKILL.md` file in `~/.flowly/workspace/skills/your-skill/`.

## Security

### Command Execution Sandbox

Flowly's shell tool uses a configurable security sandbox:

| Mode | Behavior |
|------|----------|
| `deny` | All commands blocked (default) |
| `allowlist` | Only approved patterns run; unknown commands are asked or denied |
| `full` | All commands allowed (use with caution) |

**Ask modes** (for `allowlist`):
- `on-miss` — ask the user via chat when a command isn't in the allowlist (recommended)
- `always` — ask for every command
- `off` — silently deny unknown commands

```bash
flowly setup              # Configure via wizard
flowly approvals status   # View current config
flowly approvals list     # View allowlist
```

### Device Pairing

Channels use a pairing system to authorize users:

```bash
flowly pairing list               # Pending requests
flowly pairing approve telegram CODE  # Approve
flowly pairing revoke telegram USER   # Revoke
flowly pairing allowed telegram       # List allowed
```

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
flowly setup              # Configure Twilio + STT/TTS
flowly gateway            # Start with voice enabled
```

**Supported providers:**
- **STT:** Groq Whisper, Deepgram, OpenAI, ElevenLabs
- **TTS:** ElevenLabs, Deepgram, OpenAI
- **Telephony:** Twilio

## CLI Reference

```
Setup & Config
  flowly onboard                   Initialize config & workspace
  flowly setup                     Interactive setup wizard
  flowly setup agents              Configure multi-agent (add agents, teams)
  flowly status                    Overall system status

Agent
  flowly agent -m "..."            Send a single message
  flowly agent                     Interactive chat mode
  flowly gateway                   Start gateway (all channels)
  flowly gateway --persona jarvis  Start with a persona

Service
  flowly service install --start   Install and start background service
  flowly service status            Health check
  flowly service logs -f           Follow logs
  flowly service restart           Restart service
  flowly service stop / uninstall  Stop or remove

Channels
  flowly channels login            Link WhatsApp (QR code)
  flowly channels status           Channel connection status

Personas
  flowly persona list              List all personas
  flowly persona set <name>        Switch active persona
  flowly persona show <name>       View persona details

Skills
  flowly skills list               List installed skills
  flowly skills search <query>     Search skill hub
  flowly skills install <name>     Install a skill
  flowly skills remove <name>      Remove a skill

Scheduling
  flowly cron list                 List scheduled jobs
  flowly cron add                  Add a new job
  flowly cron remove <id>          Remove a job
  flowly cron run <id>             Manually run a job

Security
  flowly approvals status          Exec sandbox config
  flowly approvals list            View allowlist
  flowly approvals add <pattern>   Add allowlist pattern
  flowly approvals remove <id>     Remove allowlist entry
  flowly pairing list              Pending pairing requests
  flowly pairing approve <ch> <code>  Approve user
  flowly pairing revoke <ch> <user>   Revoke access
```

## Configuration

All config lives in `~/.flowly/config.json` (camelCase keys):

```json
{
  "providers": {
    "openrouter": { "apiKey": "sk-or-v1-..." },
    "xai": { "apiKey": "xai-..." },
    "groq": { "apiKey": "gsk_..." }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5",
      "maxTokens": 16384,
      "temperature": 0.7,
      "persona": "default"
    },
    "agents": {
      "coder": { "provider": "anthropic", "model": "sonnet" },
      "reviewer": { "provider": "openai", "model": "gpt-5.3-codex" }
    },
    "teams": {
      "dev": { "agents": ["coder", "reviewer"], "leaderAgent": "coder" }
    }
  },
  "channels": {
    "telegram": { "enabled": true, "token": "...", "dmPolicy": "pairing" },
    "discord": { "enabled": true, "token": "..." },
    "slack": { "enabled": true, "botToken": "xoxb-...", "appToken": "xapp-..." },
    "whatsapp": { "enabled": true }
  },
  "tools": {
    "web": { "search": { "braveApiKey": "..." } },
    "exec": {
      "enabled": true,
      "security": "allowlist",
      "ask": "on-miss"
    }
  },
  "integrations": {
    "trello": { "apiKey": "...", "token": "..." },
    "x": {
      "bearerToken": "...",
      "apiKey": "...", "apiSecret": "...",
      "accessToken": "...", "accessTokenSecret": "..."
    },
    "voice": { "enabled": true, "twilioAccountSid": "...", "twilioAuthToken": "..." }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  }
}
```

## Project Structure

```
flowly/
├── agent/              # Core agent loop, context, memory
│   └── tools/          # Built-in tools (shell, web, file, cron, delegate, ...)
├── multiagent/         # Multi-agent orchestration (router, invoker, orchestrator)
├── channels/           # Chat platform adapters (Telegram, Discord, ...)
├── providers/          # LLM provider abstraction (LiteLLM)
├── cli/                # CLI commands and setup wizard
├── config/             # Configuration schema and loader
├── cron/               # Task scheduling service
├── session/            # Conversation session management
├── bus/                # Event bus for message routing
├── heartbeat/          # Periodic wake-up service
└── utils/              # Cross-platform utilities
```

## Requirements

| | Minimum |
|---|---|
| **Python** | ≥ 3.11 |
| **Node.js** | ≥ 18 (only for WhatsApp bridge) |
| **OS** | macOS, Linux, or Windows |

## Desktop App

[Flowly Desktop](https://github.com/hakansoren/flowly-desktop) — Electron app with guided setup, one-click install, and visual management.

## Contributing

Contributions are welcome! Flowly is designed to be readable and extensible:

- **Add a tool:** Create a class extending `Tool` in `flowly/agent/tools/`, register it in `loop.py`
- **Add a channel:** Implement `BaseChannel` in `flowly/channels/`
- **Add a provider:** Add detection logic in `flowly/providers/litellm_provider.py`
- **Add a skill:** Drop a `SKILL.md` in a new folder under `~/.flowly/workspace/skills/`

Please open an issue first for large changes.

---

## Changelog

<details>
<summary><strong>2026-02-11</strong> — Multi-agent, X API, command execution (v1.0.0)</summary>

- Multi-agent delegation: send tasks to Claude Code or Codex via `@mention` or `delegate_to` tool
- Fire-and-forget execution — agents run in background, results delivered asynchronously
- Interactive agent setup wizard: `flowly setup agents`
- X (Twitter) API integration (post, search, timeline, profiles)
- xAI/Grok as LiteLLM provider
- Command execution setup wizard
- Cron job results injected into user session
- License changed to Apache 2.0

</details>

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
  <sub>Apache License 2.0 · Copyright 2025-2026 Nocetic Limited</sub>
</p>
