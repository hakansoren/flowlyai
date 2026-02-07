# Flowly Entegrasyon Haritasi (UIA/Yuva Icin)

Bu dokumanin amaci: UIA'nin hangi entegrasyonu hangi dosyaya yazacagini ve hangi ek adimlarin zorunlu oldugunu netlestirmek.

## 1) Ana Dosya ve Dizimler

- Ana config dosyasi: `~/.flowly/config.json`
- Pairing/izin dosyalari: `~/.flowly/credentials/`
- WhatsApp auth dosyalari (QR eslesme sonrasi): `~/.flowly/whatsapp-auth/`
- WhatsApp bridge calisma kopyasi (CLI login akisinda olusur): `~/.flowly/bridge/`
- Opsiyonel Node voice-bridge env dosyasi (ayri servis modu): `voice-bridge/.env`

Not: `config.json` degisince servisler bu ayarlari otomatik hot-reload etmez; pratikte `flowly gateway` restart etmek gerekir.

---

## 2) Entegrasyon Ozet Tablosu

| Entegrasyon | Nereye Yazilir | Zorunlu Alanlar | Sadece Yazmak Yeterli mi? | Ek Gereksinim |
|---|---|---|---|---|
| LLM Provider (OpenRouter/OpenAI/Anthropic vb.) | `~/.flowly/config.json` -> `providers.*` | En az 1 provider `apiKey` | Evet (gateway restart ile) | Gecerli API key |
| Telegram | `~/.flowly/config.json` -> `channels.telegram.*` | `enabled=true`, `token` | Buyuk oranda evet | `dmPolicy` pairing/allowlist ise izin adimi gerekir |
| WhatsApp | `~/.flowly/config.json` -> `channels.whatsapp.*` | `enabled=true` (genelde `bridgeUrl`) | Hayir | QR link + `~/.flowly/whatsapp-auth` olusmali + bridge sureci calismali |
| Voice Calls (Twilio) | `~/.flowly/config.json` -> `integrations.voice.*` | `enabled=true`, Twilio SID/token/numara, provider key(leri) | Hayir | Public webhook URL + Twilio konfig + voice runtime |
| ElevenLabs (voice icinde) | `~/.flowly/config.json` -> `integrations.voice.elevenlabsApiKey` (+ provider secimleri) | STT/TTS icin ilgili provider secimi ve key | Tek basina hayir | Voice entegrasyonu calisiyor olmali |
| Trello | `~/.flowly/config.json` -> `integrations.trello.*` | `apiKey`, `token` | Evet (gateway restart ile) | Gecerli Trello token |
| Brave Web Search | `~/.flowly/config.json` -> `tools.web.search.apiKey` | `apiKey` | Evet | Gecerli Brave Search key |

---

## 3) Detayli Yazim Rehberi

## 3.1 LLM Provider'lar

Yazilacak yer:

- `providers.openrouter.apiKey`
- veya `providers.openai.apiKey`
- veya `providers.anthropic.apiKey`
- opsiyonel: `providers.openrouter.apiBase`
- model secimi: `agents.defaults.model`

Minimum ornek:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx",
      "apiBase": "https://openrouter.ai/api/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5"
    }
  }
}
```

## 3.2 Telegram

Yazilacak yer:

- `channels.telegram.enabled`
- `channels.telegram.token`
- `channels.telegram.dmPolicy` (`open` | `pairing` | `allowlist`)
- opsiyonel: `channels.telegram.allowFrom` (user id/username listesi)

Minimum ornek:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABCDEF...",
      "dmPolicy": "pairing",
      "allowFrom": []
    }
  }
}
```

Ek notlar:

- `dmPolicy=open`: token dogruysa direkt calisir.
- `dmPolicy=pairing`: kullanici bota yazinca pairing kodu uretilir; onay gerekir.
- Pairing dosyalari:
  - `~/.flowly/credentials/telegram-pairing.json`
  - `~/.flowly/credentials/telegram-allowFrom.json`

## 3.3 WhatsApp

Yazilacak yer:

- `channels.whatsapp.enabled`
- `channels.whatsapp.bridgeUrl` (default: `ws://localhost:3001`)
- opsiyonel: `channels.whatsapp.allowFrom`

