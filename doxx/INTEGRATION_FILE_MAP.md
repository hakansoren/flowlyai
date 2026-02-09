# Flowly Entegrasyon Dosya Haritasi

Bu belge, her entegrasyonun credential'larinin hangi dosyalara yazildigini, hangi config key'leri kullandigini ve runtime'da hangi dosyalardan okunup kullanildigini detayli olarak gosterir.

---

## Merkezi Konfigürasyon

| Bilgi | Deger |
|---|---|
| **Config dosyasi** | `~/.flowly/config.json` |
| **Schema tanimi** | `flowly/config/schema.py` |
| **Okuma/yazma** | `flowly/config/loader.py` → `load_config()` / `save_config()` |
| **JSON format** | camelCase key'ler (Python'da snake_case'e dönüstürülür) |

Tüm entegrasyon credential'lari bu tek JSON dosyasina yazilir. `save_config()` fonksiyonu snake_case field'lari otomatik olarak camelCase'e cevirir.

---

## 1. Telegram

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `token` | `str` | @BotFather'dan alinan bot token'i |
| `dm_policy` | `"open" \| "pairing" \| "allowlist"` | Kimlerin mesaj atabilecegi |
| `allow_from` | `list[str]` | Izin verilen kullanici ID/username listesi |
| `enabled` | `bool` | Telegram aktif mi |

