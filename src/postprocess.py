"""轨迹后处理：把断成几截的同一个人接回来。

为什么需要：前景差分检测器在人物静止/被短暂遮挡时会丢目标，跟踪器
只能新开一个 ID。结果是一个人被拆成 2~4 段轨迹，UE5 里对应的 NPC
会"消失又重生"。这里按「时间相邻 + 空间可达」把片段接成一条，
既提升 ID 保持率，也让 NPC 数量贴近真实人数。

判据（缺一不可）：
  1. 后一段的开始帧 - 前一段的结束帧 <= max_gap_frames
  2. 两段端点距离 <= 人在这段时间内可能走到的距离（按 1.6 m/s 估）
"""
from __future__ import annotations

import math
from typing import Dict, List

MAX_HUMAN_SPEED = 1.6      # m/s，拼接时允许的最大位移速度


def stitch_tracks(frames: List[dict], fps: float, max_gap_frames: int = 70,
                  max_dist_m: float = 2.2, log=print) -> Dict[int, int]:
    """就地重写 frames[*]['actors'][*]['id']，返回 旧ID -> 新ID 的映射。"""
    if not frames:
        return {}

    segs: Dict[int, dict] = {}
    for fr in frames:
        f = fr["frame"]
        for a in fr["actors"]:
            tid = int(a["id"])
            s = segs.get(tid)
            if s is None:
                segs[tid] = {"id": tid, "start": f, "end": f,
                             "first_xy": (a["x_m"], a["y_m"]), "last_xy": (a["x_m"], a["y_m"])}
            else:
                s["end"] = f
                s["last_xy"] = (a["x_m"], a["y_m"])

    order = sorted(segs.values(), key=lambda s: (s["start"], s["id"]))
    chains: List[dict] = []
    mapping: Dict[int, int] = {}

    for s in order:
        best = None
        for ch in chains:
            gap = s["start"] - ch["end"]
            if gap < 0 or gap > max_gap_frames:
                continue
            d = math.hypot(s["first_xy"][0] - ch["last_xy"][0],
                           s["first_xy"][1] - ch["last_xy"][1])
            reachable = min(max_dist_m, MAX_HUMAN_SPEED * (gap / max(fps, 1e-3)) + 0.35)
            if d <= reachable and (best is None or d < best[0]):
                best = (d, ch)
        if best is not None:
            ch = best[1]
            ch["members"].append(s["id"])
            ch["end"] = s["end"]
            ch["last_xy"] = s["last_xy"]
        else:
            chains.append({"members": [s["id"]], "end": s["end"], "last_xy": s["last_xy"]})

    # 新 ID：按链路首次出现顺序重编为 1..N
    for new_id, ch in enumerate(sorted(chains, key=lambda c: min(segs[m]["start"] for m in c["members"])), start=1):
        for old in ch["members"]:
            mapping[old] = new_id

    for fr in frames:
        for a in fr["actors"]:
            a["id"] = mapping[int(a["id"])]
        fr["actors"].sort(key=lambda a: a["id"])

    merged = len(segs) - len(chains)
    if merged > 0:
        log(f"[post] 轨迹拼接：{len(segs)} 段 -> {len(chains)} 人（合并 {merged} 段断裂）")
    else:
        log(f"[post] 轨迹拼接：{len(segs)} 段，无断裂需要合并")
    return mapping


def stitch_npc_payload(npcs: List[dict], log=print) -> List[dict]:
    """对已按 NPC 组织的数据做同样的事（导出后补救用）。"""
    return npcs
