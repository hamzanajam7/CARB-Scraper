# CARB Regulations Scraper + Chatbot

A web crawler and local chatbot for California Air Resources Board (CARB) regulations sourced from Westlaw's California Code of Regulations browser.

---

## Quick Start (3 steps)

### 1. Install dependencies

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync
uv run playwright install chromium
```

### 2. Set your API key

```bash
cp .env.example .env
# Open .env and set: ANTHROPIC_API_KEY=sk-ant-...
# Get a key at: https://console.anthropic.com
```

### 3. Start the app

```bash
uv run python -m src.api.main
```

Open **http://localhost:8000**

> The database (`data/carb.db`) is pre-built and included — 903 pages of CARB Division 3 regulations are ready to query immediately. No crawling needed.

**To re-crawl or update the database:**
```bash
uv run python -m src.crawler.crawler
```
The crawler saves progress as it runs — Ctrl+C and restart safely. Already-visited pages are skipped via GUID deduplication (~40 min for a full crawl).

---

## What It Does

### Crawler

Starts from the CARB Division 3 entry point on Westlaw and BFS-crawls the full regulation tree:

```
Division 3 (depth 0)
  └── Chapter 1 (depth 1)
        └── Article 2 (depth 2)
              └── § 1950. Requirements (depth 3)
                    └── Subarticle (depth 4)
```

Westlaw is a JavaScript-rendered SPA, so the crawler uses Playwright (headless Chromium). Each page is fully rendered before content is extracted.

**What gets stored per page:**
- `title` — e.g. `§ 1956.8. Exhaust Emissions Standards`
- `content` — full regulation text (up to 850,000 chars for large sections)
- `url` + `guid` — Westlaw's canonical document identifier
- `depth` + `parent_id` — position in hierarchy
- `edges` — every link between pages (stored separately for graph traversal)

The database also maintains an **FTS5 full-text search index** (BM25 + porter stemming) that updates automatically via SQLite triggers on every insert/update.

**Final crawl result:** 903 pages, 810 section documents, 1,194 edges, 0 errors.

### Chatbot

Every user message is classified and routed one of two ways:

#### Path A — Relationship queries → pure SQL

Triggered by keywords: `children of`, `parent of`, `siblings of`, `path to/from`, `hierarchy of`, `where does X sit`, `links from`, etc.

Flow:
1. **Classifier** (`classifier.py`) — regex matches relationship intent
2. **Subject extraction** (`graph_queries.py`) — regex pulls the document name from the query (e.g. `"children of Article 2"` → `"Article 2"`)
3. **SQL lookup** — `SELECT * FROM pages WHERE title LIKE '%Article 2%'`
4. **Graph query** — depending on intent:
   - Children: `SELECT * FROM pages WHERE parent_id = ?`
   - Parent: `JOIN pages ON parent_id`
   - Siblings: `WHERE parent_id = (SELECT parent_id FROM pages WHERE id = ?)`
   - Path to root: recursive CTE walking `parent_id` chain
   - Outgoing links: `JOIN edges ON from_id = ?`
5. **Response** — formatted markdown list, no LLM involved

This is intentional: relationship queries have exact deterministic answers. Routing them through an LLM would risk hallucination.

#### Path B — Content queries → FTS search + Claude

Everything that isn't a relationship query.

Flow:
1. **Classifier** — no relationship keywords detected → content path
2. **FTS5 search** (`database.py`) — tokenises the query, removes stopwords, runs BM25-ranked search across all 903 pages:
   ```sql
   SELECT ... FROM pages_fts WHERE pages_fts MATCH ? ORDER BY rank LIMIT 8
   ```
3. **Content enrichment** — top 5 results get their full content fetched (up to 4,000 chars each) to replace the snippet
4. **Claude** (`claude-sonnet-4-6`) — receives the query + document excerpts as context, streams a grounded answer citing sources
5. **Sources** — appended at the end with titles and Westlaw URLs

Claude is instructed to answer only from the provided excerpts and clearly state if the answer isn't found — preventing hallucination on regulatory specifics.

---

## Architecture

```
src/
├── crawler/
│   ├── browser.py       # Playwright context: headless Chromium, JS enabled, TOC expansion
│   ├── extractor.py     # Link + content extraction from rendered HTML
│   └── crawler.py       # BFS queue, GUID deduplication, DB upserts
├── db/
│   ├── schema.py        # DDL: pages, edges, FTS5 virtual table, update triggers
│   └── database.py      # All reads/writes: upsert, FTS search, graph traversal
├── chatbot/
│   ├── classifier.py    # Regex router: 'relationship' vs 'content'
│   ├── graph_queries.py # SQL-based hierarchy answers (no LLM)
│   └── llm.py           # FTS retrieval + Claude streaming RAG
└── api/
    ├── main.py          # FastAPI app, DB lifespan
    ├── routes.py        # POST /api/chat (SSE), GET /api/stats, /api/tree
    └── static/
        └── index.html   # Self-contained chat UI (no build step)
```

**Key schema:**
```sql
pages  (id, url, guid, title, content, depth, parent_id, status, crawled_at)
edges  (from_id, to_id, link_text)
pages_fts  -- FTS5 virtual table, auto-synced via triggers
```

---

## Design Decisions

| Decision | Rationale |
|---|---|
| SQLite + FTS5 | Zero infrastructure. Built-in BM25 ranking with porter stemming handles legal text variants (e.g. "emission" matches "emissions") |
| BFS crawl | Captures full breadth before depth — ensures all chapters/articles are indexed even if depth limit is hit |
| `parent_id` + `edges` | `parent_id` gives a clean spanning tree for path/hierarchy queries; `edges` captures all cross-references |
| Regex classifier | Relationship queries have exact answers — SQL is faster, cheaper, and hallucination-free vs LLM |
| Playwright | Westlaw is a JS SPA — static HTTP returns an empty shell. Full render required |
| Link extraction before stripping | Navigation panels must be read before removing them, otherwise section links disappear |
| Document URL format | Westlaw section pages use `/calregs/Document/GUID` (path-based GUID), not `?guid=GUID` (query-based). Both formats handled |
| Self-contained HTML | No npm, no build step — fully portable |

---

## Example Queries

**Relationship (SQL only, instant):**
- `What are the children of Chapter 1?`
- `What is the parent of § 1950?`
- `Show the path from root to Article 6`
- `What are the siblings of Chapter 3?`

**Content (FTS + Claude, streamed):**
- `What are the exhaust emission standards for heavy-duty engines?`
- `What does § 1956.8 say about zero-emission powertrains?`
- `What are the OBD requirements for 2010 and subsequent model years?`
- `What are the fuel sulfur requirements for diesel?`
