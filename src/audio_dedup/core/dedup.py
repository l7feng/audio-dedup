from collections import defaultdict
from dataclasses import dataclass

from .paths import LOSSLESS_EXTS, ext_of


@dataclass
class FileRec:
    path: str
    size: int
    mtime_ns: int = 0
    sha256: str | None = None
    duration: float | None = None
    pcm_hash: str | None = None


def l1_groups(recs):
    by_size = defaultdict(list)
    for r in recs:
        by_size[r.size].append(r)
    groups = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        by_hash = defaultdict(list)
        for r in same_size:
            if r.sha256:
                by_hash[r.sha256].append(r)
        groups.extend(g for g in by_hash.values() if len(g) >= 2)
    return groups


def l2_candidates(recs, tolerance: float):
    # 时长仅用于预筛：同 PCM 哈希必然同解码时长，分桶±1 决定谁值得解码，不影响分组正确性
    buckets = defaultdict(list)
    for r in recs:
        if r.duration is not None and r.duration > 0:
            buckets[round(r.duration / tolerance)].append(r)
    candidates = set()
    for k, rs in buckets.items():
        near = len(rs) + len(buckets.get(k - 1, ())) + len(buckets.get(k + 1, ()))
        if near >= 2:
            candidates.update(r.path for r in rs)
    return candidates


def l2_groups(recs):
    by_pcm = defaultdict(list)
    for r in recs:
        if r.pcm_hash:
            by_pcm[r.pcm_hash].append(r)
    return [g for g in by_pcm.values() if len(g) >= 2]


def keep_suggestion(group):
    def key(r):
        lossless = 0 if ext_of(r.path) in LOSSLESS_EXTS else 1
        bitrate = r.size * 8 / r.duration if r.duration else 0
        return (lossless, -bitrate, len(r.path), r.path)

    return min(group, key=key)