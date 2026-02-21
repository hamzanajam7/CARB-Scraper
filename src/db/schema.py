"""SQL schema constants for the CARB database."""

CREATE_PAGES = """
CREATE TABLE IF NOT EXISTS pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT UNIQUE NOT NULL,
    guid        TEXT,
    title       TEXT,
    content     TEXT DEFAULT '',
    depth       INTEGER DEFAULT 0,
    parent_id   INTEGER REFERENCES pages(id),
    status      TEXT DEFAULT 'ok',
    crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_INDEX_GUID = "CREATE INDEX IF NOT EXISTS idx_pages_guid ON pages(guid);"
CREATE_INDEX_PARENT = "CREATE INDEX IF NOT EXISTS idx_pages_parent ON pages(parent_id);"

CREATE_EDGES = """
CREATE TABLE IF NOT EXISTS edges (
    from_id     INTEGER REFERENCES pages(id),
    to_id       INTEGER REFERENCES pages(id),
    link_text   TEXT,
    PRIMARY KEY (from_id, to_id)
);
"""

CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    title,
    content,
    content=pages,
    content_rowid=id,
    tokenize='porter ascii'
);
"""

CREATE_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, title, content)
    VALUES (new.id, COALESCE(new.title, ''), COALESCE(new.content, ''));
END;
"""

CREATE_TRIGGER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, content)
    VALUES ('delete', old.id, COALESCE(old.title, ''), COALESCE(old.content, ''));
    INSERT INTO pages_fts(rowid, title, content)
    VALUES (new.id, COALESCE(new.title, ''), COALESCE(new.content, ''));
END;
"""

ALL_DDL = [
    CREATE_PAGES,
    CREATE_INDEX_GUID,
    CREATE_INDEX_PARENT,
    CREATE_EDGES,
    CREATE_FTS,
    CREATE_TRIGGER_INSERT,
    CREATE_TRIGGER_UPDATE,
]
