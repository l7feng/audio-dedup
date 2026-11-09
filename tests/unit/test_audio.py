import shutil

import pytest
from helpers import ffmpeg_meta_copy, write_wav

from audio_dedup.core.audio import AudioError, decode_pcm_hash, duration_wav, probe_duration

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 不在 PATH")


def test_duration_and_decode(tmp_path):
    a = tmp_path / "a.wav"
    write_wav(a)
    assert duration_wav(str(a)) == pytest.approx(1.0, abs=0.01)
    assert probe_duration(str(a)) == pytest.approx(1.0, abs=0.05)
    h1, n1 = decode_pcm_hash(str(a))
    h2, n2 = decode_pcm_hash(str(a))
    assert h1 == h2 and n1 == n2 == 48000


def test_metadata_variant_same_pcm(tmp_path):
    a = tmp_path / "a.wav"
    write_wav(a)
    meta = tmp_path / "meta.wav"
    ffmpeg_meta_copy(a, meta)
    assert a.read_bytes() != meta.read_bytes()
    assert decode_pcm_hash(str(a))[0] == decode_pcm_hash(str(meta))[0]


def test_same_duration_different_content_differs(tmp_path):
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    write_wav(a, freq=440)
    write_wav(b, freq=880)
    assert decode_pcm_hash(str(a))[0] != decode_pcm_hash(str(b))[0]


def test_garbage_raises(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFFxxxxWAVEjunk")
    with pytest.raises(AudioError):
        probe_duration(str(bad))
    with pytest.raises(AudioError):
        decode_pcm_hash(str(bad))