### Config JSON Yolu

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABC-xyz...",
      "dmPolicy": "pairing",
      "allowFrom": ["123456789"]
    }
  }
}
```

### Setup Akisi

| Adim | Dosya | Satir | Islem |
|---|---|---|---|
| 1 | `flowly/cli/commands.py` | 75-79 | `flowly setup telegram` komutu |
| 2 | `flowly/cli/setup.py` | 26-113 | `setup_telegram()` wizard'i calisir |
| 3 | `flowly/cli/setup.py` | 11-23 | Token dogrulama: `api.telegram.org/bot{token}/getMe` |
| 4 | `flowly/cli/setup.py` | 74-76 | `config.channels.telegram.token = token` → `save_config()` |
| 5 | `flowly/cli/setup.py` | 89-90 | DM policy secimi → `save_config()` |

### Runtime Kullanimi

| Dosya | Ne Yapar |
|---|---|
| `flowly/cli/commands.py:832` | `ChannelManager(config, bus)` → config icinden telegram token alinir |
| `flowly/channels/telegram.py:126` | `TelegramChannel(config, bus, groq_api_key)` constructor'a TelegramConfig gider |
| `flowly/channels/telegram.py:144-148` | `Application.builder().token(self.config.token).build()` → Token ile bot olusturulur |

### Pairing Store (Ek Dosyalar)

Telegram pairing modundayken ek dosyalar olusturulur:

| Dosya | Yol | Aciklama |
|---|---|---|
| Pairing requests | `~/.flowly/credentials/telegram-pairing.json` | Bekleyen eslestirme istekleri |
| Allow-from store | `~/.flowly/credentials/telegram-allowFrom.json` | Pairing ile onaylanan kullanicilar |

Bu dosyalar `flowly/pairing/store.py` tarafindan yönetilir. `approve_pairing_code()` fonksiyonu kullaniciyi `telegram-allowFrom.json`'a ekler.

---

## 2. Twilio (Sesli Arama)

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `twilio_account_sid` | `str` | Twilio hesap SID'i |
| `twilio_auth_token` | `str` | Twilio auth token |
| `twilio_phone_number` | `str` | Twilio telefon numarasi (ör: +905...) |
| `webhook_base_url` | `str` | Twilio callback'lerin gelecegi public URL |
| `enabled` | `bool` | Voice aktif mi |
| `skip_signature_verification` | `bool` | Twilio imza dogrulamasi kapali mi |
| `telegram_chat_id` | `str` | Voice call'lari Telegram session'ina baglamak icin |
| `default_to_number` | `str` | Varsayilan aranacak numara |

### Config JSON Yolu

```json
{
  "integrations": {
    "voice": {
      "enabled": true,
      "twilioAccountSid": "AC...",
      "twilioAuthToken": "abc123...",
      "twilioPhoneNumber": "+1234567890",
      "webhookBaseUrl": "https://your-domain.com",
      "skipSignatureVerification": false,
      "telegramChatId": "",
      "defaultToNumber": "",
      "sttProvider": "groq",
      "ttsProvider": "elevenlabs",
      "groqApiKey": "gsk_...",
      "deepgramApiKey": "",
      "elevenlabsApiKey": "sk_...",
      "ttsVoice": "21m00Tcm4TlvDq8ikWAM",
      "language": "tr-TR",
      "webhookSecurity": {
        "allowedHosts": ["your-domain.com"],
        "trustForwardingHeaders": false,
        "trustedProxyIps": []
      },
      "liveCall": {
        "strictToolSandbox": true,
        "allowTools": ["voice_call", "message", "screenshot", "system"]
      }
    }
  }
}
```

### Setup Akisi

| Adim | Dosya | Satir | Islem |
|---|---|---|---|
| 1 | `flowly/cli/commands.py` | 89-92 | `flowly setup voice-calls` komutu |
| 2 | `flowly/cli/setup.py` | 279-454 | `setup_voice_calls()` wizard'i calisir |
| 3 | `flowly/cli/setup.py` | 308-323 | Account SID, Auth Token, Phone alimi |
| 4 | `flowly/cli/setup.py` | 326-328 | Webhook URL alimi |
| 5 | `flowly/cli/setup.py` | 331-353 | STT provider secimi + API key |
| 6 | `flowly/cli/setup.py` | 356-416 | TTS provider secimi + ses secimi |
| 7 | `flowly/cli/setup.py` | 422-442 | Tüm config set edilir → `save_config()` |

### Runtime Kullanimi

| Dosya | Satir | Ne Yapar |
|---|---|---|
| `flowly/cli/commands.py:894-904` | `VoicePlugin(config, agent)` olusturulur |
| `flowly/voice/plugin.py:35-94` | VoicePlugin constructor → STT/TTS/Twilio client olusturur |
| `flowly/voice/plugin.py:79-84` | `TwilioClient(account_sid, auth_token, phone_number, webhook_url)` |
| `flowly/voice/plugin.py:87-93` | `create_voice_app(...)` → Starlette app, auth_token ile imza dogrulamasi |
| `flowly/voice/webhook.py:160-175` | `_validate_twilio_signature()` → auth_token ile HMAC-SHA1 dogrulama |
| `flowly/voice/webhook.py:389-467` | `TwilioClient.make_call()` → account_sid + auth_token ile Twilio REST API |

---

## 3. Groq (STT - Ses Tanima)

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `api_key` | `str` | Groq API key (gsk_...) |

### Config JSON Yolu (2 farkli yer)

**Yer 1: Genel provider olarak (ses mesaji transkripsiyonu icin)**
```json
{
  "providers": {
    "groq": {
      "apiKey": "gsk_..."
    }
  }
}
```

**Yer 2: Voice calls icinde (STT olarak secildiginde)**
```json
{
  "integrations": {
    "voice": {
      "sttProvider": "groq",
      "groqApiKey": "gsk_..."
    }
  }
}
```

### Setup Akisi

| Komut | Dosya | Fonksiyon | Yazildigi Yer |
|---|---|---|---|
| `flowly setup voice` | `flowly/cli/setup.py:116-154` | `setup_voice()` | `config.providers.groq.api_key` |
| `flowly setup voice-calls` (STT=groq secilirse) | `flowly/cli/setup.py:345-347` | `setup_voice_calls()` | `config.integrations.voice.groq_api_key` |

### Runtime Kullanimi

| Dosya | Satir | Ne Yapar |
|---|---|---|
| `flowly/voice/plugin.py:98-103` | `_get_stt_api_key("groq")` → Önce `voice.groq_api_key`, yoksa `providers.groq.api_key` |
| `flowly/voice/stt.py:27-119` | `GroqWhisperSTT(api_key, language)` → `api.groq.com/openai/v1/audio/transcriptions` |
| `flowly/channels/telegram.py:669-675` | Telegram ses mesajlari icin `GroqTranscriptionProvider(groq_api_key)` |

---

## 4. ElevenLabs (STT + TTS)

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `elevenlabs_api_key` | `str` | ElevenLabs API key (sk_...) |
| `tts_voice` | `str` | ElevenLabs voice ID (ör: 21m00Tcm4TlvDq8ikWAM = rachel) |

### Config JSON Yolu

```json
{
  "integrations": {
    "voice": {
      "elevenlabsApiKey": "sk_...",
      "ttsVoice": "21m00Tcm4TlvDq8ikWAM",
      "sttProvider": "elevenlabs",
      "ttsProvider": "elevenlabs"
    }
  }
}
```

### Setup Akisi

| Adim | Dosya | Satir | Islem |
|---|---|---|---|
| 1 | STT olarak secilirse | `flowly/cli/setup.py:351-353` | ElevenLabs API key alimi |
| 2 | TTS olarak secilirse | `flowly/cli/setup.py:366-370` | API key alimi (zaten alinmadiysa) |
| 3 | Ses secimi | `flowly/cli/setup.py:372-389` | rachel/bella/elli/josh/adam/sam |
| 4 | Kayit | `flowly/cli/setup.py:439` | `config.integrations.voice.elevenlabs_api_key = elevenlabs_key` |

### Runtime Kullanimi

| Dosya | Satir | Ne Yapar |
|---|---|---|
| `flowly/voice/plugin.py:105-106` | `_get_stt_api_key("elevenlabs")` → `voice.elevenlabs_api_key` |
| `flowly/voice/plugin.py:117-118` | `_get_tts_api_key("elevenlabs")` → `voice.elevenlabs_api_key` |
| `flowly/voice/stt.py:121-203` | `ElevenLabsSTT` → `api.elevenlabs.io/v1/speech-to-text` (header: `xi-api-key`) |
| `flowly/voice/tts.py:29-79` | `ElevenLabsTTS` → `api.elevenlabs.io/v1/text-to-speech/{voice_id}` (header: `xi-api-key`) |

---

## 5. Deepgram (STT/TTS)

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `deepgram_api_key` | `str` | Deepgram API key |

### Config JSON Yolu

```json
{
  "integrations": {
    "voice": {
      "deepgramApiKey": "dg_...",
      "sttProvider": "deepgram",
      "ttsProvider": "deepgram",
      "ttsVoice": "aura-asteria-en"
    }
  }
}
```

### Setup Akisi

| Adim | Dosya | Satir | Islem |
|---|---|---|---|
| 1 | STT olarak secilirse | `flowly/cli/setup.py:348-350` | API key alimi |
| 2 | TTS ses secimi | `flowly/cli/setup.py:403-416` | Aura voice secimi |
| 3 | Kayit | `flowly/cli/setup.py:438` | `config.integrations.voice.deepgram_api_key = deepgram_key` |

### Runtime Kullanimi

| Dosya | Satir | Ne Yapar |
|---|---|---|
| `flowly/voice/plugin.py:107-108` | `_get_stt_api_key("deepgram")` → `voice.deepgram_api_key` |
| `flowly/voice/plugin.py:121-122` | `_get_tts_api_key("deepgram")` → `voice.deepgram_api_key` |
| `flowly/voice/tts.py:125-163` | `DeepgramTTS` → `api.deepgram.com/v1/speak` (header: `Token {api_key}`) |

---

## 6. OpenAI (TTS)

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `api_key` | `str` | OpenAI API key |

### Config JSON Yolu

```json
{
  "providers": {
    "openai": {
      "apiKey": "sk-..."
    }
  }
}
```

> **Not:** OpenAI TTS secildigi zaman API key `providers.openai.api_key`'den cekilir, `integrations.voice` icinde ayri bir field yoktur.

### Runtime Kullanimi

| Dosya | Satir | Ne Yapar |
|---|---|---|
| `flowly/voice/plugin.py:109` | `_get_stt_api_key("openai")` → `providers.openai.api_key` |
| `flowly/voice/plugin.py:119-120` | `_get_tts_api_key("openai")` → `providers.openai.api_key` |
| `flowly/voice/tts.py:82-122` | `OpenAITTS` → `api.openai.com/v1/audio/speech` (header: `Bearer {api_key}`) |

---

## 7. Trello

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `api_key` | `str` | Trello API key (trello.com/app-key) |
| `token` | `str` | Trello user token |

### Config JSON Yolu

```json
{
  "integrations": {
    "trello": {
      "apiKey": "abc123...",
      "token": "xyz789..."
    }
  }
}
```

### Setup Akisi

| Adim | Dosya | Satir | Islem |
|---|---|---|---|
| 1 | `flowly/cli/commands.py` | 103-107 | `flowly setup trello` komutu |
| 2 | `flowly/cli/setup.py` | 222-276 | `setup_trello()` wizard'i |
| 3 | `flowly/cli/setup.py` | 266-268 | API key + token → `save_config()` |

### Runtime Kullanimi

| Dosya | Satir | Ne Yapar |
|---|---|---|
| `flowly/cli/commands.py:757` | `trello_config=config.integrations.trello` → AgentLoop'a verilir |
| `flowly/agent/loop.py` | TrelloTool olusturulur ve agent tool registry'ye eklenir |

---

## 8. OpenRouter (LLM Provider)

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `api_key` | `str` | OpenRouter API key (sk-or-...) |
| `api_base` | `str \| None` | API base URL (default: `https://openrouter.ai/api/v1`) |

