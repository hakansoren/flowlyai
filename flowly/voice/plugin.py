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
        has_webhook_url = bool((voice_config.webhook_base_url or "").strip())
        has_ngrok = bool((voice_config.ngrok_authtoken or "").strip())

        if not has_webhook_url and not has_ngrok:
            raise ValueError(
                "Voice calls require either webhook_base_url or ngrok_authtoken"
            )

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

        # Store webhook base URL — may be set later by ngrok tunnel
        self._webhook_base_url = voice_config.webhook_base_url or ""
        self._ngrok_tunnel = None
        self._ready = asyncio.Event()

        # Create Twilio client and webhook app if URL is already known
        if has_webhook_url:
            self.twilio = TwilioClient(
                account_sid=voice_config.twilio_account_sid,
                auth_token=voice_config.twilio_auth_token,
                phone_number=voice_config.twilio_phone_number,
                webhook_base_url=self._webhook_base_url,
            )
            self.app = create_voice_app(
                call_manager=self.call_manager,
                webhook_base_url=self._webhook_base_url,
                twilio_auth_token=voice_config.twilio_auth_token,
                webhook_security=voice_config.webhook_security,
                skip_signature_verification=voice_config.skip_signature_verification,
            )
            self._ready.set()
        else:
            # Ngrok mode: Twilio client and app will be created in start()
            self.twilio = None
            self.app = None

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

        # Set message tool context for Telegram if we have chat_id
        telegram_chat_id = call.telegram_chat_id
        if telegram_chat_id:
            from flowly.agent.tools.message import MessageTool
            message_tool = self.agent.tools.get("message")
            if isinstance(message_tool, MessageTool):
                message_tool.set_context("telegram", telegram_chat_id)
                logger.info(f"Set message context for voice call: telegram:{telegram_chat_id}")

        # Build prompt for agent
        telegram_instruction = ""
        if telegram_chat_id:
            telegram_instruction = f"""
4. Telegram'a göndermek için: message(content="mesaj", media_paths=["/path/to/file"]) - chat_id otomatik ayarlı ({telegram_chat_id})
5. Screenshot alıp Telegram'a göndermek için: ÖNCE screenshot() çağır, SONRA dönen path'i message() ile gönder."""
        else:
            telegram_instruction = """
4. Telegram erişimi yok - kullanıcıya sadece sesli yanıt verebilirsin."""

        prompt = f"""[AKTİF TELEFON GÖRÜŞMESI]
Call SID: {call_sid}
Arayan: {call.from_number}

Kullanıcı şunu söyledi: "{text}"

ÖNEMLİ KURALLAR:
1. TÜRKÇE KONUŞ - Kullanıcı Türkçe konuşuyor, sen de Türkçe yanıt ver.
2. Bu bir telefon görüşmesi - kullanıcı sadece senin söylediklerini duyuyor.
3. Gerekirse yalnızca güvenli tool setini kullan (voice_call end/list, screenshot, message, system).{telegram_instruction}
6. Normal yanıtlarında voice_call(action="speak") çağırma; düz metin ver, sistem zaten seslendirecek.
7. Aramayı kapatmak için: voice_call(action="end_call", call_sid="{call_sid}", message="Görüşürüz!")
8. Kısa ve net konuş - telefonda uzun cümleler zor anlaşılır.

Şimdi kullanıcıya Türkçe yanıt ver:"""

        # Use session key to maintain context
        session_key = call.session_key or f"voice:{call_sid}"

        try:
            response = await self.agent.process_direct(prompt, session_key=session_key)
            return response or "Bir sorun oluştu, tekrar söyler misin?"
        except Exception as e:
            logger.error(f"Agent error during voice call: {e}")
            return "Bir hata oluştu, lütfen tekrar dene."

    def _start_ngrok_tunnel_sync(self, port: int, authtoken: str) -> str:
        """Start ngrok tunnel (blocking). Must be called via asyncio.to_thread()."""
        from pyngrok import ngrok, conf

        conf.get_default().auth_token = authtoken
        tunnel = ngrok.connect(port, bind_tls=True)
        public_url = tunnel.public_url

        if not public_url:
            raise RuntimeError("Ngrok tunnel opened but no public URL was assigned")

        self._ngrok_tunnel = tunnel
        return public_url

    async def _update_twilio_webhook_url(
        self, account_sid: str, auth_token: str, phone_number: str, webhook_url: str,
    ):
        """Update Twilio phone number webhook URL automatically."""
        import httpx

        try:
            list_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json"
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    list_url,
                    auth=(account_sid, auth_token),
                    params={"PhoneNumber": phone_number},
                )
                if resp.status_code != 200:
                    logger.error(f"Twilio API error listing numbers: {resp.status_code} {resp.text}")
                    return

                numbers = resp.json().get("incoming_phone_numbers", [])
                if not numbers:
                    logger.warning(f"Phone number {phone_number} not found in Twilio account")
                    return

                phone_sid = numbers[0]["sid"]

                update_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers/{phone_sid}.json"
                update_resp = await client.post(
                    update_url,
                    auth=(account_sid, auth_token),
                    data={
                        "VoiceUrl": f"{webhook_url}/incoming",
                        "VoiceMethod": "POST",
                        "StatusCallback": f"{webhook_url}/status",
                        "StatusCallbackMethod": "POST",
                    },
                )
                if update_resp.status_code != 200:
                    logger.error(f"Twilio API error updating webhook: {update_resp.status_code} {update_resp.text}")
                    return

                logger.info(f"Twilio webhook URL updated to {webhook_url}")
        except Exception as e:
            logger.error(f"Failed to update Twilio webhook URL: {e}")

    async def start(self, host: str = "0.0.0.0", port: int = 8765):
        """Start the voice plugin server.

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        # Start call manager
        await self.call_manager.start()

        voice_cfg = self.config.integrations.voice

        # Ngrok auto-tunnel: open tunnel if webhook_base_url is not set
        if not self._webhook_base_url and voice_cfg.ngrok_authtoken:
            try:
                # Run blocking ngrok.connect() in thread pool to avoid blocking event loop
                logger.info("Opening ngrok tunnel...")
                self._webhook_base_url = await asyncio.to_thread(
                    self._start_ngrok_tunnel_sync, port, voice_cfg.ngrok_authtoken,
                )
                logger.info(f"Ngrok tunnel opened: {self._webhook_base_url} -> localhost:{port}")
            except Exception as e:
                logger.error(f"Failed to open ngrok tunnel: {e}")
                raise RuntimeError(
                    f"Ngrok tunnel failed to start: {e}. "
                    "Check your ngrok_authtoken or set webhook_base_url manually."
                ) from e

            # Now create Twilio client and webhook app with the ngrok URL
            self.twilio = TwilioClient(
                account_sid=voice_cfg.twilio_account_sid,
                auth_token=voice_cfg.twilio_auth_token,
                phone_number=voice_cfg.twilio_phone_number,
                webhook_base_url=self._webhook_base_url,
            )
            self.app = create_voice_app(
                call_manager=self.call_manager,
                webhook_base_url=self._webhook_base_url,
                twilio_auth_token=voice_cfg.twilio_auth_token,
                webhook_security=voice_cfg.webhook_security,
                skip_signature_verification=voice_cfg.skip_signature_verification,
            )

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

        # Mark plugin as ready (make_call/end_call can now be used)
        self._ready.set()

        logger.info(f"Voice plugin started on {host}:{port}")

        # Auto-update Twilio webhook URL AFTER server is running
        if self._ngrok_tunnel and voice_cfg.twilio_account_sid and voice_cfg.twilio_phone_number:
            await self._update_twilio_webhook_url(
                account_sid=voice_cfg.twilio_account_sid,
                auth_token=voice_cfg.twilio_auth_token,
                phone_number=voice_cfg.twilio_phone_number,
                webhook_url=self._webhook_base_url,
            )

    async def stop(self):
        """Stop the voice plugin server."""
        # Close ngrok tunnel
        if self._ngrok_tunnel:
            try:
                from pyngrok import ngrok
                ngrok.disconnect(self._ngrok_tunnel.public_url)
                logger.info("Ngrok tunnel closed")
            except Exception as e:
                logger.warning(f"Error closing ngrok tunnel: {e}")
            self._ngrok_tunnel = None

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
        greeting: str | None = None,
    ) -> str:
        """Initiate an outbound call.

        Args:
            to_number: Phone number to call
            telegram_chat_id: Optional Telegram chat ID for session linking
            greeting: Optional greeting to speak when call is answered

        Returns:
            Call SID
        """
        # Wait for plugin to be ready (ngrok tunnel + Twilio client initialized)
        await asyncio.wait_for(self._ready.wait(), timeout=30.0)

        if not self.twilio:
            raise RuntimeError("Twilio client not initialized")

        return await self.twilio.make_call(
            to_number=to_number,
            call_manager=self.call_manager,
            telegram_chat_id=telegram_chat_id,
            pending_greeting=greeting,
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

        if not self.twilio:
            raise RuntimeError("Twilio client not initialized")

        await self.twilio.end_call(call_sid)
