"""轻量多目标跟踪（SimpleSORT）。

为什么不用现成的 ByteTrack：饭堂场景目标少（几十人）、遮挡不重，
一个 IoU + 速度预测 + 匈牙利匹配的 SORT 变体就够用，而且零额外依赖、
行为可预期，方便调参和在 UE5 侧对齐"每帧一个稳定 ID"。

核心规则：
  1. 用上一帧速度预测当前框位置（线性外推），弥补检测跳变；
  2. 检测框与预测框做 IoU 匹配（匈牙利算法求全局最优）；
  3. 连续 min_hits 帧匹配成功的轨迹才输出（抑制背景差分误检）；
  4. 连续 max_age 帧匹配失败才删除（短暂遮挡不换 ID）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a: (N,4) b: (M,4) -> (N,M) 的 IoU 矩阵。"""
    if a.size == 0 or b.size == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)
    ax1, ay1, ax2, ay2 = a[:, 0:1], a[:, 1:2], a[:, 2:3], a[:, 3:4]
    bx1, by1, bx2, by2 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    inter_w = np.clip(np.minimum(ax2, bx2) - np.maximum(ax1, bx1), 0, None)
    inter_h = np.clip(np.minimum(ay2, by2) - np.maximum(ay1, by1), 0, None)
    inter = inter_w * inter_h
    area_a = np.clip(ax2 - ax1, 0, None) * np.clip(ay2 - ay1, 0, None)
    area_b = np.clip(bx2 - bx1, 0, None) * np.clip(by2 - by1, 0, None)
    union = area_a + area_b - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-6), 0.0).astype(np.float32)


class Track:
    __slots__ = ("id", "bbox", "vx", "vy", "hits", "age", "time_since_update",
                 "confirmed", "score", "smooth_bbox", "last_bbox", "hist")

    def __init__(self, tid: int, bbox, score: float = 1.0):
        self.id = tid
        self.bbox = np.asarray(bbox, dtype=np.float32)
        self.last_bbox = self.bbox.copy()
        self.smooth_bbox = self.bbox.copy()
        self.vx = 0.0
        self.vy = 0.0
        self.hits = 1
        self.age = 1
        self.time_since_update = 0
        self.confirmed = False
        self.score = score
        self.hist = None

    # ---- 位置相关 ----
    @property
    def cx(self) -> float:
        return float((self.bbox[0] + self.bbox[2]) * 0.5)

    @property
    def cy(self) -> float:
        return float((self.bbox[1] + self.bbox[3]) * 0.5)

    def predict(self):
        self.last_bbox = self.bbox.copy()
        if self.vx or self.vy:
            self.bbox[[0, 2]] += self.vx
            self.bbox[[1, 3]] += self.vy

    def update(self, bbox, score: float, alpha: float = 0.6, hist=None, decay: float = 0.7):
        new = np.asarray(bbox, dtype=np.float32)
        old_cx, old_cy = self.cx, self.cy
        self.vx = alpha * ((new[0] + new[2]) * 0.5 - old_cx) + (1 - alpha) * self.vx
        self.vy = alpha * ((new[1] + new[3]) * 0.5 - old_cy) + (1 - alpha) * self.vy
        self.bbox = new
        self.smooth_bbox = self.smooth_bbox * 0.5 + new * 0.5
        if hist is not None:
            self.hist = hist if self.hist is None else cv2.addWeighted(self.hist, decay, hist, 1 - decay, 0)
        self.hits += 1
        self.time_since_update = 0
        self.score = score

    def mark_missed(self):
        self.time_since_update += 1
        self.vx *= 0.8
        self.vy *= 0.8
        # 丢失时回退到外推前的位置，避免框一路飘走导致后续匹配越来越偏
        self.bbox = self.last_bbox.copy()


