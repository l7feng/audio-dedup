from audio_dedup.core.store import Store


def test_upsert_and_reuse(tmp_path):
    s = Store(str(tmp_path / "i.sqlite3"))
    s.upsert("a.wav", 10, 100)
    s.set_sha256("a.wav", "h")
    s.commit()
    row = s.get("a.wav")
    assert row["status"] == "ok" and row["sha256"] == "h"
    s.upsert("a.wav", 10, 200)
    row = s.get("a.wav")
    assert row["status"] == "new" and row["sha256"] is None
    s.close()


def test_error_blacklist_and_missing(tmp_path):
    s = Store(str(tmp_path / "i.sqlite3"))
    s.upsert("bad.wav", 10, 100)
    s.set_error("bad.wav", "probe", "broken")
    s.upsert("gone.wav", 10, 100)
    s.set_sha256("gone.wav", "h")
    s.commit()
    assert s.get("bad.wav")["status"] == "error"
    gone = s.mark_missing({"bad.wav"})
    assert gone == ["gone.wav"]
    assert s.get("gone.wav")["status"] == "missing"
    assert s.counts() == {"error": 1, "missing": 1}
    s.close()


def test_fp_migration_from_old_schema(tmp_path):
    import sqlite3

    db = str(tmp_path / "old.sqlite3")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE files (path TEXT PRIMARY KEY, size INTEGER NOT NULL, "
        "mtime_ns INTEGER NOT NULL, sha256 TEXT, duration REAL, pcm_hash TEXT, "
        "status TEXT NOT NULL DEFAULT 'new', error TEXT)")
    conn.execute("INSERT INTO files(path,size,mtime_ns,sha256,status) VALUES('a.wav',10,100,'h','ok')")
    conn.commit()
    conn.close()

    s = Store(db)
    row = s.get("a.wav")
    assert row["sha256"] == "h" and row["fp"] is None
    s.set_fp("a.wav", b"\x01\x02")
    assert s.get("a.wav")["fp"] == b"\x01\x02"
    s.set_fp_error("a.wav", "decode: x")
    row = s.get("a.wav")
    assert row["status"] == "ok" and row["fp_error"] == "decode: x"
    s.upsert("a.wav", 10, 200)
    row = s.get("a.wav")
    assert row["fp"] is None and row["fp_error"] is None
    s.close()