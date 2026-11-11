"""波形峰值：8kHz 解码 → 每桶 min/max，供 GUI 对比绘制。进程内缓存。"""
from .fingerprint import decode_pcm

_CACHE: dict[str, tuple] = {}
BUCKETS = 1200


def peaks(path: str, ffmpeg: str = "ffmpeg", buckets: int = BUCKETS):
    key = path
    if key in _CACHE:
        return _CACHE[key]
    pcm = decode_pcm(path, ffmpeg)
    n = len(pcm)
    if n == 0:
        raise ValueError("空 PCM")
    step = max(1, n // buckets)
    trimmed = pcm[: (n // step) * step].reshape(-1, step)
    mins = trimmed.min(axis=1)
    maxs = trimmed.max(axis=1)
    result = (mins, maxs, n / 8000.0)
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[key] = result
    return result