class SimpleTracker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.tracks: Dict[int, Track] = {}
        self._next_id = 1
        self.frame_idx = 0
        self._use_app = bool(getattr(cfg, "use_appearance", False))
        self._app_w = float(getattr(cfg, "appearance_weight", 0.45))
        self._app_decay = float(getattr(cfg, "appearance_decay", 0.7))

    @staticmethod
    def _hist(frame, bbox) -> Optional[np.ndarray]:
        """框内中上部（躯干）的 HSV 二维直方图，用作身份外观特征。"""
        if frame is None:
            return None
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1, x2 = max(0, min(x1, w - 1)), max(0, min(x2, w))
        y1, y2 = max(0, min(y1, h - 1)), max(0, min(y2, h))
        if x2 - x1 < 4 or y2 - y1 < 6:
            return None
        # 取中间 60%，避开头部/脚部与背景边缘
        dh, dw = y2 - y1, x2 - x1
        roi = frame[y1 + int(dh * 0.2):y1 + int(dh * 0.8), x1 + int(dw * 0.2):x1 + int(dw * 0.8)]
        if roi.size == 0:
            return None
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist

    def update(self, detections, frame=None) -> List[Track]:
        self.frame_idx += 1
        dets = detections or []

        # 1) 预测
        for t in self.tracks.values():
            t.predict()
            t.age += 1

        det_boxes = np.array([d.bbox for d in dets], dtype=np.float32) if dets else np.zeros((0, 4), np.float32)
        trk_ids = list(self.tracks.keys())
        trk_boxes = (np.array([self.tracks[i].bbox for i in trk_ids], dtype=np.float32)
                     if trk_ids else np.zeros((0, 4), np.float32))

        # 2) 匹配
        matched, unmatched_dets, unmatched_trks = [], list(range(len(dets))), list(range(len(trk_ids)))
        if trk_boxes.size and det_boxes.size:
            iou = iou_matrix(trk_boxes, det_boxes)
            aff = iou
            # 小目标/快速移动时 IoU 会掉到 0，用"中心距"补一条命，避免 ID 频繁切换
            cw = getattr(self.cfg, "center_weight", 0.0)
            gate = getattr(self.cfg, "center_gate", 0.8)
            if cw > 0 and gate > 0:
                tc = np.stack([(trk_boxes[:, 0] + trk_boxes[:, 2]) / 2,
                               (trk_boxes[:, 1] + trk_boxes[:, 3]) / 2], axis=1)
                dc = np.stack([(det_boxes[:, 0] + det_boxes[:, 2]) / 2,
                               (det_boxes[:, 1] + det_boxes[:, 3]) / 2], axis=1)
                dist = np.linalg.norm(tc[:, None, :] - dc[None, :, :], axis=2)
                scale = float(np.mean(trk_boxes[:, 3] - trk_boxes[:, 1])) + 1e-6
                aff = np.maximum(iou, cw * np.exp(-dist / (gate * scale)))

            # 外观相似度：并排走/交叉时，衣色是比位置更可靠的线索
            if self._use_app and frame is not None and len(trk_ids):
                det_hists = [self._hist(frame, b) for b in det_boxes]
                sim = np.zeros_like(aff)
                for i, tid in enumerate(trk_ids):
                    th = self.tracks[tid].hist
                    if th is None:
                        continue
                    for j, dh in enumerate(det_hists):
                        if dh is None:
                            continue
                        sim[i, j] = max(0.0, float(cv2.compareHist(th, dh, cv2.HISTCMP_CORREL)))
                # 乘子形式：位置不合理时外观再像也不给匹配，避免轨迹漂移到别人身上
                aff = aff * (1.0 - self._app_w + self._app_w * sim)
            rows, cols = linear_sum_assignment(-aff)
            for r, c in zip(rows, cols):
                if aff[r, c] >= self.cfg.iou_threshold:
                    matched.append((r, c))
                    if r in unmatched_trks:
                        unmatched_trks.remove(r)
                    if c in unmatched_dets:
                        unmatched_dets.remove(c)

        # 3) 更新已匹配
        det_hists_all = ([self._hist(frame, b) for b in det_boxes]
                         if (self._use_app and frame is not None) else None)
        for r, c in matched:
            t = self.tracks[trk_ids[r]]
            hist = det_hists_all[c] if det_hists_all else None
            t.update(det_boxes[c], dets[c].score, hist=hist, decay=self._app_decay)
            if not t.confirmed and t.hits >= self.cfg.min_hits:
                t.confirmed = True

        # 4) 新建
        for c in unmatched_dets:
            t = Track(self._next_id, det_boxes[c], dets[c].score)
            if self._use_app and frame is not None:
                t.hist = self._hist(frame, det_boxes[c])
            t.confirmed = self.cfg.min_hits <= 1
            self.tracks[t.id] = t
            self._next_id += 1

        # 5) 删除过期
        for r in unmatched_trks:
            t = self.tracks[trk_ids[r]]
            t.mark_missed()
            if t.time_since_update > self.cfg.max_age:
                del self.tracks[t.id]

        return [t for t in self.tracks.values() if t.confirmed]

    @property
    def active_count(self) -> int:
        return sum(1 for t in self.tracks.values() if t.confirmed and t.time_since_update == 0)
