#!/usr/bin/env python3
"""视频分析管线主入口：视频 -> 检测 -> 跟踪 -> 透视换算 -> 统计 -> JSON/看板。

用法：
    python3 -m src.run_pipeline --config configs/entrance.json
    python3 -m src.run_pipeline --video data/input/canteen.mp4 --detector yolo
    python3 -m src.run_pipeline --config configs/entrance.json --max-frames 200

输出（默认在 out/<name>/）：
    tracks.json      逐帧全量数据
    npc_tracks.json  UE5 蓝图专用（每 NPC 一条轨迹，cm 坐标 + 朝向）
    analytics.json   统计汇总
    tracks.csv       表格版，方便丢进 Excel
    dashboard.html   网页看板（UE5 Web Browser 可直接加载）
    heatmap.png      地面热力图
    annotated.mp4    带检测框/ID/区域叠加的核对视频
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional

import cv2
import numpy as np

if __package__ in (None, ""):   # 支持 python3 src/run_pipeline.py 直接跑
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src import analytics as ana
    from src import detector as det_mod
    from src import exporter as exp
    from src import homography as homo
    from src import postprocess as post
    from src.config import load_config, apply_overrides
    from src.tracker import SimpleTracker
else:
    from . import analytics as ana
    from . import detector as det_mod
    from . import exporter as exp
    from . import homography as homo
    from . import postprocess as post
    from .config import load_config, apply_overrides
    from .tracker import SimpleTracker


# ---------------------------------------------------------------- 地面映射
class GroundMapper:
    """像素脚点 -> 地面米制坐标，带平滑与速度估计。"""

    def __init__(self, H, cfg, fps: float):
        self.H = H
        self.cfg = cfg
        self.fps = max(fps, 1e-3)
        self.last: Dict[int, tuple] = {}      # id -> (x, y)
        self.vel: Dict[int, tuple] = {}       # id -> (vx, vy) m/s
        self.yaw: Dict[int, float] = {}

    def update(self, tid: int, foot_xy_px, ground_h_m: float,
               ue_origin=(0, 0, 0), flip_x=False) -> Optional[dict]:
        g = homo.img_to_ground(self.H, foot_xy_px)
        if g is None or not np.isfinite(g).all():
            return None
        x, y = float(g[0]), float(g[1])

        prev = self.last.get(tid)
        a = max(0.0, min(0.95, float(self.cfg.smooth)))
        if prev is not None and a > 0:
            x = a * prev[0] + (1 - a) * x
            y = a * prev[1] + (1 - a) * y

        vx = vy = 0.0
        if prev is not None:
            dx, dy = (x - prev[0]) * self.fps, (y - prev[1]) * self.fps
            # 跳变保护：单帧位移超过 max_speed 视为误匹配，速度按上限裁剪
            sp = (dx * dx + dy * dy) ** 0.5
            cap = max(0.1, float(self.cfg.max_speed_mps))
            if sp > cap:
                dx, dy = dx / sp * cap, dy / sp * cap
            vx, vy = dx, dy
        self.last[tid] = (x, y)
        self.vel[tid] = (vx, vy)
        speed = (vx * vx + vy * vy) ** 0.5

        # 朝向：速度够大才更新，且按最短角差平滑，避免排队时的微小晃动让 NPC 乱转
        if speed > 0.25:
            new_yaw = homo.yaw_from_velocity_ue(vx, vy)
            prev_yaw = self.yaw.get(tid)
            if prev_yaw is None:
                self.yaw[tid] = new_yaw
            else:
                delta = ((new_yaw - prev_yaw + 180.0) % 360.0) - 180.0
                self.yaw[tid] = ((prev_yaw + 0.35 * delta + 180.0) % 360.0) - 180.0
        yaw = self.yaw.get(tid, 0.0)

        ue = homo.ground_to_ue(x, y, ground_h_m, ue_origin, flip_x)
        return {
            "x_m": round(x, 3), "y_m": round(y, 3),
            "speed_mps": round(speed, 3),
            "ue_cm": [round(ue[0], 1), round(ue[1], 1), round(ue[2], 1)],
            "yaw": round(yaw, 1),
        }


def make_counters(cfg, fps: float):
    """按配置构造计数线，防抖阈值统一从这里下发。

    三处（首遍可视化、出图重放、最终统计）都走这里，避免参数写歪导致
    画面上显示的 in/out 数字和 analytics.json 对不上。
    fps 是「处理后帧率」，与 update 传入的帧号单位一致。
    """
    return [ana.CounterLine(
        c.p1, c.p2, c.name, c.inward_sign,
        debounce_sec=getattr(c, "debounce_sec", 0.5),
        min_travel_m=getattr(c, "min_travel_m", 0.15),
        fps=fps,
    ) for c in cfg.counters]


# ---------------------------------------------------------------- 可视化
def draw_zones(frame, H, zones, counters):
    Hinv = homo.invert_homography(H)
    for name, label, poly, color in zones:
        pts = homo.apply_homography(Hinv, poly).reshape(-1, 1, 2).astype(np.int32)
        overlay = frame.copy()
        cv2.fillPoly(overlay, [pts], color)
        frame[:] = cv2.addWeighted(overlay, 0.13, frame, 0.87, 0)
        cv2.polylines(frame, [pts], True, color, 2, cv2.LINE_AA)
        cx, cy = pts.reshape(-1, 2).mean(axis=0)
        cv2.putText(frame, name, (int(cx) - 20, int(cy)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color, 1, cv2.LINE_AA)

    for c in counters:
        p1 = homo.ground_to_img(H, c.p1.reshape(1, 2))[0]
        p2 = homo.ground_to_img(H, c.p2.reshape(1, 2))[0]
        cv2.line(frame, tuple(p1.astype(int)), tuple(p2.astype(int)), (0, 200, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, f"{c.name} in:{c.in_count} out:{c.out_count}",
                    (int(p1[0]) + 6, int(p1[1]) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1, cv2.LINE_AA)


def draw_actor(frame, bbox, aid, info, zone_label):
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cv2.rectangle(frame, (x1, y1), (x2, y2), (53, 208, 186), 2, cv2.LINE_AA)
    tag = f"#{aid} {info['x_m']:.1f},{info['y_m']:.1f}m"
    (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 8, y1), (12, 25, 40), -1)
    cv2.putText(frame, tag, (x1 + 4, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 235, 220), 1, cv2.LINE_AA)
    if zone_label:
        cv2.putText(frame, zone_label, (x1 + 2, y2 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 190, 90), 1, cv2.LINE_AA)


def draw_hud(frame, seq, fps, count, det_name):
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 34), (12, 20, 32), -1)
    txt = f"frame {seq:05d} | t={seq / max(fps, 1e-3):6.2f}s | in-scene: {count:02d} | detector: {det_name}"
    cv2.putText(frame, txt, (12, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (210, 230, 255), 1, cv2.LINE_AA)


def render_video(video_path, frames_out, H, cfg, fps, step, start_frame_idx,
                 detector_name, out_path, log=print):
    """第二遍出图：不重新检测，只按已算好的结果重放一遍。

    这样做是为了让视频里的 ID 和 JSON 里（轨迹拼接后）的 ID 完全一致 ——
    否则给人核对时会发现"视频上是 16 号，json 里是 13 号"。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log("[warn] 无法重新打开视频，跳过叠加视频输出")
        return None
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sc = cfg.output.video_scale
    size = (max(2, int(w * sc)), max(2, int(h * sc)))
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), max(fps, 1.0), size)

    zone_mgr = ana.ZoneManager(cfg.zones, log=lambda *a, **k: None)
    zone_labels = zone_mgr.labels()
    counters = make_counters(cfg, fps)

    raw = 0
    for fr in frames_out:
        target = start_frame_idx + fr["frame"] * step
        while raw < target:
            if not cap.grab():
                break
            raw += 1
        ok, frame = cap.read()
        if not ok:
            break
        raw += 1

        for a in fr["actors"]:                      # 先更新计数，再画（文本里要显示最新值）
            for c in counters:
                c.update(int(a["id"]), (a["x_m"], a["y_m"]), fr["frame"])
        vis = frame.copy()
        draw_zones(vis, H, zone_mgr.zones, counters)
        for a in fr["actors"]:
            if "_bbox" in a:
                draw_actor(vis, a["_bbox"], a["id"], a, zone_labels.get(a.get("zone") or "", ""))
        draw_hud(vis, fr["frame"], fps, fr["count"], detector_name)
        if sc != 1.0:
            vis = cv2.resize(vis, size)
        writer.write(vis)

    cap.release()
    writer.release()
    return out_path


