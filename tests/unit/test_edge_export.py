import json

import numpy as np

from audio_dedup.core import export, store
from audio_dedup.core import fingerprint as fp


def _pcm(seconds=2.0, seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fp.RATE)) / fp.RATE
    chirp = np.sin(2 * np.pi * (300 * t + 400 * t * t))
    noise = rng.standard_normal(len(t)) * 0.15
    return (0.6 * chirp + noise).astype(np.float32)


def _entries():
    base = _pcm(seed=11)
    return [
        ("a.wav", *fp.signature(base)),
        ("a_gain.wav", *fp.signature(base * 2.0)),
        ("a_trim.wav", *fp.signature(base[1200:])),
        ("b.wav", *fp.signature(_pcm(seed=12))),
    ]


def _db(tmp_path):
    return store.Store(str(tmp_path / "index.sqlite3"))


def _seed_db(db):
    for path, size, dur in (("E:/lib/a.wav", 1000, 1.0),
                            ("E:/lib/a_copy.wav", 1000, 1.0),
                            ("E:/lib/x.wav", 800, 1.5)):
        db.upsert(path, size, 1)
        db.set_sha256(path, "h" * 8)
        db.set_duration(path, dur)
    db.append_l3_edge("E:/lib/x.wav", "E:/lib/a.wav", 0.08)
    db.commit()


def test_edge_sink_streams_and_equals_return_edges():
    seen = []
    groups = fp.match(_entries(), edge_sink=lambda a, b, ber: seen.append((a, b, ber)))
    groups2, edge_list = fp.match(_entries(), return_edges=True)

    assert seen == edge_list
    assert seen, "正例家族应至少产出一条边"
    assert all(ber <= fp.GRADE_LOW for _a, _b, ber in seen)
    assert len({(a, b) for a, b, _ in seen}) == len(seen), "同一对不得重复回调"
    assert [sorted(p for p, _ in g) for g in groups] == [sorted(p for p, _ in g) for g in groups2]
    assert all("b.wav" not in {p for p, _ in g} for g in groups), "异源不得入组"


def test_groups_from_edges_transitive_member_has_no_fake_ber():
    groups = fp.groups_from_edges(["a", "b", "c"], [("a", "b", 0.05), ("b", "c", 0.08)])
    assert len(groups) == 1
    bers = [b for _p, b in groups[0]]
    assert 0.0 in bers
    assert None in bers, "传递连通但无直连边应留空，不伪造数值"


def test_append_l3_edge_incremental(tmp_path):
    db = _db(tmp_path)
    db.append_l3_edge("a", "b", 0.20)
    db.append_l3_edge("a", "b", 0.30)  # 更差：不覆盖
    db.append_l3_edge("a", "b", 0.05)  # 更优：覆盖
    db.append_l3_edge("b", "c", 0.10)
    db.commit()
    rows = {(r["a"], r["b"]): r["ber"] for r in db.load_l3_edges()}
    assert rows == {("a", "b"): 0.05, ("b", "c"): 0.10}
    db.clear_l3_edges()
    db.commit()
    assert list(db.load_l3_edges()) == []
    db.close()


def test_export_payload_and_files(tmp_path):
    db = _db(tmp_path)
    _seed_db(db)
    payload = export.export_workdir(str(tmp_path), "E:/lib", db)

    assert payload["schema"] == export.SCHEMA_VERSION
    assert payload["summary"]["l1_groups"] == 1
    assert payload["summary"]["l3_groups"] == 1
    assert payload["summary"]["edges"] == 1

    data = json.loads((tmp_path / export.GROUPS_JSON).read_text(encoding="utf-8"))
    assert data["root"] == "E:/lib"
    l3 = next(g for g in data["groups"] if g["layer"] == "L3")
    assert l3["grade"] == "高疑似"
    assert l3["keep"]
    assert l3["edges"][0]["ber"] == 0.08
    assert l3["reclaimable_bytes"] > 0
    assert any(f["keep"] for f in l3["files"])

    csv_text = (tmp_path / export.EDGES_CSV).read_text(encoding="utf-8")
    assert "E:/lib/x.wav" in csv_text
    assert "高疑似" in csv_text
    assert l3["id"] in csv_text
    db.close()


def test_rebuild_without_edges_does_not_recompute(tmp_path):
    db = _db(tmp_path)
    _seed_db(db)
    db.clear_l3_edges()
    db.commit()
    l1, l2, l3, edges = export.rebuild_groups(db)
    assert len(l1) == 1
    assert l2 == []
    assert l3 == [] and edges == [], "无边时不得偷偷重算指纹"
    db.close()
