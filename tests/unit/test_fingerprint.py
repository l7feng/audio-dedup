import numpy as np

from audio_dedup.core import fingerprint as fp


def _pcm(seconds=2.0, seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fp.RATE)) / fp.RATE
    chirp = np.sin(2 * np.pi * (300 * t + 400 * t * t))
    noise = rng.standard_normal(len(t)) * 0.15
    return (0.6 * chirp + noise).astype(np.float32)


def _sig(pcm):
    return fp.signature(pcm)


def test_signature_deterministic():
    a = _sig(_pcm())
    b = _sig(_pcm())
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
    assert a[0].dtype == np.uint32


def test_gain_variant_matches():
    base = _pcm()
    assert fp.ber(_sig(base), _sig(base * 2.0)) <= fp.GRADE_HIGH


def test_trim_variant_matches():
    base = _pcm()
    assert fp.ber(_sig(base), _sig(base[1200:])) <= fp.GRADE_MID


def test_stretch_variant_matches():
    base = _pcm()
    stretched = np.interp(
        np.arange(0, len(base), 1.03), np.arange(len(base)), base
    ).astype(np.float32)
    # 线性插值拉伸附带低通效应，噪声分量频谱变化 → 低疑似档
    assert fp.ber(_sig(base), _sig(stretched)) <= fp.GRADE_LOW


def test_reverse_rejected():
    base = _pcm()
    assert fp.ber(_sig(base), _sig(base[::-1].copy())) > fp.GRADE_LOW


def test_different_content_rejected():
    assert fp.ber(_sig(_pcm(seed=7)), _sig(_pcm(seed=8))) > fp.GRADE_LOW


def test_silence_never_matches():
    z = np.zeros(fp.RATE * 2, dtype=np.float32)
    assert fp.ber(_sig(z), _sig(z)) == 1.0


def test_pure_tone_gain_matches_and_other_tone_rejected():
    t = np.arange(fp.RATE * 2) / fp.RATE
    a = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    b = (0.5 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
    assert fp.ber(_sig(a), _sig(a * 2.0)) <= fp.GRADE_HIGH
    assert fp.ber(_sig(a), _sig(b)) > fp.GRADE_LOW


def test_short_input_safe():
    z = np.zeros(100, dtype=np.float32)
    s = _sig(z)
    assert len(s[0]) == 0
    assert fp.ber(s, s) == 1.0


def test_pack_roundtrip():
    sig, mask = _sig(_pcm())
    s2, m2 = fp.unpack_fp(fp.pack_fp(sig, mask))
    assert np.array_equal(sig, s2) and np.array_equal(mask, m2)


def test_match_groups_variants_and_rejects_other():
    base = _pcm(seed=11)
    other = _pcm(seed=12)
    entries = [
        ("a.wav", *_sig(base)),
        ("a_gain.wav", *_sig(base * 2.0)),
        ("a_trim.wav", *_sig(base[1200:])),
        ("b.wav", *_sig(other)),
    ]
    groups = fp.match(entries)
    assert len(groups) == 1
    paths = {p for p, _b in groups[0]}
    assert paths == {"a.wav", "a_gain.wav", "a_trim.wav"}
    assert all(b <= fp.GRADE_LOW for _p, b in groups[0])


def test_match_silence_no_groups():
    z = np.zeros(fp.RATE * 2, dtype=np.float32)
    groups = fp.match([("s1.wav", *_sig(z)), ("s2.wav", *_sig(z))])
    assert groups == []