### Config JSON Yolu

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-...",
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

### Setup Akisi

| Adim | Dosya | Satir | Islem |
|---|---|---|---|
| 1 | `flowly/cli/commands.py` | 96-100 | `flowly setup openrouter` komutu |
| 2 | `flowly/cli/setup.py` | 157-219 | `setup_openrouter()` wizard'i |
| 3 | `flowly/cli/setup.py` | 189-191 | API key + base URL → `save_config()` |
| 4 | `flowly/cli/setup.py` | 214-215 | Model secimi → `config.agents.defaults.model` |

### Runtime Kullanimi

| Dosya | Satir | Ne Yapar |
|---|---|---|
| `flowly/cli/commands.py:696-698` | `config.get_api_key()` → Provider öncelik sirasi: OpenRouter > Anthropic > OpenAI > Gemini > Zhipu > vLLM |
| `flowly/cli/commands.py:704-708` | `LiteLLMProvider(api_key, api_base, model)` olusturulur |
| `flowly/config/schema.py:196-206` | `get_api_key()` öncelik sirasi |
| `flowly/config/schema.py:208-216` | `get_api_base()` OpenRouter/Zhipu/vLLM icin base URL |

---

## 9. Brave Search (Web Arama)

### Credential'lar

| Field | Tip | Aciklama |
|---|---|---|
| `api_key` | `str` | Brave Search API key |

