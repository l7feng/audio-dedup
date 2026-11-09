from audio_dedup.core.dedup import (
    FileRec,
    keep_suggestion,
    l1_groups,
    l2_candidates,
    l2_groups,
)


def rec(path, size=100, sha=None, duration=None, pcm=None):
    return FileRec(path=path, size=size, sha256=sha, duration=duration, pcm_hash=pcm)


def test_l1_same_size_same_hash_groups():
    a = rec("a.wav", sha="x")
    b = rec("dir/b.wav", sha="x")
    c = rec("c.wav", sha="y")
    groups = l1_groups([a, b, c])
    assert len(groups) == 1
    assert {r.path for r in groups[0]} == {"a.wav", "dir/b.wav"}


def test_l1_same_size_different_hash_no_group():
    assert l1_groups([rec("a.wav", sha="x"), rec("b.wav", sha="y")]) == []


def test_l1_different_size_no_group():
    assert l1_groups([rec("a.wav", size=1, sha="x"), rec("b.wav", size=2, sha="x")]) == []


def test_l2_candidates_neighbor_buckets():
    a = rec("a.wav", duration=1.01)
    b = rec("b.wav", duration=1.04)
    lonely = rec("lonely.wav", duration=99.0)
    cand = l2_candidates([a, b, lonely], tolerance=0.05)
    assert "a.wav" in cand and "b.wav" in cand
    assert "lonely.wav" not in cand


def test_l2_candidates_same_bucket():
    a = rec("a.wav", duration=2.0)
    b = rec("b.wav", duration=2.0)
    assert l2_candidates([a, b], tolerance=0.5) == {"a.wav", "b.wav"}


def test_l2_groups_by_pcm_hash():
    a = rec("a.wav", pcm="p")
    b = rec("b.flac", pcm="p")
    c = rec("c.wav", pcm="q")
    d = rec("d.wav", pcm=None)
    groups = l2_groups([a, b, c, d])
    assert len(groups) == 1
    assert {r.path for r in groups[0]} == {"a.wav", "b.flac"}


def test_keep_lossless_first():
    wav = rec("long/path/name.wav", size=1000, duration=1.0)
    mp3 = rec("a.mp3", size=5000, duration=1.0)
    assert keep_suggestion([mp3, wav]).path == "long/path/name.wav"


def test_keep_bitrate_then_short_path():
    hi = rec("long/path/hi.mp3", size=5000, duration=1.0)
    lo = rec("lo.mp3", size=1000, duration=1.0)
    assert keep_suggestion([lo, hi]).path == "long/path/hi.mp3"
    same1 = rec("aaaa.wav", size=100, duration=1.0)
    same2 = rec("b.wav", size=100, duration=1.0)
    assert keep_suggestion([same1, same2]).path == "b.wav"