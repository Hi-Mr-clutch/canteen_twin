#!/usr/bin/env python3
"""冒烟测试：不依赖 pytest，直接 `python3 tests/test_smoke.py` 跑。

覆盖点（前 6 项纯逻辑/内存数据，不需要任何视频素材）：
  1. 单应变换与逆变换自洽（像素 <-> 地面）
  2. 脚点提取
  3. UE 坐标映射与朝向
  4. 跟踪器：单人匀速移动应保持同一个 ID
  5. 跟踪器：两个人交叉经过不串 ID
  6. 检测器：内存里画个移动色块，确认前景差分能出框
  7. 导出：JSON schema 关键字段齐全
  8. 实时时间轴：逐帧累计数与最终汇总一致、事件流方向正确
  9. 实时数据：导出 realtime.json，字段/事件/帧号符合数据契约
  10. 计数防抖：脚点在门线抖动不重复计数、真正往返能分别计数、可关闭
  11. 全链路：data/input 里有视频就跑 40 帧 mini pipeline，没有则跳过
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import homography as homo            # noqa: E402
from src import exporter as exp               # noqa: E402
from src.config import load_config            # noqa: E402
from src.detector import Detection            # noqa: E402
from src.tracker import SimpleTracker         # noqa: E402

PASS, FAIL = [], []


SKIPPED = []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  [PASS] {name}")
    except Skip as exc:
        SKIPPED.append(name)
        print(f"  [SKIP] {name}: {exc}")
    except Exception as exc:
        FAIL.append((name, exc))
        print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")


# ------------------------------------------------------------------ 用例
def t_homography():
    ipts = [[102, 711], [1178, 711], [923, 310], [357, 310]]
    gpts = [[0, 0], [12, 0], [12, 9], [0, 9]]
    H = homo.build_homography(ipts, gpts)
    back = homo.ground_to_img(H, np.array(gpts, np.float32))
    err = np.abs(back - np.array(ipts, np.float32)).max()
    assert err < 1e-3, f"往返误差过大 {err}"


def t_foot_point():
    x, y = homo.foot_point((100, 50, 140, 210))
    assert abs(x - 120) < 1e-6 and abs(y - 210) < 1e-6, (x, y)
    x2, y2 = homo.foot_point((100, 50, 140, 210), -0.1)
    assert y2 < 210


def t_ue_mapping():
    ue = homo.ground_to_ue(3.0, 4.0, 9.0)
    assert ue == (-500.0, 300.0, 0.0), ue          # X=(4-9)*100, Y=3*100
    # 进店（y_m 增大）应朝 UE 的 +X
    assert abs(homo.yaw_from_velocity_ue(0.0, 1.0)) < 1e-6
    # 出店 = 朝 -X
    assert abs(abs(homo.yaw_from_velocity_ue(0.0, -1.0)) - 180.0) < 1e-6
    # 画面右 = UE 的 +Y
    assert abs(homo.yaw_from_velocity_ue(1.0, 0.0) - 90.0) < 1e-6
    # 画面左 = UE 的 -Y
    assert abs(homo.yaw_from_velocity_ue(-1.0, 0.0) + 90.0) < 1e-6


def _cfg():
    return load_config(os.path.join(ROOT, "configs", "entrance.json"))


class Skip(Exception):
    """素材没准备好时跳过该用例（不算失败）。"""


def t_tracker_single():
    cfg = _cfg()
    trk = SimpleTracker(cfg.tracker)
    ids = set()
    for i in range(40):
        x = 100 + i * 6
        dets = [Detection((x, 100, x + 40, 220), 0.9)]
        for t in trk.update(dets):
            ids.add(t.id)
    assert len(ids) == 1, f"单人移动应只有 1 个 ID，实际 {ids}"


def t_tracker_cross():
    cfg = _cfg()
    trk = SimpleTracker(cfg.tracker)
    seen = []
    for i in range(30):
        a = (100 + i * 12, 100, 140 + i * 12, 220)
        b = (520 - i * 12, 100, 560 - i * 12, 220)
        tracks = trk.update([Detection(a, 0.9), Detection(b, 0.9)])
        seen.append(sorted(t.id for t in tracks))
    # 每帧应稳定返回 2 条轨迹（中间可能短暂 1 条，但不应爆炸式增长）
    assert max(len(s) for s in seen) == 2, seen[:8]
    assert len(set(t for s in seen for t in s)) <= 4, "交叉时 ID 数量应保持克制"


def t_detector_motion():
    """不依赖素材：内存里画个移动的亮块，前景差分应该能框住它。"""
    import cv2
    from src.detector import MotionPersonDetector
    cfg = _cfg()
    det = MotionPersonDetector(cfg.detector.motion)
    base = np.full((240, 320, 3), 110, np.uint8)
    got = 0
    for i in range(40):
        frame = base.copy()
        x = 30 + i * 5
        cv2.rectangle(frame, (x, 80), (x + 34, 200), (205, 205, 208), -1)
        got += len(det.detect(frame, i))
    assert got > 0, "移动色块应被检测到"


def t_export_schema():
    tmp = tempfile.mkdtemp()
    meta = {"processed_fps": 20.0, "frame_count": 2, "duration_sec": 0.1,
            "frame_width": 640, "frame_height": 360, "detector": "motion",
            "ground_plane": {"width_m": 12, "height_m": 9, "cell_m": 0.25},
            "source_video": "x.mp4"}
    frames = [{"frame": 0, "t": 0.0, "count": 1, "actors": [
        {"id": 1, "x_m": 1.0, "y_m": 2.0, "speed_mps": 0.5, "zone": "dining",
         "ue_cm": [700.0, 100.0, 0.0], "yaw": 90.0}]}]
    p = exp.export_tracks(tmp, exp.build_tracks_payload(meta, [], frames))
    n = exp.export_npc_tracks(tmp, frames, meta, ground_h_m=9.0)
    d = json.load(open(p, encoding="utf-8"))
    assert d["schema"] == exp.SCHEMA_TRACKS and len(d["frames"]) == 1
    assert d["frames"][0]["actors"][0]["ue_cm"][2] == 0.0
    nd = json.load(open(n, encoding="utf-8"))
    assert nd["schema"] == exp.SCHEMA_NPC and nd["npcs"][0]["samples"][0]["x"] == 700.0


def _mini_analytics():
    """3 帧小场景：1 号进→出，2 号进；用于验证逐帧累计口径。

    这里显式关闭防抖（debounce_sec=0, min_travel_m=0），因为相邻帧的进出
    是本用例刻意构造的；防抖行为由 t_counter_debounce 单独覆盖。
    """
    from src import analytics as ana
    cfg = _cfg()
    a = ana.Analytics(cfg, 10.0)
    a.set_heatmap(12, 9)
    a.add_counter(ana.CounterLine([0, 0], [10, 0], "door", 1,
                                  debounce_sec=0, min_travel_m=0, fps=10.0))
    a.update_frame(0, [{"id": 1, "x_m": 1.0, "y_m": -0.5, "speed_mps": 0.5}])
    a.update_frame(1, [{"id": 1, "x_m": 1.0, "y_m": 0.5, "speed_mps": 0.5},
                       {"id": 2, "x_m": 2.0, "y_m": -0.5, "speed_mps": 0.5}])
    a.update_frame(2, [{"id": 1, "x_m": 1.0, "y_m": -0.5, "speed_mps": 0.5},
                       {"id": 2, "x_m": 2.0, "y_m": 0.5, "speed_mps": 0.5}])
    return a


def t_timeline():
    a = _mini_analytics()
    tl = a.timeline(ground_size=(12, 9))
    assert tl["frame_count"] == 3 and tl["fps"] == 10.0
    assert [r[0] for r in tl["rows"]] == [1, 2, 2], "当前人数"
    assert [r[1] for r in tl["rows"]] == [0, 1, 2], "累计进店"
    assert [r[2] for r in tl["rows"]] == [0, 0, 1], "累计出店"
    assert [r[3] for r in tl["rows"]] == [1, 2, 2], "累计人数"
    assert len(tl["points"]) == 3 and len(tl["points"][1]) == 2
    kinds = [e[1] for e in tl["events"]]
    assert kinds.count(0) == 2 and kinds.count(1) == 2 and kinds.count(2) == 1, kinds
    s = a.summary()
    assert tl["rows"][-1][1] == s["counters"][0]["in"], "最后一帧累计进店应等于报告"
    assert tl["rows"][-1][2] == s["counters"][0]["out"]
    assert tl["rows"][-1][3] == s["people_total"]


def t_realtime_export():
    a = _mini_analytics()
    tl = a.timeline(ground_size=(12, 9))
    tmp = tempfile.mkdtemp()
    meta = {"source_video": "x.mp4", "detector": "motion",
            "frame_width": 640, "frame_height": 360}
    p = exp.export_realtime(
        tmp, tl, meta,
        zone_payload=[{"name": z["name"], "label": z["label"],
                       "polygon_m": [[0, 0], [12, 0], [12, 9], [0, 9]],
                       "color": [60, 170, 255]} for z in tl["zones"]],
        counter_payload=[{"name": "door", "p1": [0, 9], "p2": [12, 9], "inward_sign": 1}])
    d = json.load(open(p, encoding="utf-8"))
    assert os.path.basename(p) == "realtime.json"
    assert d["schema"] == exp.SCHEMA_REALTIME
    assert d["meta"]["frame_count"] == 3 and d["meta"]["fps"] == 10.0
    assert [fr["count"] for fr in d["frames"]] == [1, 2, 2]
    assert [fr["in"] for fr in d["frames"]] == [0, 1, 2]
    assert [fr["out"] for fr in d["frames"]] == [0, 0, 1]
    assert d["frames"][-1]["people"] == 2 and d["frames"][-1]["net"] == 1
    types = [e["type"] for e in d["events"]]
    assert types.count("in") == 2 and types.count("out") == 1 and types.count("new") == 2, types
    assert d["frames"][1]["actors"][0]["id"] in (1, 2)
    assert d["frames"][1]["events"][0]["type"] == "in"
    assert d["ground_m"] == [12.0, 9.0]


def t_counter_debounce():
    """脚点在门线附近抖动会被反复计数，防抖应压掉；真正往返仍能分别计数。"""
    from src import analytics as ana

    # 门线 y=0，x∈[0,10]；y<0 为负侧、y>0 为正侧，负→正算「进」
    def make(**kw):
        return ana.CounterLine([0, 0], [10, 0], "door", 1, fps=10.0, **kw)

    # 场景 1：同一人在门线附近反复横跨 ±0.03m（位移远小于 0.15m），持续 30 帧
    c = make(debounce_sec=0.5, min_travel_m=0.15)   # 0.5s@10fps = 5 帧
    for f in range(30):
        c.update(1, (5.0, -0.03 if f % 2 == 0 else 0.03), f)
    assert c.in_count + c.out_count <= 1, \
        f"抖动应被抑制为最多 1 次，实际 {c.in_count}/{c.out_count}"

    # 场景 2：关闭防抖应回到旧行为（同样抖动会记很多次）
    c0 = make(debounce_sec=0, min_travel_m=0)
    for f in range(30):
        c0.update(1, (5.0, -0.03 if f % 2 == 0 else 0.03), f)
    assert c0.in_count + c0.out_count >= 20, "关闭防抖后应恢复重复计数"

    # 场景 3：真正「走进去停留再走出来」应分别记 in / out
    c2 = make(debounce_sec=0.5, min_travel_m=0.15)
    for f in range(0, 6):                       # 从负侧走到正侧远处
        c2.update(7, (5.0, -0.8 + f * 0.3), f)
    for f in range(6, 20):                      # 停留（间隔拉开）
        c2.update(7, (5.0, 1.0), f)
    for f in range(20, 26):                     # 再走回负侧，穿线 → out
        c2.update(7, (5.0, 1.0 - (f - 19) * 0.3), f)
    assert c2.in_count == 1 and c2.out_count == 1, \
        f"一次往返应 in=1/out=1，实际 {c2.in_count}/{c2.out_count}"

    # 场景 4：配置里的两个阈值确实被读取（CounterCfg 有默认值且可覆盖）
    from src.config import CounterCfg
    assert CounterCfg().debounce_sec == 0.5 and CounterCfg().min_travel_m == 0.15
    assert CounterCfg(debounce_sec=0.7, min_travel_m=0.25).debounce_sec == 0.7


def _first_input_video():
    d = os.path.join(ROOT, "data", "input")
    if not os.path.isdir(d):
        return None
    for f in sorted(os.listdir(d)):
        if f.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
            return os.path.join(d, f)
    return None


def t_end_to_end_mini():
    """真正跑一遍管线。素材放在 data/input/ 下时才会执行。"""
    video = _first_input_video()
    if not video:
        raise Skip("data/input/ 下还没有视频")
    out = tempfile.mkdtemp()
    r = subprocess.run(
        [sys.executable, "-m", "src.run_pipeline", "--config",
         os.path.join(ROOT, "configs", "entrance.json"), "--video", video,
         "--out", out, "--max-frames", "40", "--detector", "motion", "--no-video", "--quiet"],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout[-600:] + r.stderr[-800:])
    for f in ["tracks.json", "npc_tracks.json", "analytics.json",
              "dashboard.html", "realtime.json"]:
        assert os.path.exists(os.path.join(out, f)), f"{f} 未生成"


def main():
    print("=" * 56)
    print("  canteen_twin 冒烟测试")
    print("=" * 56)
    check("单应变换自洽", t_homography)
    check("脚点提取", t_foot_point)
    check("UE 坐标映射", t_ue_mapping)
    check("跟踪：单人保持 ID", t_tracker_single)
    check("跟踪：两人交叉不串 ID", t_tracker_cross)
    check("检测器：移动色块出框", t_detector_motion)
    check("导出：JSON schema", t_export_schema)
    check("实时时间轴：逐帧累计与汇总一致", t_timeline)
    check("实时数据：realtime.json 数据契约", t_realtime_export)
    check("计数防抖：抖动抑制/往返可计/可关闭", t_counter_debounce)
    check("全链路：40 帧 mini pipeline", t_end_to_end_mini)

    print("-" * 56)
    print(f"  通过 {len(PASS)} / {len(PASS) + len(FAIL)}"
          + (f"，跳过 {len(SKIPPED)}（{SKIPPED}）" if SKIPPED else ""))
    if FAIL:
        for name, exc in FAIL:
            print(f"  失败：{name} -> {exc}")
        sys.exit(1)
    print("  全部通过 ✅")


if __name__ == "__main__":
    main()
