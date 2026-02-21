# CARB Scraper + Chatbot — Implementation Plan

## Context

This is an interview assignment to build a web crawler for California Air Resources Board (CARB) regulations on Westlaw and a local chatbot to query the scraped data. The site is publicly accessible (no auth) but JS-rendered, hence Playwright. The deliverable is a 15-minute demo showcasing design decisions.

**Starting URL**: `https://shared-govt.westlaw.com/calregs/Browse/Home/California/CaliforniaCodeofRegulations?guid=I789FF3B05A1E11EC8227000D3A7C4BC3&originationContext=documenttoc&transitionType=Default&contextData=(sc.Default)`

---

## Prerequisites (Do First)

### 1. Get Anthropic API Key
- Go to **console.anthropic.com** → sign up → API Keys → Create key
- You'll need a credit card (small cost, ~$0.01 for this project)
- Save the key as `ANTHROPIC_API_KEY=sk-ant-...` in a `.env` file

### 2. Install uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Project Structure

```
/Users/hamzanajam/Downloads/Proj/
├── pyproject.toml
├── .env                    # ANTHROPIC_API_KEY=...
├── .env.example
├── data/
│   └── carb.db             # Created at runtime
└── src/
    ├── crawler/
    │   ├── browser.py      # Playwright context manager
    │   ├── extractor.py    # CSS selector cascade → ExtractedPage
    │   └── crawler.py      # BFS orchestrator + entry point
    ├── db/
    │   ├── schema.py       # SQL string constants
    │   └── database.py     # Database class: all read/write methods
    ├── chatbot/
    │   ├── classifier.py   # classify_query() → 'relationship' | 'content'
    │   ├── graph_queries.py# SQL-based answers for hierarchy questions
    │   └── llm.py          # Claude RAG for content questions
    └── api/
        ├── main.py         # FastAPI app
        ├── routes.py       # /api/chat, /api/stats, /api/tree
        └── static/
            └── index.html  # Self-contained chat UI
```

---

## pyproject.toml Dependencies

```toml
[project]
name = "carb-scraper"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "playwright>=1.40",
    "anthropic>=0.34",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "python-dotenv>=1.0",
    "aiosqlite>=0.20",
]
```

---

## Database Schema (SQLite)

```sql
-- Core pages table
CREATE TABLE pages (
    id          INTEGER PRIMARY KEY,
    url         TEXT UNIQUE NOT NULL,
    guid        TEXT,
    title       TEXT,
    content     TEXT DEFAULT '',
    depth       INTEGER DEFAULT 0,
    parent_id   INTEGER REFERENCES pages(id),
    status      TEXT DEFAULT 'ok',   -- 'ok' | 'empty' | 'error'
    crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_pages_guid     ON pages(guid);
CREATE INDEX idx_pages_parent   ON pages(parent_id);

-- Full link graph (all discovered links, not just spanning tree)
CREATE TABLE edges (
    from_id     INTEGER REFERENCES pages(id),
    to_id       INTEGER REFERENCES pages(id),
    link_text   TEXT,
    PRIMARY KEY (from_id, to_id)
);

-- FTS5 virtual table for content search (porter stemmer)
CREATE VIRTUAL TABLE pages_fts USING fts5(
    title, content,
    content=pages, content_rowid=id,
    tokenize='porter ascii'
);

-- Triggers to keep FTS5 in sync
CREATE TRIGGER pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
    INSERT INTO pages_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
```

**Design rationale**: `parent_id` stores the BFS spanning tree (clean hierarchy for path queries). `edges` stores the full link graph (cross-references). Both together enable both tree traversal and graph analysis. FTS5 with porter stemmer handles legal morphological variants (emit/emission/emitting) without needing embeddings.

---

## Crawler Design

### Key Parameters (tuneable)
```python
MAX_PAGES = 500          # Hard cap
MAX_DEPTH = 6            # TOC depth (Title → Chapter → Article → Section)
CRAWL_TIMEOUT_SEC = 1800 # 30-minute wall-clock limit
REQUEST_DELAY_SEC = 1.0  # Polite rate limiting
DOMAIN_FILTER = "shared-govt.westlaw.com"
PATH_PREFIX = "/calregs/"
```

### BFS Flow (`crawler.py`)
1. Seed queue with `(root_url, depth=0, parent_id=None)`
2. Pop URL, skip if already visited (dedup by GUID if present, else URL)
3. Call `fetch_page(url)` — Playwright: `goto()` → `wait_for_load_state('networkidle')` → try expanding collapsed TOC nodes
4. Call `extract_page(page_html)` — CSS selector cascade for title + content
5. Upsert page into SQLite; record parent relationship
6. Extract all `<a>` tags; filter by domain + path prefix; enqueue unseen URLs with `depth+1`
7. Insert edges for all discovered links (not just followed ones)
8. `await asyncio.sleep(REQUEST_DELAY_SEC)`