### Config JSON Yolu

```json
{
  "tools": {
    "web": {
      "search": {
        "apiKey": "BSA...",
        "maxResults": 5
      }
    }
  }
}
```

### Setup Akisi

> **Not:** Brave Search icin ayri bir `flowly setup` komutu **yoktur**. Config dosyasi elle düzenlenmeli veya UI'dan ayarlanmalidir.

### Runtime Kullanimi

| Dosya | Satir | Ne Yapar |
|---|---|---|
| `flowly/cli/commands.py:752` | `brave_api_key=config.tools.web.search.api_key or None` → AgentLoop'a verilir |
| `flowly/agent/tools/web.py:31-75` | `WebSearchTool(api_key)` → `api.search.brave.com/res/v1/web/search` (header: `X-Subscription-Token`) |

---

## 10. Diger LLM Provider'lar

### Anthropic

```json
{ "providers": { "anthropic": { "apiKey": "sk-ant-..." } } }
```

### Gemini

```json
{ "providers": { "gemini": { "apiKey": "AI..." } } }
```

### Zhipu

```json
{ "providers": { "zhipu": { "apiKey": "...", "apiBase": "..." } } }
```

### vLLM (Lokal)

```json
{ "providers": { "vllm": { "apiKey": "token", "apiBase": "http://localhost:8000/v1" } } }
```

