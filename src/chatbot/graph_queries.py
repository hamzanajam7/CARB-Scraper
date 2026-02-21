"""Answer relationship/hierarchy questions directly via SQL graph traversal."""

from __future__ import annotations

import re

from src.db.database import Database


def _fmt_page(p: dict, indent: str = "") -> str:
    title = p.get("title") or "Untitled"
    url = p.get("url", "")
    return f"{indent}• **{title}**\n{indent}  {url}"


def _extract_subject(query: str) -> str:
    """Pull the document name / keyword from a relationship query."""
    patterns = [
        r"(?:parent|children?|siblings?)\s+of\s+['\"]?(.+?)['\"]?\??$",
        r"(?:path\s+(?:from|to))\s+['\"]?(.+?)['\"]?\??$",
        r"(?:hierarchy|structure)\s+of\s+['\"]?(.+?)['\"]?\??$",
        r"(?:where\s+(?:does|is))\s+['\"]?(.+?)['\"]?\s+(?:sit|belong|live)",
        r"(?:under\s+which).*?['\"]?(.+?)['\"]?\??$",
        r"links?\s+(?:from|to)\s+['\"]?(.+?)['\"]?\??$",
    ]
    for pat in patterns:
        m = re.search(pat, query, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # Fallback: last few words
    words = query.split()
    return " ".join(words[-3:]) if len(words) >= 3 else query


async def answer_relationship(query: str, db: Database) -> str:
    subject = _extract_subject(query)
    pages = await db.find_pages_by_title(subject, limit=3)

    if not pages:
        return (
            f"I couldn't find any document matching **{subject}** in the database. "
            "Try a different keyword or check that the crawler has indexed that section."
        )

    # Use the best match (first result)
    page = pages[0]
    pid = page["id"]
    q = query.lower()

    lines: list[str] = []

    # Determine what kind of relationship is asked
    if re.search(r"\bparent\b", q):
        parent = await db.get_parent(pid)
        if parent:
            lines.append(f"**Parent of '{page['title']}':**")
            lines.append(_fmt_page(parent))
        else:
            lines.append(f"**'{page['title']}'** has no parent — it is a root node.")

    elif re.search(r"\bchildren?\b|\bchild\b", q):
        children = await db.get_children(pid)
        if children:
            lines.append(f"**Children of '{page['title']}' ({len(children)} total):**")
            for c in children[:20]:
                lines.append(_fmt_page(c, "  "))
            if len(children) > 20:
                lines.append(f"  _(and {len(children) - 20} more…)_")
        else:
            lines.append(f"**'{page['title']}'** has no children indexed yet.")

    elif re.search(r"\bsiblings?\b", q):
        siblings = await db.get_siblings(pid)
        if siblings:
            lines.append(f"**Siblings of '{page['title']}' ({len(siblings)} total):**")
            for s in siblings[:15]:
                lines.append(_fmt_page(s, "  "))
        else:
            lines.append(f"No siblings found for **'{page['title']}'**.")

    elif re.search(r"\bpath\b|\bhierarchy\b|\bwhere\b|\bsit\b|\bbelong\b", q):
        path = await db.get_path_to_root(pid)
        if path:
            lines.append(f"**Path from root to '{page['title']}':**")
            for i, node in enumerate(path):
                lines.append(f"{'  ' * i}{'└─ ' if i else ''}**{node['title'] or 'Untitled'}**")
        else:
            lines.append(f"Could not determine path for **'{page['title']}'**.")

    elif re.search(r"\blinks?\b", q):
        outgoing = await db.get_outgoing_links(pid)
        if outgoing:
            lines.append(f"**Links from '{page['title']}' ({len(outgoing)} total):**")
            for link in outgoing[:15]:
                label = link.get("link_text") or link.get("title") or link.get("url")
                lines.append(f"  • {label}")
        else:
            lines.append(f"No outgoing links indexed for **'{page['title']}'**.")

    else:
        # Generic: show hierarchy context
        parent = await db.get_parent(pid)
        children = await db.get_children(pid)
        lines.append(f"**'{page['title']}'** — hierarchy context:")
        if parent:
            lines.append(f"  Parent: **{parent['title']}**")
        lines.append(f"  Children: {len(children)}")
        lines.append(f"  Depth: {page.get('depth', '?')}")
        lines.append(f"  URL: {page['url']}")

    if len(pages) > 1:
        lines.append(
            f"\n_Note: Found {len(pages)} documents matching '{subject}'. "
            f"Showing results for the first match: '{page['title']}'._"
        )

    return "\n".join(lines)
