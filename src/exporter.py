"""结果导出：JSON / CSV / HTML 看板。

产出三份核心文件：
  tracks.json      —— 全量逐帧数据（含元信息、标定参数、区域），供分析/追溯
  npc_tracks.json  —— UE5 蓝图专用，每个 NPC 一条逐帧轨迹（cm 坐标 + 朝向）
  analytics.json   —— 统计汇总（人数、峰值、区域停留、进出计数）
"""
from __future__ import annotations

import base64
import csv
import datetime as _dt
import json
import os
from typing import Dict, List

import numpy as np

from . import homography as homo

SCHEMA_TRACKS = "canteen-twin/tracks@1.0"
SCHEMA_NPC = "canteen-twin/npc@1.0"


def _ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def build_tracks_payload(meta: dict, zones: list, frames: List[dict]) -> dict:
    return {
        "schema": SCHEMA_TRACKS,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "zones": zones,
        "frames": frames,
    }


def export_tracks(out_dir: str, payload: dict) -> str:
    _ensure_dir(out_dir)
    path = os.path.join(out_dir, "tracks.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False)
    return path


def export_npc_tracks(out_dir: str, frames: List[dict], meta: dict,
                      keyframe_step: int = 1, ground_h_m: float = 9.0,
                      ue_origin_cm=(0, 0, 0), flip_x: bool = False) -> str:
    """把逐帧数据重排成「每个 NPC 一条轨迹」，蓝图侧按帧插值最省事。

    keyframe_step > 1 时抽稀关键帧，蓝图 Lerp 插值即可，可显著减小 JSON 体积。
    注意：抽稀会丢细节，门口快速进出这类关键动作建议保持 1。
    """
    _ensure_dir(out_dir)
    by_id: Dict[int, List[dict]] = {}
    for fr in frames:
        for a in fr["actors"]:
            by_id.setdefault(int(a["id"]), []).append({
                "f": int(fr["frame"]),
                "x": round(a["ue_cm"][0], 1),
                "y": round(a["ue_cm"][1], 1),
                "z": round(a["ue_cm"][2], 1),
                "yaw": round(a["yaw"], 1),
            })

    npcs = []
    for tid in sorted(by_id):
        samples = by_id[tid]
        if keyframe_step > 1:
            samples = samples[::keyframe_step]
            if samples and by_id[tid][-1]["f"] != samples[-1]["f"]:
                samples.append(by_id[tid][-1])
        npcs.append({
            "id": tid,
            "start_frame": samples[0]["f"],
            "end_frame": samples[-1]["f"],
            "samples": samples,
        })

    payload = {
        "schema": SCHEMA_NPC,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "meta": {
            "unit": "cm",
            "coordinate_system": "UE5 左手系：X 前（进店 = +X，门洞墙 X=0）/ Y 右 / Z 上，地面 Z=0",
            "fps": meta.get("processed_fps", 25.0),
            "frame_count": meta.get("frame_count", 0),
            "duration_sec": meta.get("duration_sec", 0.0),
            "keyframe_step": keyframe_step,
            "ground_height_m": ground_h_m,
            "ue_origin_cm": list(ue_origin_cm),
            "flip_x": flip_x,
            "npcs": len(npcs),
        },
        "npcs": npcs,
    }
    path = os.path.join(out_dir, "npc_tracks.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False)
    return path


def export_analytics(out_dir: str, summary: dict, track_rows: List[dict]) -> str:
    _ensure_dir(out_dir)
    payload = {
        "schema": "canteen-twin/analytics@1.0",
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "tracks": track_rows,
    }
    path = os.path.join(out_dir, "analytics.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return path


def export_csv(out_dir: str, frames: List[dict]) -> str:
    _ensure_dir(out_dir)
    path = os.path.join(out_dir, "tracks.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["frame", "t_sec", "track_id", "x_m", "y_m", "speed_mps", "zone", "ue_x_cm", "ue_y_cm", "yaw_deg"])
        for fr in frames:
            for a in fr["actors"]:
                w.writerow([fr["frame"], round(fr["t"], 3), a["id"], round(a["x_m"], 3), round(a["y_m"], 3),
                            round(a["speed_mps"], 3), a.get("zone", ""), round(a["ue_cm"][0], 1),
                            round(a["ue_cm"][1], 1), round(a["yaw"], 1)])
    return path


def _img_b64(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as fp:
        return "data:image/png;base64," + base64.b64encode(fp.read()).decode()


def export_dashboard(out_dir: str, summary: dict, track_rows: List[dict], meta: dict,
                     heatmap_png: str = "", video_name: str = "") -> str:
    """生成一份自包含的 HTML 看板（无外部依赖，可直接用 UE5 的 Web Browser 控件加载）。"""
    _ensure_dir(out_dir)
    series = summary["per_frame_count"]
    zones = summary["zones"]
    hm = _img_b64(heatmap_png)

    data = {
        "meta": meta,
        "summary": {k: v for k, v in summary.items() if k not in ("per_frame_count", "per_frame_zone")},
        "countSeries": series,
        "zoneSeries": summary["per_frame_zone"],
        "fps": meta.get("processed_fps", 25.0),
        "tracks": track_rows[:12],
        "video": video_name,
        "zones": zones,
    }
    html = _DASHBOARD_TMPL.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__HEATMAP__", hm)
    path = os.path.join(out_dir, "dashboard.html")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(html)
    return path


_DASHBOARD_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>饭堂门口人流量 · 数据看板</title>
<style>
  :root{
    --bg:#0b1220; --panel:#131c2e; --line:#22304a; --txt:#e8eef8;
    --sub:#8ea3c2; --accent:#35d0ba; --accent2:#4a8cff; --warn:#ffb02e;
  }
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 600px at 20% -10%,#16233a 0%,var(--bg) 55%);
       color:var(--txt);font-family:"Microsoft YaHei","PingFang SC",Segoe UI,system-ui,sans-serif;}
  .wrap{max-width:1240px;margin:0 auto;padding:24px 22px 48px}
  header{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;
         border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:22px}
  h1{font-size:21px;margin:0;letter-spacing:.5px}
  h1 span{color:var(--accent)}
  .meta{font-size:12px;color:var(--sub);text-align:right;line-height:1.7}
  .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}
  .card{background:linear-gradient(180deg,#16203380,#101a2b80);border:1px solid var(--line);
        border-radius:12px;padding:16px 18px;position:relative;overflow:hidden}
  .card::after{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--accent);opacity:.85}
  .k{font-size:12px;color:var(--sub);letter-spacing:.4px}
  .v{font-size:30px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}
  .v small{font-size:13px;font-weight:400;color:var(--sub);margin-left:4px}
  .row{display:grid;grid-template-columns:1.55fr 1fr;gap:14px;margin-bottom:18px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
  .panel h2{font-size:14px;margin:0 0 12px;color:#cfe0f7;font-weight:600;letter-spacing:.4px}
  canvas{width:100%;display:block}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th,td{text-align:left;padding:8px 6px;border-bottom:1px solid #1c2740}
  th{color:var(--sub);font-weight:500}
  td.num{font-variant-numeric:tabular-nums}
  .tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;
       background:#1b2b45;color:#9fc0ea;border:1px solid #27395a}
  .hm{width:100%;max-height:380px;object-fit:contain;border-radius:8px;
       border:1px solid var(--line);display:block;background:#080c14}
  .legend{display:flex;gap:14px;font-size:11.5px;color:var(--sub);margin-top:10px;flex-wrap:wrap}
  .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px}
  footer{margin-top:26px;color:#5d6f8d;font-size:11.5px;text-align:center;line-height:1.8}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>学校饭堂门口 · 人流量 <span>数据看板</span></h1>
    <div class="meta" id="meta"></div>
  </header>

  <div class="grid" id="kpis"></div>

  <div class="row">
    <div class="panel">
      <h2>画面内人数曲线（逐帧）</h2>
      <canvas id="line" height="220"></canvas>
      <div class="legend">
        <span><i class="dot" style="background:#35d0ba"></i>画面内人数</span>
        <span><i class="dot" style="background:#ffb02e"></i>峰值</span>
      </div>
    </div>
    <div class="panel">
      <h2>门前区域平均占用</h2>
      <canvas id="bars" height="220"></canvas>
    </div>
  </div>

  <div class="row">
    <div class="panel">
      <h2>门前人流热力图（地面俯视，米制）</h2>
      <img class="hm" id="hm" alt="heatmap"/>
      <div class="legend"><span>深红 = 高频经过/停留区域</span></div>
    </div>
    <div class="panel">
      <h2>门前区域明细</h2>
      <table id="zoneTable"></table>
    </div>
  </div>

  <div class="panel">
    <h2>个体轨迹摘要（按停留时长排序，前 12 条）</h2>
    <table id="trkTable"></table>
  </div>

  <footer>
    数据源：<span id="src"></span> · 坐标单位：米（地面平面）/ cm（UE5 世界）<br/>
    YOLO 检测 + 多目标跟踪 + 四点透视换算 · canteen_twin 管线自动生成
  </footer>
</div>

<script>
const D = __DATA__;
const fmt = (n,d=1)=> Number(n).toFixed(d);

/* KPI：门口场景只关心「来了多少人 / 进了多少 / 出了多少 / 同时最多几个人」 */
const ct = (D.summary.counters && D.summary.counters[0]) || {in:0, out:0, name:'door'};
const net = ct.in - ct.out;
const kpiDefs = [
  ['累计人数', D.summary.people_total, '人'],
  ['进店', ct.in, '人次'],
  ['出店', ct.out, '人次'],
  ['峰值同框', D.summary.peak_count, '人 @ ' + fmt(D.summary.peak_time_sec) + 's'],
];
document.getElementById('kpis').innerHTML = kpiDefs.map(([k,v,u])=>
  `<div class="card"><div class="k">${k}</div><div class="v">${v}<small>${u}</small></div></div>`).join('');

/* meta */
const m = D.meta;
document.getElementById('meta').innerHTML =
  `检测器 ${m.detector} · ${m.frame_width}×${m.frame_height} · ${fmt(m.processed_fps,0)} fps<br/>
   处理 ${m.frame_count} 帧 / ${fmt(m.duration_sec)} 秒 · 门口场地 ${m.ground_plane.width_m}×${m.ground_plane.height_m} m<br/>
   净流入 <b style="color:#35d0ba">${net>=0?'+':''}${net}</b> 人 · 人均停留 ${fmt(D.summary.avg_dwell_sec,1)} 秒`;
document.getElementById('src').textContent = m.source_video || '合成测试视频';
document.getElementById('hm').src = "__HEATMAP__" || "";

/* 折线图 */
(function(){
  const c = document.getElementById('line'), ctx = c.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const W = c.clientWidth, H = 220;
  c.width = W*dpr; c.height = H*dpr; ctx.scale(dpr,dpr);
  const s = D.countSeries.length ? D.countSeries : [0];
  const pad = {l:34,r:8,t:10,b:20};
  const maxY = Math.max(...s, 1) * 1.15;
  const x = i => pad.l + (W-pad.l-pad.r) * (i/Math.max(s.length-1,1));
  const y = v => H-pad.b - (H-pad.t-pad.b) * (v/maxY);
  ctx.strokeStyle = '#1e2a42'; ctx.lineWidth = 1; ctx.font = '10px system-ui'; ctx.fillStyle = '#6b7f9e';
  for (let i=0;i<=4;i++){
    const yy = pad.t + (H-pad.t-pad.b)*i/4;
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(W-pad.r, yy); ctx.stroke();
    ctx.fillText(Math.round(maxY*(1-i/4)), 6, yy+3);
  }
  const g = ctx.createLinearGradient(0,pad.t,0,H-pad.b);
  g.addColorStop(0,'rgba(53,208,186,.42)'); g.addColorStop(1,'rgba(53,208,186,0)');
  ctx.beginPath(); ctx.moveTo(x(0), y(s[0]));
  s.forEach((v,i)=>ctx.lineTo(x(i), y(v)));
  ctx.lineTo(x(s.length-1), H-pad.b); ctx.lineTo(x(0), H-pad.b); ctx.closePath();
  ctx.fillStyle = g; ctx.fill();
  ctx.beginPath(); ctx.moveTo(x(0), y(s[0]));
  s.forEach((v,i)=>ctx.lineTo(x(i), y(v)));
  ctx.strokeStyle = '#35d0ba'; ctx.lineWidth = 1.8; ctx.stroke();
  const pi = s.indexOf(Math.max(...s));
  ctx.beginPath(); ctx.arc(x(pi), y(s[pi]), 4, 0, 7); ctx.fillStyle = '#ffb02e'; ctx.fill();
  ctx.fillStyle = '#6b7f9e';
  ctx.fillText('0s', pad.l, H-4);
  ctx.fillText(fmt(D.summary.peak_time_sec,0)+'s', x(pi)-8, H-4);
  ctx.fillText(fmt(m.duration_sec,0)+'s', W-pad.r-22, H-4);
})();

/* 区域柱状图 */
(function(){
  const c = document.getElementById('bars'), ctx = c.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const W = c.clientWidth, H = 220;
  c.width = W*dpr; c.height = H*dpr; ctx.scale(dpr,dpr);
  const zs = D.zones.length ? D.zones : [{label:'无数据', avg_occupancy:0}];
  const maxV = Math.max(...zs.map(z=>z.avg_occupancy), 1);
  const bw = Math.min(96, (W-40)/zs.length*0.62);
  const gap = (W-40)/zs.length;
  ctx.font = '11px system-ui';
  zs.forEach((z,i)=>{
    const h = (H-56) * (z.avg_occupancy/maxV);
    const cx = 24 + gap*i + gap/2;
    const grad = ctx.createLinearGradient(0, H-40-h, 0, H-40);
    grad.addColorStop(0,'#4a8cff'); grad.addColorStop(1,'#2b4d9e');
    ctx.fillStyle = grad;
    ctx.beginPath(); ctx.roundRect(cx-bw/2, H-40-h, bw, h, [5,5,0,0]); ctx.fill();
    ctx.fillStyle = '#cfe0f7'; ctx.textAlign='center';
    ctx.fillText(fmt(z.avg_occupancy,1), cx, H-46-h);
    ctx.fillStyle = '#8ea3c2';
    ctx.fillText(z.label, cx, H-22);
  });
})();

/* 表格 */
document.getElementById('zoneTable').innerHTML =
  `<tr><th>区域</th><th>到访人数</th><th>平均占用</th><th>人均停留</th></tr>` +
  D.zones.map(z=>`<tr><td>${z.label}</td><td class="num">${z.visits}</td>
    <td class="num">${fmt(z.avg_occupancy,2)}</td><td class="num">${fmt(z.avg_dwell_sec,1)}s</td></tr>`).join('');

const rows = [...D.tracks].sort((a,b)=>b.duration_sec-a.duration_sec);
document.getElementById('trkTable').innerHTML =
  `<tr><th>ID</th><th>进入帧</th><th>停留</th><th>路径长度</th><th>均速</th><th>主要区域</th></tr>` +
  rows.map(t=>`<tr><td><span class="tag">#${t.id}</span></td><td class="num">${t.first_frame}</td>
    <td class="num">${fmt(t.duration_sec,1)}s</td><td class="num">${fmt(t.path_length_m,1)}m</td>
    <td class="num">${fmt(t.avg_speed_mps,2)} m/s</td><td>${t.main_zone || '-'}</td></tr>`).join('');
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 实时数据接口：只产出数据，不掺 UI 逻辑
#
# 设计原则：看板（ui/index.html）只依赖 realtime.json 一个文件就能做出
# 「跟着视频时间走」的统计面板，不需要读 tracks.json、不需要自己实现
# 任何统计算法，也不需要改动本管线。帧号 f 与 npc_tracks.json 完全对齐。
# 字段契约见 docs/realtime_data_contract.md。
# ---------------------------------------------------------------------------
SCHEMA_REALTIME = "canteen-twin/realtime@1.0"

_EVENT_CODE = {0: "new", 1: "in", 2: "out"}


def build_realtime_payload(timeline: dict, meta: dict,
                            zone_payload: list | None = None,
                            counter_payload: list | None = None) -> dict:
    """把 analytics.timeline() 的紧凑时间轴整理成给 UI 的自解释 JSON。

    frames 里每一帧都是「截至该帧」的快照，UI 按 f = floor((t - offset) * fps)
    直接取一帧渲染即可；events 另外单独给一份完整事件流，方便做订阅/动画。
    """
    fps = float(timeline.get("fps", 25.0))
    offset = float(timeline.get("time_offset_sec", 0.0))
    cols = timeline.get("cols", [])
    zone_names = cols[5:] if len(cols) > 5 else []
    rows = timeline.get("rows", [])
    points = timeline.get("points", [])

    ev_by_frame: dict = {}
    for e in timeline.get("events", []):
        f = int(e[0])
        ev_by_frame.setdefault(f, []).append({
            "f": f,
            "t": round(f / fps, 3),
            "type": _EVENT_CODE.get(int(e[1]), "new"),
            "id": int(e[2]),
            "counter": e[3] if len(e) > 3 else "",
        })

    frame_rows = []
    for f, r in enumerate(rows):
        frame_rows.append({
            "f": f,
            "t": round(f / fps, 3),
            "count": int(r[0]),       # 当前画面内人数
            "in": int(r[1]),          # 截至此刻累计进店人次
            "out": int(r[2]),         # 截至此刻累计出店人次
            "people": int(r[3]),      # 截至此刻累计独立人数
            "peak": int(r[4]),        # 截至此刻峰值同框
            "net": int(r[1]) - int(r[2]),
            "zones": {name: int(r[5 + i]) if 5 + i < len(r) else 0
                      for i, name in enumerate(zone_names)},
            "actors": [{"id": int(a[0]), "x_m": float(a[1]), "y_m": float(a[2])}
                       for a in (points[f] if f < len(points) else [])],
            "events": ev_by_frame.get(f, []),
        })

    events = [e for f in sorted(ev_by_frame) for e in ev_by_frame[f]]
    gm = timeline.get("ground_m", [0.0, 0.0])
    return {
        "schema": SCHEMA_REALTIME,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "meta": {
            "source_video": meta.get("source_video", ""),
            "detector": meta.get("detector", ""),
            "fps": fps,
            "frame_count": len(rows),
            "duration_sec": round(len(rows) / fps, 3) if fps else 0.0,
            "time_offset_sec": offset,
            "frame_width": meta.get("frame_width", 0),
            "frame_height": meta.get("frame_height", 0),
            "length_unit": "m",
            "note": "f 为处理后帧号，与 npc_tracks.json 的 samples[].f 完全一致",
        },
        "ground_m": [float(gm[0]), float(gm[1])],
        "zone_names": zone_names,
        "zones": zone_payload or [],
        "counters": counter_payload or [],
        "frames": frame_rows,
        "events": events,
    }


def export_realtime(out_dir: str, timeline: dict, meta: dict,
                     zone_payload: list | None = None,
                     counter_payload: list | None = None) -> str:
    """导出 realtime.json —— 实时看板的唯一数据源。"""
    _ensure_dir(out_dir)
    payload = build_realtime_payload(timeline, meta, zone_payload, counter_payload)
    path = os.path.join(out_dir, "realtime.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, separators=(",", ":"))
    return path
