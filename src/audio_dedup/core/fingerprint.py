"""L3 感知指纹：频带能量差符号哈希＋活跃位掩码加权 BER。

选型依据见知识库项目 92《01-L3指纹选型实测》：真实音效正例 BER ≤ 0.234、
负例 ≥ 0.361；近静音（活跃位 <10%）判不可匹配。L3 只产疑似组，不自动处置。
"""
import math
import subprocess
import tempfile
import threading

import numpy as np

from .audio import AudioError
from .paths import io_path

RATE = 8000
FRAME = 1024
HOP = 256
N_BANDS = 32
MIN_FRAMES = 8

GRADE_HIGH = 0.10
GRADE_MID = 0.25
GRADE_LOW = 0.35


def grade_of(ber: float) -> str:
    if ber <= GRADE_HIGH:
        return "高疑似"
    if ber <= GRADE_MID:
        return "中疑似"
    return "低疑似"


def decode_pcm(path: str, ffmpeg: str = "ffmpeg", timeout: float = 120) -> np.ndarray:
    cmd = [
        ffmpeg, "-v", "error", "-i", io_path(path),
        "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(RATE), "pipe:1",
    ]
    timed_out = threading.Event()
    with tempfile.TemporaryFile() as errf:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf) as p:
            def _kill():
                timed_out.set()
                p.kill()

            watchdog = threading.Timer(timeout, _kill)
            watchdog.start()
            try:
                data = p.stdout.read()
                rc = p.wait()
            finally:
                watchdog.cancel()
        errf.seek(0)
        err = errf.read().decode("utf-8", errors="replace")
    if timed_out.is_set():
        raise AudioError(f"解码超时 {timeout}s 被终止")
    if rc != 0:
        raise AudioError(err.strip()[-500:] or f"ffmpeg 退出码 {rc}")
    if len(data) < 4:
        raise AudioError("解码产出 0 样本")
    return np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0


