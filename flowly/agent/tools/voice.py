"""Voice call tool for making and managing phone calls via voice-bridge."""

from typing import Any

import httpx
from loguru import logger

from flowly.agent.tools.base import Tool


class VoiceCallTool(Tool):
    """
    Tool to make and manage voice calls via the voice-bridge service.

    The voice-bridge handles Twilio, STT (Deepgram/OpenAI), and TTS (OpenAI).
    This tool provides an interface for the agent to control calls.
    """

    def __init__(self, bridge_url: str = "http://localhost:8765"):
        """
        Initialize the voice call tool.

        Args:
            bridge_url: URL of the voice-bridge API.
        """
        self.bridge_url = bridge_url.rstrip("/")

    @property
    def name(self) -> str:
        return "voice_call"

    @property
    def description(self) -> str:
        return """Make and manage voice phone calls.

Actions:
- call: Make a call and start a conversation
- speak: Speak a message on an active call
- end_call: End a call (optionally with goodbye message)
- get_call: Get call status and transcript
- list_calls: List all active calls

Phone numbers should be in E.164 format (e.g., +1234567890).

When you make a call with action="call", the system will:
1. Call the phone number
2. Speak your greeting message
3. Listen for the user's response
4. Send the transcribed speech back to you automatically

Your responses to voice messages will be automatically spoken to the caller.

Examples:
- Make a call: voice_call(action="call", to="+1234567890", greeting="Hello, how can I help?")
- End call: voice_call(action="end_call", call_sid="CA...", message="Goodbye!")
- Get status: voice_call(action="get_call", call_sid="CA...")"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform",
                    "enum": ["call", "speak", "end_call", "get_call", "list_calls"],
                },
                "to": {
                    "type": "string",
                    "description": "Phone number to call (for action=call)",
                },
                "greeting": {
                    "type": "string",
                    "description": "Initial greeting message (for action=call)",
                },
                "message": {
                    "type": "string",
                    "description": "Message to speak (for action=speak, end_call)",
                },
                "call_sid": {
                    "type": "string",
                    "description": "Call SID (for speak, end_call, get_call)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, **kwargs: Any) -> str:
        """Execute a voice call action."""
        try:
            if action == "call":
                return await self._make_call(
                    to=kwargs.get("to", ""),
                    greeting=kwargs.get("greeting", "Hello!"),
                )
            elif action == "speak":
                return await self._speak(
                    call_sid=kwargs.get("call_sid", ""),
                    message=kwargs.get("message", ""),
                )
            elif action == "end_call":
                return await self._end_call(
                    call_sid=kwargs.get("call_sid", ""),
                    message=kwargs.get("message"),
                )
            elif action == "get_call":
                return await self._get_call(kwargs.get("call_sid", ""))
            elif action == "list_calls":
                return await self._list_calls()
            else:
                return f"Unknown action: {action}"

        except httpx.ConnectError:
            return "Error: Voice bridge is not running. Start it with: cd voice-bridge && npm start"
        except Exception as e:
            logger.error(f"Voice call error: {e}")
            return f"Error: {str(e)}"

    async def _make_call(self, to: str, greeting: str) -> str:
        """Make a conversation call."""
        if not to:
            return "Error: 'to' phone number is required"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.bridge_url}/api/call",
                json={
                    "to": to,
                    "greeting": greeting,
                    "conversation": True,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

        call_sid = data.get("callSid", "unknown")

        return f"""📞 Call initiated!

Call SID: {call_sid}
To: {to}
Greeting: "{greeting}"

The call is being placed. When the user answers and speaks, their words will appear in the conversation.
Your responses will be automatically spoken to them."""

    async def _speak(self, call_sid: str, message: str) -> str:
        """Speak on an active call."""
        if not call_sid:
            return "Error: 'call_sid' is required"
        if not message:
            return "Error: 'message' is required"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.bridge_url}/api/speak",
                json={"callSid": call_sid, "message": message},
                timeout=30,
            )
            response.raise_for_status()

        return f"🗣️ Speaking on call {call_sid}: \"{message}\""

    async def _end_call(self, call_sid: str, message: str | None = None) -> str:
        """End a call."""
        if not call_sid:
            return "Error: 'call_sid' is required"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.bridge_url}/api/end",
                json={"callSid": call_sid, "message": message},
                timeout=30,
            )
            response.raise_for_status()

        if message:
            return f"📞 Call ended with message: \"{message}\""
        return f"📞 Call {call_sid} ended."

    async def _get_call(self, call_sid: str) -> str:
        """Get call details."""
        if not call_sid:
            return "Error: 'call_sid' is required"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.bridge_url}/api/call/{call_sid}",
                timeout=30,
            )

            if response.status_code == 404:
                return f"Call not found: {call_sid}"

            response.raise_for_status()
            call = response.json()

        # Format transcript
        transcript_lines = []
        for entry in call.get("transcript", []):
            role = "🤖 Assistant" if entry["role"] == "assistant" else "👤 User"
            transcript_lines.append(f"  {role}: {entry['text']}")

        transcript = "\n".join(transcript_lines) if transcript_lines else "  (no transcript)"

        state = call.get("state", "unknown")
        duration = call.get("durationSeconds")
        duration_str = f"{duration}s" if duration else "ongoing"

        return f"""📞 Call Status: {call_sid}

State: {state}
From: {call.get("from", "unknown")}
To: {call.get("to", "unknown")}
Duration: {duration_str}

📝 Transcript:
{transcript}"""

    async def _list_calls(self) -> str:
        """List active calls."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.bridge_url}/api/calls",
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

        calls = data.get("calls", [])

        if not calls:
            return "📞 No active calls."

        lines = ["📞 Active Calls:\n"]
        for call in calls:
            lines.append(f"• {call['callSid']}")
            lines.append(f"  To: {call['to']} | State: {call['state']}")
            lines.append("")

        return "\n".join(lines)
