#!/usr/bin/env python3
"""可视化点选：在画面上直接点出计数线和区域，自动换算成地面米制坐标。

**不需要卷尺**。前提是 homography 已经标好（tools/calibrate_homography.py），
剩下的「门洞在哪、门前缓冲带多宽」全部用鼠标点，程序反算成米。
画面上会叠加 1m 网格，点的时候能直接看出点在了地面上第几米。

用法
----
# 1) 点进出计数线（点 3 下：线的一端 → 另一端 → 门内方向任意一点）
python3 tools/pick_zones.py --config configs/entrance.json \
        --video data/input/door_front.mp4 --mode counter --name door

# 2) 点门前区域（按顺序点 >=3 个角，回车结束）
python3 tools/pick_zones.py --config configs/entrance.json \
        --video data/input/door_front.mp4 --mode zone \
        --name door_front --label 门前缓冲区

操作：鼠标左键加点，u 撤销上一点，回车确认，ESC 退出。

没有桌面环境时改用坐标参数：
    --line "x1,y1 x2,y2" --inward "x3,y3"      # 计数线两点 + 门内方向一点
    --polygon "x1,y1 x2,y2 x3,y3 x4,y4"        # 区域多边形
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import homography as homo            # noqa: E402
from src.config import load_config            # noqa: E402

ZONE_COLORS = [[60, 170, 255], [255, 190, 80], [120, 240, 160], [230, 120, 220]]   # BGR


def parse_pts(text: str):
    out = []
    for tok in text.replace(";", " ").split():
        x, y = tok.split(",")
        out.append([float(x), float(y)])
    return out


def draw_grid(img, H, gw, gh):
    """把 1m 地面网格投影回画面，点选时用来判断位置。"""
    for x in np.arange(0, gw + 1e-6, 1.0):
        p = homo.ground_to_img(H, np.array([[x, 0], [x, gh]], np.float32))
        cv2.line(img, tuple(p[0].astype(int)), tuple(p[1].astype(int)), (70, 120, 90), 1, cv2.LINE_AA)
        q = homo.ground_to_img(H, np.array([[x, 0]], np.float32))[0]
        cv2.putText(img, f"{x:.0f}", (int(q[0]) + 2, int(q[1]) - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (110, 180, 140), 1, cv2.LINE_AA)
    for y in np.arange(0, gh + 1e-6, 1.0):
        p = homo.ground_to_img(H, np.array([[0, y], [gw, y]], np.float32))
        cv2.line(img, tuple(p[0].astype(int)), tuple(p[1].astype(int)), (70, 120, 90), 1, cv2.LINE_AA)
        q = homo.ground_to_img(H, np.array([[0, y]], np.float32))[0]
        cv2.putText(img, f"{y:.0f}", (int(q[0]) + 2, int(q[1]) - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (110, 180, 140), 1, cv2.LINE_AA)


def interactive(frame, H, mode, gw, gh):
    pts = []
    need = 3 if mode == "counter" else 3            # counter 要 3 点（含方向），zone 至少 3 点
    hint = ("click: line end 1 -> line end 2 -> one point INSIDE the door (direction of entering)"
            if mode == "counter" else "click corners in order (>=3), ENTER to finish")
    win = f"pick {mode} - {hint}   u=undo  ENTER=ok  ESC=quit"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            pts.append((float(x), float(y)))

    cv2.setMouseCallback(win, on_mouse)
    while True:
        vis = frame.copy()
        draw_grid(vis, H, gw, gh)
        for i, (x, y) in enumerate(pts):
            cv2.circle(vis, (int(x), int(y)), 5, (0, 60, 255), -1)
            cv2.putText(vis, str(i + 1), (int(x) + 7, int(y) - 7),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 60, 255), 2)
        if len(pts) >= 2:
            if mode == "counter":
                cv2.line(vis, tuple(np.int32(pts[0])), tuple(np.int32(pts[1])), (0, 220, 255), 2, cv2.LINE_AA)
            else:
                cv2.polylines(vis, [np.int32(pts)], False, (0, 220, 255), 2, cv2.LINE_AA)
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 46), (16, 22, 32), -1)
        cv2.putText(vis, hint, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 220, 255), 1, cv2.LINE_AA)
        cv2.putText(vis, f"points: {len(pts)}   u=undo  ENTER=ok  ESC=quit", (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 235, 220), 1, cv2.LINE_AA)
        cv2.imshow(win, vis)
        k = cv2.waitKey(20) & 0xFF
        if k == 27:
            cv2.destroyAllWindows()
            raise SystemExit("已取消")
        if k == ord("u") and pts:
            pts.pop()
        if k in (13, 10):
            if len(pts) >= need:
                cv2.destroyAllWindows()
                return pts
            print(f"  还差 {need - len(pts)} 个点")


def to_ground(H, px, gw, gh, tol=0.5):
    """像素 -> 地面米制。

    单应是全局的，点到墙上/天上也算得出一个数（往往是几百米），所以必须做范围检查，
    否则会把离谱的坐标写进配置。tol 允许超出标定矩形边界 50%（门洞常常就在边上）。
    """
    g = homo.img_to_ground(H, np.array([px], np.float32))[0]
    if not np.isfinite(g).all():
        return None
    x, y = float(g[0]), float(g[1])
    if not (-tol * gw <= x <= (1 + tol) * gw and -tol * gh <= y <= (1 + tol) * gh):
        return None
    return [round(x, 2), round(y, 2)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--config", default="configs/entrance.json", help="提供 homography 的配置文件")
    ap.add_argument("--mode", required=True, choices=["counter", "zone"])
    ap.add_argument("--name", required=True, help="区域/计数线的 name（英文，会画在视频上）")
    ap.add_argument("--label", default="", help="区域的中文标签（只用于看板）")
    ap.add_argument("--color-index", type=int, default=0)
    ap.add_argument("--time-sec", type=float, default=0.0, help="取第几秒的帧来点选")
    ap.add_argument("--line", default=None, help='"x1,y1 x2,y2" 计数线两端像素（无 GUI 时用）')
    ap.add_argument("--inward", default=None, help='"x,y" 门内方向一点（无 GUI 时用）')
    ap.add_argument("--polygon", default=None, help='"x1,y1 x2,y2 ..." 区域多边形像素（无 GUI 时用）')
    ap.add_argument("--inward-sign", type=int, default=None, help="直接指定 +1/-1，跳过方向点")
    ap.add_argument("--out", default=None, help="把结果写成 json 文件")
    args = ap.parse_args()

    cfg = load_config(args.config)
    gw, gh = cfg.homography.ground_size_m
    H = homo.build_homography(cfg.homography.image_points, cfg.homography.ground_points)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"打不开视频：{args.video}")
    if args.time_sec > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, args.time_sec * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("读不到视频帧")

    # ---------- 取像素点 ----------
    if args.mode == "counter" and args.line:
        pts = parse_pts(args.line)
        if len(pts) != 2:
            raise SystemExit("--line 需要 2 个点")
    elif args.mode == "zone" and args.polygon:
        pts = parse_pts(args.polygon)
        if len(pts) < 3:
            raise SystemExit("--polygon 至少 3 个点")
    else:
        try:
            pts = interactive(frame, H, args.mode, gw, gh)
        except SystemExit:
            raise
        except Exception as exc:
            raise SystemExit(f"无法打开交互窗口（{exc}）。请改用 --line / --polygon 指定像素坐标。")

    # ---------- 换算成米 ----------
    ground = []
    for p in pts:
        g = to_ground(H, p, gw, gh)
        if g is None:
            raise SystemExit(f"点 ({p[0]:.0f}, {p[1]:.0f}) 不在标定的地面范围内，无法换算成米。"
                             f"请点地面上的位置（画面里的地面区域）。")
        ground.append(g)

    if args.mode == "counter":
        p1, p2 = ground[0], ground[1]
        if args.inward_sign is not None:
            sign = args.inward_sign
        else:
            if len(ground) >= 3:
                inward_g = ground[2]
            elif args.inward:
                inward_g = to_ground(H, parse_pts(args.inward)[0], gw, gh)
                if inward_g is None:
                    raise SystemExit("--inward 点不在标定的地面范围内")
            else:
                raise SystemExit("需要门内方向点：交互时点第 3 下，或给 --inward / --inward-sign")
            # 叉积符号 = 门内方向在线段哪一侧；人从另一侧穿过即为「进」
            a = np.array(p2) - np.array(p1)
            b = np.array(inward_g) - np.array(p1)
            sign = 1 if (a[0] * b[1] - a[1] * b[0]) > 0 else -1
        item = {"name": args.name, "p1": p1, "p2": p2, "inward_sign": sign}
        check = draw_counter_check(frame, H, item, gw, gh)
        desc = f"计数线 {args.name}: {p1} -> {p2}  长度 {np.hypot(p2[0]-p1[0], p2[1]-p1[1]):.2f} m"
    else:
        poly = ground
        item = {"name": args.name, "label": args.label or args.name, "polygon": poly,
                "color": ZONE_COLORS[args.color_index % len(ZONE_COLORS)]}
        check = draw_zone_check(frame, H, item, gw, gh)
        area = 0.5 * abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                             for i in range(len(poly))))
        desc = f"区域 {item['label']}: {len(poly)} 个角，面积约 {area:.2f} m²"

    print(f"[ok] {desc}")
    print(f"[i] 校验图：{check}  ← 打开看一眼，边界贴不贴地面")
    payload = [item]
    print("\n把下面这段加进 config 的 " + ("counters" if args.mode == "counter" else "zones") + " 数组：")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        print(f"[ok] 已写入 {args.out}")


def _overlay_poly(frame, H, poly, color, thickness=2, fill=False):
    pts = homo.ground_to_img(H, np.asarray(poly, np.float32)).reshape(-1, 1, 2).astype(np.int32)
    if fill:
        ov = frame.copy()
        cv2.fillPoly(ov, [pts], color)
        cv2.addWeighted(ov, 0.2, frame, 0.8, 0, dst=frame)
    cv2.polylines(frame, [pts], True, color, thickness, cv2.LINE_AA)
    return pts


def draw_counter_check(frame, H, item, gw, gh):
    os.makedirs("out", exist_ok=True)
    img = frame.copy()
    draw_grid(img, H, gw, gh)
    p1 = homo.ground_to_img(H, np.array([item["p1"]], np.float32))[0]
    p2 = homo.ground_to_img(H, np.array([item["p2"]], np.float32))[0]
    cv2.line(img, tuple(p1.astype(int)), tuple(p2.astype(int)), (0, 220, 255), 3, cv2.LINE_AA)
    cv2.putText(img, item["name"], (int(p1[0]) + 6, int(p1[1]) - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2, cv2.LINE_AA)
    path = os.path.join("out", "zone_counter_pick_check.png")
    cv2.imwrite(path, img)
    return path


def draw_zone_check(frame, H, item, gw, gh):
    os.makedirs("out", exist_ok=True)
    img = frame.copy()
    draw_grid(img, H, gw, gh)
    _overlay_poly(img, H, item["polygon"], item["color"], 3, fill=True)
    path = os.path.join("out", f"zone_{item['name']}_check.png")
    cv2.imwrite(path, img)
    return path


if __name__ == "__main__":
    main()
