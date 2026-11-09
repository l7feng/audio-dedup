import argparse
import os
import shutil
import sys
import time

from . import __version__
from .core import audio, dedup, report, scan, store
from .core.hashing import sha256_file
from .core.paths import ext_of

try:
    import msvcrt

    class SingleInstance:
        # OS 持有的文件锁：进程崩溃自动释放，不留 O_EXCL 死锁文件
        def __init__(self, lock_path: str):
            self._f = open(lock_path, "a+b")  # noqa: SIM115 - 锁句柄须活到进程结束
            try:
                msvcrt.locking(self._f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self._f.close()
                raise RuntimeError("另一个 audio-dedup 实例正在使用此 workdir") from None

        def close(self):
            self._f.close()

except ImportError:
    SingleInstance = None


def _progress(done: int, total_hint: str, stage: str):
    print(f"[{stage}] {done} {total_hint}", flush=True)


def cmd_scan(args) -> int:
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"扫描根不存在或不可达：{root}", file=sys.stderr)
        return 2
    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    lock = SingleInstance(os.path.join(workdir, ".lock")) if SingleInstance else None
    db = store.Store(os.path.join(workdir, "index.sqlite3"))
    started = time.time()
    errors = []
    try:
        live = set()
        new = reused = blacklisted = 0
        for path, size, mtime_ns in scan.walk_audio(root, errors):
            live.add(path)
            row = db.get(path)
            if row and row["size"] == size and row["mtime_ns"] == mtime_ns and row["status"] in ("ok", "error"):
                if row["status"] == "error":
                    blacklisted += 1
                else:
                    reused += 1
                continue
            db.upsert(path, size, mtime_ns)
            try:
                db.set_sha256(path, sha256_file(path))
            except OSError as e:
                db.set_error(path, "sha256", str(e))
                errors.append(f"{path}: {e}")
            new += 1
            if new % 500 == 0:
                db.commit()
                _progress(new, "new hashed", "L1")
        gone = db.mark_missing(live)
        db.commit()
        counts = db.counts()
        print(f"扫描完成：新算 {new}，复用 {reused}，黑名单跳过 {blacklisted}，消失 {len(gone)}；状态 {counts}", flush=True)

        recs = [dedup.FileRec(**{k: r[k] for k in ("path", "size", "mtime_ns", "sha256", "duration", "pcm_hash")})
                for r in db.ok_rows()]
        groups_l1 = dedup.l1_groups(recs)
        groups_l2 = []
        if not args.skip_l2:
            if not shutil.which(args.ffmpeg) or not shutil.which(args.ffprobe):
                print("缺少 ffmpeg/ffprobe，L2 未执行（通过 --ffmpeg/--ffprobe 指定路径）", file=sys.stderr)
                return 3
            probed = 0
            for r in recs:
                if r.duration is not None:
                    continue
                d = audio.duration_wav(r.path) if ext_of(r.path) in (".wav", ".wave") else None
                try:
                    if d is None:
                        d = audio.probe_duration(r.path, args.ffprobe)
                    db.set_duration(r.path, d)
                    r.duration = d
                except audio.AudioError as e:
                    db.set_error(r.path, "probe", str(e))
                    errors.append(f"{r.path}: probe: {e}")
                probed += 1
                if probed % 500 == 0:
                    db.commit()
                    _progress(probed, "probed", "L2")
            db.commit()
            recs = [dedup.FileRec(**{k: row[k] for k in ("path", "size", "mtime_ns", "sha256", "duration", "pcm_hash")})
                    for row in db.ok_rows()]
            by_path = {r.path: r for r in recs}
            candidates = dedup.l2_candidates(recs, args.tolerance)
            # 字节相同的文件解码结果必然相同：每个 sha256 只解码一次再传播
            pcm_by_sha = {r.sha256: r.pcm_hash for r in recs if r.pcm_hash}
            decoded = failed = 0
            for path in sorted(candidates):
                r = by_path[path]
                if r.pcm_hash:
                    continue
                if r.sha256 in pcm_by_sha:
                    db.set_pcm(path, pcm_by_sha[r.sha256])
                    continue
                try:
                    pcm_hash, _samples = audio.decode_pcm_hash(path, args.ffmpeg)
                    db.set_pcm(path, pcm_hash)
                    pcm_by_sha[r.sha256] = pcm_hash
                except audio.AudioError as e:
                    db.set_error(path, "decode", str(e))
                    errors.append(f"{path}: decode: {e}")
                    failed += 1
                decoded += 1
                if decoded % 200 == 0:
                    db.commit()
                    _progress(decoded, f"decoded ({failed} failed)", "L2")
            db.commit()
            for row in db.ok_rows():
                r = by_path.get(row["path"])
                if r is not None and row["pcm_hash"] and not r.pcm_hash:
                    r.pcm_hash = row["pcm_hash"]
            recs = [by_path[row["path"]] for row in db.ok_rows()]
            groups_l2 = dedup.l2_groups(recs)
            print(f"L2：候选 {len(candidates)}，解码 {decoded}，失败 {failed}", flush=True)

        counts = db.counts()
        n_groups = report.write_reports(workdir, root, counts, errors, groups_l1, groups_l2, args.skip_l2)
        print(f"报告：{os.path.join(workdir, 'report.md')} / report.csv；共 {n_groups} 组；耗时 {time.time() - started:.0f}s", flush=True)
        return 0
    finally:
        db.close()
        if lock:
            lock.close()


def cmd_report(args) -> int:
    workdir = os.path.abspath(args.workdir)
    db = store.Store(os.path.join(workdir, "index.sqlite3"))
    try:
        recs = [dedup.FileRec(**{k: r[k] for k in ("path", "size", "mtime_ns", "sha256", "duration", "pcm_hash")})
                for r in db.ok_rows()]
        errors = [f"{r['path']}: {r['error']}" for r in db.conn.execute(
            "SELECT path, error FROM files WHERE status='error'").fetchall()]
        n = report.write_reports(workdir, args.root or "(见索引)", db.counts(), errors,
                                 dedup.l1_groups(recs), dedup.l2_groups(recs), False)
        print(f"报告重写完成：{n} 组", flush=True)
        return 0
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audio-dedup", description="音效库重复音频识别（源库只读，不处置文件）")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_scan = sub.add_parser("scan", help="扫描 + L1/L2 判定 + 分组报告")
    p_scan.add_argument("--root", required=True, help="被扫描库根（只读）")
    p_scan.add_argument("--workdir", required=True, help="索引与报告目录（库外）")
    p_scan.add_argument("--tolerance", type=float, default=0.5, help="L2 时长预筛容差秒（默认 0.5）")
    p_scan.add_argument("--skip-l2", action="store_true", help="只做 L1 字节级")
    p_scan.add_argument("--ffmpeg", default="ffmpeg")
    p_scan.add_argument("--ffprobe", default="ffprobe")
    p_scan.set_defaults(func=cmd_scan)
    p_report = sub.add_parser("report", help="从既有索引重写报告")
    p_report.add_argument("--workdir", required=True)
    p_report.add_argument("--root", default=None)
    p_report.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())