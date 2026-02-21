"""FastAPI route handlers."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from src.chatbot.classifier import classify_query
from src.chatbot.graph_queries import answer_relationship
from src.chatbot.llm import answer_content_stream
from src.db.database import Database

logger = logging.getLogger(__name__)
router = APIRouter()


def get_db(request: Request) -> Database:
    return request.app.state.db


@router.get("/api/stats")
async def stats(request: Request):
    db = get_db(request)
    return await db.get_stats()


@router.get("/api/crawl-status")
async def crawl_status(request: Request):
    db = get_db(request)
    return await db.get_crawl_status()


@router.get("/api/tree")
async def tree(request: Request):
    db = get_db(request)
    return await db.get_tree(max_depth=4)


@router.get("/api/search")
async def search(request: Request, q: str = ""):
    db = get_db(request)
    if not q:
        return []
    results = await db.fts_search(q, limit=10)
    return results


@router.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "Empty query"}, status_code=400)

    db = get_db(request)
    query_type = classify_query(query)
    logger.info(f"Query [{query_type}]: {query[:80]}")

    if query_type == "relationship":
        # Synchronous graph answer — return as plain SSE
        answer = await answer_relationship(query, db)

        if answer is not None:
            async def relationship_stream():
                yield f"data: {json.dumps({'text': answer, 'done': False})}\n\n"
                yield f"data: {json.dumps({'text': '', 'done': True})}\n\n"

            return StreamingResponse(
                relationship_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        # No document matched — fall through to LLM content path
        logger.info("Relationship lookup found no document; falling back to content path")

    # Streaming LLM answer (content path, or fallback from failed relationship lookup)
    async def content_stream():
        try:
            async for token in answer_content_stream(query, db):
                payload = json.dumps({"text": token, "done": False})
                yield f"data: {payload}\n\n"
            yield f"data: {json.dumps({'text': '', 'done': True})}\n\n"
        except Exception as e:
            error_payload = json.dumps({"text": f"\n\n**Error:** {e}", "done": True})
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        content_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
