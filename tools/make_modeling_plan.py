#!/usr/bin/env python3
"""生成 docs/modeling_plan.png —— 门廊俯视图（UE5 建模坐标）。

尺寸常量与 configs/*.json 的 homography.ground_size_m 保持一致；
改了尺寸重跑本脚本，图和文档就不会脱节。

坐标约定（与 src/homography.py 的 ground_to_ue 完全一致）：
    UE.X = (y_m - 进深)   -> 进店 = +X，门洞墙 X=0，室外柱脚线 X=-进深
    UE.Y = x_m            -> 画面右 = +Y
"""
from __future__ import annotations

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyBboxPatch, Polygon

# ---------------- 实测尺寸（cm），与配置文件保持一致 ----------------
DEPTH = 213.0        # 柱到门的进深：柱脚线 -> 门洞面
WIDTH = 447.0        # 柱距（外沿 -> 外沿）
DOOR_W = 327.0       # 门洞净宽
DOOR_L = (WIDTH - DOOR_W) / 2.0     # 60
DOOR_R = DOOR_L + DOOR_W            # 387

FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

INK = "#16324f"
SUB = "#6b7f9e"
BLUE = "#2f7fd0"
CYAN = "#2fbcd1"
RED = "#e5484d"
WALL = "#1f2d3d"
PILLAR = "#55617a"


def setup_font() -> None:
    if os.path.exists(FONT_PATH):
        fm.fontManager.addfont(FONT_PATH)
        plt.rcParams["font.family"] = fm.FontProperties(fname=FONT_PATH).get_name()
    plt.rcParams["axes.unicode_minus"] = False


def dim_h(ax, x1, x2, y, text, off=13, color=BLUE, fs=11):
    ax.annotate("", xy=(x2, y), xytext=(x1, y),
                arrowprops=dict(arrowstyle="<|-|>", color=color, lw=1.5,
                                mutation_scale=13, shrinkA=0, shrinkB=0), zorder=6)
    ax.text((x1 + x2) / 2, y + off, text, ha="center", va="bottom",
            color=color, fontsize=fs, zorder=6)


def dim_v(ax, y1, y2, x, text, off=-12, color=BLUE, fs=11):
    ax.annotate("", xy=(x, y2), xytext=(x, y1),
                arrowprops=dict(arrowstyle="<|-|>", color=color, lw=1.5,
                                mutation_scale=13, shrinkA=0, shrinkB=0), zorder=6)
    ax.text(x + off, (y1 + y2) / 2, text, ha="right", va="center", rotation=90,
            color=color, fontsize=fs, zorder=6)


