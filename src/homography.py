"""透视（单应）换算：图像像素坐标 <-> 饭堂地面米制坐标。

为什么需要它：监控相机是斜视的，画面里"上面的人"看起来更小更远，
直接用像素算距离/速度是错的。用四点标定求出单应矩阵 H 之后，
人脚下的地面点就能换算成真实米制坐标，人数统计、区域停留、
热力图、UE5 里的 NPC 位置才有物理意义。

标定方法（现场 1 分钟可做完）：
  **建筑自身的角点就是最好的标记**——柱子与地面的交界、门框竖边、台阶沿，
  边缘锐利、永久固定，不需要摆任何东西。已知门廊尺寸时（如柱距 4.47 / 门宽 3.27 /
  进深 2.13），四点构成一个等腰梯形：近边=两柱脚，远边=两门框竖边。
  按 近左/近右/远右/远左 记下 4 个角点的像素坐标，与米制坐标一一配对
  （本模块只要求 4 点对应、形状自洽，矩形或梯形都行）。
  尺度是估的还是实测的，不影响人数/进出/峰值/停留，只影响速度与 UE 里的绝对距离。
"""
from __future__ import annotations

import json
import os
from typing import Iterable, Sequence

import cv2
import numpy as np


def build_homography(image_points: Sequence[Sequence[float]],
                     ground_points: Sequence[Sequence[float]]) -> np.ndarray:
    """四点法求单应矩阵 H (3x3)，把图像像素映射到地面米制坐标。"""
    if len(image_points) != 4 or len(ground_points) != 4:
        raise ValueError("四点标定需要正好 4 个图像点和 4 个地面点")
    src = np.asarray(image_points, dtype=np.float32).reshape(4, 2)
    dst = np.asarray(ground_points, dtype=np.float32).reshape(4, 2)
    H = cv2.getPerspectiveTransform(src, dst)
    if not np.isfinite(H).all():
        raise ValueError("单应矩阵求解失败，请检查 4 个点是否共线")
    return H


def invert_homography(H: np.ndarray) -> np.ndarray:
    return np.linalg.inv(H)


def apply_homography(H: np.ndarray, pts: Iterable[Sequence[float]]) -> np.ndarray:
    """对 N 个点做透视变换，输入支持 (N,2) 或单点 (2,)。返回 (N,2) float32。"""
    arr = np.asarray(pts, dtype=np.float32)
    single = arr.ndim == 1
    if single:
        arr = arr.reshape(1, 2)
    out = cv2.perspectiveTransform(arr.reshape(-1, 1, 2), H).reshape(-1, 2)
    return out[0] if single else out


def img_to_ground(H: np.ndarray, points) -> np.ndarray:
    return apply_homography(H, points)


def ground_to_img(H: np.ndarray, points) -> np.ndarray:
    return apply_homography(invert_homography(H), points)


def foot_point(bbox: Sequence[float], offset_ratio: float = 0.0) -> tuple[float, float]:
    """取人体框底边中点作为"脚点"——斜视下它就是人与地面的接触点。"""
    x1, y1, x2, y2 = bbox[:4]
    return (float((x1 + x2) * 0.5), float(y2 + (y2 - y1) * offset_ratio))


def ground_to_ue(x_m: float, y_m: float, ground_h_m: float,
                 origin_cm=(0.0, 0.0, 0.0), flip_x: bool = False) -> tuple[float, float, float]:
    """地面米制坐标 -> UE5 世界坐标（cm，左手系：X 前 / Y 右 / Z 上）。

    约定：图像坐标系 x 向右、y 向下（远离相机）。映射到 UE 时：
        UE.X = ground_h_m - y_m   （画面越靠下 = 离相机越近 = UE 里越靠前）
        UE.Y = x_m
        UE.Z = 0                  （站在地面）
    这样在 UE 里摆饭堂时，只要让场景的"远墙"对齐 X=0、"左墙"对齐 Y=0 即可。
    """
    gx = -x_m if flip_x else x_m
    ux = (ground_h_m - y_m) * 100.0 + origin_cm[0]
    uy = gx * 100.0 + origin_cm[1]
    uz = 0.0 + origin_cm[2]
    return (float(ux), float(uy), float(uz))


def yaw_from_velocity_ue(vx_mps: float, vy_mps: float) -> float:
    """地面速度 -> UE 里的朝向角（度，绕 Z 轴）。UE 里 X 前 Y 右，yaw 顺时针为正。"""
    import math
    ux, uy = -vy_mps, vx_mps        # 与 ground_to_ue 的轴映射保持一致
    if abs(ux) < 1e-6 and abs(uy) < 1e-6:
        return 0.0
    return float(math.degrees(math.atan2(uy, ux)))


def save_calibration(path: str, H: np.ndarray, image_points, ground_points,
                     ground_size_m=(12.0, 9.0), extra: dict | None = None) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        "homography": np.asarray(H, dtype=float).round(8).tolist(),
        "image_points": np.asarray(image_points, dtype=float).tolist(),
        "ground_points": np.asarray(ground_points, dtype=float).tolist(),
        "ground_size_m": list(ground_size_m),
        "note": "image_points 为像素坐标，ground_points 为地面米制坐标，顺序一一对应",
    }
    if extra:
        payload.update(extra)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


def reload_points_from_cfg(cfg) -> tuple[list, list]:
    return list(cfg.image_points), list(cfg.ground_points)


def reprojection_error(H, image_points, ground_points) -> float:
    """标定质量自检：把图像点正变换到地面，和真实地面点的平均像素误差（米）。"""
    pred = img_to_ground(H, image_points)
    gt = np.asarray(ground_points, dtype=np.float32)
    return float(np.mean(np.linalg.norm(pred - gt, axis=1)))
