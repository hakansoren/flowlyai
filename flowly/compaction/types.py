"""Types for compaction system."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class MemoryFlushConfig:
    """Configuration for pre-compaction memory flush."""

    enabled: bool = True
    soft_threshold_tokens: int = 4000
    prompt: str = (
        "Pre-compaction memory flush. "
        "Store durable memories now (use memory/YYYY-MM-DD.md). "
        "If nothing to store, reply with NO_REPLY."
    )
    system_prompt: str = (
        "Pre-compaction memory flush turn. "
        "The session is near auto-compaction; capture durable memories to disk. "
        "You may reply, but usually NO_REPLY is correct."
    )


@dataclass
class CompactionConfig:
    """Configuration for compaction."""

    # Mode: "default" (simple) or "safeguard" (robust with pruning)
    mode: Literal["default", "safeguard"] = "safeguard"

    # Reserve tokens for output + prompts (floor)
    reserve_tokens_floor: int = 20_000

    # Max share of context window for history (safeguard mode)
    max_history_share: float = 0.5

    # Context window size (model-specific, will be auto-detected)
    context_window: int = 128_000

    # Memory flush settings
    memory_flush: MemoryFlushConfig = field(default_factory=MemoryFlushConfig)


@dataclass
class CompactionResult:
    """Result of a compaction operation."""

    summary: str
    tokens_before: int
    tokens_after: int
    messages_removed: int
    dropped_chunks: int = 0
    dropped_messages: int = 0
    dropped_tokens: int = 0


# Constants (matching moltbot)
BASE_CHUNK_RATIO = 0.4
MIN_CHUNK_RATIO = 0.15
SAFETY_MARGIN = 1.2  # 20% buffer for token estimation inaccuracy

DEFAULT_SUMMARY_FALLBACK = "No prior history."
DEFAULT_PARTS = 2

MERGE_SUMMARIES_INSTRUCTIONS = (
    "Merge these partial summaries into a single cohesive summary. "
    "Preserve decisions, TODOs, open questions, and any constraints."
)

SILENT_REPLY_TOKEN = "NO_REPLY"
