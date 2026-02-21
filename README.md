# CARB Regulations Scraper + Chatbot

A web crawler and local chatbot for California Air Resources Board (CARB) regulations sourced from Westlaw.

## What it does

1. **Crawler** — Crawls all regulation pages reachable from the CARB Westlaw entry point using Playwright (handles JS-rendered content). Stores titles, content, links, and parent-child relationships in SQLite.

2. **Chatbot** — Web-based chat interface that answers two types of questions:
   - **Content questions** — "What does CARB say about emissions limits?" → FTS5 search + Claude LLM synthesis
   - **Relationship questions** — "What are the children of Chapter 1?", "Show path from root to Title 13" → direct SQL graph traversal (no LLM needed)

## Quick Start

### 1. Prerequisites

```bash
# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Install Playwright browser
uv run playwright install chromium
```

### 2. API Key

Copy `.env.example` to `.env` and add your Anthropic API key:

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
# Get a key at: console.anthropic.com
```

### 3. Run the Crawler

```bash
uv run python -m src.crawler.crawler
```

Crawls up to 500 pages over ~30 minutes. You can stop it early with Ctrl+C — data is saved as it goes.

> **Note:** If `data/carb.db` is already included in this repo, you can skip this step and use the pre-built database.

### 4. Start the Chatbot

```bash
uv run python -m src.api.main
```

Open **http://localhost:8000** in your browser.

## Architecture

```
src/
├── crawler/
│   ├── browser.py      # Playwright browser context
│   ├── extractor.py    # CSS selector cascade for content extraction
│   └── crawler.py      # BFS orchestrator (entry point)
├── db/
│   ├── schema.py       # SQLite schema (pages, edges, FTS5 virtual table)
│   └── database.py     # All database operations
├── chatbot/
│   ├── classifier.py   # Routes query to 'relationship' or 'content' handler
│   ├── graph_queries.py # SQL-based hierarchy answers
│   └── llm.py          # Claude RAG for content questions
└── api/
    ├── main.py         # FastAPI app
    ├── routes.py       # /api/chat, /api/stats, /api/tree, /api/crawl-status
    └── static/
        └── index.html  # Self-contained chat UI
```

## Design Decisions

| Decision | Rationale |
|---|---|
| SQLite + FTS5 | Zero infrastructure, built-in BM25 ranking with porter stemming for legal text variants |
| BFS traversal | Captures full breadth of hierarchy before depth — better dataset for time-limited crawl |
| `parent_id` + `edges` table | Spanning tree for clean path queries; full edge graph for cross-references |
| Rule-based query classifier | Relationship queries have exact deterministic answers — routing to SQL avoids LLM hallucination |
| Playwright | Site is a JS-rendered SPA; static fetching returns empty shell |
| Self-contained HTML | No build step, no npm — fully portable, runs anywhere |

## Example Queries

**Relationship:**
- "What are the children of Division 3?"
- "What is the parent of Chapter 1?"
- "Show path from root to Chapter 8"
- "What are the siblings of Title 13?"

**Content:**
- "What does CARB say about vehicle emissions limits?"
- "What are the requirements for zero emission vehicles?"
- "What regulations cover heavy-duty diesel smoke testing?"
