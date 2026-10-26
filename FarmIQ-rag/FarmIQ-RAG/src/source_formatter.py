"""Source citation formatting for FarmIQ-RAG.

Converts :class:`~src.vector_store.RetrievedItem` objects into readable strings
used in two distinct contexts:

1. **Inside the LLM prompt** – compact numbered references like
   ``[1] soil_health.pdf (p. 4)`` so the model can cite sources by number.
2. **CLI display** – a slightly richer block that includes the relevance score
   and a text snippet, making it easy for a developer to verify that the
   retrieved passages are on-topic.

Both formats only reveal what is genuinely present in the metadata; nothing is
invented or padded.
"""

from __future__ import annotations

from typing import List, Optional

from src.vector_store import RetrievedItem


# ── Prompt-side citation helpers ──────────────────────────────────────────────

def format_context_block(items: List[RetrievedItem], snippet_chars: int = 600) -> str:
    """Format retrieved chunks as a numbered context block for the LLM prompt.

    Each entry includes a reference tag ``[N]``, the source filename + page,
    and the raw passage text (truncated to *snippet_chars*). A reference legend
    at the end lists each source so the model can cite ``[N]`` inline.

    Parameters
    ----------
    items:
        Retrieved passages in descending similarity order.
    snippet_chars:
        Maximum characters per passage included in the prompt. Longer passages
        are truncated with an ellipsis to keep prompts within token budgets.
    """
    if not items:
        return "No relevant agricultural information was found in the knowledge base."

    lines: List[str] = ["--- Retrieved agricultural passages ---"]
    for idx, item in enumerate(items, start=1):
        loc = _location_tag(item)
        text = item.text[:snippet_chars]
        if len(item.text) > snippet_chars:
            text += " …"
        lines.append(f"\n[{idx}] Source: {loc}\n{text}")

    lines.append("\n--- End of retrieved passages ---")
    return "\n".join(lines)


def format_citation_legend(items: List[RetrievedItem]) -> str:
    """Return a compact reference legend for appending to a generated answer.

    Example::

        Sources used:
          [1] soil_health.pdf — page 4
          [2] irrigation_guide.pdf — page 12
    """
    if not items:
        return ""
    legend_lines = ["Sources used:"]
    for idx, item in enumerate(items, start=1):
        legend_lines.append(f"  [{idx}] {_location_tag(item)}")
    return "\n".join(legend_lines)


# ── CLI display helpers ───────────────────────────────────────────────────────

def format_sources_for_display(
    items: List[RetrievedItem],
    snippet_chars: int = 200,
    show_score: bool = True,
) -> str:
    """Human-readable multi-line block for CLI output.

    Includes source name, page, similarity score, and a short snippet so users
    can judge relevance without reading the full passages.
    """
    if not items:
        return "  (no sources)"

    parts: List[str] = []
    for idx, item in enumerate(items, start=1):
        loc = _location_tag(item)
        score_str = f"  similarity: {item.similarity:.2f}" if show_score else ""
        snippet = item.text[:snippet_chars].replace("\n", " ").strip()
        if len(item.text) > snippet_chars:
            snippet += " …"
        parts.append(f"  [{idx}] {loc}{score_str}\n      \"{snippet}\"")
    return "\n".join(parts)


def format_no_evidence_warning(message: str) -> str:
    """Wrap the retriever's insufficient-evidence message in a visible warning."""
    border = "=" * 60
    return f"\n{border}\n⚠  INSUFFICIENT EVIDENCE\n{border}\n{message}\n{border}"


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _location_tag(item: RetrievedItem) -> str:
    """Build a short ``filename (p. N)`` citation string from item metadata."""
    source = item.metadata.get("source") or "unknown"
    page: Optional[int] = item.page
    if page is not None:
        return f"{source} (p. {page})"
    return str(source)