Minimum ornek:

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "allowFrom": ["+90555..."]
    }
  }
}
```

Kritik:

- Bu ayarlari yazmak tek basina yetmez.
- QR link adimi zorunlu (WhatsApp Linked Devices).
- QR sonrasi auth durumlari `~/.flowly/whatsapp-auth/` altinda tutulur.
- Bridge sureci calisiyor olmalidir.

## 3.4 Voice Calls (Twilio + STT/TTS)

Yazilacak yer:

- `integrations.voice.enabled`
- `integrations.voice.twilioAccountSid`
- `integrations.voice.twilioAuthToken`
- `integrations.voice.twilioPhoneNumber`
- `integrations.voice.webhookBaseUrl` (public URL)
- `integrations.voice.sttProvider` (`groq` | `deepgram` | `openai` | `elevenlabs`)
- `integrations.voice.ttsProvider` (`openai` | `deepgram` | `elevenlabs`)
- ilgili key alanlari:
  - `integrations.voice.groqApiKey`
  - `integrations.voice.deepgramApiKey`
  - `integrations.voice.elevenlabsApiKey`
  - veya `providers.openai.apiKey` (openai secildiyse)

Minimum ornek:

```json
{
  "integrations": {
    "voice": {
      "enabled": true,
      "twilioAccountSid": "ACxxx",
      "twilioAuthToken": "xxx",
      "twilioPhoneNumber": "+1...",
      "webhookBaseUrl": "https://your-domain.com",
      "sttProvider": "elevenlabs",
      "ttsProvider": "elevenlabs",
      "elevenlabsApiKey": "xi-xxx",
      "ttsVoice": "21m00Tcm4TlvDq8ikWAM",
      "language": "en-US"
    }
  }
}
```

Kritik:

- Config yazimi gerekli ama tek basina yeterli degil.
- Twilio tarafinda webhook URL dogru ayarlanmis olmali.
- Voice runtime ayakta olmali (Flowly icindeki voice plugin veya ayri voice-bridge servisi).

## 3.5 ElevenLabs (ayri not)

ElevenLabs baglantisi genelde voice entegrasyonunun altinda kullanilir:

- STT icin: `integrations.voice.sttProvider = "elevenlabs"` + `integrations.voice.elevenlabsApiKey`
- TTS icin: `integrations.voice.ttsProvider = "elevenlabs"` + `integrations.voice.elevenlabsApiKey`

Sadece key yazmak ElevenLabs'i "tam aktif" yapmaz; voice akisinin kendisi de calismalidir.

## 3.6 Trello

Yazilacak yer:

- `integrations.trello.apiKey`
- `integrations.trello.token`

Minimum ornek:

```json
{
  "integrations": {
    "trello": {
      "apiKey": "xxx",
      "token": "xxx"
    }
  }
}
```

## 3.7 Brave Web Search (opsiyonel ama pratikte entegrasyon)

Yazilacak yer:

- `tools.web.search.apiKey`
- opsiyonel: `tools.web.search.maxResults`

Minimum ornek:

```json
{
  "tools": {
    "web": {
      "search": {
        "apiKey": "xxx",
        "maxResults": 5
      }
    }
  }
}
```

---

## 4) UIA/Yuva Icin Uygulama Kurallari

- UIA config'e yazarken `camelCase` kullanmali (or. `allowFrom`, `apiKey`, `dmPolicy`).
- Kullanici "Kaydet" dediginde sadece dosyaya yazmak degil, durum mesaji da donmeli:
  - `saved`
  - `saved_requires_runtime_step`
  - `saved_requires_pairing`
- WhatsApp ve Voice icin UIA ayrica "ek adim gerekli" ekranlari gostermeli.
- Telegram token'i kayit oncesi dogrulanabiliyorsa dogrulanmali (getMe benzeri kontrol).

---

## 5) "Kuruldu" Tanimi (Takim Standardi)

- Telegram: config yazildi + gateway calisiyor + token gecerli.
- WhatsApp: config yazildi + bridge calisiyor + QR auth tamamlandi.
- Voice: config yazildi + provider keyleri tam + Twilio webhook/public URL dogru + voice runtime calisiyor.
- Trello/LLM/Brave: config yazildi + key gecerli + gateway restart edildi.