def save_calibration_check(frame, H, cfg, out_dir):
    """把地面网格反投影回图像，一眼看出透视标定准不准。"""
    img = frame.copy()
    gw, gh = cfg.homography.ground_size_m[0], cfg.homography.ground_size_m[1]
    step = 1.0
    for x in np.arange(0, gw + 1e-6, step):
        p = homo.ground_to_img(H, np.array([[x, 0], [x, gh]], np.float32))
        cv2.line(img, tuple(p[0].astype(int)), tuple(p[1].astype(int)), (80, 160, 255), 1, cv2.LINE_AA)
    for y in np.arange(0, gh + 1e-6, step):
        p = homo.ground_to_img(H, np.array([[0, y], [gw, y]], np.float32))
        cv2.line(img, tuple(p[0].astype(int)), tuple(p[1].astype(int)), (80, 160, 255), 1, cv2.LINE_AA)
    for name, label, poly, color in ana.ZoneManager(cfg.zones).zones:
        pts = homo.apply_homography(homo.invert_homography(H), poly).reshape(-1, 1, 2).astype(np.int32)
        cv2.polylines(img, [pts], True, color, 2, cv2.LINE_AA)
    path = os.path.join(out_dir, "calibration_check.png")
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------- 主流程
def resolve_video(cfg) -> str:
    path = cfg.video.path
    if path and os.path.exists(path):
        return path
    hint_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "input"))
    cands = []
    if os.path.isdir(hint_dir):
        cands = [f for f in os.listdir(hint_dir) if f.lower().endswith((".mp4", ".avi", ".mov", ".mkv"))]
    msg = [f"[error] 找不到视频文件: {path or '(未配置)'}",
           f"        请把素材放到 {hint_dir}/ 下，然后：",
           f"        python3 -m src.run_pipeline --video {hint_dir}/<你的视频>.mp4 --config configs/entrance.json"]
    if cands:
        msg.append(f"        该目录下现有视频: {cands}")
    print("\n".join(msg))
    sys.exit(2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="饭堂人流量视频分析管线")
    ap.add_argument("--config", default="configs/entrance.json")
    ap.add_argument("--video", default=None, help="覆盖配置里的视频路径")
    ap.add_argument("--out", default=None, help="覆盖输出目录")
    ap.add_argument("--detector", default=None, choices=["auto", "yolo", "motion"])
    ap.add_argument("--max-frames", type=int, default=None, help="只处理前 N 帧（快速试跑）")
    ap.add_argument("--frame-step", type=int, default=None, help="抽帧步长，默认 1")
    ap.add_argument("--no-video", action="store_true", help="不输出叠加视频（更快）")
    ap.add_argument("--no-stitch", action="store_true", help="关闭轨迹拼接后处理")
    ap.add_argument("--npc-keyframe-step", type=int, default=1, help="npc_tracks.json 关键帧抽稀步长")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    log = (lambda *a, **k: None) if args.quiet else print
    cfg = load_config(args.config)
    cfg = apply_overrides(cfg, args)

    video_path = resolve_video(cfg)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[error] 无法打开视频: {video_path}")
        sys.exit(2)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    if not np.isfinite(src_fps) or src_fps <= 0:
        src_fps = 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if cfg.video.start_sec > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, cfg.video.start_sec * 1000)

    step = max(1, int(cfg.video.frame_step))
    fps = src_fps / step

    # --- 标定 ---
    gw, gh = cfg.homography.ground_size_m
    if len(cfg.homography.image_points) == 4 and len(cfg.homography.ground_points) == 4:
        H = homo.build_homography(cfg.homography.image_points, cfg.homography.ground_points)
        err = homo.reprojection_error(H, cfg.homography.image_points, cfg.homography.ground_points)
        log(f"[calib] 四点标定已加载，重投影误差 {err:.4f} m（4 个角点应严格为 0，非 0 说明点没配好）")
    else:
        H = homo.build_homography([[0, 0], [width, 0], [width, height], [0, height]],
                                  [[0, 0], [gw, 0], [gw, gh], [0, gh]])
        log("[calib] ⚠ 未配置四点标定，暂用「整帧=地面矩形」近似，仅用于跑通链路，"
            "真实视频请先用 tools/calibrate_homography.py 标定")

    # 尺度一致性检查：把 ground_size_m 从示例的 12x9 改成实测读数后，
    # 配置里旧的示例 zones/counters 坐标会整体飞出场地，表现为区域不显示、热力图空白。
    _pts = [p for z in cfg.zones for p in z.polygon] + \
           [p for c in cfg.counters for p in (c.p1, c.p2)]
    _outside = [p for p in _pts
                if not (-0.01 <= p[0] <= gw + 0.01 and -0.01 <= p[1] <= gh + 0.01)]
    if _outside:
        log(f"[calib] ⚠ 有 {len(_outside)} 个 zones/counters 坐标超出场地 {gw}x{gh} m"
            f"（例如 {_outside[0]}），多半是按旧的 ground_size_m 写的。"
            f"请用 tools/pick_zones.py 在当前标定下重新点，否则区域和计数线不会出现在画面里。")

    out_dir = cfg.output.out_dir
    os.makedirs(out_dir, exist_ok=True)

    # --- 组件 ---
    detector = det_mod.build_detector(cfg.detector, log=log)
    tracker = SimpleTracker(cfg.tracker)
    mapper = GroundMapper(H, cfg.tracker, fps)
    stats = ana.Analytics(cfg, fps, log=log)
    stats.set_heatmap(gw, gh)
    for c in make_counters(cfg, fps):
        stats.add_counter(c)

    vpath = os.path.join(out_dir, "annotated.mp4")
    start_frame_idx = int(round(cfg.video.start_sec * src_fps))

    frames_out: List[dict] = []
    seq = 0
    raw_idx = 0
    t0 = time.time()
    first_frame_saved = False

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if raw_idx % step != 0:
            raw_idx += 1
            continue
        raw_idx += 1

        if not first_frame_saved:
            first_frame_saved = True

        dets = detector.detect(frame, seq)
        tracks = tracker.update(dets, frame)
        actors = []
        for tr in tracks:
            fx, fy = homo.foot_point(tr.bbox, cfg.detector.motion.foot_offset_ratio
                                     if isinstance(detector, det_mod.MotionPersonDetector) else 0.0)
            info = mapper.update(tr.id, (fx, fy), gh, cfg.homography.ue_origin_cm, cfg.homography.flip_x)
            if info is None:
                continue
            info["id"] = int(tr.id)
            info["_bbox"] = [round(float(v), 1) for v in tr.bbox]   # 临时字段，仅供出图，导出前删除
            actors.append((tr, info))

        frame_actors = []
        for tr, info in actors:
            frame_actors.append(info)
        # 可视化用的轻量更新：逐帧标区域 + 驱动进出计数线（轨迹统计放到拼接后统一做）
        for info in frame_actors:
            info["zone"] = stats.zones.locate(info["x_m"], info["y_m"])
            for c in stats.counters:
                c.update(int(info["id"]), (info["x_m"], info["y_m"]), seq)
        zone_labels = stats.zones.labels()

        frames_out.append({
            "frame": seq,
            "t": round(seq / fps, 3),
            "count": len(frame_actors),
            "actors": frame_actors,
        })

        seq += 1
        if seq % 50 == 0 and not args.quiet:
            el = time.time() - t0
            print(f"  ... {seq} frames processed  ({(seq / max(el, 1e-6)):.1f} fps)", flush=True)
        if cfg.video.max_frames and seq >= cfg.video.max_frames:
            break
        if cfg.video.end_sec is not None and seq / fps >= cfg.video.end_sec:
            break

    cap.release()

    elapsed = time.time() - t0
    if seq == 0:
        print("[error] 视频里没读到任何帧，检查文件是否损坏")
        sys.exit(3)

    # --- 轨迹拼接：把断成几截的同一个人接回来（减少 UE5 里 NPC 的消失/重生）---
    if not args.no_stitch:
        post.stitch_tracks(frames_out, fps, log=log)

    # --- 用拼接后的 ID 重算统计（纯内存重放，几十毫秒）---
    stats_final = ana.Analytics(cfg, fps, log=log)
    stats_final.set_heatmap(gw, gh)
    for c in make_counters(cfg, fps):
        stats_final.add_counter(c)
    for fr in frames_out:
        stats_final.update_frame(fr["frame"], fr["actors"])

    # --- 出图：用拼接后的 ID 重放一遍 ---
    if cfg.output.save_video and not args.no_video:
        render_video(video_path, frames_out, H, cfg, fps, step, start_frame_idx,
                     detector.name, vpath, log=log)

    # 临时字段（bbox）不写进交付文件
    for fr in frames_out:
        for a in fr["actors"]:
            a.pop("_bbox", None)

    # --- 汇总导出 ---
    summary = stats_final.summary()
    track_rows = stats_final.track_table()

    meta = {
        "source_video": os.path.basename(video_path),
        "source_path": video_path,
        "video_fps": round(src_fps, 3),
        "processed_fps": round(fps, 3),
        "frame_step": step,
        "frame_width": width,
        "frame_height": height,
        "frame_count": seq,
        "duration_sec": round(seq / fps, 2),
        "detector": detector.name,
        "ground_plane": {"width_m": gw, "height_m": gh, "cell_m": 0.25},
        "homography": np.asarray(H).round(8).tolist(),
        "calibration": {
            "image_points": cfg.homography.image_points,
            "ground_points": cfg.homography.ground_points,
            "calibrated": bool(len(cfg.homography.image_points) == 4),
        },
        "elapsed_sec": round(elapsed, 2),
        "throughput_fps": round(seq / max(elapsed, 1e-6), 1),
    }

    zone_payload = [{"name": n, "label": l, "polygon_m": p.tolist(), "color": c}
                    for n, l, p, c in stats_final.zones.zones]

    tracks_json = exp.export_tracks(out_dir, exp.build_tracks_payload(meta, zone_payload, frames_out))
    npc_json = exp.export_npc_tracks(out_dir, frames_out, meta,
                                     keyframe_step=max(1, args.npc_keyframe_step),
                                     ground_h_m=gh, ue_origin_cm=cfg.homography.ue_origin_cm,
                                     flip_x=cfg.homography.flip_x)
    analytics_json = exp.export_analytics(out_dir, summary, track_rows)

    csv_path = None
    if cfg.output.save_csv:
        csv_path = exp.export_csv(out_dir, frames_out)

    heat_path = None
    if cfg.output.save_heatmap and stats_final.heat is not None:
        heat_path = os.path.join(out_dir, "heatmap.png")
        img = stats_final.heat.to_image()
        if float(stats_final.heat.grid.max()) <= 0:
            # 一帧都没落到地面上（标定错/人不在标定范围内），给个明确提示，别给一张黑图
            h_img, w_img = img.shape[:2]
            cv2.putText(img, "no samples on ground plane - check homography", (16, h_img // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)
        # 加一点坐标刻度，方便和 UE 里对位
        img = cv2.copyMakeBorder(img, 26, 8, 8, 8, cv2.BORDER_CONSTANT, value=(40, 26, 18))
        cv2.putText(img, f"ground heatmap  {gw}x{gh} m  (0.25 m/cell)", (10, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (235, 225, 205), 1, cv2.LINE_AA)
        cv2.imwrite(heat_path, img)

    if first_frame_saved:
        cap2 = cv2.VideoCapture(video_path)
        ok, f0 = cap2.read()
        if ok:
            save_calibration_check(f0, H, cfg, out_dir)
        cap2.release()

    dash = None
    if cfg.output.save_dashboard:
        dash = exp.export_dashboard(out_dir, summary, track_rows, meta,
                                    heatmap_png=heat_path or "", video_name="annotated.mp4")

    # 实时数据（供 ui/index.html 消费；看板另由 tools/build_ui.py 生成）：
    # 与 npc_tracks.json 同源的逐帧时间轴，帧号 f 两边完全对齐。
    realtime_json = None
    if cfg.output.save_realtime:
        tl = stats_final.timeline(ground_size=(gw, gh),
                                   time_offset_sec=cfg.video.start_sec)
        counter_payload = [{"name": c.name, "p1": list(c.p1), "p2": list(c.p2),
                            "inward_sign": c.inward_sign} for c in cfg.counters]
        realtime_json = exp.export_realtime(
            out_dir, tl, meta, zone_payload=zone_payload,
            counter_payload=counter_payload)

    # --- 控制台摘要 ---
    print("\n" + "=" * 62)
    print("  饭堂门口 · 人流量分析完成")
    print("=" * 62)
    print(f"  视频          : {os.path.basename(video_path)}  {width}x{height} @ {src_fps:.1f}fps")
    print(f"  处理          : {seq} 帧 / {meta['duration_sec']}s，检测器={detector.name}，"
          f"耗时 {elapsed:.1f}s ({meta['throughput_fps']} fps)")
    print(f"  累计人数      : {summary['people_total']} 人（去重后轨迹数）")
    print(f"  峰值同框      : {summary['peak_count']} 人 @ {summary['peak_time_sec']}s")
    print(f"  平均同框      : {summary['avg_count']} 人")
    print(f"  人均停留      : {summary['avg_dwell_sec']} s")
    for c in summary["counters"]:
        net = c["in"] - c["out"]
        print(f"  进出计数[{c['name']}] : 进 {c['in']} / 出 {c['out']} / 净流入 {net:+d}")
    print("  " + "-" * 58)
    print("  门口区域统计：")
    for z in summary["zones"]:
        print(f"    {z['label']:<10} 到访 {z['visits']:>3} 人 | 平均占用 {z['avg_occupancy']:>5.2f} | "
              f"人均停留 {z['avg_dwell_sec']:>5.1f}s")
    print("  " + "-" * 58)
    print(f"  输出目录      : {out_dir}")
    for p in [tracks_json, npc_json, analytics_json, csv_path, heat_path, dash, realtime_json]:
        if p:
            print(f"    - {os.path.basename(p):<20} {os.path.getsize(p) / 1024:8.1f} KB")
    if realtime_json:
        print("  实时数据      : realtime.json → 看板数据源，字段见 docs/realtime_data_contract.md")
        print("  实时看板      : python3 tools/build_ui.py 生成 dashboard_live.html")
    print("=" * 62 + "\n")
    return out_dir


if __name__ == "__main__":
    main()