def main(out_path: str) -> None:
    setup_font()
    fig, ax = plt.subplots(figsize=(11.2, 7.4), dpi=160)
    fig.patch.set_facecolor("white")
    fig.subplots_adjust(left=0.055, right=0.975, top=0.845, bottom=0.155)

    ax.set_xlim(-165, 665)
    ax.set_ylim(-372, 155)
    ax.set_aspect("equal")
    ax.axis("off")

    # 1 m 网格（原点对齐 X=0 / Y=0）
    for v in range(-160, 666, 100):
        ax.plot([v, v], [-372, 155], color="#e3ecf4", lw=0.7, zorder=0)
    for v in range(-370, 156, 100):
        ax.plot([-165, 665], [v, v], color="#e3ecf4", lw=0.7, zorder=0)

    # 门廊地面（梯形：近边柱距，远边门宽）
    ground = [(0, -DEPTH), (WIDTH, -DEPTH), (DOOR_R, 0), (DOOR_L, 0)]
    ax.add_patch(Polygon(ground, closed=True, facecolor="#e6f2fa",
                         edgecolor="#9dc3dd", lw=1.6, zorder=1))

    # 墙（门洞两侧各一段）
    ax.plot([-90, DOOR_L], [0, 0], color=WALL, lw=10, solid_capstyle="butt", zorder=4)
    ax.plot([DOOR_R, 505], [0, 0], color=WALL, lw=10, solid_capstyle="butt", zorder=4)
    ax.text(-62, 14, "墙", color="#4a5b70", fontsize=11, ha="center", zorder=5)
    ax.text(492, 14, "墙", color="#4a5b70", fontsize=11, ha="center", zorder=5)

    # 门洞开口（文字放室内侧，避开箭头）
    ax.plot([DOOR_L, DOOR_R], [0, 0], color=CYAN, lw=4.5, ls=(0, (5, 4)), zorder=6)
    ax.text((DOOR_L + DOOR_R) / 2, 20, f"门洞开口 · Y {DOOR_L:.0f}~{DOOR_R:.0f}",
            color="#1d8ea0", fontsize=10.5, ha="center", va="bottom", zorder=6)

    # 两根柱子（柱脚线 X = -DEPTH）
    for cx in (4, WIDTH - 4):
        ax.add_patch(FancyBboxPatch((cx - 27, -DEPTH - 27), 54, 54,
                                    boxstyle="round,pad=0,rounding_size=10",
                                    facecolor=PILLAR, edgecolor="none", zorder=7))

    # 进店方向：+X（朝门里）
    ax.annotate("", xy=(WIDTH / 2, -26), xytext=(WIDTH / 2, -168),
                arrowprops=dict(arrowstyle="-|>", color=RED, lw=4.2,
                                mutation_scale=28, shrinkA=0, shrinkB=0), zorder=8)
    ax.text(WIDTH / 2 + 30, -104, "进店 = +X", color=RED, fontsize=15,
            fontweight="bold", ha="left", va="center", zorder=8)

    # 尺寸标注
    dim_h(ax, DOOR_L, DOOR_R, 72, f"门宽 {DOOR_W:.0f} cm（居中）")
    dim_h(ax, 0, WIDTH, -306, f"柱距 {WIDTH:.0f} cm", off=-40)
    dim_v(ax, -DEPTH, 0, -92, f"进深 {DEPTH:.0f} cm")

    # 柱脚位置文字（居中放柱子下方，抬高 zorder 防遮挡）
    ax.text(4, -DEPTH - 52, "左柱脚 · Y = 0", color="#4a5b70", fontsize=10.5,
            ha="center", va="top", zorder=9)
    ax.text(WIDTH - 4, -DEPTH - 52, "右柱脚 · Y = 447", color="#4a5b70", fontsize=10.5,
            ha="center", va="top", zorder=9)

    # 左上角轴示意：+X 向上，+Y 向右
    ox, oy = -132, 58
    ax.annotate("", xy=(ox, oy + 54), xytext=(ox, oy),
                arrowprops=dict(arrowstyle="-|>", color=SUB, lw=1.8, mutation_scale=12))
    ax.annotate("", xy=(ox + 62, oy), xytext=(ox, oy),
                arrowprops=dict(arrowstyle="-|>", color=SUB, lw=1.8, mutation_scale=12))
    ax.text(ox - 7, oy + 60, "+X", color=SUB, fontsize=10.5, ha="center", va="bottom")
    ax.text(ox + 68, oy, "+Y", color=SUB, fontsize=10.5, ha="left", va="center")

    # 关键 X 位置刻度线
    ax.annotate("门洞墙  X = 0", xy=(WIDTH + 26, 0), xytext=(WIDTH + 58, 44),
                color=BLUE, fontsize=10, va="center",
                arrowprops=dict(arrowstyle="-", color=BLUE, lw=1.0,
                                connectionstyle="angle,angleA=0,angleB=90,rad=0"))
    ax.annotate(f"柱脚线  X = −{DEPTH:.0f}", xy=(WIDTH + 26, -DEPTH),
                xytext=(WIDTH + 58, -DEPTH - 16), color=BLUE, fontsize=10, va="center",
                arrowprops=dict(arrowstyle="-", color=BLUE, lw=1.0,
                                connectionstyle="angle,angleA=0,angleB=90,rad=0"))

    # 标题 / 说明
    fig.text(0.055, 0.958, "门廊俯视图 · 建模坐标（1 格 = 1 米）",
             fontsize=17.5, fontweight="bold", color=INK, va="top")
    fig.text(0.055, 0.912, "屏幕向上 = UE +X（进店方向）；屏幕向右 = UE +Y",
             fontsize=10.8, color=SUB, va="top")

    fig.text(0.055, 0.098,
             "四个角点 UE 坐标：左柱脚 (−213, 0) · 右柱脚 (−213, 447) · "
             "右门框底 (0, 387) · 左门框底 (0, 60)",
             fontsize=10.6, color=INK, va="top")
    fig.text(0.055, 0.062,
             "Z = 0 为地面；门洞墙贴 X = 0，左柱外沿贴 Y = 0 —— 这两条对齐了，NPC 就不会跑偏。",
             fontsize=10.6, color=SUB, va="top")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    print(f"已生成 {out_path}  ({os.path.getsize(out_path) / 1024:.0f} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="生成门廊俯视建模图")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs", "modeling_plan.png"))
    main(ap.parse_args().out)
