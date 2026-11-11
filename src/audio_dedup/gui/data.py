"""GUI 数据层：只读 groups.json；必要时从 index.sqlite3 现导一次。

不重算指纹、不碰源音频。GUI 与 CLI 共用 core.export 的同一份数据契约。
"""
import json
import os

from ..core import dedup, export, fingerprint, quarantine, report, store


def payload_path(workdir: str) -> str:
    return os.path.join(workdir, export.GROUPS_JSON)


def index_path(workdir: str) -> str:
    return os.path.join(workdir, "index.sqlite3")


def load_payload(workdir: str):
    path = payload_path(workdir)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ensure_payload(workdir: str, root: str | None = None):
    """打开索引：有 groups.json 直接读；只有索引时现导一次。"""
    data = load_payload(workdir)
    if data is not None:
        return data
    if not os.path.isfile(index_path(workdir)):
        raise FileNotFoundError("目录内没有 groups.json，也没有 index.sqlite3")
    return refresh_payload(workdir, root)


def refresh_payload(workdir: str, root: str | None = None):
    db = store.Store(index_path(workdir))
    try:
        return export.export_workdir(workdir, root or "(见索引)", db)
    finally:
        db.close()


def rewrite_report(workdir: str, root: str) -> int:
    """从既有索引重写 Markdown/CSV 报告，并同步刷新 GUI 数据包。"""
    db = store.Store(index_path(workdir))
    try:
        l1, l2, l3, _edges = export.rebuild_groups(db)
        errors = [f"{r['path']}: {r['error']}" for r in db.conn.execute(
            "SELECT path, error FROM files WHERE status='error'").fetchall()]
        n = report.write_reports(workdir, root, db.counts(), errors,
                                 l1, l2, False, groups_l3=l3)
        export.export_workdir(workdir, root, db)
        return n
    finally:
        db.close()


def mark_quarantined(workdir: str, paths: list):
    db = store.Store(index_path(workdir))
    try:
        db.mark_quarantined(paths)
        db.commit()
    finally:
        db.close()


def mark_restored(workdir: str, paths: list):
    db = store.Store(index_path(workdir))
    try:
        db.mark_restored(paths)
        db.commit()
    finally:
        db.close()


def fmt_size(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_dur(d) -> str:
    return "—" if d is None else f"{d:.2f}s"


def fmt_ber(b) -> str:
    return "—" if b is None else f"{b:.3f}"


def layer_color(layer: str) -> str:
    from . import theme
    return {"L1": theme.L1, "L2": theme.L2, "L3": theme.L3}.get(layer, theme.MUTED)


def grade_color(grade: str) -> str:
    from . import theme
    if grade == "确定":
        return theme.L1
    return {"高疑似": theme.HIGH, "中疑似": theme.MID,
            "低疑似": theme.LOW}.get(grade, theme.MUTED)


def short_name(path: str) -> str:
    return os.path.basename(path.rstrip("\\/")) or path


def parent_hint(path: str) -> str:
    parent = os.path.dirname(path.rstrip("\\/"))
    return os.path.basename(parent) if parent else ""


def default_qdir(root: str) -> str:
    return quarantine.default_quarantine_dir(root)


def manifest_batches(qdir: str) -> list:
    try:
        return quarantine.load_manifest(qdir).get("batches", [])
    except (OSError, ValueError):
        return []


def l3_thresholds() -> dict:
    return {"高疑似": fingerprint.GRADE_HIGH,
            "中疑似": fingerprint.GRADE_MID,
            "低疑似": fingerprint.GRADE_LOW}


def rec_from_dict(d: dict) -> dedup.FileRec:
    return dedup.FileRec(path=d["path"], size=d["size"],
                         sha256=d.get("sha256"), duration=d.get("duration"),
                         pcm_hash=d.get("pcm_hash"))
