import csv
import os
import shutil

import pytest
from helpers import ffmpeg_meta_copy, ffmpeg_to_flac, write_wav

from audio_dedup.cli import main
from audio_dedup.core.hashing import sha256_file

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 不在 PATH")


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    write_wav(root / "a.wav", freq=440)
    shutil.copyfile(root / "a.wav", root / "a_copy.wav")
    ffmpeg_meta_copy(root / "a.wav", root / "a_meta.wav")
    ffmpeg_to_flac(root / "a.wav", root / "a.flac")
    write_wav(root / "b.wav", freq=880)
    (root / "garbage.wav").write_bytes(b"RIFFxxxxWAVEjunk")
    (root / "notes.txt").write_text("非音频，应被跳过", encoding="utf-8")
    return root


def _hashes(root):
    return {p: sha256_file(os.path.join(dp, p))
            for dp, _, fns in os.walk(root) for p in fns}


def test_scan_matrix_and_readonly(tmp_path, library):
    before = _hashes(library)
    wd = tmp_path / "wd"
    rc = main(["scan", "--root", str(library), "--workdir", str(wd)])
    assert rc == 0
    assert _hashes(library) == before

    with open(wd / "report.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    l1 = [r for r in rows if r["layer"] == "L1"]
    l2 = [r for r in rows if r["layer"] == "L2"]
    assert {os.path.basename(r["path"]) for r in l1} == {"a.wav", "a_copy.wav"}
    assert {os.path.basename(r["path"]) for r in l2} == {"a.wav", "a_copy.wav", "a_meta.wav", "a.flac"}
    assert all("b.wav" not in r["path"] and "garbage" not in r["path"] for r in rows)
    assert sum(r["keep_suggestion"] == "1" for r in l1) == 1
    assert (wd / "report.md").exists()


def test_rescan_reuse_and_blacklist(tmp_path, library, capsys):
    wd = tmp_path / "wd"
    assert main(["scan", "--root", str(library), "--workdir", str(wd)]) == 0
    capsys.readouterr()
    assert main(["scan", "--root", str(library), "--workdir", str(wd)]) == 0
    out = capsys.readouterr().out
    assert "新算 0" in out
    assert "黑名单跳过 1" in out


def test_skip_l2(tmp_path, library):
    wd = tmp_path / "wd"
    assert main(["scan", "--root", str(library), "--workdir", str(wd), "--skip-l2"]) == 0
    with open(wd / "report.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and all(r["layer"] == "L1" for r in rows)


@pytest.mark.skipif(os.name != "nt", reason="msvcrt 锁仅 Windows")
def test_single_instance_lock(tmp_path):
    from audio_dedup.cli import SingleInstance

    lock_path = str(tmp_path / ".lock")
    first = SingleInstance(lock_path)
    try:
        with pytest.raises(RuntimeError):
            SingleInstance(lock_path)
    finally:
        first.close()
    second = SingleInstance(lock_path)
    second.close()


def test_l3_groups_and_readonly(tmp_path, library):
    before = _hashes(library)
    wd = tmp_path / "wd"
    assert main(["scan", "--root", str(library), "--workdir", str(wd)]) == 0
    assert main(["l3", "--workdir", str(wd), "--root", str(library)]) == 0
    assert _hashes(library) == before

    with open(wd / "report.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    l3 = [r for r in rows if r["layer"] == "L3"]
    names = {os.path.basename(r["path"]) for r in l3}
    assert {"a.wav", "a_meta.wav", "a.flac"} <= names
    assert "b.wav" not in names and "garbage.wav" not in names
    assert all(r["ber"] for r in l3)


def test_l3_rescan_reuse(tmp_path, library, capsys):
    wd = tmp_path / "wd"
    assert main(["scan", "--root", str(library), "--workdir", str(wd)]) == 0
    assert main(["l3", "--workdir", str(wd)]) == 0
    capsys.readouterr()
    assert main(["l3", "--workdir", str(wd)]) == 0
    out = capsys.readouterr().out
    assert "待算指纹 0" in out