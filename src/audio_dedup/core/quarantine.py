"""隔离与恢复：同盘 rename＋manifest 清单＋SHA256 往返核验。无永久删除路径。

隔离目录默认与被隔离文件同盘（rename 原子、可恢复）；每次隔离由人类在 GUI
逐次确认清单后调用。manifest 是唯一恢复依据，原子写入、只追加批次。
"""
import json
import os
import time
import uuid

from .hashing import sha256_file
from .paths import io_path
from .report import atomic_write


class QuarantineError(Exception):
    pass


def default_quarantine_dir(root: str) -> str:
    drive = os.path.splitdrive(os.path.abspath(root))[0] or "C:"
    return os.path.join(drive + os.sep, "audio-dedup-quarantine")


def _manifest_path(qdir: str) -> str:
    return os.path.join(qdir, "manifest.json")


def load_manifest(qdir: str) -> dict:
    p = _manifest_path(qdir)
    if not os.path.exists(io_path(p)):
        return {"batches": []}
    with open(io_path(p), encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(qdir: str, manifest: dict):
    atomic_write(_manifest_path(qdir), json.dumps(manifest, ensure_ascii=False, indent=1))


def quarantine_files(paths: list, qdir: str, root: str) -> dict:
    """把 paths 移入 qdir/<批次>/ 下，保留相对 root 的目录结构。返回批次记录。

    全部校验通过后才开始移动；逐个 rename，任一失败即停止并保留已移动清单
    （已移动部分可按 manifest 恢复）。同名冲突拒绝，不覆盖。
    """
    qdir = os.path.abspath(qdir)
    root = os.path.abspath(root)
    for p in paths:
        if not os.path.isfile(io_path(p)):
            raise QuarantineError(f"源文件不存在：{p}")
        rel = os.path.relpath(p, root)
        if rel.startswith(".."):
            raise QuarantineError(f"文件不在扫描根内，拒绝隔离：{p}")
    if os.path.splitdrive(qdir)[0].lower() != os.path.splitdrive(root)[0].lower():
        raise QuarantineError("隔离目录与源库不同盘，rename 不原子；请选同盘目录")

    batch_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    batch_dir = os.path.join(qdir, batch_id)
    entries = []
    for p in paths:
        rel = os.path.relpath(p, root)
        dst = os.path.join(batch_dir, rel)
        if os.path.exists(io_path(dst)):
            raise QuarantineError(f"隔离目标已存在，拒绝覆盖：{dst}")
        entries.append({
            "original": p, "quarantined": dst,
            "size": os.path.getsize(io_path(p)), "sha256": sha256_file(p),
        })
    os.makedirs(io_path(batch_dir), exist_ok=True)
    moved = []
    try:
        for e in entries:
            os.makedirs(io_path(os.path.dirname(e["quarantined"])), exist_ok=True)
            os.rename(io_path(e["original"]), io_path(e["quarantined"]))
            moved.append(e)
    except OSError as e:
        _record_batch(qdir, batch_id, root, moved, partial=True)
        raise QuarantineError(f"移动中断（已移动 {len(moved)} 个，可按清单恢复）：{e}") from e
    batch = _record_batch(qdir, batch_id, root, moved, partial=False)
    return batch


def _record_batch(qdir: str, batch_id: str, root: str, moved: list, partial: bool) -> dict:
    manifest = load_manifest(qdir)
    batch = {"id": batch_id, "root": root, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
             "partial": partial, "files": moved, "restored": []}
    manifest["batches"].append(batch)
    _save_manifest(qdir, manifest)
    return batch


def restore_files(qdir: str, batch_id: str, originals: list | None = None) -> list:
    """按 manifest 恢复指定批次（默认全部未恢复文件）。返回恢复成功的原路径。

    恢复前核验隔离件 SHA256 与清单一致；原位已有文件则拒绝覆盖。
    """
    qdir = os.path.abspath(qdir)
    manifest = load_manifest(qdir)
    batch = next((b for b in manifest["batches"] if b["id"] == batch_id), None)
    if batch is None:
        raise QuarantineError(f"批次不存在：{batch_id}")
    done = set(batch.get("restored", []))
    targets = [e for e in batch["files"]
               if e["original"] not in done
               and (originals is None or e["original"] in set(originals))]
    for e in targets:
        if not os.path.isfile(io_path(e["quarantined"])):
            raise QuarantineError(f"隔离件缺失：{e['quarantined']}")
        if os.path.exists(io_path(e["original"])):
            raise QuarantineError(f"原位已有文件，拒绝覆盖：{e['original']}")
        actual = sha256_file(e["quarantined"])
        if actual != e["sha256"]:
            raise QuarantineError(f"隔离件 SHA256 与清单不符，拒绝恢复：{e['quarantined']}")
    restored = []
    for e in targets:
        os.makedirs(io_path(os.path.dirname(e["original"])), exist_ok=True)
        os.rename(io_path(e["quarantined"]), io_path(e["original"]))
        if sha256_file(e["original"]) != e["sha256"]:
            raise QuarantineError(f"恢复后 SHA256 不符：{e['original']}")
        restored.append(e["original"])
    batch["restored"] = sorted(done | set(restored))
    _save_manifest(qdir, manifest)
    return restored