"""Voice webhook server for Twilio integration.

Handles:
- HTTP webhooks for call events (incoming, status callbacks)
- WebSocket connections for media streams
"""

import asyncio
import base64
import json
import logging
from typing import Callable, Awaitable
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse
from starlette.websockets import WebSocket

from .call_manager import CallManager

logger = logging.getLogger(__name__)


def create_voice_app(
    call_manager: CallManager,
    webhook_base_url: str,
) -> Starlette:
    """Create the voice webhook Starlette application.

    Args:
        call_manager: Call manager instance
        webhook_base_url: Public URL for Twilio webhooks (e.g., ngrok URL)

    Returns:
        Starlette application
    """

    async def handle_incoming_call(request: Request) -> Response:
        """Handle incoming call from Twilio.

        Returns TwiML to connect media stream.
        """
        form = await request.form()
        call_sid = form.get("CallSid", "")
        from_number = form.get("From", "")
        to_number = form.get("To", "")

        logger.info(f"Incoming call: {call_sid} from {from_number}")

        # Create call state
        call_manager.create_call(
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
        )

        # Build media stream URL
        stream_url = f"{webhook_base_url.replace('https://', 'wss://').replace('http://', 'ws://')}/media-stream"

        # Return TwiML to connect media stream
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="callSid" value="{call_sid}"/>
        </Stream>
    </Connect>
</Response>"""

        return Response(
            content=twiml,
            media_type="application/xml",
        )

    async def handle_outgoing_call(request: Request) -> Response:
        """Handle outgoing call webhook (when our call is answered).

        Returns TwiML to connect media stream.
        """
        form = await request.form()
        call_sid = form.get("CallSid", "")
        call_status = form.get("CallStatus", "")

        logger.info(f"Outgoing call status: {call_sid} -> {call_status}")

        if call_status == "in-progress":
            # Build media stream URL
            stream_url = f"{webhook_base_url.replace('https://', 'wss://').replace('http://', 'ws://')}/media-stream"

            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="callSid" value="{call_sid}"/>
        </Stream>
    </Connect>
</Response>"""

            return Response(
                content=twiml,
                media_type="application/xml",
            )

        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )

    async def handle_call_status(request: Request) -> Response:
        """Handle call status webhook."""
        form = await request.form()
        call_sid = form.get("CallSid", "")
        call_status = form.get("CallStatus", "")

        logger.info(f"Call status update: {call_sid} -> {call_status}")

        if call_status in ("completed", "failed", "busy", "no-answer", "canceled"):
            await call_manager.handle_call_ended(call_sid)

        return PlainTextResponse("OK")

    async def handle_media_stream(websocket: WebSocket):
        """Handle Twilio Media Stream WebSocket connection."""
        await websocket.accept()

        stream_sid = None
        call_sid = None

        try:
            async for message in websocket.iter_text():
                data = json.loads(message)
                event = data.get("event")

                if event == "connected":
                    logger.info("Media stream connected")

                elif event == "start":
                    stream_sid = data.get("streamSid")
                    start_data = data.get("start", {})
                    call_sid = start_data.get("customParameters", {}).get("callSid")

                    logger.info(f"Media stream started: {stream_sid} for call {call_sid}")

                    # Register stream
                    call_manager.register_stream(stream_sid, websocket)

                    # Mark call as answered
                    if call_sid:
                        await call_manager.handle_call_answered(call_sid, stream_sid)

                elif event == "media":
                    media = data.get("media", {})
                    payload = media.get("payload", "")

                    if call_sid and payload:
                        await call_manager.handle_audio(call_sid, payload)

                elif event == "stop":
                    logger.info(f"Media stream stopped: {stream_sid}")
                    if call_sid:
                        await call_manager.handle_call_ended(call_sid)

        except Exception as e:
            logger.error(f"Media stream error: {e}")
        finally:
            if stream_sid:
                call_manager.unregister_stream(stream_sid)

    async def health_check(request: Request) -> Response:
        """Health check endpoint."""
        return PlainTextResponse("OK")

    routes = [
        Route("/incoming", handle_incoming_call, methods=["POST"]),
        Route("/outgoing", handle_outgoing_call, methods=["POST"]),
        Route("/status", handle_call_status, methods=["POST"]),
        Route("/health", health_check, methods=["GET"]),
        WebSocketRoute("/media-stream", handle_media_stream),
    ]

    return Starlette(routes=routes)


class TwilioClient:
    """Twilio REST API client for initiating calls."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        phone_number: str,
        webhook_base_url: str,
    ):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.phone_number = phone_number
        self.webhook_base_url = webhook_base_url

    async def make_call(
        self,
        to_number: str,
        call_manager: CallManager,
        telegram_chat_id: str | None = None,
    ) -> str:
        """Initiate an outbound call.

        Args:
            to_number: Phone number to call
            call_manager: Call manager instance
            telegram_chat_id: Optional Telegram chat ID to link session

        Returns:
            Call SID
        """
        import httpx

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls.json"

        # TwiML for outbound call
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{self.webhook_base_url.replace('https://', 'wss://').replace('http://', 'ws://')}/media-stream">
            <Parameter name="callSid" value="{{{{CallSid}}}}"/>
        </Stream>
    </Connect>
</Response>"""

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                auth=(self.account_sid, self.auth_token),
                data={
                    "To": to_number,
                    "From": self.phone_number,
                    "Twiml": twiml,
                    "StatusCallback": f"{self.webhook_base_url}/status",
                    "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
                },
            )

            if response.status_code not in (200, 201):
                raise Exception(f"Twilio API error: {response.status_code} - {response.text}")

            result = response.json()
            call_sid = result["sid"]

            # Create call state
            call_manager.create_call(
                call_sid=call_sid,
                from_number=self.phone_number,
                to_number=to_number,
                telegram_chat_id=telegram_chat_id,
            )

            logger.info(f"Outbound call initiated: {call_sid} to {to_number}")
            return call_sid

    async def end_call(self, call_sid: str) -> bool:
        """End an active call.

        Args:
            call_sid: Call SID to end

        Returns:
            True if successful
        """
        import httpx

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls/{call_sid}.json"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                auth=(self.account_sid, self.auth_token),
                data={"Status": "completed"},
            )

            if response.status_code != 200:
                logger.error(f"Failed to end call: {response.status_code} - {response.text}")
                return False

            logger.info(f"Call ended via API: {call_sid}")
            return True