### Content Extraction (`extractor.py`)
CSS selector cascade (try in order, use first non-empty result):
```
Title:   h1.document-title, .co_heading, h1, title
Content: .co_contentBlock, article, main, [role="main"], body
```
Strip: nav, header, footer, .co_breadcrumb, script, style

---

## Chatbot Architecture

### Query Classification (`classifier.py`)
Regex + keyword patterns — **no LLM needed for classification**:
```python
RELATIONSHIP_PATTERNS = [
    r"parent\s+of", r"child(ren)?\s+of", r"siblings?\s+of",
    r"path\s+(from|to)", r"hierarchy", r"where.*sit",
    r"under\s+which", r"belongs?\s+to"
]
```
Routes to `'relationship'` or `'content'`.

### Relationship Queries (`graph_queries.py`) — direct SQL
| Question | SQL |
|---|---|
| Parent of X | `SELECT p.* FROM pages p JOIN pages c ON c.parent_id=p.id WHERE c.title LIKE '%X%'` |
| Children of Y | `SELECT * FROM pages WHERE parent_id=(SELECT id FROM pages WHERE title LIKE '%Y%')` |
| Path from root to Z | Recursive CTE walking `parent_id` up to root |
| Siblings of X | `SELECT * FROM pages WHERE parent_id=(SELECT parent_id FROM pages WHERE title LIKE '%X%')` |

### Content Queries (`llm.py`) — FTS5 + Claude
1. FTS5 BM25 search: `SELECT * FROM pages_fts WHERE pages_fts MATCH ? ORDER BY rank LIMIT 5`
2. Assemble context: top-5 page titles + content snippets (truncated to 2000 chars each)
3. Send to Claude claude-sonnet-4-6:
   ```
   System: You are a regulatory assistant. Answer using ONLY the provided documents. Cite document titles.
   User: [query]
   Context: [retrieved docs]
   ```
4. Stream response back to UI via SSE

---

## Web UI

**FastAPI endpoints**:
- `GET /` → serve `index.html`
- `POST /api/chat` → JSON `{query: string}` → SSE stream of answer
- `GET /api/stats` → `{pages: int, edges: int, max_depth: int}`
- `GET /api/tree` → nested JSON hierarchy for sidebar

**Single HTML file** (`index.html`) — no build step, vanilla JS:
- Left sidebar: collapsible document tree (populated from `/api/tree`)
- Right panel: chat window (messages + citations)
- Header: crawl stats bar (pages indexed, edges, depth)
- Clicking a tree node pre-fills the chat with "Tell me about [title]"

---

## Implementation Order (2-hour build)

| Step | Task | Time |
|---|---|---|
| 1 | `uv init`, pyproject.toml, install deps + playwright | 5 min |
| 2 | `db/schema.py` + `db/database.py` (schema + upsert + FTS + graph queries) | 20 min |
| 3 | `crawler/browser.py` + `extractor.py` (fetch + extract) | 20 min |
| 4 | `crawler/crawler.py` (BFS loop) — run crawler, verify data | 20 min |
| 5 | `chatbot/classifier.py` + `graph_queries.py` (relationship answers) | 15 min |
| 6 | `chatbot/llm.py` (Claude RAG + streaming) | 15 min |
| 7 | `api/main.py` + `routes.py` + `index.html` (web UI) | 20 min |
| 8 | End-to-end test + polish | 5 min |

---

## Key Design Decisions (for demo explanation)

1. **SQLite + FTS5 over vector DB**: Zero infrastructure, built-in full-text search with BM25 + porter stemming handles legal terminology variants. Overkill-free for this scope.
2. **BFS over DFS**: Captures full breadth of hierarchy before depth — better dataset for a time-limited crawl.
3. **Two storage layers** (`parent_id` spanning tree + `edges` graph): Spanning tree gives clean path/hierarchy queries; full edge graph captures cross-references.
4. **Rule-based classifier before LLM**: Relationship questions have exact deterministic answers — routing them to SQL avoids hallucination and wastes no tokens.
5. **Playwright over requests+BS4**: JS-rendered SPA; static fetching returns an empty shell.
6. **Self-contained HTML**: No build step, no npm, fully portable. Interviewer can run it anywhere.

---

## Running the System

```bash
# 1. Setup
uv sync
uv run playwright install chromium

# 2. Add API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 3. Crawl (runs for up to 30 min or 500 pages)
uv run python -m src.crawler.crawler

# 4. Start chatbot
uv run python -m src.api.main
# → Open http://localhost:8000
```

---

## Verification

- [ ] Crawler populates `data/carb.db` with pages, edges, FTS index
- [ ] `/api/stats` returns non-zero page count
- [ ] `/api/tree` returns nested hierarchy
- [ ] Relationship query ("What is the parent of Title 13?") returns SQL-sourced answer
- [ ] Content query ("What does CARB say about emissions limits?") returns Claude answer with citations
- [ ] Path query ("Show path from root to section X") returns correct breadcrumb
