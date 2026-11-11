import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT,
    duration REAL,
    pcm_hash TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    error TEXT
);
CREATE TABLE IF NOT EXISTS l3_edges (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    ber REAL NOT NULL,
    PRIMARY KEY (a, b)
);
"""


class Store:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(files)")}
        if "fp" not in cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN fp BLOB")
            self.conn.execute("ALTER TABLE files ADD COLUMN fp_error TEXT")
        self.conn.commit()

    def get(self, path: str):
        return self.conn.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()

    def upsert(self, path: str, size: int, mtime_ns: int):
        self.conn.execute(
            "INSERT INTO files(path,size,mtime_ns,status) VALUES(?,?,?,'new') "
            "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns, "
            "sha256=NULL, duration=NULL, pcm_hash=NULL, fp=NULL, fp_error=NULL, status='new', error=NULL",
            (path, size, mtime_ns),
        )

    def set_sha256(self, path: str, sha256: str):
        self.conn.execute(
            "UPDATE files SET sha256=?, status='ok', error=NULL WHERE path=?", (sha256, path)
        )

    def set_duration(self, path: str, duration: float):
        self.conn.execute("UPDATE files SET duration=? WHERE path=?", (duration, path))

    def set_pcm(self, path: str, pcm_hash: str):
        self.conn.execute("UPDATE files SET pcm_hash=? WHERE path=?", (pcm_hash, path))

    def set_fp(self, path: str, fp: bytes):
        self.conn.execute("UPDATE files SET fp=?, fp_error=NULL WHERE path=?", (fp, path))

    def set_fp_error(self, path: str, error: str):
        # L3 失败不改 status：文件仍是 L1/L2 的 ok 行，只拉黑指纹环节
        self.conn.execute("UPDATE files SET fp_error=? WHERE path=?", (error, path))

    _UPSERT_EDGE = (
        "INSERT INTO l3_edges(a,b,ber) VALUES(?,?,?) "
        "ON CONFLICT(a,b) DO UPDATE SET ber=excluded.ber "
        "WHERE excluded.ber < l3_edges.ber"
    )

    def append_l3_edge(self, a: str, b: str, ber: float):
        """match 的 edge_sink 落库入口：边算边写、中断不丢；同一对保留更优 BER。"""
        self.conn.execute(self._UPSERT_EDGE, (a, b, ber))

    def clear_l3_edges(self):
        self.conn.execute("DELETE FROM l3_edges")

    def save_l3_edges(self, edges: list, replace: bool = True):
        """整批写入；replace=False 时增量追加，不覆盖既有边。"""
        if replace:
            self.clear_l3_edges()
        self.conn.executemany(self._UPSERT_EDGE, edges)

    def load_l3_edges(self):
        return self.conn.execute("SELECT a, b, ber FROM l3_edges").fetchall()

    def mark_quarantined(self, paths: list):
        self.conn.executemany(
            "UPDATE files SET status='quarantined' WHERE path=?", [(p,) for p in paths])

    def mark_restored(self, paths: list):
        self.conn.executemany(
            "UPDATE files SET status='ok' WHERE path=? AND status='quarantined'",
            [(p,) for p in paths])

    def set_error(self, path: str, stage: str, error: str):
        self.conn.execute(
            "UPDATE files SET status='error', error=? WHERE path=?", (f"{stage}: {error}", path)
        )

    def mark_missing(self, live_paths: set):
        rows = self.conn.execute(
            "SELECT path FROM files WHERE status NOT IN ('missing','quarantined')").fetchall()
        gone = [r["path"] for r in rows if r["path"] not in live_paths]
        self.conn.executemany(
            "UPDATE files SET status='missing' WHERE path=?", [(p,) for p in gone]
        )
        return gone

    def ok_rows(self):
        return self.conn.execute("SELECT * FROM files WHERE status='ok'").fetchall()

    def counts(self):
        rows = self.conn.execute("SELECT status, COUNT(*) n FROM files GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.commit()
        self.conn.close()