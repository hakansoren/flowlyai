"""HTTP API server for gateway integrations."""

import asyncio
import json
from typing import Callable, Awaitable

from aiohttp import web
from loguru import logger


class GatewayServer:
    """
    HTTP API server for voice bridge and other integrations.

    Provides endpoints for:
    - Voice message handling (POST /api/voice/message)
    - Health check (GET /health)
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 18790,
        on_voice_message: Callable[[str, str, str], Awaitable[str]] | None = None,
    ):
        """
        Initialize the gateway server.

        Args:
            host: Host to bind to.
            port: Port to listen on.
            on_voice_message: Callback for voice messages (call_sid, from, text) -> response.
        """
        self.host = host
        self.port = port
        self.on_voice_message = on_voice_message
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def _create_app(self) -> web.Application:
        """Create the aiohttp application."""
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        if self.on_voice_message:
            app.router.add_post("/api/voice/message", self._handle_voice_message)
        return app

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok"})

    async def _handle_voice_message(self, request: web.Request) -> web.Response:
        """
        Handle incoming voice message from voice bridge.

        Expected JSON body:
        {
            "call_sid": "CA...",
            "from": "+1234567890",
            "text": "User's transcribed speech"
        }

        Returns:
        {
            "response": "Agent's response to speak"
        }
        """
        try:
            data = await request.json()
            call_sid = data.get("call_sid", "")
            from_number = data.get("from", "")
            text = data.get("text", "")

            logger.info(f"Voice message from {from_number}: {text[:50]}...")

            if not self.on_voice_message:
                return web.json_response(
                    {"error": "Voice handler not configured"},
                    status=500
                )

            # Get response from agent
            response = await self.on_voice_message(call_sid, from_number, text)

            return web.json_response({"response": response})

        except json.JSONDecodeError:
            return web.json_response(
                {"error": "Invalid JSON"},
                status=400
            )
        except Exception as e:
            logger.error(f"Error handling voice message: {e}")
            return web.json_response(
                {"error": str(e)},
                status=500
            )

    async def start(self) -> None:
        """Start the HTTP server."""
        self._app = self._create_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info(f"Gateway API listening on http://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        logger.info("Gateway API stopped")