> Bu provider'lar icin setup wizard'i yoktur. Config dosyasi elle düzenlenmeli veya UI'dan ayarlanmalidir. `get_api_key()` metodu priority sirasina göre ilk buldugunu kullanir.

---

## Ek: Diger Dosya Konumlari

Credential dosyasi disinda yazilan diger runtime verileri:

| Veri | Dosya Yolu | Aciklama |
|---|---|---|
| **Cron jobs** | `~/.flowly/cron/jobs.json` | Zamanlanmis görevler |
| **Sessions** | `~/.flowly/sessions/` | Konusma gecmisleri |
| **Memory** | `~/.flowly/workspace/memory/` | Agent hafizasi |
| **Workspace** | `~/.flowly/workspace/` | AGENTS.md, SOUL.md, USER.md |
| **Media** | `~/.flowly/media/` | Telegram'dan indirilen medya dosyalari |
| **Exec approvals** | `~/.flowly/credentials/exec-approvals.json` | Komut calistirma izinleri |
| **Pairing (Telegram)** | `~/.flowly/credentials/telegram-pairing.json` | Bekleyen eslestirme kodlari |
| **Allow-from (Telegram)** | `~/.flowly/credentials/telegram-allowFrom.json` | Pairing ile onaylanan kullanicilar |
| **Pairing (WhatsApp)** | `~/.flowly/credentials/whatsapp-pairing.json` | WhatsApp pairing |
| **Allow-from (WhatsApp)** | `~/.flowly/credentials/whatsapp-allowFrom.json` | WhatsApp onaylanan kullanicilar |

---

## Özet: UI Entegrasyonu Icin Gerekli Bilgiler

UI'dan entegrasyonlari yönetmek icin yapilmasi gereken:

1. **Oku:** `~/.flowly/config.json` dosyasini oku
2. **Goster:** Her entegrasyonun mevcut durumunu goster (enabled/disabled, hangi key'ler dolu)
3. **Düzenle:** Kullanicidan credential al, config'e yaz
4. **Kaydet:** `save_config()` veya dogrudan JSON yaz (camelCase key'ler kullan)
5. **Dogrula:** Yazilan credential'i dogrula (ör: Telegram token → getMe API cagir)

### JSON'daki Key Isimleri (camelCase)

| Python (snake_case) | JSON (camelCase) |
|---|---|
| `twilio_account_sid` | `twilioAccountSid` |
| `twilio_auth_token` | `twilioAuthToken` |
| `twilio_phone_number` | `twilioPhoneNumber` |
| `webhook_base_url` | `webhookBaseUrl` |
| `elevenlabs_api_key` | `elevenlabsApiKey` |
| `groq_api_key` | `groqApiKey` |
| `deepgram_api_key` | `deepgramApiKey` |
| `stt_provider` | `sttProvider` |
| `tts_provider` | `ttsProvider` |
| `tts_voice` | `ttsVoice` |
| `dm_policy` | `dmPolicy` |
| `allow_from` | `allowFrom` |
| `api_key` | `apiKey` |
| `api_base` | `apiBase` |
| `telegram_chat_id` | `telegramChatId` |
| `default_to_number` | `defaultToNumber` |
| `skip_signature_verification` | `skipSignatureVerification` |
