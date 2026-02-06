"""Call Manager - manages active voice calls and their state."""

import asyncio
import base64
import logging
import time
from typing import Callable, Awaitable

from .types import CallState, CallStatus, VoiceCall, STTResult
from .audio import (
    twilio_to_stt,
    tts_to_twilio,
    detect_speech_energy,
    calculate_audio_duration_ms,
    TWILIO_SAMPLE_RATE,
)
from .stt import STTProvider
from .tts import TTSProvider

logger = logging.getLogger(__name__)

# Configuration
SILENCE_THRESHOLD_MS = 1500  # Silence duration to trigger transcription
MIN_SPEECH_DURATION_MS = 300  # Minimum speech to process
SPEECH_ENERGY_THRESHOLD = 500  # RMS threshold for speech detection


class CallManager:
    """Manages active voice calls.

    Handles:
    - Call state tracking
    - Audio buffering and processing
    - Speech detection and silence detection
    - STT/TTS coordination
    - TTS queue management
    """

    def __init__(
        self,
        stt_provider: STTProvider,
        tts_provider: TTSProvider,
        on_transcription: Callable[[str, str], Awaitable[str]],  # (call_sid, text) -> response
    ):
        self.stt = stt_provider
        self.tts = tts_provider
        self.on_transcription = on_transcription

        # Active calls by call_sid
        self.calls: dict[str, CallState] = {}

        # WebSocket connections by stream_sid
        self.streams: dict[str, any] = {}  # stream_sid -> websocket

        # Background tasks
        self._silence_detector_task: asyncio.Task | None = None
        self._tts_tasks: dict[str, asyncio.Task] = {}

    async def start(self):
        """Start the call manager."""
        self._silence_detector_task = asyncio.create_task(self._silence_detector_loop())
        logger.info("Call manager started")

    async def stop(self):
        """Stop the call manager."""
        if self._silence_detector_task:
            self._silence_detector_task.cancel()
            try:
                await self._silence_detector_task
            except asyncio.CancelledError:
                pass

        for task in self._tts_tasks.values():
            task.cancel()

        logger.info("Call manager stopped")

    def create_call(
        self,
        call_sid: str,
        from_number: str,
        to_number: str,
        telegram_chat_id: str | None = None,
    ) -> CallState:
        """Create a new call state."""
        state = CallState(
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
            status=CallStatus.INITIATED,
            telegram_chat_id=telegram_chat_id,
        )

        if telegram_chat_id:
            state.session_key = f"telegram:{telegram_chat_id}"
        else:
            state.session_key = f"voice:{call_sid}"

        self.calls[call_sid] = state
        logger.info(f"Call created: {call_sid} from {from_number} to {to_number}")
        return state

    def get_call(self, call_sid: str) -> CallState | None:
        """Get call state by call_sid."""
        return self.calls.get(call_sid)

    def get_call_by_stream(self, stream_sid: str) -> CallState | None:
        """Get call state by stream_sid."""
        for call in self.calls.values():
            if call.stream_sid == stream_sid:
                return call
        return None

    async def handle_call_answered(self, call_sid: str, stream_sid: str):
        """Handle call answered event."""
        call = self.calls.get(call_sid)
        if not call:
            logger.warning(f"Call not found: {call_sid}")
            return

        call.status = CallStatus.ACTIVE
        call.stream_sid = stream_sid
        call.answered_at = time.time()
        call.is_listening = True

        # Start TTS processor for this call
        self._tts_tasks[call_sid] = asyncio.create_task(
            self._tts_processor(call_sid)
        )

        logger.info(f"Call answered: {call_sid}, stream: {stream_sid}")

    async def handle_call_ended(self, call_sid: str):
        """Handle call ended event."""
        call = self.calls.get(call_sid)
        if not call:
            return

        call.status = CallStatus.COMPLETED
        call.ended_at = time.time()

        # Cancel TTS task
        if call_sid in self._tts_tasks:
            self._tts_tasks[call_sid].cancel()
            del self._tts_tasks[call_sid]

        # Clean up stream
        if call.stream_sid and call.stream_sid in self.streams:
            del self.streams[call.stream_sid]

        logger.info(f"Call ended: {call_sid}")

    def register_stream(self, stream_sid: str, websocket):
        """Register a WebSocket connection for a stream."""
        self.streams[stream_sid] = websocket
        logger.debug(f"Stream registered: {stream_sid}")

    def unregister_stream(self, stream_sid: str):
        """Unregister a stream's WebSocket connection."""
        if stream_sid in self.streams:
            del self.streams[stream_sid]
            logger.debug(f"Stream unregistered: {stream_sid}")

    async def handle_audio(self, call_sid: str, audio_base64: str):
        """Handle incoming audio from Twilio.

        Args:
            call_sid: Call SID
            audio_base64: Base64 encoded mu-law audio
        """
        call = self.calls.get(call_sid)
        if not call or not call.is_listening:
            return

        # Decode audio
        mulaw_audio = base64.b64decode(audio_base64)

        # Convert to PCM for STT
        pcm_audio = twilio_to_stt(mulaw_audio)

        # Check for speech
        has_speech = detect_speech_energy(pcm_audio, SPEECH_ENERGY_THRESHOLD)

        if has_speech:
            # Add to speech buffer
            call.speech_buffer.append(pcm_audio)
            call.last_speech_time = time.time()
            call.silence_start = None
        else:
            # Start silence timer
            if call.silence_start is None:
                call.silence_start = time.time()

    async def _silence_detector_loop(self):
        """Background task to detect silence and trigger transcription."""
        while True:
            try:
                await asyncio.sleep(0.1)  # Check every 100ms

                current_time = time.time()

                for call_sid, call in list(self.calls.items()):
                    if call.status != CallStatus.ACTIVE:
                        continue

                    if not call.is_listening:
                        continue

                    if not call.speech_buffer:
                        continue

                    # Check if silence threshold reached
                    if call.silence_start is not None:
                        silence_duration = (current_time - call.silence_start) * 1000

                        if silence_duration >= SILENCE_THRESHOLD_MS:
                            # Process accumulated speech
                            await self._process_speech(call)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in silence detector: {e}")

    async def _process_speech(self, call: CallState):
        """Process accumulated speech buffer."""
        if not call.speech_buffer:
            return

        # Combine all audio chunks
        combined_audio = b''.join(call.speech_buffer)
        call.speech_buffer.clear()
        call.silence_start = None

        # Check minimum duration
        duration_ms = calculate_audio_duration_ms(combined_audio, 16000)
        if duration_ms < MIN_SPEECH_DURATION_MS:
            logger.debug(f"Speech too short: {duration_ms}ms, skipping")
            return

        # Stop listening while processing
        call.status = CallStatus.PROCESSING

        try:
            # Transcribe
            result = await self.stt.transcribe(combined_audio)

            if result and result.text:
                logger.info(f"Transcription: {result.text}")

                # Get response from agent
                response = await self.on_transcription(call.call_sid, result.text)

                if response:
                    # Queue TTS
                    await self.speak(call.call_sid, response)

        except Exception as e:
            logger.error(f"Error processing speech: {e}")
        finally:
            call.status = CallStatus.ACTIVE
            call.is_listening = True

    async def speak(self, call_sid: str, text: str):
        """Queue text for TTS playback.

        Args:
            call_sid: Call SID
            text: Text to speak
        """
        call = self.calls.get(call_sid)
        if not call:
            return

        await call.tts_queue.put(text)

    async def _tts_processor(self, call_sid: str):
        """Background task to process TTS queue for a call."""
        call = self.calls.get(call_sid)
        if not call:
            return

        while True:
            try:
                # Wait for text in queue
                text = await call.tts_queue.get()

                # Stop listening while speaking
                call.is_listening = False
                call.status = CallStatus.SPEAKING

                # Synthesize speech
                pcm_audio = await self.tts.synthesize(text)

                # Convert to Twilio format
                mulaw_audio = tts_to_twilio(pcm_audio, self.tts.sample_rate)

                # Send to Twilio
                await self._send_audio(call, mulaw_audio)

                # Resume listening
                call.status = CallStatus.ACTIVE
                call.is_listening = True

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in TTS processor: {e}")
                call.is_listening = True

    async def _send_audio(self, call: CallState, audio: bytes):
        """Send audio to Twilio via WebSocket.

        Args:
            call: Call state
            audio: mu-law audio bytes
        """
        if not call.stream_sid:
            logger.warning(f"No stream_sid for call {call.call_sid}")
            return

        ws = self.streams.get(call.stream_sid)
        if not ws:
            logger.warning(f"No WebSocket for stream {call.stream_sid}")
            return

        # Twilio expects audio in chunks (e.g., 20ms chunks = 160 bytes at 8kHz)
        chunk_size = 160  # 20ms of mu-law audio at 8kHz
        audio_base64 = base64.b64encode(audio).decode()

        # Send media message
        import json
        message = {
            "event": "media",
            "streamSid": call.stream_sid,
            "media": {
                "payload": audio_base64
            }
        }

        try:
            await ws.send_text(json.dumps(message))

            # Calculate duration and wait for playback
            duration_ms = len(audio) * 1000 // TWILIO_SAMPLE_RATE
            await asyncio.sleep(duration_ms / 1000)

        except Exception as e:
            logger.error(f"Error sending audio: {e}")

    async def end_call(self, call_sid: str, message: str | None = None):
        """End a call with optional goodbye message.

        Args:
            call_sid: Call SID
            message: Optional message to speak before ending
        """
        call = self.calls.get(call_sid)
        if not call:
            return

        if message:
            await self.speak(call_sid, message)
            # Wait for TTS to complete
            while not call.tts_queue.empty():
                await asyncio.sleep(0.1)

        # The actual call termination will be handled by Twilio webhook
        await self.handle_call_ended(call_sid)

    def list_active_calls(self) -> list[VoiceCall]:
        """List all active calls."""
        return [
            VoiceCall.from_state(call)
            for call in self.calls.values()
            if call.status in (CallStatus.ACTIVE, CallStatus.SPEAKING, CallStatus.LISTENING)
        ]
