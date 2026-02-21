# Demo Script — CARB Scraper + Chatbot

## Timing Overview

| Section | Time |
|---|---|
| Opening + what you built | 1 min |
| Architecture walkthrough | 2 min |
| Live demo — crawler data | 2 min |
| Live demo — chatbot | 6 min |
| Design decisions Q&A | 3 min |
| Wrap up / limitations | 1 min |

---

## 1. Opening (1 min)

> "I built two things: a crawler that ingests all CARB regulation pages from the Westlaw entry point, and a local chatbot that lets you query that data — both for content and for document relationships.
>
> The site is a JavaScript-rendered single-page app, so I used Playwright to render it in a real browser. The data is stored in SQLite. The chatbot uses Claude as the LLM for content questions, and direct SQL for hierarchy questions.
>
> Let me show you what it does, then I'll walk through the design decisions."

---

## 2. Architecture Walkthrough (2 min)

Point to the file structure in your editor or the README:

```
crawler/   → Playwright BFS, extracts title + content + links
db/        → SQLite: pages table, edges table, FTS5 virtual table
chatbot/   → classifier routes to SQL (relationships) or Claude (content)
api/       → FastAPI serves the UI and streams answers
```

> "The key structural decision was storing two things: a `parent_id` spanning tree for clean hierarchy queries, and a separate `edges` table for the full link graph. The spanning tree gives you fast path-to-root and children queries. The edges table captures cross-references between documents.
>
> For search, I used SQLite's FTS5 with a porter stemmer — so queries for 'emission' match 'emissions', 'emitting', 'emitted' without needing a vector database."

---

## 3. Live Demo — Show the Data (2 min)

Open **DB Browser for SQLite** (or terminal with `sqlite3`):

```sql
SELECT COUNT(*) FROM pages;          -- 93 pages
SELECT COUNT(*) FROM edges;          -- 165 links
SELECT title, depth FROM pages ORDER BY depth, title LIMIT 15;
```

> "The crawler found 93 pages across 4 depth levels — Division 3 at the root, then Chapters, Articles, and Subarticles. 165 edges total, including cross-references between documents. Everything is scoped to Division 3 Air Resources Board — the crawler filters out links that go up to parent Title pages, which would drag in unrelated divisions like DMV and CHP."

Show one content row:

```sql
SELECT title, substr(content, 1, 300) FROM pages WHERE title LIKE '%Chapter 5%';
```

> "Content starts from the first § marker on each page — I strip the breadcrumb header that Westlaw injects at the top of every page."

---

## 4. Live Demo — Chatbot (6 min)

Open **http://localhost:8000**

Point out the UI briefly:

> "Left sidebar has the document tree and crawl status. The main area is the chat — multiple conversations, dark and light mode."

### Relationship Queries — show all 4 types (~3 min)

Click each example button or type them directly.

**Children:**

> "Let's start with hierarchy. What are the children of Division 3?"

*Shows 24 chapters.* Say:

> "This goes straight to SQL — no LLM involved, so it's instant and deterministic. No hallucination risk."

**Parent:**

> "What is the parent of Chapter 1?"

*Shows Division 3.*

**Siblings:**

> "What are the siblings of Chapter 1?"

*Shows the other 23 chapters at the same level.*

**Path:**

> "Show path from root to Chapter 1."

*Shows: Division 3 → Chapter 1.*

> "All four relationship types from the spec — parent, children, siblings, path — are answered with a recursive SQL query, not Claude. The classifier routes the question based on keywords before even calling the API."

---

### Content Queries (~3 min)

**Query 1:**

> "Now a content question. What are the requirements for zero emission vehicles?"

*Wait for streaming response. Say while it streams:*

> "This goes through FTS5 full-text search first — finds the top 5 most relevant documents by BM25 score — then sends those as context to Claude. You can see it's streaming the response token by token via SSE."

*When done:*

> "Notice it cites the source documents at the bottom. It found Article 4.3 for transit buses, Article 3.5 for heavy-duty ZEV sales requirements, and so on."

**Query 2:**

> "What does CARB regulate for heavy-duty diesel vehicles?"

*While it streams:*

> "The FTS5 index uses a porter stemmer, so 'diesel' matches across morphological variants. This is why I chose FTS5 over a simple LIKE search."

**New chat:**

> "I can also open a new conversation — these are independent sessions."

Click `+`, open a new chat, ask:

> "Where does Chapter 5 sit in the hierarchy?"

*Shows the path. Flip back to the previous chat — history is preserved.*

---

## 5. Design Decisions (3 min)

### "Why SQLite instead of a vector database?"

> "For this scope, FTS5 gives me BM25 ranking with zero infrastructure. Legal text has strong morphological patterns — emission/emitting/emitted — which porter stemming handles directly. A vector DB would add meaningful complexity without a clear benefit at 93 documents."

### "Why two storage layers — parent_id and edges?"

> "The `parent_id` spanning tree is the BFS discovery tree — it gives me clean, unambiguous path-to-root and children queries. The `edges` table is the full link graph — it captures cross-references where one regulation links to another outside its direct lineage. Both together let me answer hierarchy questions and graph questions."

### "Why BFS over DFS?"

> "BFS captures the full breadth of the hierarchy before going deep. If I had a hard time limit and had to stop early, BFS gives me a better representative dataset — all Chapters before any Articles — rather than one deep branch of the tree."

### "Why Playwright instead of requests?"

> "The site is a JavaScript SPA. A static HTTP request returns an empty HTML shell — the content is rendered client-side. Playwright runs a real Chromium instance and waits for the network to go idle before extracting."

### "Why a rule-based classifier instead of asking Claude to classify?"

> "Relationship queries have exact, deterministic answers in the database. Routing them to an LLM adds latency, cost, and hallucination risk for questions that don't need intelligence — they just need a SQL join. The classifier uses regex patterns, runs in microseconds, and is 100% reliable."

### "Why scope only to Division 3?"

> "The starting URL is the Division 3 Air Resources Board entry point. Without scoping, the crawler would follow breadcrumb links up to Title 13 Motor Vehicles, then into Division 1 (DMV) and Division 2 (CHP) — thousands of unrelated pages. I filter to only follow links that have a GUID parameter and skip any link whose text matches 'Title N.' which are the upward navigation links."

---

## 6. Wrap Up / Limitations (1 min)

> "A couple of honest limitations worth noting:
>
> First, the Westlaw TOC pages list section numbers and titles rather than the full paragraph text of each regulation. So content answers are strong for navigation and overview, but don't contain the verbatim regulatory text.
>
> Second, the crawler found 93 pages — that's all the GUID-linked content reachable from the Division 3 entry point. There may be more content behind dynamically loaded sections.
>
> If I had more time, I'd add full-text extraction by following individual section links, and consider a hybrid FTS5 + embedding approach for semantic search."

---

## Things to Have Open During the Demo

1. **http://localhost:8000** — the chatbot (primary screen)
2. **DB Browser for SQLite** with `data/carb.db` open — to show raw data
3. **Terminal** — in case you want to run a live SQL query
4. **GitHub** — https://github.com/hamzanajam7/CARB-Scraper (to show code structure if asked)

---

## If Something Goes Wrong

| Problem | Recovery |
|---|---|
| Content query returns thin answer | "The source pages are TOC-style — they list sections. The architecture would pull full text if the pages had it." |
| Relationship query finds wrong match | "There are multiple documents with similar names — the classifier picks the first FTS match. In production I'd add disambiguation." |
| Server is down | Run `uv run python -m src.api.main` from the project folder |
| Claude API slow | "Streaming response via SSE — latency is on the API side. Relationship queries are instant since they're pure SQL." |
