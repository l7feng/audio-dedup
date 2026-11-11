"""边导出与 GUI 数据契约。

`fingerprint.match()` 通过 `edge_sink` 边算边把 L3 相似边写入 `l3_edges`（可中断续），
本模块只负责「从既有索引重建分组并导出」，不重算任何指纹、不碰源音频。

产物（都在 workdir，原子写）：

- `groups.json`：GUI 唯一数据源，含 L1/L2/L3 分组、组内文件元数据、边与疑似分级。
- `edges.csv`：人可读的边清单（a, b, ber, grade），便于外部核对与留证。

L3 分组完全由已导出的边经连通分量重建，因此「导出边」与「报告分组」永远同源。
"""
import csv
import io
import json
import os
from datetime import datetime

from . import dedup, fingerprint
from .report import atomic_write

SCHEMA_VERSION = 1
GROUPS_JSON = "groups.json"
EDGES_CSV = "edges.csv"


def _recs(db):
    return [dedup.FileRec(**{
        k: r[k] for k in ("path", "size", "mtime_ns", "sha256", "duration", "pcm_hash")
    }) for r in db.ok_rows()]


def rebuild_groups(db):
    """从既有索引重建三层分组；L3 只依赖已导出的边，不重算指纹。

    返回 (groups_l1, groups_l2, groups_l3, edges)；L3 组内 BER 可能为 None
    （传递连通但无直连边），由展示层显示「—」。
    """
    recs = _recs(db)
    by_path = {r.path: r for r in recs}
    l1 = dedup.l1_groups(recs)
    l2 = dedup.l2_groups(recs)
    edges = [(r["a"], r["b"], r["ber"]) for r in db.load_l3_edges()]
    l3 = []
    if edges:
        l3 = [[(by_path[p], b) for p, b in g if p in by_path]
              for g in fingerprint.groups_from_edges(list(by_path), edges)]
    return l1, l2, l3, edges


def _file_dict(r, keep_path, ber=None):
    return {
        "path": r.path,
        "size": r.size,
        "duration": r.duration,
        "sha256": r.sha256,
        "pcm_hash": r.pcm_hash,
        "ber": ber,
        "keep": r.path == keep_path,
    }


def _group_dict(gid, layer, pairs, all_edges):
    """pairs: [(FileRec, ber|None)]；ber 为 None 表示无直连边，展示为「—」。"""
    recs = [r for r, _b in pairs]
    keep = dedup.keep_suggestion(recs)
    paths = {r.path for r in recs}
    group_edges = [
        {"a": a, "b": b, "ber": ber, "grade": fingerprint.grade_of(ber)}
        for a, b, ber in all_edges if a in paths and b in paths
    ]
    valid = [b for _r, b in pairs if b is not None]
    grade = "确定" if layer != "L3" else (
        fingerprint.grade_of(min(valid)) if valid else "未分级")
    return {
        "id": gid,
        "layer": layer,
        "grade": grade,
        "count": len(recs),
        "keep": keep.path,
        "reclaimable_bytes": sum(r.size for r in recs if r.path != keep.path),
        "files": [_file_dict(r, keep.path, b) for r, b in pairs],
        "edges": group_edges,
    }


def build_payload(workdir: str, root: str, db) -> dict:
    """组装 GUI 数据包（纯读，不写盘）。"""
    l1, l2, l3, edges = rebuild_groups(db)
    groups = []
    for layer, batch in (("L1", l1), ("L2", l2)):
        for i, group in enumerate(sorted(batch, key=lambda g: (-len(g), g[0].path)), 1):
            groups.append(_group_dict(
                f"{layer}-{i}", layer, [(r, None) for r in group], edges))
    for i, group in enumerate(sorted(l3, key=lambda g: (-len(g), g[0][0].path)), 1):
        groups.append(_group_dict(f"L3-{i}", "L3", group, edges))
    errors = [f"{r['path']}: {r['error']}" for r in db.conn.execute(
        "SELECT path, error FROM files WHERE status='error'").fetchall()]
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": root,
        "workdir": os.path.abspath(workdir),
        "counts": db.counts(),
        "summary": {
            "l1_groups": len(l1), "l2_groups": len(l2), "l3_groups": len(l3),
            "edges": len(edges), "groups": len(groups),
            "reclaimable_bytes": sum(g["reclaimable_bytes"] for g in groups),
        },
        "groups": groups,
        "errors": errors,
    }


def export_workdir(workdir: str, root: str, db) -> dict:
    """导出 groups.json 与 edges.csv；返回同一份 payload 供调用方复用。"""
    payload = build_payload(workdir, root, db)
    atomic_write(
        os.path.join(workdir, GROUPS_JSON),
        json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False),
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["a", "b", "ber", "grade", "group_id"])
    owner = {}
    for g in payload["groups"]:
        for e in g["edges"]:
            owner.setdefault((e["a"], e["b"]), g["id"])
    for row in db.load_l3_edges():
        a, b, ber = row["a"], row["b"], row["ber"]
        writer.writerow([a, b, f"{ber:.4f}", fingerprint.grade_of(ber),
                         owner.get((a, b), "")])
    atomic_write(os.path.join(workdir, EDGES_CSV), buf.getvalue())
    return payload
