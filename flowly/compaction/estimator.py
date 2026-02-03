"""Token estimation for messages."""

import tiktoken
from typing import Any

# Cache the encoder
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Get or create the tiktoken encoder."""
    global _encoder
    if _encoder is None:
        # Use cl100k_base which is used by GPT-4 and Claude
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def estimate_tokens(text: str) -> int:
    """
    Estimate the number of tokens in a text string.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    if not text:
        return 0

    encoder = _get_encoder()
    return len(encoder.encode(text))


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """
    Estimate tokens for a single message.

    Args:
        message: Message dict with role and content.

    Returns:
        Estimated token count.
    """
    tokens = 0

    # Role overhead (approximately 4 tokens per message for formatting)
    tokens += 4

    # Content
    content = message.get("content", "")
    if isinstance(content, str):
        tokens += estimate_tokens(content)
    elif isinstance(content, list):
        # Multi-part content (images, etc.)
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    tokens += estimate_tokens(part.get("text", ""))
                elif part.get("type") == "image_url":
                    # Rough estimate for images (Claude uses ~1000 tokens for small images)
                    tokens += 1000

    # Tool calls
    tool_calls = message.get("tool_calls", [])
    if tool_calls:
        for tc in tool_calls:
            if isinstance(tc, dict):
                func = tc.get("function", {})
                tokens += estimate_tokens(func.get("name", ""))
                tokens += estimate_tokens(func.get("arguments", ""))
                tokens += 10  # Overhead

    return tokens


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """
    Estimate total tokens for a list of messages.

    Args:
        messages: List of message dicts.

    Returns:
        Total estimated token count.
    """
    return sum(estimate_message_tokens(msg) for msg in messages)
