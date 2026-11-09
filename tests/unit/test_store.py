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