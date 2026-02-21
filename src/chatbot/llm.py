"""Claude RAG for content questions — streams answer tokens."""

from __future__ import annotations

import os
from typing import AsyncGenerator

import anthropic

from src.db.database import Database

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


async def answer_content_stream(
    query: str, db: Database
) -> AsyncGenerator[str, None]:
    """Yield answer tokens from Claude with FTS5-retrieved context."""
    docs = await db.fts_search(query, limit=5)

    # Enrich snippets with fuller content for top 2 results
    for doc in docs[:2]:
        full = await db.get_full_content(doc["id"])
        if full:
            doc["snippet"] = full[:2000]

    context = _build_context(docs)

    user_message = f"Question: {query}\n\nRelevant document excerpts:\n{context}"

    client = get_client()
    async with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
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
