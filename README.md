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
| `flowly status` | Show status |
| `flowly channels login` | Link WhatsApp (scan QR) |
| `flowly channels status` | Show channel status |
| `flowly voice install` | Install voice bridge dependencies |
| `flowly voice start` | Start the voice bridge server |
| `flowly voice status` | Check voice bridge status |

> On Windows, use `uv run flowly <command>` or add the script to your PATH.

---

## 🤝 Credits

Based on [nanobot](https://github.com/HKUDS/nanobot) by HKUDS.

<p align="center">
  <em>Thanks for visiting ✨ Flowly!</em>
</p>
