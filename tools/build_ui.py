#!/usr/bin/env python3
"""把 realtime.json 内嵌进 ui/index.html，生成可直接双击打开的实时看板。

为什么需要这一步：
  UE5 的 Web Browser（CEF）用 file:// 加载页面时，fetch('realtime.json')
  会被 CORS 拦掉。把数据直接写进 HTML 就没有这个限制——单文件自包含，
  双击能看、放进 Content/ 或任意目录都能用，也不需要起 http 服务。

用法：
  python3 tools/build_ui.py                              # 自动找数据，输出到 out/entrance_a/
  python3 tools/build_ui.py --data out/entrance_b/realtime.json --out out/entrance_b/dashboard_live.html
  python3 tools/build_ui.py --data examples/realtime_a_1080p.json --video annotated.mp4 --out ui/preview.html

换素材、重跑管线之后，重跑本脚本即可，UI 代码不用动。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "ui", "index.html")

# 找不到 --data 时按这个顺序自动挑一份
CANDIDATES = [
    "out/entrance_a/realtime.json",
    "out/entrance/realtime.json",
    "out/entrance_b/realtime.json",
    "examples/realtime_a_1080p.json",
    "examples/realtime_b_720p.json",
    "examples/realtime_sample.json",
]

BEGIN = "/* BEGIN_DATA */"
END = "/* END_DATA */"


def find_data() -> str | None:
    for rel in CANDIDATES:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            return p
    return None


def slim(payload: dict) -> dict:
    """去掉 UI 用不到的冗余，减小成品体积（不改变任何口径）。

    frames[*].events 与顶层 events 完全重复，UI 事件流只读顶层 events。
    """
    for fr in payload.get("frames", []):
        fr.pop("events", None)
    return payload


def js_json(obj) -> str:
    """紧凑 JSON，并转义 '<' 防止意外闭合 <script>。"""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def make_h264(src: str) -> str:
    """把 mp4v 等浏览器不认的编码转成网页可播格式，返回新文件名（与源同目录）。

    管线用 OpenCV 写出的 annotated.mp4 通常是 mp4v，Chrome/CEF 不能播。
    优先 H.264（libx264 / libopenh264），都没有就退到 VP9(webm)——
    三种 Chromium 都能解，选到哪个都行。
    """
    if not shutil.which("ffmpeg"):
        print("[提示] 没装 ffmpeg，跳过转码；视频区会提示编码不支持。", file=sys.stderr)
        return os.path.basename(src)

    base, _ = os.path.splitext(src)
    attempts = [
        (["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"], ".mp4"),
        (["-c:v", "libopenh264", "-b:v", "3M", "-g", "60"], ".mp4"),
        (["-c:v", "libvpx-vp9", "-b:v", "2M", "-deadline", "realtime", "-cpu-used", "5"], ".webm"),
    ]
    for opts, ext in attempts:
        dst = base + "_web" + ext
        if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            return os.path.basename(dst)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src] + opts + \
              ["-pix_fmt", "yuv420p", "-an"]
        if ext == ".mp4":
            cmd += ["-movflags", "+faststart"]
        cmd.append(dst)
        try:
            subprocess.run(cmd, check=True, timeout=600)
            return os.path.basename(dst)
        except Exception:
            continue

    print("[提示] 没有可用的 H.264/VP9 编码器，继续用原视频。", file=sys.stderr)
    return os.path.basename(src)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成自包含的实时看板 HTML")
    ap.add_argument("--data", help="realtime.json 路径；不填则自动查找")
    ap.add_argument("--out", help="输出 HTML 路径")
    ap.add_argument("--template", default=TEMPLATE, help="模板路径（默认 ui/index.html）")
    ap.add_argument("--video", default="", help="同目录视频文件名，如 annotated.mp4；留空用模板默认")
    ap.add_argument("--label", default="", help="视频窗口标题，默认用 source_video 文件名（长哈希名会自动替换）")
    ap.add_argument("--h264", action="store_true", help="用 ffmpeg 把视频转成 H.264（浏览器/CEF 才能播）")
    ap.add_argument("--no-slim", action="store_true", help="不做精简，保留完整 frames[].events")
    args = ap.parse_args()

    data_path = args.data or find_data()
    if not data_path or not os.path.exists(data_path):
        print("[错误] 找不到 realtime.json。先跑管线，或用 --data 指定一份：", file=sys.stderr)
        for rel in CANDIDATES:
            print("   " + rel, file=sys.stderr)
        return 2

    if not os.path.exists(args.template):
        print(f"[错误] 模板不存在：{args.template}", file=sys.stderr)
        return 2

    with open(data_path, "r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not payload.get("meta") or not payload.get("frames"):
        print("[错误] 数据缺少 meta / frames，不是有效的 realtime.json", file=sys.stderr)
        return 2
    if not args.no_slim:
        payload = slim(payload)

    meta = payload["meta"]
    src_label = meta.get("source_video", "")
    payload["source_label"] = args.label or src_label

    with open(args.template, "r", encoding="utf-8") as fp:
        html = fp.read()

    if BEGIN not in html or END not in html:
        print("[错误] 模板里找不到数据占位标记 BEGIN_DATA / END_DATA", file=sys.stderr)
        return 2

    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    replacement = BEGIN + "\n  var EMBEDDED = " + js_json(payload) + ";\n  " + END
    html, n = pattern.subn(lambda _m: replacement, html, count=1)
    if n != 1:
        print("[错误] 数据注入失败", file=sys.stderr)
        return 2

    out = args.out or os.path.join(ROOT, "out", "entrance_a", "dashboard_live.html")
    if not os.path.isabs(out):
        out = os.path.normpath(os.path.join(ROOT, out))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    video_name = args.video
    if video_name and args.h264:
        src_video = os.path.join(os.path.dirname(os.path.abspath(out)), video_name)
        if os.path.exists(src_video):
            video_name = make_h264(src_video)
        else:
            print(f"[提示] 找不到视频 {src_video}，跳过转码。", file=sys.stderr)

    if video_name:
        inject = ("<script>window.__UI_VIDEO_SRC__ = " +
                  js_json(video_name) + ";</script>\n</head>")
        html = html.replace("</head>", inject, 1)

    with open(out, "w", encoding="utf-8") as fp:
        fp.write(html)

    size_kb = os.path.getsize(out) / 1024
    print(f"[完成] {out}")
    print(f"        数据源 : {os.path.relpath(data_path, ROOT)}  "
          f"({meta.get('frame_count')} 帧 / {meta.get('fps', 0):.2f} fps / "
          f"{meta.get('duration_sec')}s / {len(payload['events'])} 事件)")
    print(f"        末帧   : 进 {payload['frames'][-1]['in']} / 出 {payload['frames'][-1]['out']} / "
          f"累计 {payload['frames'][-1]['people']} 人")
    print(f"        体积   : {size_kb:.0f} KB（单文件自包含，可直接双击打开）")
    if video_name:
        print(f"        视频   : 同目录 {video_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
