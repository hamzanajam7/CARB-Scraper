"""BFS crawler entry point."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from urllib.parse import urlparse, parse_qs

from src.crawler.browser import managed_browser, fetch_page
from src.crawler.extractor import extract_page
from src.db.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT_URL = (
    "https://shared-govt.westlaw.com/calregs/Browse/Home/California/"
    "CaliforniaCodeofRegulations?guid=I789FF3B05A1E11EC8227000D3A7C4BC3"
    "&originationContext=documenttoc&transitionType=Default"
    "&contextData=(sc.Default)"
)

MAX_PAGES = 500
MAX_DEPTH = 6
CRAWL_TIMEOUT_SEC = 1800  # 30 minutes
REQUEST_DELAY_SEC = 1.0


def _guid_from_url(url: str) -> str | None:
    qs = parse_qs(urlparse(url).query)
    guids = qs.get("guid", [])
    return guids[0] if guids else None


async def crawl(start_url: str = ROOT_URL, db: Database | None = None) -> None:
    if db is None:
        db = Database()
        await db.connect()
        owns_db = True
    else:
        owns_db = False

    queue: deque[tuple[str, int, int | None]] = deque()
    queue.append((start_url, 0, None))

    visited_guids: set[str] = set()
    visited_urls: set[str] = set()
    total = 0
    start_time = time.time()

    try:
        async with managed_browser() as context:
            while queue and total < MAX_PAGES:
                if time.time() - start_time > CRAWL_TIMEOUT_SEC:
                    logger.info("Crawl timeout reached")
                    break

                url, depth, parent_id = queue.popleft()

                # Dedup by GUID (Westlaw uses GUIDs as canonical IDs)
                guid = _guid_from_url(url)
                dedup_key = guid or url
                if dedup_key in visited_guids:
                    continue
                if url in visited_urls:
                    continue
                visited_guids.add(dedup_key)
                visited_urls.add(url)

                logger.info(f"[{total+1}] depth={depth} {url[:80]}")

                try:
                    page = await fetch_page(context, url)
                    extracted = await extract_page(page, url)
                    await page.close()
                except Exception as e:
                    logger.warning(f"  Failed: {e}")
                    await db.upsert_page(
                        url=url, guid=guid, title=None,
                        content="", depth=depth,
                        parent_id=parent_id, status="error"
                    )
                    await asyncio.sleep(REQUEST_DELAY_SEC)
                    continue

                status = "ok" if extracted.content else "empty"
                page_id = await db.upsert_page(
                    url=extracted.url,
                    guid=extracted.guid,
                    title=extracted.title,
                    content=extracted.content,
                    depth=depth,
                    parent_id=parent_id,
                    status=status,
                )
                total += 1
                logger.info(f"  → '{extracted.title[:60]}' | {len(extracted.links)} links")

                # Enqueue child links and record edges
                if depth < MAX_DEPTH:
                    for child_url, link_text in extracted.links:
                        child_guid = _guid_from_url(child_url)
                        child_dedup = child_guid or child_url
                        if child_dedup not in visited_guids and child_url not in visited_urls:
                            queue.append((child_url, depth + 1, page_id))

                        # Record edge (try to resolve to_id if already crawled)
                        child_id = (
                            await db.get_id_by_guid(child_guid)
                            if child_guid
                            else await db.get_id_by_url(child_url)
                        )
                        if child_id and child_id != page_id:
                            await db.insert_edge(page_id, child_id, link_text)

                await asyncio.sleep(REQUEST_DELAY_SEC)

    finally:
        stats = await db.get_stats()
        logger.info(
            f"\nCrawl complete: {stats['pages']} pages, "
            f"{stats['edges']} edges, max depth {stats['max_depth']}"
        )
        if owns_db:
            await db.close()


if __name__ == "__main__":
    asyncio.run(crawl())
