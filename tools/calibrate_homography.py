#!/usr/bin/env python3
"""四点透视标定工具：给真实饭堂视频生成 homography 配置。

两种用法
--------
1) 交互点选（本机有桌面环境时最方便）：
       python3 tools/calibrate_homography.py --video data/input/canteen.mp4
   在首帧上依次点击地面矩形的 4 个角：近左 → 近右 → 远右 → 远左，
   ESC 取消，回车确认。

2) 直接给像素坐标（服务器/远程环境）：
       python3 tools/calibrate_homography.py --video data/input/canteen.mp4 \
           --image-points "102,711 1178,711 923,310 357,310" --ground-size 12x9 \
           --out configs/calibration_real.json

点哪四个点：**建筑自身的角点就是最好的标记**，不需要摆任何东西。
柱子、门框、台阶沿在画面里边缘锐利、永久固定、不会被人踩走——比临时摆的 A4 纸可靠。
已量好门廊尺寸时最省事（本例柱距 4.47m / 门宽 3.27m / 进深 2.13m）：

    python3 tools/calibrate_homography.py --video data/input/door_front.mp4 \
            --entrance-geometry 4.47,3.27,2.13

工具会自动推出梯形四点与门洞计数线，你只需在首帧上点：
左柱脚 → 右柱脚 → 右门框底 → 左门框底。

尺度（W/H）不影响人数、进出人次、峰值同框、人均停留、热力图形状，
只影响速度数值与 UE 里的绝对距离，因此估一个也能跑完整报告。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import homography as homo  # noqa: E402


def parse_points(text: str):
    pts = []
    for tok in text.replace(";", " ").split():
        x, y = tok.split(",")
        pts.append([float(x), float(y)])
    if len(pts) != 4:
        raise SystemExit(f"需要 4 个点，收到 {len(pts)} 个：{text}")
    return pts


def _fmt_pts(pts):
    """紧凑打印点列表：[[1, 2], [3, 4]]，比 json.dumps(indent=2) 好读也好粘。"""
    return "[" + ", ".join(f"[{float(p[0]):g}, {float(p[1]):g}]" for p in pts) + "]"


def interactive(frame):
    clicks = []
    win = "calibration - click 4 corners: near-left, near-right, far-right, far-left"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 4:
            clicks.append([float(x), float(y)])

    cv2.setMouseCallback(win, on_mouse)
    while True:
        vis = frame.copy()
        for i, (x, y) in enumerate(clicks):
            cv2.circle(vis, (int(x), int(y)), 5, (0, 0, 255), -1)
            cv2.putText(vis, str(i + 1), (int(x) + 8, int(y) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        if len(clicks) > 1:
            cv2.polylines(vis, [np.array(clicks, np.int32)], len(clicks) == 4, (0, 255, 0), 2)
        cv2.putText(vis, f"clicked {len(clicks)}/4   ENTER=ok  ESC=cancel", (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imshow(win, vis)
        k = cv2.waitKey(20) & 0xFF
        if k == 27:
            cv2.destroyAllWindows()
            raise SystemExit("已取消")
        if k in (13, 10) and len(clicks) == 4:
            cv2.destroyAllWindows()
            return clicks


def draw_check(frame, H, gw, gh, out_png, poly_ground=None):
    img = frame.copy()
    # 网格先画在单独图层上；梯形标定下要裁掉梯形之外的部分，
    # 否则网格线会爬到墙面/天上，看着像标定错了。
    grid = np.zeros_like(img)
    for x in np.arange(0, gw + 1e-6, 1.0):
        p = homo.ground_to_img(H, np.array([[x, 0], [x, gh]], np.float32))
        cv2.line(grid, tuple(p[0].astype(int)), tuple(p[1].astype(int)),
                 (80, 200, 255), 1, cv2.LINE_AA)
    for y in np.arange(0, gh + 1e-6, 1.0):
        p = homo.ground_to_img(H, np.array([[0, y], [gw, y]], np.float32))
        cv2.line(grid, tuple(p[0].astype(int)), tuple(p[1].astype(int)),
                 (80, 200, 255), 1, cv2.LINE_AA)
    blended = cv2.add(img, grid)
    if poly_ground is not None:
        mask = np.zeros(img.shape[:2], np.uint8)
        corners = homo.ground_to_img(H, np.array(poly_ground, np.float32)).astype(np.int32)
        cv2.fillConvexPoly(mask, corners, 255)
        img = np.where(mask[..., None] > 0, blended, img)
        cv2.polylines(img, [corners], True, (0, 255, 0), 2, cv2.LINE_AA)
    else:
        img = blended
    cv2.putText(img, "1m grid reprojected onto image - check it follows the floor", (12, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.imwrite(out_png, img)
    return out_png


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--image-points", default=None, help='"x1,y1 x2,y2 x3,y3 x4,y4" 像素坐标')
    ap.add_argument("--ground-points", default=None,
                    help='对应地面米制坐标，默认按 --ground-size 生成矩形四角')
    ap.add_argument("--ground-size", default="12x9",
                    help="地面矩形尺寸（米），如 3.8x2.6；只在不用 --entrance-geometry 时才需要，估一个也行")
    ap.add_argument("--entrance-geometry", default=None,
                    help='"柱距,门宽,柱到门进深"（米），如 "4.47,3.27,2.13"；'
                         '自动推出梯形四点 + 门洞计数线，免去手算')
    ap.add_argument("--out", default="configs/calibration_real.json")
    ap.add_argument("--apply", default=None, metavar="CONFIG",
                    help="把标定结果直接写回这个配置文件（如 configs/entrance_measured.json），"
                         "省掉手工复制粘贴")
    ap.add_argument("--time-sec", type=float, default=0.0, help="取第几秒的帧做标定")
    ap.add_argument("--dump-frame", default=None,
                    help="只导出这一帧成 PNG 然后退出，方便用看图软件取像素坐标再配合 --image-points")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"打不开视频：{args.video}")
    if args.time_sec > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, args.time_sec * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("读不到视频帧")

    if args.dump_frame:
        os.makedirs(os.path.dirname(os.path.abspath(args.dump_frame)) or ".", exist_ok=True)
        cv2.imwrite(args.dump_frame, frame)
        print(f"[ok] 首帧已导出 : {args.dump_frame}  ({frame.shape[1]}x{frame.shape[0]})")
        print("     用看图软件读出 4 个角点的像素坐标（柱子/门框的角点即可，不用摆标记），然后：")
        print(f'     python3 tools/calibrate_homography.py --video {args.video} '
              f'--image-points "x1,y1 x2,y2 x3,y3 x4,y4" --entrance-geometry 4.47,3.27,2.13')
        return

    gw, gh = [float(v) for v in args.ground_size.lower().split("x")]
    poly_ground = None
    suggested = None
    if args.entrance_geometry:
        vals = [float(v) for v in args.entrance_geometry.replace(",", " ").split()]
        if len(vals) != 3:
            raise SystemExit("--entrance-geometry 需要 3 个数：柱距,门宽,柱到门进深")
        span, door_w, depth = vals
        if not (0 < door_w < span and depth > 0):
            raise SystemExit("门宽必须小于柱距、进深必须为正")
        side = round((span - door_w) / 2.0, 3)          # 门居中，两侧各余多少
        gpts = [[0.0, 0.0], [span, 0.0],
                [round(span - side, 3), depth], [side, depth]]
        gw, gh = span, depth
        poly_ground = gpts
        suggested = {
            "counters": [{"name": "door", "p1": [side, depth],
                          "p2": [round(span - side, 3), depth], "inward_sign": 1}],
            "zones": [{"name": "porch", "label": "门前平台",
                       "polygon": gpts, "color": [60, 170, 255]}],
        }
        print(f"[i] 由柱距/门宽/进深推出梯形：近边两柱脚 {span}m，"
              f"远边两门框竖边 {door_w}m，两侧各余 {side}m，进深 {depth}m")
        print(f"[i] ground_points = {gpts}")
        print("[i] 请在首帧上依次点：左柱脚 → 右柱脚 → 右门框底 → 左门框底（都是建筑自身的角点）")
        print("[i] 门框底比柱脚高 0.2m 的话直接点门框底也行，只让纵深比例偏一成；"
              "想更准就沿门框竖边下移到与柱脚齐平处再点")
    elif args.ground_points:
        gpts = parse_points(args.ground_points)
    else:
        gpts = [[0, 0], [gw, 0], [gw, gh], [0, gh]]

    if args.image_points:
        ipts = parse_points(args.image_points)
    else:
        try:
            ipts = interactive(frame)
        except Exception as exc:
            raise SystemExit(
                f"无法打开交互窗口（{exc}）。\n"
                f"请改用：--image-points \"x1,y1 x2,y2 x3,y3 x4,y4\" 指定 4 个像素点。")

    H = homo.build_homography(ipts, gpts)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    homo.save_calibration(args.out, H, ipts, gpts, (gw, gh))

    check_png = os.path.splitext(args.out)[0] + "_check.png"
    draw_check(frame, H, gw, gh, check_png, poly_ground)

    print(f"[ok] 标定结果 : {args.out}")
    print(f"[ok] 校验图   : {check_png}  ← 打开看 1m 网格是否贴住地面，没贴住说明点选错了")
    print(f"[i] 地面尺寸 : {gw}m x {gh}m")
    payload = {"image_points": ipts, "ground_points": gpts, "ground_size_m": [gw, gh]}
    if suggested:
        payload.update(suggested)
        print("[i] 已顺带生成门洞计数线与门前平台区域（几何上直接由实测数据推出）")

    if args.apply:
        # 直接把结果写回配置文件，省掉手工复制粘贴这一步
        with open(args.apply, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("homography", {})
        cfg["homography"]["image_points"] = ipts
        cfg["homography"]["ground_points"] = gpts
        cfg["homography"]["ground_size_m"] = [gw, gh]
        if suggested:
            cfg["counters"] = suggested["counters"]
            cfg["zones"] = suggested["zones"]
        os.makedirs(os.path.dirname(os.path.abspath(args.apply)) or ".", exist_ok=True)
        with open(args.apply, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"\n[ok] 已直接写回配置：{args.apply}")
        print(f"     下一步直接跑：python3 -m src.run_pipeline --config {args.apply}")
        return

    print("\n把下面这段贴进 configs/*.json（或下次加 --apply configs/xxx.json 自动写入）：")
    print("{")
    print(f'  "image_points":  {_fmt_pts(ipts)},')
    print(f'  "ground_points": {_fmt_pts(gpts)},')
    print(f'  "ground_size_m": [{gw:g}, {gh:g}]'
          + ("," if suggested else ""))
    if suggested:
        print(f'  "counters": {json.dumps(suggested["counters"], ensure_ascii=False)},')
        print(f'  "zones":    {json.dumps(suggested["zones"], ensure_ascii=False)}')
    print("}")


if __name__ == "__main__":
    main()
