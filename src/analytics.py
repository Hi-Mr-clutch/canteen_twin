"""统计分析：人数、区域占用、停留时长、进出计数、热力栅格。

所有计算都在「地面米制坐标」上做，和 UE5 场景比例一一对应。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2
import numpy as np


@dataclass
class ZoneHit:
    name: str
    label: str
    frames: int = 0
    unique_ids: set = field(default_factory=set)


@dataclass
class PersonTrack:
    """一个人的完整轨迹（地面坐标序列）。"""
    track_id: int
    first_frame: int = 0
    last_frame: int = 0
    points: List[tuple] = field(default_factory=list)   # [(frame, x_m, y_m), ...]
    speeds: List[float] = field(default_factory=list)
    zone_counts: Dict[str, int] = field(default_factory=dict)
    entry_frame: Optional[int] = None    # 首次进入计数区的帧
    exit_frame: Optional[int] = None     # 离开计数区的帧

    @property
    def duration_sec(self) -> float:
        return 0.0  # 由 analytics 用 fps 计算，这里占位

    def path_length_m(self) -> float:
        if len(self.points) < 2:
            return 0.0
        pts = np.array([[p[1], p[2]] for p in self.points], dtype=np.float32)
        return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())

    def main_zone(self) -> str:
        if not self.zone_counts:
            return ""
        return max(self.zone_counts.items(), key=lambda kv: kv[1])[0]


class ZoneManager:
    """把地面平面切成若干多边形区域（取餐区/就餐区/出入口…）。"""

    def __init__(self, zones, log=print):
        self.zones = []
        for z in zones:
            if len(z.polygon) >= 3:
                poly = np.asarray(z.polygon, dtype=np.float32).reshape(-1, 2)
                self.zones.append((z.name, z.label or z.name, poly, list(z.color)))
        if not self.zones:
            log("[analytics] 警告：没有配置任何区域，区域统计将为空")

    def locate(self, x_m: float, y_m: float) -> Optional[str]:
        for name, _label, poly, _color in self.zones:
            if cv2.pointPolygonTest(poly, (float(x_m), float(y_m)), False) >= 0:
                return name
        return None

    def labels(self) -> Dict[str, str]:
        return {name: label for name, label, _p, _c in self.zones}


class CounterLine:
    """进出计数：一条地面线段，统计轨迹从中穿过的人与方向。

    防抖（debounce）：脚点在线附近来回抖几厘米就会让叉积符号反复翻转，
    若每次翻转都记一次，进出人次会严重虚高（真实视频实测高估 60%~80%）。
    因此一次「有效穿越」必须同时满足两个条件：
      1) 距该 ID 上一次成功计数 >= debounce_sec（按 fps 换算成帧数）；
      2) 当前脚点距上一次成功计数的位置 >= min_travel_m（确实离开了门线）。
    两个阈值都可在配置里调；设为 0 即关闭防抖，回到旧行为。
    """

    def __init__(self, p1, p2, name="door", inward_sign=1,
                 debounce_sec=0.5, min_travel_m=0.15, fps=30.0):
        self.p1 = np.asarray(p1, dtype=np.float32)
        self.p2 = np.asarray(p2, dtype=np.float32)
        self.name = name
        self.inward_sign = inward_sign
        self.in_count = 0
        self.out_count = 0
        self.debounce_sec = float(debounce_sec)
        self.min_travel_m = float(min_travel_m)
        self.min_gap_frames = max(0, int(round(self.debounce_sec * max(fps, 1e-3))))
        self._last_side: Dict[int, float] = {}
        self._last_hit_frame: Dict[int, int] = {}
        self._last_hit_pos: Dict[int, tuple] = {}
        self._tick = 0

    def _side(self, p) -> float:
        """叉积符号：正负表示点在线段的哪一侧。"""
        a = self.p2 - self.p1
        b = np.asarray(p, dtype=np.float32) - self.p1
        return float(a[0] * b[1] - a[1] * b[0])

    def update(self, track_id: int, p, frame=None) -> Optional[str]:
        """p=(x_m, y_m) 为地面脚点；frame 为处理后帧号（不传则用内部自增时钟兜底）。"""
        s = self._side(p)
        prev = self._last_side.get(track_id)
        self._last_side[track_id] = s
        if prev is None or prev * s >= 0:
            return None                      # 首帧 / 没穿越

        if frame is None:
            self._tick += 1
            f = self._tick
        else:
            f = int(frame)

        # 条件 1：与上一次成功计数至少间隔 min_gap_frames 帧
        last_f = self._last_hit_frame.get(track_id, -10 ** 9)
        if f - last_f < self.min_gap_frames:
            return None
        # 条件 2：脚点确实离开了上次计数的位置
        last_p = self._last_hit_pos.get(track_id)
        if last_p is not None and self.min_travel_m > 0:
            dx, dy = float(p[0]) - last_p[0], float(p[1]) - last_p[1]
            if (dx * dx + dy * dy) ** 0.5 < self.min_travel_m:
                return None

        direction = "in" if (s - prev) * self.inward_sign > 0 else "out"
        if direction == "in":
            self.in_count += 1
        else:
            self.out_count += 1
        self._last_hit_frame[track_id] = f
        self._last_hit_pos[track_id] = (float(p[0]), float(p[1]))
        return direction


class Heatmap:
    """地面坐标栅格热力图（0.25m 一格），统计人流密度分布。"""

    def __init__(self, width_m: float, height_m: float, cell_m: float = 0.25):
        self.cell = cell_m
        self.w = max(1, int(round(width_m / cell_m)))
        self.h = max(1, int(round(height_m / cell_m)))
        self.grid = np.zeros((self.h, self.w), dtype=np.float32)

    def add(self, x_m: float, y_m: float, weight: float = 1.0):
        cx = int(x_m / self.cell)
        cy = int(y_m / self.cell)
        if 0 <= cx < self.w and 0 <= cy < self.h:
            self.grid[cy, cx] += weight

    def to_image(self, blur: int = 9, gamma: float = 0.55) -> np.ndarray:
        g = self.grid.copy()
        if g.max() > 0:
            g = g / g.max()
        k = max(3, blur | 1)
        # 先在细网格上模糊，再二次归一化 —— 否则高斯会削掉峰值，整张图全是蓝的
        g = cv2.GaussianBlur(g, (k, k), 0)
        if g.max() > 0:
            g = g / g.max()
        g = np.power(np.clip(g, 0, 1), gamma)      # 提亮中低密度区，路径更明显
        g = (g * 255).astype(np.uint8)
        g = cv2.resize(g, (self.w * 8, self.h * 8), interpolation=cv2.INTER_CUBIC)
        return cv2.applyColorMap(g, cv2.COLORMAP_JET)


class Analytics:
    def __init__(self, cfg, fps: float, log=print):
        self.cfg = cfg
        self.fps = max(fps, 1e-3)
        self.log = log
        self.zones = ZoneManager(cfg.zones, log=log) if hasattr(cfg, "zones") else ZoneManager([], log=log)
        self.tracks: Dict[int, PersonTrack] = {}
        self.per_frame_count: List[int] = []
        self.per_frame_zone: Dict[str, List[int]] = {n: [] for n, _l, _p, _c in self.zones.zones}
        # --- 实时看板用：逐帧点位 + 事件流 ---
        self.per_frame_points: List[List[list]] = []      # 每帧 [[id, x_m, y_m], ...]
        self.events: List[tuple] = []                    # (frame, "new"|"in"|"out", track_id, counter_name)
        self.first_seen: Dict[int, int] = {}            # track_id -> 首次出现帧
        self.heat = None
        self.counters: List[CounterLine] = []

    def set_heatmap(self, width_m: float, height_m: float, cell_m: float = 0.25):
        self.heat = Heatmap(width_m, height_m, cell_m)

    def add_counter(self, counter: CounterLine):
        self.counters.append(counter)

    def update_frame(self, frame_idx: int, actors: List[dict]):
        """actors: [{'id':int, 'x_m':float, 'y_m':float, 'speed_mps':float, 'zone':str}]"""
        self.per_frame_count.append(len(actors))
        zone_now = {n: 0 for n in self.per_frame_zone}
        pts_now: List[list] = []
        for a in actors:
            tid = int(a["id"])
            x, y = float(a["x_m"]), float(a["y_m"])
            zone = a.get("zone") or self.zones.locate(x, y)
            a["zone"] = zone
            pts_now.append([tid, round(x, 2), round(y, 2)])
            if zone in zone_now:
                zone_now[zone] += 1

            tr = self.tracks.get(tid)
            if tr is None:
                tr = PersonTrack(track_id=tid, first_frame=frame_idx)
                self.tracks[tid] = tr
                self.first_seen[tid] = frame_idx
                self.events.append((frame_idx, "new", tid, ""))
            tr.last_frame = frame_idx
            tr.points.append((frame_idx, x, y))
            tr.speeds.append(float(a.get("speed_mps", 0.0)))
            if zone:
                tr.zone_counts[zone] = tr.zone_counts.get(zone, 0) + 1

            if self.heat is not None:
                self.heat.add(x, y)

            for c in self.counters:
                d = c.update(tid, (x, y), frame_idx)
                if d == "in" and tr.entry_frame is None:
                    tr.entry_frame = frame_idx
                elif d == "out":
                    tr.exit_frame = frame_idx
                if d in ("in", "out"):
                    self.events.append((frame_idx, d, tid, c.name))

        for n, v in zone_now.items():
            self.per_frame_zone[n].append(v)
        self.per_frame_points.append(pts_now)

    # ---------- 汇总 ----------
    def summary(self) -> dict:
        counts = np.array(self.per_frame_count, dtype=np.float32) if self.per_frame_count else np.zeros(1, np.float32)
        peak_idx = int(counts.argmax()) if len(counts) else 0
        durations = []
        for tr in self.tracks.values():
            durations.append((tr.last_frame - tr.first_frame + 1) / self.fps)
        zone_stats = []
        for name, label, _poly, _color in self.zones.zones:
            series = self.per_frame_zone.get(name, [])
            occ = np.array(series, dtype=np.float32) if series else np.zeros(1, np.float32)
            # 该区域人均停留时长 = 该区域总人帧 / 独立人数
            frames_in_zone = sum(t.zone_counts.get(name, 0) for t in self.tracks.values())
            uid = [t.track_id for t in self.tracks.values() if t.zone_counts.get(name, 0) > 0]
            zone_stats.append({
                "zone": name,
                "label": label,
                "visits": len(uid),
                "avg_occupancy": round(float(occ.mean()), 2),
                "peak_occupancy": int(occ.max()) if len(occ) else 0,
                "avg_dwell_sec": round(frames_in_zone / self.fps / max(len(uid), 1), 2),
                "total_dwell_sec": round(frames_in_zone / self.fps, 2),
            })

        return {
            "people_total": len(self.tracks),
            "avg_count": round(float(counts.mean()), 2),
            "peak_count": int(counts.max()) if len(counts) else 0,
            "peak_frame": peak_idx,
            "peak_time_sec": round(peak_idx / self.fps, 2),
            "avg_dwell_sec": round(float(np.mean(durations)), 2) if durations else 0.0,
            "zones": zone_stats,
            "counters": [{"name": c.name, "in": c.in_count, "out": c.out_count} for c in self.counters],
            "per_frame_count": [int(v) for v in self.per_frame_count],
            "per_frame_zone": {k: [int(x) for x in v] for k, v in self.per_frame_zone.items()},
        }

    # ---------- 实时看板时间轴 ----------
    def timeline(self, ground_size=None, time_offset_sec: float = 0.0) -> dict:
        """把「最终汇总」拆成「截至每一帧」的累计序列，供 UE5 按视频时间回放。

        口径与 summary() 完全一致（同一套 counters / zones），所以 UI 上的数字
        一定和报告里的最终值对得上。rows 每行对应一个处理后帧（索引 = 帧号）：
            [当前人数, 累计进, 累计出, 累计人数, 截至此刻峰值, 各区域当前人数...]
        events：逐帧事件（新人物出现 / 进店 / 出店），UI 用它做实时事件流。
        points：每帧的人物地面点位，UI 用它画实时俯视图。
        """
        n_frames = len(self.per_frame_count)
        fps = self.fps
        zone_defs = [{"name": n, "label": l} for n, l, _p, _c in self.zones.zones]
        zone_names = [z["name"] for z in zone_defs]

        ev_by_frame: Dict[int, List[tuple]] = {}
        for f, kind, tid, cname in self.events:
            ev_by_frame.setdefault(f, []).append((kind, tid, cname))
        new_by_frame: Dict[int, int] = {}
        for f in self.first_seen.values():
            new_by_frame[f] = new_by_frame.get(f, 0) + 1

        def zone_at(name: str, f: int) -> int:
            s = self.per_frame_zone.get(name, [])
            return int(s[f]) if f < len(s) else 0

        rows = []
        cum_in = cum_out = people = peak = 0
        for f in range(n_frames):
            for kind, _tid, _cn in ev_by_frame.get(f, []):
                if kind == "in":
                    cum_in += 1
                elif kind == "out":
                    cum_out += 1
            people += new_by_frame.get(f, 0)
            n = int(self.per_frame_count[f])
            peak = max(peak, n)
            rows.append([n, cum_in, cum_out, people, peak]
                        + [zone_at(z, f) for z in zone_names])

        events = []
        for f in sorted(ev_by_frame):
            for kind, tid, cname in ev_by_frame[f]:
                events.append([f, {"new": 0, "in": 1, "out": 2}[kind], int(tid), cname])

        if ground_size is None:
            hp = getattr(getattr(self.cfg, "homography", None), "ground_size_m", None)
            ground_size = (hp[0], hp[1]) if hp else (0.0, 0.0)
        gw, gh = float(ground_size[0]), float(ground_size[1])

        return {
            "fps": fps,
            "frame_count": n_frames,
            "duration_sec": round(n_frames / fps, 3) if n_frames else 0.0,
            "time_offset_sec": float(time_offset_sec),
            "ground_m": [gw, gh],
            "zones": zone_defs,
            "cols": ["count", "in", "out", "people", "peak"] + zone_names,
            "rows": rows,
            "events": events,
            "points": self.per_frame_points,
        }

    def track_table(self) -> List[dict]:
        rows = []
        for tr in sorted(self.tracks.values(), key=lambda t: t.track_id):
            rows.append({
                "id": tr.track_id,
                "first_frame": tr.first_frame,
                "last_frame": tr.last_frame,
                "duration_sec": round((tr.last_frame - tr.first_frame + 1) / self.fps, 2),
                "path_length_m": round(tr.path_length_m(), 2),
                "avg_speed_mps": round(float(np.mean(tr.speeds)) if tr.speeds else 0.0, 2),
                "main_zone": tr.main_zone(),
                "zone_frames": {k: int(v) for k, v in tr.zone_counts.items()},
            })
        return rows