def signature(pcm: np.ndarray):
    """返回 (sig, mask)：31bit/帧 uint32 数组；mask 标记活跃频带对。"""
    if len(pcm) < FRAME + HOP:
        z = np.zeros(0, dtype=np.uint32)
        return z, z.copy()
    n = 1 + (len(pcm) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = pcm[idx] * np.hanning(FRAME).astype(np.float32)
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(FRAME, 1.0 / RATE)
    edges = np.geomspace(60.0, RATE / 2 - 1, N_BANDS + 1)
    bands = np.empty((n, N_BANDS), dtype=np.float64)
    for i in range(N_BANDS):
        m = (freqs >= edges[i]) & (freqs < edges[i + 1])
        bands[:, i] = power[:, m].mean(axis=1) if m.any() else 1e-12
    log = np.log(bands + 1e-12)
    floor = log.max(axis=1, keepdims=True) - math.log(1e5)  # 相对本底 -50dB
    active = (log > floor) & (bands > 1e-10)  # 绝对本底：数字静音全带相等，须整体判 inactive
    log = np.maximum(log, floor)
    d = log[:, :-1] - log[:, 1:]
    bits = (d[1:] - d[:-1]) > 0
    am = active[:, :-1] | active[:, 1:]
    mask = am[1:] | am[:-1]
    w = 1 << np.arange(31, dtype=np.uint32)
    sig = (bits.astype(np.uint32) * w).sum(axis=1, dtype=np.uint32)
    msk = (mask.astype(np.uint32) * w).sum(axis=1, dtype=np.uint32)
    return sig, msk


def pack_fp(sig: np.ndarray, mask: np.ndarray) -> bytes:
    return sig.tobytes() + mask.tobytes()


def unpack_fp(blob: bytes):
    half = len(blob) // 2
    sig = np.frombuffer(blob[:half], dtype=np.uint32)
    mask = np.frombuffer(blob[half:], dtype=np.uint32)
    return sig, mask


def _ber_at(x, mx, y, my):
    m = min(len(x), len(y))
    if m < MIN_FRAMES:
        return 1.0
    union = np.bitwise_or(mx[:m], my[:m])
    # 活跃位置不同本身就是差异：稳态纯音的活跃位也是 False，不能只比 bit 值
    err_bits = (np.bitwise_xor(x[:m], y[:m]) & union) | np.bitwise_xor(mx[:m], my[:m])
    err = np.unpackbits(err_bits.view(np.uint8).reshape(-1, 4), axis=1).sum()
    tot = np.unpackbits(union.view(np.uint8).reshape(-1, 4), axis=1).sum()
    if tot < 0.03 * 31 * m:
        return 1.0
    return float(err) / float(tot)


def ber(a, b, max_shift: int | None = None, chunks: int = 4) -> float:
    """分段偏移搜索的最小活跃位误码率；段内 ±3 帧微调吸收 ±3% 拉伸漂移。"""
    sa, ma = a
    sb, mb = b
    if len(sa) < MIN_FRAMES or len(sb) < MIN_FRAMES:
        return 1.0
    if max_shift is None:
        max_shift = max(len(sa), len(sb))
    best = 1.0
    for shift in range(-max_shift, max_shift + 1):
        if shift >= 0:
            x, y, xm, ym = sa[shift:], sb, ma[shift:], mb
        else:
            x, y, xm, ym = sa, sb[-shift:], ma, mb[-shift:]
        b = _ber_aligned(x, xm, y, ym, chunks)
        best = min(best, b)
    return best


def _ber_aligned(x, xm, y, ym, chunks: int) -> float:
    m = min(len(x), len(y))
    if m < MIN_FRAMES:
        return 1.0
    if m < 32 or chunks <= 1:
        return _ber_at(x, xm, y, ym)
    step = m // chunks
    bers = []
    for k in range(chunks):
        sl = slice(k * step, (k + 1) * step if k < chunks - 1 else m)
        xs, ys, xms, yms = x[sl], y[sl], xm[sl], ym[sl]
        cb = 1.0
        for ds in range(-3, 4):
            if ds >= 0:
                xx, yy, xxm, yym = xs[ds:], ys, xms[ds:], yms
            else:
                xx, yy, xxm, yym = xs, ys[-ds:], xms, yms[-ds:]
            if min(len(xx), len(yy)) >= MIN_FRAMES:
                bb = _ber_at(xx, xxm, yy, yym)
                cb = min(cb, bb)
        bers.append(cb)
    return sum(bers) / len(bers)


def ber_at_offset(a, b, offset: int, chunks: int = 4) -> float:
    """投票给出的对齐偏移处直接验证（生产路径，避免全偏移搜索）。"""
    sa, ma = a
    sb, mb = b
    if offset >= 0:
        return _ber_aligned(sa[offset:], ma[offset:], sb, mb, chunks)
    return _ber_aligned(sa, ma, sb[-offset:], mb[-offset:], chunks)


def _profiles(entries):
    """活跃频带直方图（32 维 L2 归一）：时间对齐无关的内容粗描，用于兜底候选。"""
    prof = np.zeros((len(entries), N_BANDS), dtype=np.float32)
    bitpos = np.arange(31, dtype=np.uint32)
    for i, (_p, _sig, mask) in enumerate(entries):
        bits = ((mask[:, None] >> bitpos) & 1).astype(np.float32)
        m = bits.mean(axis=0)
        prof[i, :-1] += m / 2
        prof[i, 1:] += m / 2
    norms = np.linalg.norm(prof, axis=1, keepdims=True)
    return prof / np.maximum(norms, 1e-9)


def groups_from_edges(paths: list, edges: list) -> list:
    """edges: [(path_a, path_b, ber)] → 连通分量分组 [(path, ber_to_first)]。

    传递连通但无直连边的成员 BER 为 None（GUI 显示「—」），不伪造数值。
    """
    idx = {p: i for i, p in enumerate(paths)}
    parent = list(range(len(paths)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    direct = {}
    for a, b, ber in edges:
        if a not in idx or b not in idx:
            continue
        i, k = idx[a], idx[b]
        direct[(min(i, k), max(i, k))] = ber
        ri, rk = find(i), find(k)
        if ri != rk:
            parent[ri] = rk
    comps: dict[int, list] = {}
    for i in range(len(paths)):
        comps.setdefault(find(i), []).append(i)
    groups = []
    for members in comps.values():
        if len(members) < 2:
            continue
        rep = members[0]
        group = [(paths[rep], 0.0)]
        for i in members[1:]:
            group.append((paths[i], direct.get((min(rep, i), max(rep, i)))))
        groups.append(group)
    groups.sort(key=lambda g: (-len(g), g[0][0]))
    return groups


def match(entries: list, threshold: float = GRADE_LOW, min_votes: int = 2,
          top_k: int = 12, bucket_cap: int = 1000, progress=None,
          fallback_top: int = 8, profile_cos: float = 0.90,
          return_edges: bool = False, edge_sink=None):
    """entries: [(path, sig, mask)]。倒排索引投票 → BER 验证 → 频带直方图兜底 → 连通分量。

    投票抓精确/近精确对齐（增益、转码、慢变素材裁剪）；快速瞬态的分数帧偏移裁剪
    精确票为零，由直方图余弦 ≥ profile_cos 且长度比 ∈ [0.7, 1.43] 的兜底候选补抓。
    返回 [[(path, ber_to_first), ...], ...]；组内首成员为 BER 参照。

    edge_sink(a, b, ber) 在每条边**首次确认时立即回调**：调用方可边算边落库或边导出，
    不必等全库匹配结束，中断也已导出的边不会丢。return_edges 保留向后兼容，
    返回的边列表与 sink 收到的内容一致。
    """
    entries = [(p, s, m) for p, s, m in entries if len(s) >= MIN_FRAMES]
    index: dict[int, list] = {}
    for i, (_p, sig, mask) in enumerate(entries):
        for j in np.nonzero(mask)[0]:
            h = int(sig[j])
            bucket = index.get(h)
            if bucket is None:
                index[h] = [(i << 24) | int(j)]
            elif len(bucket) < bucket_cap:
                bucket.append((i << 24) | int(j))
    oversized = {h for h, b in index.items() if len(b) >= bucket_cap}
    for h in oversized:
        del index[h]  # 超高频哈希（静音/恒定音）无判别力，整桶丢弃

    edges = {}

    def emit(i: int, k: int, ber_value: float):
        """边首次确认即导出；同一对不重复回调。"""
        key = (i, k)
        if key in edges:
            return
        edges[key] = ber_value
        if edge_sink is not None:
            edge_sink(entries[i][0], entries[k][0], ber_value)

    for i, (_p, sig, mask) in enumerate(entries):
        votes: dict[tuple, int] = {}
        for j in np.nonzero(mask)[0]:
            for packed in index.get(int(sig[j]), ()):
                k = packed >> 24
                if k <= i:
                    continue
                key = (k, int(j) - (packed & 0xFFFFFF))
                votes[key] = votes.get(key, 0) + 1
        best_off: dict[int, tuple] = {}
        for (k, off), n in votes.items():
            if n < min_votes:
                continue
            if k not in best_off or n > best_off[k][1]:
                best_off[k] = (off, n)
        for k, (off, _n) in sorted(best_off.items(), key=lambda kv: -kv[1][1])[:top_k]:
            b = ber_at_offset((sig, mask), (entries[k][1], entries[k][2]), off)
            if b <= threshold:
                emit(i, k, b)
        if progress and i % 500 == 0:
            progress(i, len(entries))

    prof = _profiles(entries)
    lengths = np.array([len(s) for _p, s, _m in entries], dtype=np.float32)
    n = len(entries)
    for start in range(0, n, 2048):
        stop = min(start + 2048, n)
        sims = prof[start:stop] @ prof.T
        for i in range(start, stop):
            row = sims[i - start]
            ratio = lengths / max(lengths[i], 1)
            ok = (row >= profile_cos) & (ratio >= 0.7) & (ratio <= 1.43)
            ok[: i + 1] = False
            for k in np.nonzero(ok)[0]:
                if (i, int(k)) in edges:
                    ok[k] = False
            cand = np.nonzero(ok)[0]
            if len(cand) > fallback_top:
                cand = cand[np.argsort(row[cand])[-fallback_top:]]
            for k in cand:
                k = int(k)
                shift = min(len(entries[i][1]), len(entries[k][1])) // 2
                b = ber((entries[i][1], entries[i][2]),
                        (entries[k][1], entries[k][2]), max_shift=shift)
                if b <= threshold:
                    emit(i, k, b)
        if progress:
            progress(stop, n)
    if progress:
        progress(n, n)

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, k in edges:
        ri, rk = find(i), find(k)
        if ri != rk:
            parent[ri] = rk

    comps: dict[int, list] = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(i)
    groups = []
    for members in comps.values():
        if len(members) < 2:
            continue
        rep = members[0]
        group = [(entries[rep][0], 0.0)]
        for i in members[1:]:
            key = (rep, i) if rep < i else (i, rep)
            b = edges.get(key)
            if b is None:  # 传递连通但无直连边：全偏移搜索补算（罕见路径）
                b = ber((entries[rep][1], entries[rep][2]),
                        (entries[i][1], entries[i][2]))
            group.append((entries[i][0], b))
        groups.append(group)
    groups.sort(key=lambda g: (-len(g), g[0][0]))
    if return_edges:
        edge_list = [(entries[i][0], entries[k][0], b) for (i, k), b in edges.items()]
        return groups, edge_list
    return groups