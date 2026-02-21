"""Classify a user query as 'relationship' or 'content'."""

from __future__ import annotations

import re

# Patterns that indicate the user wants to traverse the document hierarchy
_RELATIONSHIP_PATTERNS = [
    r"\bparent\s+of\b",
    r"\bchildren?\s+of\b",
    r"\bchild\s+of\b",
    r"\bsiblings?\s+of\b",
    r"\bpath\s+(from|to)\b",
    r"\bhierarchy\b",
    r"\bwhere\s+does\b",
    r"\bwhere\s+is\b",
    r"\bunder\s+which\b",
    r"\bbelongs?\s+to\b",
    r"\bstructure\s+of\b",
    r"\bshow\s+the\s+path\b",
    r"\boutgoing\s+links?\b",
    r"\blinks?\s+(from|to)\b",
    r"\brelated\s+to\b",
    r"\bsit\s+in\b",
]

_RELATIONSHIP_RE = re.compile(
    "|".join(_RELATIONSHIP_PATTERNS), re.IGNORECASE
)


def classify_query(query: str) -> str:
    """Return 'relationship' or 'content'."""
    if _RELATIONSHIP_RE.search(query):
        return "relationship"
    return "content"
