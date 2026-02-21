# Development Notes — CARB Regulations Chatbot

A running log of findings, decisions, and known limitations from development sessions. Intended as a reference for future development.

---

## Architecture Overview

- **Crawler**: Playwright (headless Chromium) BFS-crawls Westlaw's JS-rendered SPA
- **Storage**: SQLite + FTS5 (BM25 + porter stemming), no external infrastructure
- **Routing**: Regex classifier → SQL graph traversal (relationship queries) or FTS + Claude RAG (content queries)
- **API**: FastAPI with SSE streaming, self-contained HTML frontend

---

## Bugs Found & Fixed

### Classifier Routing

| Query | Problem | Fix |
|---|---|---|
| "What regulations are related to zero emission buses?" | `r"\brelated\s+to\b"` too broad — matched content questions | Removed the pattern |
| "What section links to the clean fuels program?" | `r"\blinks?\s+(from\|to)\b"` matched "links to" — sent to SQL | Removed `to`, kept `from\|does\|in` |
| "What is the structure of the OBD requirements?" | `r"\bstructure\s+of\b"` too ambiguous | Removed the pattern |
| "What sits above Article 4.3?" | "sits above" not in classifier | Added `r"\bsits?\s+(above\|below\|under)\b"` |

### Subject Extraction (`graph_queries.py`)

| Query | Problem | Fix |
|---|---|---|
| "What is the parent of the heavy-duty engine section?" | Leading "the" caused title mismatch in DB lookup | Strip leading articles (`the/a/an`) from extracted subject |
| "Where does the clean fuels program fit?" | "fit" not in sit/belong/live list | Added `fit\|fall\|go` to pattern |
| "Where does X sit in the hierarchy?" | "in the hierarchy" appended to subject | Strip trailing `"in the <words>"` |

### LLM Fallback

- **Problem**: When `answer_relationship()` found no matching document, it returned an error string instead of falling back to Claude
- **Fix**: Return `None` from `answer_relationship()` when no document matched; caller in `routes.py` falls through to LLM content path

### FTS Content Extraction (`llm.py` — `_best_excerpt`)

This was the most complex fix. Several iterations:

1. **Original**: `full[:4000]` — always grabbed the Westlaw citation header (boilerplate at top of every doc), not the actual regulation text
2. **Anchor extraction bug**: FTS `snippet()` always starts with `"..."`, so the original `split("...")[0].strip()[:80]` always returned an empty string → window always started at position 0 → same citation header problem
3. **Fix**: Use `max(segments, key=len)` to pick the longest non-empty segment between `"..."` delimiters as the anchor
4. **Bias**: 1/4 backward bias (anchor in last quarter of 6K window) → missed table headers/definitions that precede the FTS match
5. **Fix**: 3/4 backward bias — anchor sits in the final quarter of the window, so headers above the match are captured
6. **Window size**: 6K was too small for some tables → increased to 8K
7. **Secondary search by year/section**: Caused regressions (relocated window to cross-reference citations instead of substantive content) → removed entirely

**Final implementation:**
```python
def _best_excerpt(full: str, fts_snippet: str, window: int = 8000) -> str:
    if len(full) <= window:
        return full
    anchor_text = re.sub(r"</?b>", "", fts_snippet or "")
    segments = [s.strip() for s in anchor_text.split("...") if len(s.strip()) > 10]
    anchor = max(segments, key=len)[:80] if segments else ""
    pos = full.find(anchor) if len(anchor) > 10 else -1
    # 3/4 backward bias: anchor sits in final quarter of window
    start = max(0, pos - window * 3 // 4) if pos >= 0 else min(800, len(full) - window)
    return full[start : start + window]
```

### Tree Sort Order (`database.py`)

- **Problem**: `ORDER BY title` sorts chapters alphabetically — "Chapter 10" appears right after "Chapter 1", "Chapter 9" appears last. User sees chapters out of order.
- **Fix**: `ORDER BY id` — crawler inserted chapters in BFS/document order, so `id` order = correct numeric sequence

---

## FTS Improvements

### Acronym Expansion
CARB documents store full spelled-out terms, but users query with acronyms. Added expansion before FTS query:

