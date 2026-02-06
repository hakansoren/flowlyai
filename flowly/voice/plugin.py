"""Voice plugin - integrates voice system with the agent.

This is the main entry point for the integrated voice system.
It connects the call manager with the agent for full tool access.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

import uvicorn

from flowly.config import Config
from .call_manager import CallManager
from .stt import create_stt_provider
from .tts import create_tts_provider
from .webhook import create_voice_app, TwilioClient

if TYPE_CHECKING:
    from flowly.agent import AgentLoop

logger = logging.getLogger(__name__)


class VoicePlugin:
    """Voice plugin for integrated voice call support.

    Provides:
    - Incoming call handling via Twilio webhooks
    - Outgoing call initiation
    - STT/TTS integration
    - Full agent tool access during calls
    """

    def __init__(self, config: Config, agent: "AgentLoop"):
        self.config = config
        self.agent = agent

        voice_config = config.integrations.voice

        # Create STT provider
        stt_provider_name = voice_config.stt_provider or "groq"
        stt_api_key = self._get_stt_api_key(stt_provider_name)

        if not stt_api_key:
            raise ValueError(f"No API key configured for STT provider: {stt_provider_name}")

        self.stt = create_stt_provider(
            provider=stt_provider_name,
            api_key=stt_api_key,
            language=voice_config.language or "tr",
        )

        # Create TTS provider
        tts_provider_name = voice_config.tts_provider or "elevenlabs"
        tts_api_key = self._get_tts_api_key(tts_provider_name)

        if not tts_api_key:
            raise ValueError(f"No API key configured for TTS provider: {tts_provider_name}")

        self.tts = create_tts_provider(
            provider=tts_provider_name,
            api_key=tts_api_key,
            voice=voice_config.tts_voice,
        )

        # Create call manager
        self.call_manager = CallManager(
            stt_provider=self.stt,
            tts_provider=self.tts,
            on_transcription=self._handle_transcription,
        )

        # Create Twilio client
        self.twilio = TwilioClient(
            account_sid=voice_config.twilio_account_sid,
            auth_token=voice_config.twilio_auth_token,
            phone_number=voice_config.twilio_phone_number,
            webhook_base_url=voice_config.webhook_base_url,
        )

        # Create webhook app
        self.app = create_voice_app(
            call_manager=self.call_manager,
            webhook_base_url=voice_config.webhook_base_url,
        )

        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task | None = None

    def _get_stt_api_key(self, provider: str) -> str | None:
        """Get API key for STT provider."""
        voice_config = self.config.integrations.voice

        if provider == "groq":
            return voice_config.groq_api_key or self.config.providers.groq.api_key
        elif provider == "elevenlabs":
            return voice_config.elevenlabs_api_key
        elif provider == "deepgram":
            return voice_config.deepgram_api_key
        elif provider == "openai":
            return self.config.providers.openai.api_key

        return None

    def _get_tts_api_key(self, provider: str) -> str | None:
        """Get API key for TTS provider."""
        voice_config = self.config.integrations.voice

        if provider == "elevenlabs":
            return voice_config.elevenlabs_api_key
        elif provider == "openai":
            return self.config.providers.openai.api_key
        elif provider == "deepgram":
            return voice_config.deepgram_api_key

        return None

    async def _handle_transcription(self, call_sid: str, text: str) -> str:
        """Handle transcription from a call.

        This is where the magic happens - the agent processes the
        transcribed speech with full tool access.

        Args:
            call_sid: Call SID
            text: Transcribed speech

        Returns:
            Agent response to speak back
        """
        call = self.call_manager.get_call(call_sid)
        if not call:
            return "Bir hata oluştu."

        # Build prompt for agent
        prompt = f"""[AKTİF TELEFON GÖRÜŞMESI]
Call SID: {call_sid}
Arayan: {call.from_number}

Kullanıcı şunu söyledi: "{text}"

ÖNEMLİ KURALLAR:
1. TÜRKÇE KONUŞ - Kullanıcı Türkçe konuşuyor, sen de Türkçe yanıt ver.
2. Bu bir telefon görüşmesi - kullanıcı sadece senin söylediklerini duyuyor.
3. Tool kullanabilirsin (screenshot, exec, web_search, cron vb.) - kullan ve sonucu söyle.
4. Screenshot alırsan otomatik Telegram'a gider, kullanıcıya "ekran görüntüsünü Telegram'a gönderdim" de.
5. Aramayı kapatmak için: voice_call(action="end_call", call_sid="{call_sid}", message="Görüşürüz!")
6. Kısa ve net konuş - telefonda uzun cümleler zor anlaşılır.

Şimdi kullanıcıya Türkçe yanıt ver:"""

        # Use session key to maintain context
        session_key = call.session_key or f"voice:{call_sid}"

        try:
            response = await self.agent.process_direct(prompt, session_key=session_key)
            return response or "Bir sorun oluştu, tekrar söyler misin?"
        except Exception as e:
            logger.error(f"Agent error during voice call: {e}")
            return "Bir hata oluştu, lütfen tekrar dene."

    async def start(self, host: str = "0.0.0.0", port: int = 8765):
        """Start the voice plugin server.

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        # Start call manager
        await self.call_manager.start()

        # Configure uvicorn
        config = uvicorn.Config(
            app=self.app,
            host=host,
            port=port,
            log_level="info",
        )
        self._server = uvicorn.Server(config)

        # Run server in background task
        self._server_task = asyncio.create_task(self._server.serve())

        logger.info(f"Voice plugin started on {host}:{port}")

    async def stop(self):
        """Stop the voice plugin server."""
        if self._server:
            self._server.should_exit = True

        if self._server_task:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._server_task.cancel()

        await self.call_manager.stop()
        logger.info("Voice plugin stopped")

    async def make_call(
        self,
        to_number: str,
        telegram_chat_id: str | None = None,
    ) -> str:
        """Initiate an outbound call.

        Args:
            to_number: Phone number to call
            telegram_chat_id: Optional Telegram chat ID for session linking

        Returns:
            Call SID
        """
        return await self.twilio.make_call(
            to_number=to_number,
            call_manager=self.call_manager,
            telegram_chat_id=telegram_chat_id,
        )

    async def end_call(self, call_sid: str, message: str | None = None):
        """End an active call.

        Args:
            call_sid: Call SID
            message: Optional goodbye message
        """
        if message:
            await self.call_manager.speak(call_sid, message)
            # Wait for TTS to complete
            call = self.call_manager.get_call(call_sid)
            if call:
                while not call.tts_queue.empty():
                    await asyncio.sleep(0.1)

        await self.twilio.end_call(call_sid)
