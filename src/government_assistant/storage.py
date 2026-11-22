import json
import logging
import sqlite3
from pathlib import Path
from .schemas import SchemeRecord

logger=logging.getLogger(__name__)


class Repository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schemes (scheme_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (document_id TEXT PRIMARY KEY, scheme_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chunks (chunk_id TEXT PRIMARY KEY, scheme_id TEXT NOT NULL, document_id TEXT NOT NULL, payload TEXT NOT NULL, content_hash TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS chunks_scheme ON chunks(scheme_id);
            CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ingestion_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS index_manifest (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
        logger.debug("Repository ready: database=%s",path)

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def upsert_scheme(self, record: SchemeRecord):
        with self.connect() as db:
            db.execute("INSERT INTO schemes VALUES (?, ?) ON CONFLICT(scheme_id) DO UPDATE SET payload=excluded.payload", (record.scheme_id, record.model_dump_json()))
        logger.debug("Scheme record upserted: scheme_id=%s verification=%s",record.scheme_id,record.verification_status)

    def get_scheme(self, scheme_id: str):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM schemes WHERE scheme_id=?", (scheme_id,)).fetchone()
        return SchemeRecord.model_validate_json(row[0]) if row else None

    def schemes(self, q=None, category=None, level=None, state=None, district=None):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM schemes ORDER BY scheme_id").fetchall()
        items = [SchemeRecord.model_validate_json(r[0]) for r in rows]
        def has(value, pattern): return not pattern or pattern.casefold() in (value or "").casefold()
        results=[x for x in items if has(x.scheme_name + " " + (x.description or "") + " " + (x.scheme_category or "") + " " + " ".join(x.target_beneficiaries or []), q) and has(x.scheme_category, category) and has(x.scheme_level, level) and has(x.state, state) and has(x.district, district)]
        logger.debug("Scheme records queried: loaded=%d returned=%d filters=%s",len(items),len(results),[name for name,value in (("query",q),("category",category),("level",level),("state",state),("district",district)) if value])
        return results

    def chunks(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM chunks").fetchall()
        chunks=[json.loads(r[0]) for r in rows]
        logger.debug("Document chunks loaded: count=%d",len(chunks))
        return chunks

    def replace_chunks(self, scheme_id: str, chunks: list[dict]):
        with self.connect() as db:
            db.execute("DELETE FROM chunks WHERE scheme_id=?", (scheme_id,))
            for c in chunks:
                db.execute("INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?)", (c["chunk_id"], scheme_id, c["document_id"], json.dumps(c, ensure_ascii=False), c["content_hash"]))
        logger.debug("Scheme chunks replaced: scheme_id=%s count=%d",scheme_id,len(chunks))

    def save_feedback(self, payload):
        with self.connect() as db: db.execute("INSERT INTO feedback(payload) VALUES (?)", (json.dumps(payload, ensure_ascii=False),))
        logger.debug("Feedback saved: rating=%s",payload.get("rating"))

    def manifest(self):
        with self.connect() as db:
            manifest={r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value FROM index_manifest")}
        logger.debug("Index manifest loaded: entries=%d",len(manifest))
        return manifest
