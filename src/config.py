"""配置加载。

设计原则：
1. 统一使用 JSON，方便非算法同学（比如做 UE5 那部分的人）直接手改；
2. 所有字段都有默认值，配置里少写几项也不会崩；
3. 命令行参数可覆盖配置文件中的关键项。
"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class VideoCfg:
    """输入视频。视频没准备好时 path 留空即可，跑管线会给出明确提示。"""
    path: str = ""
    start_sec: float = 0.0
    end_sec: Optional[float] = None
    frame_step: int = 1          # 抽帧步长，1 = 每帧都处理
    max_frames: Optional[int] = None


@dataclass
class YoloCfg:
    weights: str = "yolov8n.pt"  # 可以换成 yolov8s.pt / 自训练权重
    conf: float = 0.25
    iou: float = 0.45
    imgsz: int = 960
    device: str = "cpu"          # "0" 表示第一块 GPU
    person_class: int = 0        # COCO 里 person 是 0


@dataclass
class MotionCfg:
    """前景差分检测器参数。用于合成视频验证 / 无 YOLO 环境时的兜底。"""
    history: int = 300
    var_threshold: float = 30.0
    learning_rate: float = -1.0   # -1 = MOG2 自动；固定小值可减缓静止目标被背景吸收
    min_area: int = 120          # 最小连通域面积（像素）
    max_area: int = 40000
    min_height: int = 18         # 最小框高，过滤噪点
    max_aspect: float = 3.0      # 宽/高 上限，过滤横向长条（多人粘连/影子）
    foot_offset_ratio: float = 0.0   # 脚点相对框底的偏移（占框高比例，负数=上移，用于剔除影子）
    skip_frames: int = 12        # 开头若干帧只建背景、不输出检测


@dataclass
class DetectorCfg:
    """type: yolo | motion | auto

    auto = 先用 yolo 试跑 probe_frames 帧，检测不到人自动切到 motion。
    """
    type: str = "auto"
    probe_frames: int = 30
    probe_min_avg: float = 0.3
    yolo: YoloCfg = field(default_factory=YoloCfg)
    motion: MotionCfg = field(default_factory=MotionCfg)


@dataclass
class TrackerCfg:
    iou_threshold: float = 0.25
    center_weight: float = 0.55  # 中心距辅助匹配权重（IoU 失效时靠它续 ID）
    center_gate: float = 0.8     # 中心距容差，单位=平均框高
    use_appearance: bool = True  # 是否用衣色直方图辅助匹配（能显著减少并排走时的 ID 互换）
    appearance_weight: float = 0.45
    appearance_decay: float = 0.7   # 历史外观直方图的动量，越大越"记仇"
    max_age: int = 30            # 连续丢失多少帧后删除轨迹
    min_hits: int = 3            # 连续命中多少帧后才确认输出（抑制误检）
    smooth: float = 0.5          # 地面坐标 EMA 平滑系数，0 = 不平滑
    max_speed_mps: float = 3.0   # 超过该速度视为跳变，冻结更新


@dataclass
class HomographyCfg:
    """四点标定：图像像素点 <-> 地面米制点（顺序一一对应）。"""
    image_points: list = field(default_factory=list)   # [[u,v], ...] 4 个
    ground_points: list = field(default_factory=list)  # [[x_m,y_m], ...] 4 个
    ground_size_m: list = field(default_factory=lambda: [12.0, 9.0])
    # UE5 落地参数：地面坐标 -> UE 世界坐标（cm）
    ue_origin_cm: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    # 保留旧字段名兼容已有配置；实际作用是把 UE.Y 取反（场景左右建反时用）
    flip_x: bool = False


@dataclass
class ZoneCfg:
    name: str = ""
    label: str = ""
    polygon: list = field(default_factory=list)   # 地面米制多边形 [[x,y],...]
    color: list = field(default_factory=lambda: [90, 200, 255])  # BGR


@dataclass
class CounterCfg:
    """进出计数线：地面平面上的两点线段。"""
    name: str = "door"
    p1: list = field(default_factory=lambda: [0.0, 0.0])
    p2: list = field(default_factory=lambda: [0.0, 1.0])
    inward_sign: int = 1      # 1 表示从 line 负侧到正侧算「进入」
    debounce_sec: float = 0.5     # 同一人两次有效穿线的最小间隔（秒），抑制脚点抖动重复计数
    min_travel_m: float = 0.15    # 两次有效穿线之间脚点至少移动的距离（米）


@dataclass
class OutputCfg:
    out_dir: str = "out/entrance"
    save_video: bool = True
    save_tracks: bool = True
    save_heatmap: bool = True
    save_dashboard: bool = True     # 离线快照看板 dashboard.html（非实时），可关
    save_realtime: bool = True      # realtime.json：给 UI 侧的实时数据源
    save_csv: bool = True
    video_scale: float = 1.0


@dataclass
class PipelineCfg:
    video: VideoCfg = field(default_factory=VideoCfg)
    detector: DetectorCfg = field(default_factory=DetectorCfg)
    tracker: TrackerCfg = field(default_factory=TrackerCfg)
    homography: HomographyCfg = field(default_factory=HomographyCfg)
    zones: list = field(default_factory=list)          # list[ZoneCfg]
    counters: list = field(default_factory=list)       # list[CounterCfg]
    output: OutputCfg = field(default_factory=OutputCfg)


def _build(cls, data: Any):
    """把 dict 递归塞进 dataclass，未知字段直接忽略。"""
    if not isinstance(data, dict):
        return cls()
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        if dataclasses.is_dataclass(f.type) or hasattr(f.type, "__dataclass_fields__"):
            kwargs[f.name] = _build(f.type, val)
        elif f.name == "detector" and isinstance(val, dict):
            kwargs[f.name] = _build(DetectorCfg, val)
        else:
            kwargs[f.name] = val
    return cls(**kwargs)


def load_config(path: str) -> PipelineCfg:
    with open(path, "r", encoding="utf-8") as fp:
        raw = json.load(fp)

    cfg = PipelineCfg()
    if "video" in raw:
        cfg.video = _build(VideoCfg, raw["video"])

    if "detector" in raw:
        d = raw["detector"]
        cfg.detector = DetectorCfg(
            type=d.get("type", cfg.detector.type),
            probe_frames=int(d.get("probe_frames", cfg.detector.probe_frames)),
            probe_min_avg=float(d.get("probe_min_avg", cfg.detector.probe_min_avg)),
            yolo=_build(YoloCfg, d.get("yolo", {})),
            motion=_build(MotionCfg, d.get("motion", {})),
        )

    if "tracker" in raw:
        cfg.tracker = _build(TrackerCfg, raw["tracker"])
    if "homography" in raw:
        cfg.homography = _build(HomographyCfg, raw["homography"])
    if "output" in raw:
        cfg.output = _build(OutputCfg, raw["output"])

    cfg.zones = [_build(ZoneCfg, z) for z in raw.get("zones", [])]
    cfg.counters = [_build(CounterCfg, c) for c in raw.get("counters", [])]

    # 相对路径按配置文件所在目录解析，切目录运行也不会找不到文件
    base = os.path.dirname(os.path.abspath(path))
    if cfg.video.path and not os.path.isabs(cfg.video.path):
        cfg.video.path = os.path.normpath(os.path.join(base, cfg.video.path))
    if not os.path.isabs(cfg.output.out_dir):
        cfg.output.out_dir = os.path.normpath(os.path.join(base, cfg.output.out_dir))
    return cfg


def apply_overrides(cfg: PipelineCfg, args) -> PipelineCfg:
    """命令行参数覆盖配置。args 是 argparse.Namespace。"""
    if getattr(args, "video", None):
        cfg.video.path = args.video
    if getattr(args, "detector", None):
        cfg.detector.type = args.detector
    if getattr(args, "out", None):
        cfg.output.out_dir = args.out
    if getattr(args, "max_frames", None):
        cfg.video.max_frames = args.max_frames
    if getattr(args, "frame_step", None):
        cfg.video.frame_step = args.frame_step
    return cfg
