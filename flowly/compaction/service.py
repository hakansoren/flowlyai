"""Compaction service for managing context compression."""

from typing import Any

from loguru import logger

from flowly.compaction.estimator import estimate_messages_tokens
from flowly.compaction.pruning import (
    prune_history_for_context_share,
    compute_adaptive_chunk_ratio,
)
from flowly.compaction.summarizer import summarize_in_stages
from flowly.compaction.types import (
    CompactionConfig,
    CompactionResult,
    SILENT_REPLY_TOKEN,
    SAFETY_MARGIN,
)
from flowly.providers.base import LLMProvider


class CompactionService:
    """
    Service for managing context compaction.

    Handles:
    - Automatic compaction when context exceeds threshold
    - Memory flush before compaction
    - Safeguard mode with adaptive chunking and pruning
    """

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        config: CompactionConfig | None = None,
    ):
        """
        Initialize the compaction service.

        Args:
            provider: LLM provider for summarization.
            model: Model to use for summarization.
            config: Compaction configuration.
        """
        self.provider = provider
        self.model = model
        self.config = config or CompactionConfig()
        self._compaction_count = 0
        self._memory_flush_compaction_count: int | None = None

    def should_compact(self, total_tokens: int) -> bool:
        """
        Check if compaction should be triggered.

        Args:
            total_tokens: Current total tokens in context.

        Returns:
            True if compaction is needed.
        """
        threshold = self.config.context_window - self.config.reserve_tokens_floor
        return total_tokens > threshold

    def should_memory_flush(self, total_tokens: int) -> bool:
        """
        Check if memory flush should run before compaction.

        Args:
            total_tokens: Current total tokens in context.

        Returns:
            True if memory flush should run.
        """
        if not self.config.memory_flush.enabled:
            return False

        # Check if already flushed in this compaction cycle
        if self._memory_flush_compaction_count == self._compaction_count:
            return False

        # Calculate soft threshold
        threshold = (
            self.config.context_window
            - self.config.reserve_tokens_floor
            - self.config.memory_flush.soft_threshold_tokens
        )

        return total_tokens > threshold

    def get_memory_flush_prompt(self) -> tuple[str, str]:
        """
        Get the prompts for memory flush turn.

        Returns:
            Tuple of (user_prompt, system_prompt).
        """
        return (
            self.config.memory_flush.prompt,
            self.config.memory_flush.system_prompt,
        )

    def mark_memory_flush_done(self) -> None:
        """Mark that memory flush has been done for this compaction cycle."""
        self._memory_flush_compaction_count = self._compaction_count

    def is_silent_reply(self, response: str) -> bool:
        """
        Check if response should be silent (not sent to user).

        Args:
            response: The response text.

        Returns:
            True if response starts with NO_REPLY token.
        """
        return response.strip().startswith(SILENT_REPLY_TOKEN)

    def strip_silent_token(self, response: str) -> str:
        """
        Strip the NO_REPLY token from response.

        Args:
            response: The response text.

        Returns:
            Response without the token.
        """
        stripped = response.strip()
        if stripped.startswith(SILENT_REPLY_TOKEN):
            return stripped[len(SILENT_REPLY_TOKEN):].strip()
        return response

    async def compact(
        self,
        messages: list[dict[str, Any]],
        custom_instructions: str | None = None,
        previous_summary: str | None = None,
    ) -> CompactionResult:
        """
        Compact messages by generating a summary.

        Args:
            messages: Messages to compact.
            custom_instructions: Optional custom instructions for summarization.
            previous_summary: Optional previous summary to incorporate.

        Returns:
            CompactionResult with summary and statistics.
        """
        if not messages:
            return CompactionResult(
                summary=previous_summary or "No prior history.",
                tokens_before=0,
                tokens_after=0,
                messages_removed=0,
            )

        tokens_before = estimate_messages_tokens(messages)
        messages_to_summarize = messages
        dropped_summary: str | None = None
        dropped_chunks = 0
        dropped_messages = 0
        dropped_tokens = 0

        # Safeguard mode: prune if needed
        if self.config.mode == "safeguard":
            pruned = prune_history_for_context_share(
                messages,
                self.config.context_window,
                self.config.max_history_share,
                parts=2,
            )

            if pruned["dropped_chunks"] > 0:
                logger.info(
                    f"Compaction safeguard: dropped {pruned['dropped_chunks']} "
                    f"chunk(s) ({pruned['dropped_messages']} messages) to fit history budget"
                )
                messages_to_summarize = pruned["messages"]
                dropped_chunks = pruned["dropped_chunks"]
                dropped_messages = pruned["dropped_messages"]
                dropped_tokens = pruned["dropped_tokens"]

                # Summarize dropped messages separately
                if pruned["dropped_messages_list"]:
                    try:
                        dropped_chunk_ratio = compute_adaptive_chunk_ratio(
                            pruned["dropped_messages_list"],
                            self.config.context_window,
                        )
                        dropped_max_chunk_tokens = max(
                            1,
                            int(self.config.context_window * dropped_chunk_ratio),
                        )
                        dropped_summary = await summarize_in_stages(
                            pruned["dropped_messages_list"],
                            self.provider,
                            self.model,
                            self.config.reserve_tokens_floor,
                            dropped_max_chunk_tokens,
                            self.config.context_window,
                            custom_instructions,
                            previous_summary,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to summarize dropped messages: {e}"
                        )

        # Calculate adaptive chunk ratio
        adaptive_ratio = compute_adaptive_chunk_ratio(
            messages_to_summarize,
            self.config.context_window,
        )
        max_chunk_tokens = max(
            1,
            int(self.config.context_window * adaptive_ratio),
        )

        # Use dropped summary as previous summary if available
        effective_previous = dropped_summary or previous_summary

        # Generate summary
        try:
            summary = await summarize_in_stages(
                messages_to_summarize,
                self.provider,
                self.model,
                self.config.reserve_tokens_floor,
                max_chunk_tokens,
                self.config.context_window,
                custom_instructions,
                effective_previous,
            )
        except Exception as e:
            logger.error(f"Compaction summarization failed: {e}")
            summary = (
                f"Context contained {len(messages)} messages. "
                "Summary unavailable due to error."
            )

        # Estimate tokens after (rough estimate based on summary length)
        from flowly.compaction.estimator import estimate_tokens
        tokens_after = estimate_tokens(summary)

        # Increment compaction count
        self._compaction_count += 1

        return CompactionResult(
            summary=summary,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_removed=len(messages),
            dropped_chunks=dropped_chunks,
            dropped_messages=dropped_messages,
            dropped_tokens=dropped_tokens,
        )

    async def compact_if_needed(
        self,
        messages: list[dict[str, Any]],
        custom_instructions: str | None = None,
    ) -> tuple[list[dict[str, Any]], CompactionResult | None]:
        """
        Compact messages if threshold exceeded.

        Args:
            messages: Current messages.
            custom_instructions: Optional custom instructions.

        Returns:
            Tuple of (possibly compacted messages, CompactionResult or None).
        """
        total_tokens = estimate_messages_tokens(messages)

        if not self.should_compact(total_tokens):
            return messages, None

        logger.info(
            f"Compacting context: {total_tokens} tokens exceeds threshold"
        )

        result = await self.compact(messages, custom_instructions)

        # Replace messages with summary
        summary_message = {
            "role": "system",
            "content": f"[Previous conversation summary]\n\n{result.summary}",
        }

        return [summary_message], result

    @property
    def compaction_count(self) -> int:
        """Get the number of compactions performed."""
        return self._compaction_count
