"""Claude RAG for content questions — streams answer tokens."""

from __future__ import annotations

import os
import re
from typing import AsyncGenerator

import anthropic

from src.db.database import Database

# CARB-specific acronym expansions for FTS query improvement.
# Keys are matched as whole words (case-insensitive); values are appended
# so the original term is preserved alongside the expansion.
_ACRONYMS: dict[str, str] = {
    "ZEB":  "zero-emission bus",
    "ZEBs": "zero-emission buses",
    "ZEV":  "zero-emission vehicle",
    "ZEVs": "zero-emission vehicles",
    "PHEV": "plug-in hybrid electric vehicle",
    "PHEVs": "plug-in hybrid electric vehicles",
    "OBD":  "on-board diagnostic",
    "NOx":  "oxides of nitrogen",
    "PM":   "particulate matter",
    "GHG":  "greenhouse gas",
    "ICT":  "innovative clean transit",
    "ACT":  "advanced clean trucks",
    "HD":   "heavy-duty",
    "LD":   "light-duty",
    "MD":   "medium-duty",
    "FTP":  "federal test procedure",
    "BHP":  "brake horsepower",
    "SOREL": "solid oxide regenerative electrolysis",
}


def _expand_acronyms(query: str) -> str:
    """Replace known acronyms with 'ACRONYM expansion' for better FTS recall."""
    result = query
    for acronym, expansion in _ACRONYMS.items():
        pattern = rf"\b{re.escape(acronym)}\b"
        result = re.sub(pattern, f"{acronym} {expansion}", result, flags=re.IGNORECASE)
    return result

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM_PROMPT = """\
You are a regulatory assistant specialising in California Air Resources Board (CARB) regulations.
Answer questions using ONLY the document excerpts provided below.
If the answer is not found in the excerpts, say so clearly — do not guess.
Always cite the document title(s) you used in your answer.
Be concise and precise."""


def _build_context(docs: list[dict]) -> str:
    if not docs:
        return "No relevant documents found."
    parts = []
    for i, doc in enumerate(docs, 1):
        title = doc.get("title") or "Untitled"
        snippet = doc.get("snippet") or doc.get("content", "")[:1500]
        parts.append(f"[{i}] **{title}**\n{snippet}")
    return "\n\n---\n\n".join(parts)


def _key_terms(query: str) -> list[str]:
    """Extract model years from a query for use as content-location anchors.

    Only years are used — they are specific enough to pinpoint the right row
    in a multi-year standards table without causing false relocations.

    Section numbers are intentionally excluded: they appear in cross-references
    throughout a document, so searching for them moves the window to citation
    text rather than the substantive content we want.

    Bigrams are also excluded: they appear too broadly and cause regressions.
    """
    return list(dict.fromkeys(re.findall(r'\b(?:19|20)\d{2}\b', query)))


def _best_excerpt(full: str, fts_snippet: str, window: int = 8000) -> str:
    """Extract the most relevant portion of a large document.

    For small docs (≤ window chars) return the whole thing.
    For large docs, use the FTS snippet as an anchor and bias the window
    3/4 backward (anchor lands in the last quarter). This ensures table
    headers, definition labels, and year rows that precede the FTS match
    are captured — which is critical for regulatory standards tables where
    the year row appears before the footnote that the FTS snippet typically
    lands on.
    """
    if len(full) <= window:
        return full

    # Longest non-empty segment between ellipses from the FTS snippet
    # (snippets always start with "..." so split("...")[0] is empty)
    anchor_text = re.sub(r"</?b>", "", fts_snippet or "")
    segments = [s.strip() for s in anchor_text.split("...") if len(s.strip()) > 10]
    anchor = max(segments, key=len)[:80] if segments else ""

    pos = full.find(anchor) if len(anchor) > 10 else -1
    # 3/4 backward bias: anchor sits in the final quarter of the window
    start = max(0, pos - window * 3 // 4) if pos >= 0 else min(800, len(full) - window)
    return full[start : start + window]


async def answer_content_stream(
    query: str, db: Database
) -> AsyncGenerator[str, None]:
    """Yield answer tokens from Claude with FTS5-retrieved context."""
    fts_query = _expand_acronyms(query)
    docs = await db.fts_search(fts_query, limit=8)

    # Enrich snippets with the most relevant portion of each document
    for doc in docs[:5]:
        full = await db.get_full_content(doc["id"])
        if full:
            doc["snippet"] = _best_excerpt(full, doc.get("snippet", ""))

    context = _build_context(docs)

    user_message = f"Question: {query}\n\nRelevant document excerpts:\n{context}"

    client = get_client()
    async with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        async for text in stream.text_stream:
            yield text

    # Yield source citations at the end
    if docs:
        yield "\n\n---\n**Sources:**\n"
        for i, doc in enumerate(docs, 1):
            title = doc.get("title") or "Untitled"
            url = doc.get("url", "")
            yield f"[{i}] [{title}]({url})\n"


async def answer_content(query: str, db: Database) -> str:
    """Non-streaming version — collects the full response."""
    parts = []
    async for token in answer_content_stream(query, db):
        parts.append(token)
    return "".join(parts)
