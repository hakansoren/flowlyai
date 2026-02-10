<div align="center">
  <img src="flowly_logo.svg" alt="Flowly" width="150">
  <h1>Flowly: Personal AI Assistant</h1>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

🐈 **Flowly** is an **ultra-lightweight** personal AI assistant based on [nanobot](https://github.com/HKUDS/nanobot)

⚡️ Delivers core agent functionality in just **~4,000** lines of code.

## Key Features of Flowly:

🪶 **Ultra-Lightweight**: Just ~4,000 lines of code - core functionality.

🔬 **Research-Ready**: Clean, readable code that's easy to understand, modify, and extend for research.

⚡️ **Lightning Fast**: Minimal footprint means faster startup, lower resource usage, and quicker iterations.

💎 **Easy-to-Use**: One-click to deploy and you're ready to go.

## 📦 Install

### Prerequisites

| Platform | Requirements |
|----------|--------------|
| **All** | Python ≥3.11, [uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **Windows** | Node.js ≥20 (for WhatsApp/Voice) |
| **macOS/Linux** | Node.js ≥20 (for WhatsApp/Voice) |

### Setup

**macOS/Linux:**
```bash
git clone https://github.com/hakansoren/flowlyai.git
cd flowlyai
uv sync
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/hakansoren/flowlyai.git
cd flowlyai
uv sync
```

> Flowly works seamlessly on Windows, macOS, and Linux.

## 🚀 Quick Start

> [!TIP]
> Set your API key in `~/.flowly/config.json`.
> Get API keys: [OpenRouter](https://openrouter.ai/keys) (LLM) · [Groq](https://console.groq.com/keys) (voice) · [Brave Search](https://brave.com/search/api/) (web search)

**1. Initialize**

```bash
uv run flowly onboard
```

**2. Configure** (`~/.flowly/config.json`)

```json
{
  "providers": {
    "openrouter": {
      "api_key": "sk-or-v1-xxx"
    },
    "groq": {
      "api_key": "gsk_xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5"
    }
  }
}
```

**3. Chat**

```bash
uv run flowly agent -m "What is 2+2?"
```

## Run In Background (Terminal Closed)

Install a user service once and keep Flowly running after terminal closes:

```bash
flowly service install --start
flowly service status
```

Manage lifecycle:

```bash
flowly service restart
flowly service stop
flowly service uninstall
```

| Platform | Backend |
|----------|---------|
| **macOS** | launchd (LaunchAgents) |
| **Linux** | systemd (user service) |
| **Windows** | Task Scheduler (schtasks) |

This runs the full gateway stack in background (agent loop + channels + cron + voice plugin).

## Personas

Give your Flowly a unique personality! Choose from 8 built-in personas:

| Persona | Style |
|---------|-------|
| `default` | Helpful and friendly (standard) |
| `jarvis` | J.A.R.V.I.S. — refined British AI, dry wit |
| `friday` | F.R.I.D.A.Y. — warm and professional |
| `pirate` | Captain Flowly — "Aye aye, Captain!" |
| `samurai` | Disciplined warrior, brief and wise |
| `casual` | Your best buddy, relaxed and fun |
| `professor` | Thorough explanations, step by step |
| `butler` | Distinguished English butler, ultra-polite |

**Set during install:**

```bash
flowly service install --start --persona jarvis
```

**Change anytime:**

```bash
flowly persona list          # See all available personas
flowly persona set pirate    # Switch to pirate mode
flowly persona show jarvis   # Preview a persona
flowly service restart       # Apply the change
```

**Or pass directly to gateway:**

```bash
flowly gateway --persona professor
```

Personas only change how the bot talks — all tools, memory, and functionality stay the same. You can also create your own by adding a `.md` file to `~/.flowly/workspace/personas/`.

## 💬 Chat Apps

Talk to your Flowly through Telegram or WhatsApp — anytime, anywhere.

| Channel | Setup |
|---------|-------|
| **Telegram** | Easy (just a token) |
| **WhatsApp** | Medium (scan QR) |

<details>
<summary><b>Telegram</b> (Recommended)</summary>

**1. Create a bot**
- Open Telegram, search `@BotFather`
- Send `/newbot`, follow prompts
- Copy the token

**2. Configure**

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

> Get your user ID from `@userinfobot` on Telegram.

**3. Run**

```bash
uv run flowly gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

Requires **Node.js ≥18**.

**1. Link device**

```bash
uv run flowly channels login
# Scan QR with WhatsApp → Settings → Linked Devices
```

**2. Configure**

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

**3. Run** (two terminals)

```bash
# Terminal 1
uv run flowly channels login

# Terminal 2
uv run flowly gateway
```

</details>

## CLI Reference

| Command | Description |
|---------|-------------|
| `flowly onboard` | Initialize config & workspace |
| `flowly agent -m "..."` | Chat with the agent |
| `flowly agent` | Interactive chat mode |
| `flowly gateway` | Start the gateway |
| `flowly gateway --persona jarvis` | Start gateway with a persona |
| `flowly service install --start` | Install/start background service |
| `flowly service install --persona pirate` | Install service with a persona |
| `flowly service status` | Check background service health |
| `flowly service logs -f` | Follow background service logs live |
| `flowly service restart` | Restart background service |
| `flowly persona list` | List available personas |
| `flowly persona set <name>` | Set active persona |
| `flowly persona show <name>` | Preview a persona |
| `flowly status` | Show status |
| `flowly setup voice-calls` | Configure integrated Twilio voice plugin |
| `flowly channels login` | Link WhatsApp (scan QR) |
| `flowly channels status` | Show channel status |

> On Windows, use `uv run flowly <command>` or add the script to your PATH.

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
- Cron scheduling tool
- Context compaction system
- Groq Whisper voice transcription
- Flowly Hub skill management
- Rebranded from nanobot to Flowly

</details>

---

<p align="center">
  <em>Thanks for visiting ✨ Flowly!</em>
</p>
