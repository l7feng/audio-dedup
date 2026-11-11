import os

import pytest

from audio_dedup.core import quarantine as q
from audio_dedup.core.hashing import sha256_file


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "lib"
    (root / "sub").mkdir(parents=True)
    (root / "a.wav").write_bytes(b"audio-a" * 100)
    (root / "sub" / "b.wav").write_bytes(b"audio-b" * 200)
    qdir = tmp_path / "quarantine"
    return root, qdir


def test_roundtrip_sha256(tree):
    root, qdir = tree
    a, b = str(root / "a.wav"), str(root / "sub" / "b.wav")
    ha, hb = sha256_file(a), sha256_file(b)
    batch = q.quarantine_files([a, b], str(qdir), str(root))
    assert not os.path.exists(a) and not os.path.exists(b)
    assert len(batch["files"]) == 2
    restored = q.restore_files(str(qdir), batch["id"])
    assert set(restored) == {a, b}
    assert sha256_file(a) == ha and sha256_file(b) == hb
    assert q.load_manifest(str(qdir))["batches"][0]["restored"] == sorted([a, b])


def test_restore_partial_selection(tree):
    root, qdir = tree
    a, b = str(root / "a.wav"), str(root / "sub" / "b.wav")
    batch = q.quarantine_files([a, b], str(qdir), str(root))
    q.restore_files(str(qdir), batch["id"], originals=[a])
    assert os.path.exists(a) and not os.path.exists(b)
    q.restore_files(str(qdir), batch["id"])
    assert os.path.exists(b)


def test_outside_root_rejected(tree):
    root, qdir = tree
    outside = root.parent / "outside.wav"
    outside.write_bytes(b"x")
    with pytest.raises(q.QuarantineError, match="不在扫描根内"):
        q.quarantine_files([str(outside)], str(qdir), str(root))


def test_cross_drive_rejected(tree):
    root, _qdir = tree
    a = str(root / "a.wav")
    other = "Z:\\" if os.path.splitdrive(str(root))[0].upper() != "Z:" else "Y:\\"
    with pytest.raises(q.QuarantineError, match="不同盘"):
        q.quarantine_files([a], other, str(root))


def test_conflict_refused(tree):
    root, qdir = tree
    a = str(root / "a.wav")
    batch = q.quarantine_files([a], str(qdir), str(root))
    (root / "a.wav").write_bytes(b"new-content")
    with pytest.raises(q.QuarantineError, match="拒绝覆盖"):
        q.restore_files(str(qdir), batch["id"])


def test_tampered_quarantine_refused(tree):
    root, qdir = tree
    a = str(root / "a.wav")
    batch = q.quarantine_files([a], str(qdir), str(root))
    with open(batch["files"][0]["quarantined"], "wb") as f:
        f.write(b"tampered")
    with pytest.raises(q.QuarantineError, match="SHA256"):
        q.restore_files(str(qdir), batch["id"])


def test_missing_source_rejected(tree):
    root, qdir = tree
    with pytest.raises(q.QuarantineError, match="不存在"):
        q.quarantine_files([str(root / "nope.wav")], str(qdir), str(root))