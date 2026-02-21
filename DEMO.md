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

## Challenges Encountered (Good to Mention in Demo)

These are real problems that came up during development — mentioning them shows honest engineering thinking and problem-solving ability.

---

### 1. Crawler Scope Drift — Going Way Outside CARB

**What happened:** The first crawl run went completely off-track — it started picking up Business Regulations, Tourism pages, and other unrelated California agencies. The crawler was following breadcrumb navigation links at the top of every Westlaw page that pointed back up to the full California Code of Regulations TOC, which then linked out to every other division and agency in the state.

**Fix 1:** Added a filter to only follow links that carry a `?guid=` parameter. Navigation and breadcrumb links don't have GUIDs — only actual content pages do. This cut out most of the drift.

**Fix 2:** A second drift remained — "Title 13. Motor Vehicles" had a GUID, so it passed the first filter. Following it led into Division 1 (DMV) and Division 2 (CHP). Added a second filter to skip any link whose text matches `Title N.` — these are always upward-hierarchy links that take you out of scope.

> "This taught me that domain filtering alone isn't enough when the site uses the same domain for everything. You need content-level filters — in this case, GUID presence and link text patterns."

---

### 2. Breadcrumb Text Leaking Into Content

**What happened:** Every single page's scraped content started with `"Home Title 13. Motor Vehicles Division 3. Air Resources Board Chapter 1..."` — the Westlaw breadcrumb navigation injected at the top of every page was being captured as part of the document content. This polluted the FTS index and made content answers noisy.

**Fix:** Added a regex stripping step in the extractor. For pages with regulation text, it finds the first `§ N` section marker and slices content from there. For TOC pages with no `§`, it strips just the opening `Home ...` line. Also ran a one-time cleanup script on the already-crawled 93 pages to fix existing records and rebuilt the FTS5 index.

> "This is a good example of why content extraction always needs domain-specific tuning — generic CSS selectors get you 80% of the way but the last 20% needs site-specific knowledge."

---

### 3. SQLite Disk I/O Error on Restart

**What happened:** When restarting the crawler, SQLite threw a disk I/O error on startup. The cause was deleting `carb.db` while the FastAPI server still had the file open — SQLite's WAL mode leaves behind `carb.db-wal` and `carb.db-shm` shared memory files, which became orphaned and corrupted the next open attempt.

**Fix:** Always stop the server before deleting the database, and delete all three files together (`carb.db`, `carb.db-wal`, `carb.db-shm`).

> "SQLite WAL mode is great for concurrent reads during a live crawl, but you have to respect the file locking — it's not safe to delete the DB out from under an open connection."

---

### 4. FTS5 Search Failing on Natural Language Queries

**What happened:** Asking "What does CARB say about vehicle emissions limits?" returned no results. FTS5 was treating the full natural language sentence as an AND query — requiring all words including "what", "does", "say", "about" to appear in the same document. The trailing `?` also broke FTS5's query parser entirely.

**Fix:** Added a preprocessing step before querying FTS5 — strip punctuation, remove common stop words (what, does, say, about, etc.), then use OR logic between the remaining keywords so BM25 can rank documents by relevance rather than requiring every word to match.

> "FTS5 is powerful but it's a query language, not a natural language processor. You need to sanitise user input before handing it to the engine."

---

### 5. Path Query Extracting the Wrong Subject

**What happened:** "Show path from root to Chapter 1" returned nothing. The subject extractor regex was capturing `"root to Chapter 1"` as the search term instead of just `"Chapter 1"`, so the database lookup found no match.

**Fix:** Added a specific regex pattern for the `path from X to Y` form that captures only the destination Y, rather than the generic `path from (.+)` that grabbed everything after "from".

> "A small regex mistake with big user-facing impact — a good reminder to test with the exact phrasing from the spec, not just obvious cases."

---

### 6. Server Showing Stale Page Count

**What happened:** After the crawl finished at 93 pages, the API was still reporting 60 pages. The FastAPI server had been started mid-crawl — while SQLite WAL mode allows concurrent writes during the crawl, the server process was reading an older snapshot.

**Fix:** Simply restarting the server after the crawl completed picked up the full 93 pages. In a production system this wouldn't be an issue since the crawl and server wouldn't run simultaneously against the same DB connection.

---

## If Something Goes Wrong

| Problem | Recovery |
|---|---|
| Content query returns thin answer | "The source pages are TOC-style — they list sections. The architecture would pull full text if the pages had it." |
| Relationship query finds wrong match | "There are multiple documents with similar names — the classifier picks the first FTS match. In production I'd add disambiguation." |
| Server is down | Run `uv run python -m src.api.main` from the project folder |
| Claude API slow | "Streaming response via SSE — latency is on the API side. Relationship queries are instant since they're pure SQL." |
