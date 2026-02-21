"""Database layer: all SQLite read/write operations."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from src.db.schema import ALL_DDL

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "carb.db"


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._migrate()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _migrate(self) -> None:
        for ddl in ALL_DDL:
            await self._db.execute(ddl)
        await self._db.commit()

    # ── Writes ────────────────────────────────────────────────────────────────

    async def upsert_page(
        self,
        url: str,
        guid: str | None,
        title: str | None,
        content: str,
        depth: int,
        parent_id: int | None,
        status: str = "ok",
    ) -> int:
        """Insert or update a page. Returns the row id."""
        async with self._db.execute(
            """
            INSERT INTO pages (url, guid, title, content, depth, parent_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                guid      = excluded.guid,
                title     = excluded.title,
                content   = excluded.content,
                depth     = excluded.depth,
                parent_id = COALESCE(pages.parent_id, excluded.parent_id),
                status    = excluded.status,
                crawled_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (url, guid, title, content, depth, parent_id, status),
        ) as cur:
            row = await cur.fetchone()
        await self._db.commit()
        return row[0]

    async def insert_edge(self, from_id: int, to_id: int, link_text: str) -> None:
        await self._db.execute(
            """
            INSERT OR IGNORE INTO edges (from_id, to_id, link_text)
            VALUES (?, ?, ?)
            """,
            (from_id, to_id, link_text),
        )
        await self._db.commit()

    # ── GUID / URL dedup lookup ────────────────────────────────────────────────

    async def get_id_by_guid(self, guid: str) -> int | None:
        async with self._db.execute(
            "SELECT id FROM pages WHERE guid = ?", (guid,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def get_id_by_url(self, url: str) -> int | None:
        async with self._db.execute(
            "SELECT id FROM pages WHERE url = ?", (url,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, int]:
        async with self._db.execute("SELECT COUNT(*) FROM pages") as cur:
            pages = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM edges") as cur:
            edges = (await cur.fetchone())[0]
        async with self._db.execute("SELECT MAX(depth) FROM pages") as cur:
            row = await cur.fetchone()
            max_depth = row[0] or 0
        return {"pages": pages, "edges": edges, "max_depth": max_depth}

    async def get_crawl_status(self) -> dict:
        """Detailed crawl progress for the status panel."""
        async with self._db.execute("SELECT COUNT(*) FROM pages") as cur:
            total = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM edges") as cur:
            edges = (await cur.fetchone())[0]
        async with self._db.execute(
            "SELECT depth, COUNT(*) as cnt FROM pages GROUP BY depth ORDER BY depth"
        ) as cur:
            by_depth = [{"depth": r[0], "count": r[1]} for r in await cur.fetchall()]
        async with self._db.execute(
            "SELECT COUNT(*) FROM pages WHERE status = 'error'"
        ) as cur:
            errors = (await cur.fetchone())[0]
        async with self._db.execute(
            """SELECT title, url, depth, crawled_at FROM pages
               ORDER BY crawled_at DESC LIMIT 10"""
        ) as cur:
            recent = [dict(r) for r in await cur.fetchall()]
        return {
            "total_pages": total,
            "total_edges": edges,
            "by_depth": by_depth,
            "errors": errors,
            "recent": recent,
        }

    # ── Hierarchy (graph queries) ─────────────────────────────────────────────

    async def get_page_by_id(self, page_id: int) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM pages WHERE id = ?", (page_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def find_pages_by_title(self, keyword: str, limit: int = 5) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM pages WHERE title LIKE ? LIMIT ?",
            (f"%{keyword}%", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_parent(self, page_id: int) -> dict | None:
        async with self._db.execute(
            """
            SELECT p.* FROM pages p
            JOIN pages c ON c.parent_id = p.id
            WHERE c.id = ?
            """,
            (page_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_children(self, page_id: int) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM pages WHERE parent_id = ? ORDER BY title",
            (page_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_siblings(self, page_id: int) -> list[dict]:
        async with self._db.execute(
            """
            SELECT * FROM pages
            WHERE parent_id = (SELECT parent_id FROM pages WHERE id = ?)
              AND id != ?
            ORDER BY title
            """,
            (page_id, page_id),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_path_to_root(self, page_id: int) -> list[dict]:
        """Return path from root down to page_id using recursive CTE."""
        async with self._db.execute(
            """
            WITH RECURSIVE path(id, title, url, parent_id, depth) AS (
                SELECT id, title, url, parent_id, depth
                FROM pages WHERE id = ?
                UNION ALL
                SELECT p.id, p.title, p.url, p.parent_id, p.depth
                FROM pages p
                JOIN path ON path.parent_id = p.id
            )
            SELECT * FROM path ORDER BY depth ASC
            """,
            (page_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_outgoing_links(self, page_id: int) -> list[dict]:
        async with self._db.execute(
            """
            SELECT p.id, p.title, p.url, e.link_text
            FROM edges e
            JOIN pages p ON p.id = e.to_id
            WHERE e.from_id = ?
            ORDER BY p.title
            """,
            (page_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ── Full-text search ──────────────────────────────────────────────────────

    async def fts_search(self, query: str, limit: int = 5) -> list[dict]:
        """BM25-ranked full-text search via FTS5."""
        import re as _re
        _STOP = {
            "what", "does", "do", "did", "is", "are", "was", "were", "the",
            "a", "an", "and", "or", "in", "on", "at", "to", "of", "for",
            "with", "by", "from", "that", "this", "it", "be", "have", "has",
            "say", "says", "about", "tell", "me", "us", "how", "why", "when",
            "where", "which", "who", "can", "carb",
        }
        # Strip punctuation and FTS5-special chars
        cleaned = _re.sub(r"[^\w\s]", " ", query)
        words = [w for w in cleaned.lower().split() if w not in _STOP and len(w) > 2]
        if not words:
            words = cleaned.split()

        # Use OR for natural-language recall; BM25 ranking handles relevance
        or_query = " OR ".join(words)
        and_query = " ".join(words)
        try:
            results = await self._fts_raw(or_query, limit)
            if not results:
                results = await self._fts_raw(and_query, limit)
        except Exception:
            try:
                results = await self._fts_raw(and_query, limit)
            except Exception:
                results = await self.find_pages_by_title(query, limit)
        return results

    async def _fts_raw(self, query: str, limit: int) -> list[dict]:
        async with self._db.execute(
            """
            SELECT p.id, p.title, p.url, p.depth,
                   snippet(pages_fts, 1, '<b>', '</b>', '...', 32) AS snippet
            FROM pages_fts
            JOIN pages p ON p.id = pages_fts.rowid
            WHERE pages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_full_content(self, page_id: int) -> str:
        async with self._db.execute(
            "SELECT content FROM pages WHERE id = ?", (page_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else ""

    # ── Tree for UI ───────────────────────────────────────────────────────────

    async def get_tree(self, max_depth: int = 4) -> list[dict]:
        """Return root nodes with nested children up to max_depth."""
        async with self._db.execute(
            "SELECT id, title, url, depth FROM pages WHERE parent_id IS NULL ORDER BY title",
        ) as cur:
            roots = [dict(r) for r in await cur.fetchall()]

        for root in roots:
            root["children"] = await self._get_children_recursive(root["id"], 1, max_depth)
        return roots

    async def _get_children_recursive(
        self, parent_id: int, current_depth: int, max_depth: int
    ) -> list[dict]:
        if current_depth > max_depth:
            return []
        async with self._db.execute(
            "SELECT id, title, url, depth FROM pages WHERE parent_id = ? ORDER BY title",
            (parent_id,),
        ) as cur:
            children = [dict(r) for r in await cur.fetchall()]
        for child in children:
            child["children"] = await self._get_children_recursive(
                child["id"], current_depth + 1, max_depth
            )
        return children