```python
_ACRONYMS = {
    "ZEB": "zero-emission bus", "ZEBs": "zero-emission buses",
    "ZEV": "zero-emission vehicle", "NOx": "oxides of nitrogen",
    "PM": "particulate matter", "OBD": "on-board diagnostic",
    "GHG": "greenhouse gas", "ICT": "innovative clean transit",
    "ACT": "advanced clean trucks", "HD": "heavy-duty",
    "LD": "light-duty", "MD": "medium-duty",
    "FTP": "federal test procedure", "BHP": "brake horsepower",
}
```

### Key Terms (Years Only)
Tried using year + section number + bigrams as secondary search anchors — caused regressions. Narrowed to years only, then removed secondary search entirely. Years are specific enough to pinpoint rows in multi-year standards tables; section numbers appear in cross-references throughout docs (wrong relocation risk).

---

## Known Limitations

### NOx 2007 Exact Value (`§ 1956.8`)
- **Section size**: ~113K chars
- **Problem**: Emission standards table column headers fall just outside the 8K extraction window when the FTS anchor lands far into the document. Claude sees the data row but not the headers that label it, leading to partial answers.
- **Root cause**: No fixed window size fully solves a 113K document — it's a fundamental chunking problem.
- **Proper fix**: **Document chunking at crawl time** — split large sections into smaller overlapping chunks (e.g. 2K chars with 500-char overlap). FTS would index each chunk separately and retrieve exactly the right piece. This is a significant architectural change to the crawler + schema.

### Context Window Size Tradeoffs
Currently `window=8000` chars per document, top 5 docs sent = ~40K chars of context per query.

- Going to 16K doubles API cost and latency
- Very large windows cause "lost in the middle" degradation — LLMs are less reliable at retrieving facts buried in long context
- Optimal range is probably 8K–16K; beyond that, document chunking is a better investment

### ~126 Stub/TOC Pages
Pages with 100–1K chars of content are Browse/TOC nodes — they just list child section names. Not a data quality issue; they're structural nodes. FTS may occasionally surface them as results, but they contribute little context.

---

## Potential Future Improvements

### High Impact
1. **Document chunking at crawl time** — Split large sections (>10K chars) into overlapping chunks. Store chunks as separate FTS rows linked back to their parent page. Would fix the NOx 2007 class of problems and improve precision across all large sections.
2. **Multi-turn conversation** — Currently each query is stateless. Passing conversation history to Claude would enable follow-up questions ("what about 2010?" after asking about 2007 standards).

### Medium Impact
3. **Hybrid search** — Combine FTS BM25 with semantic/vector search (embeddings). FTS is strong for exact regulatory terms; embeddings would help with paraphrased or conceptual queries.
4. **Re-ranking** — After FTS retrieval, use a cross-encoder or Claude to re-rank the top-8 results before selecting top-5 for context.
5. **Sidebar search/filter** — Allow filtering the tree by keyword rather than scrolling manually.

### Low Impact / Nice to Have
6. **Context window auto-sizing** — Dynamically adjust excerpt size based on how many docs were retrieved and total token budget.
7. **Citation linking** — Make source citations in Claude's answer clickable links that open the Westlaw page.
8. **Answer confidence signal** — If Claude says "not found in excerpts", surface that distinctly in the UI.
9. **Crawl refresh** — Scheduled re-crawl to pick up regulation updates (Westlaw updates CARB content periodically).

---

## Database Facts

- **Pages**: 903 total (810 section documents, ~93 Browse/TOC nodes)
- **Edges**: 1,194
- **Depth distribution**: 0 (Division) → 1 (Chapters) → 2 (Articles) → 3 (Sections) → 4 (Sub-sections)
- **Largest section**: `§ 1956.8` (~113K chars — exhaust emissions standards table)
- **FTS index**: FTS5 virtual table, auto-synced via SQLite triggers on every insert/update
- **Missing chapters**: 6 and 7 don't exist in CARB Division 3 (not a crawl gap — they're not in the regulations)
- **DB size**: ~15MB (committed to repo; no crawling needed for new users)
