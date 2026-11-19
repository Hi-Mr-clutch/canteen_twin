"""检测器：把视频帧变成「人」的包围框。

两种实现，统一接口：
  YoloPersonDetector  —— ultralytics YOLO，真实监控视频用这个（COCO person 类）。
  MotionPersonDetector—— MOG2 背景差分 + 连通域，合成视频/无权重环境用这个。
  AutoDetector        —— 先试跑 YOLO，检测不到人自动降级到 motion，并打印原因。

统一输出：list[Detection]，bbox 为像素 (x1,y1,x2,y2)。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np


@dataclass
class Detection:
    bbox: tuple            # (x1, y1, x2, y2) 像素
    score: float = 1.0
    label: str = "person"

    @property
    def center(self) -> tuple:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


class BaseDetector:
    name = "base"

    def detect(self, frame: np.ndarray, frame_idx: int = 0) -> List[Detection]:
        raise NotImplementedError

    def close(self):
        pass


class YoloPersonDetector(BaseDetector):
    name = "yolo"

    def __init__(self, cfg, log=print):
        from ultralytics import YOLO  # 延迟导入，没装也不影响其他检测器

        self.cfg = cfg
        w = str(getattr(cfg, "weights", "") or "yolov8n.pt")
        explicit_path = ("/" in w) or ("\\" in w)
        if explicit_path and not os.path.exists(w):
            # 显式写了路径却不存在：直接报错，不要让它去联网下载然后一卡几分钟
            raise FileNotFoundError(f"YOLO 权重文件不存在: {w}")
        if not explicit_path and not os.path.exists(w):
            log(f"[detector] 当前目录没有 {w}，正在下载官方预训练权重（约 6MB）。"
                f"若卡住不动，请手动下载后把 weights 改成绝对路径。")
        self.model = YOLO(w)
        self.names = self.model.names

    def detect(self, frame, frame_idx=0):
        res = self.model.predict(
            frame,
            conf=self.cfg.conf,
            iou=self.cfg.iou,
            imgsz=self.cfg.imgsz,
            classes=[self.cfg.person_class],
            device=self.cfg.device,
            verbose=False,
        )[0]
        out: List[Detection] = []
        if res.boxes is None:
            return out
        xyxy = res.boxes.xyxy.cpu().numpy()
        confs = res.boxes.conf.cpu().numpy()
        for box, cf in zip(xyxy, confs):
            out.append(Detection(tuple(float(v) for v in box[:4]), float(cf), "person"))
        return out


class MotionPersonDetector(BaseDetector):
    """背景差分检测器。

    适合固定机位的饭堂监控（背景基本静止），也用于合成视频验证：
    不依赖任何预训练权重，只要有运动的人就能出框。
    """
    name = "motion"

    def __init__(self, cfg):
        self.cfg = cfg
        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=int(cfg.history),
            varThreshold=float(cfg.var_threshold),
            detectShadows=True,
        )
        self.k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        self._seen = 0

    def detect(self, frame, frame_idx=0):
        self._seen += 1
        lr = self.cfg.learning_rate
        fg = self.bg.apply(frame, learningRate=lr) if lr and lr > 0 else self.bg.apply(frame)
        if self._seen <= self.cfg.skip_frames:
            return []
        # MOG2 把影子标记成 127，只保留硬前景
        fg = np.where(fg == 255, 255, 0).astype(np.uint8)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self.k_open, iterations=1)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self.k_close, iterations=2)
        # 让粘连的身体块更完整一点
        fg = cv2.dilate(fg, self.k_close, iterations=1)

        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out: List[Detection] = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.cfg.min_area or area > self.cfg.max_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if h < self.cfg.min_height:
                continue
            if w / max(h, 1) > self.cfg.max_aspect:
                continue
            # 前景块面积 / 外接框面积 太低，说明是细长噪声
            if area / max(w * h, 1) < 0.18:
                continue
            out.append(Detection((float(x), float(y), float(x + w), float(y + h)), 1.0, "person"))
        return out


class AutoDetector(BaseDetector):
    """先 YOLO，探测不到人自动切前景差分。

    真实饭堂视频一般 YOLO 直接可用；换成合成视频 / 俯视小目标时
    YOLO 可能一个都检不到，此时自动降级保证管线仍然跑得通。
    """

    name = "auto"

    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        self.impl = None
        self._probe = 0
        self._probe_count = 0
        self._resolved = False
        try:
            self.impl = YoloPersonDetector(cfg.yolo, log=self.log)
            self.log(f"[detector] 已加载 YOLO 权重: {cfg.yolo.weights}")
        except Exception as exc:  # 没装 ultralytics / 权重不存在
            self.log(f"[detector] YOLO 不可用（{type(exc).__name__}: {exc}），改用前景差分检测器")
            self.impl = MotionPersonDetector(cfg.motion)
            self.name = "motion"
            self._resolved = True

    def detect(self, frame, frame_idx=0):
        dets = self.impl.detect(frame, frame_idx)
        if self._resolved:
            return dets

        self._probe += 1
        self._probe_count += len(dets)
        if self._probe >= self.cfg.probe_frames:
            avg = self._probe_count / max(self._probe, 1)
            if avg < self.cfg.probe_min_avg:
                self.log(f"[detector] YOLO 前 {self._probe} 帧平均只检出 {avg:.2f} 人，"
                         f"判定不适配当前画面（俯视/合成/小目标），自动切换到前景差分检测器")
                self.impl = MotionPersonDetector(self.cfg.motion)
                self.name = "motion"
            else:
                self.log(f"[detector] YOLO 探测通过：前 {self._probe} 帧平均 {avg:.2f} 人，继续使用 YOLO")
            self._resolved = True
        return dets


def build_detector(cfg, log=print) -> BaseDetector:
    kind = (cfg.type or "auto").lower()
    if kind == "yolo":
        return YoloPersonDetector(cfg.yolo)
    if kind == "motion":
        return MotionPersonDetector(cfg.motion)
    return AutoDetector(cfg, log=log)
