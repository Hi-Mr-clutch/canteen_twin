#!/usr/bin/env bash
# 一键跑（单机位单门口）：检查素材 -> 冒烟测试 -> 跑管线 -> 提示结果位置
# 用法：bash tools/run_all.sh [视频路径] [配置文件]
#   默认配置 configs/entrance_measured.json（实测参数版），不给视频参数则用配置里的 video.path
#   标定请用 tools/calibrate_homography.py --apply 把 image_points 写回配置后再跑本脚本
set -euo pipefail

cd "$(dirname "$0")/.."

VIDEO="${1:-}"
CONFIG="${2:-configs/entrance_measured.json}"

echo "==> 0/3 检查运行环境"
python3 -c "import cv2, numpy, scipy; print('   opencv', cv2.__version__, '| numpy', numpy.__version__)" 2>/dev/null || {
  echo "   缺少依赖，先跑：pip install -r requirements.txt"; exit 1; }
python3 -c "import ultralytics; print('   ultralytics', ultralytics.__version__)" 2>/dev/null \
  || echo "   [warn] 没装 ultralytics，YOLO 不可用，会自动降级到前景差分"

echo
echo "==> 0.5/3 检查是否已标定"
python3 - "$CONFIG" <<'PY'
import json, sys
try:
    n = len(json.load(open(sys.argv[1], encoding="utf-8"))["homography"]["image_points"])
except Exception as e:
    print(f"   [warn] 读取配置失败：{e}"); sys.exit(0)
if n < 4:
    print("   [warn] 还没标定（image_points 为空），本次会用「整帧=地面」近似跑通，")
    print("          米制坐标不可用。正式出报告前请先跑：")
    print(f"          python3 tools/calibrate_homography.py --video <视频> \\")
    print(f"              --entrance-geometry 4.47,3.27,2.13 --apply {sys.argv[1]}")
else:
    print(f"   已标定（{n} 个角点）")
PY

echo
echo "==> 1/3 冒烟测试（不需要视频）"
python3 tests/test_smoke.py

echo
echo "==> 2/3 跑视频分析管线"
if [ -n "$VIDEO" ]; then
  python3 -m src.run_pipeline --config "$CONFIG" --video "$VIDEO"
else
  python3 -m src.run_pipeline --config "$CONFIG"
fi

echo
OUTDIR=$(python3 - "$CONFIG" <<'PY'
import json, os, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
d = c.get("output", {}).get("out_dir", "out/entrance")
# 配置里的 out_dir 相对 configs/ 目录，统一换算成相对项目根
if d.startswith("../"):
    d = d[3:]
print(d)
PY
)
echo "==> 3/3 完成，结果在 $OUTDIR/"
echo "   实时数据: $OUTDIR/realtime.json   （交给 UI 协作者）"
echo "   占位看板: $OUTDIR/dashboard.html  （正式 UI 可忽略）"
echo "   核对   : $OUTDIR/annotated.mp4"
echo "   标定查 : $OUTDIR/calibration_check.png  （网格贴地才算标对）"
echo "   UE5 用 : $OUTDIR/npc_tracks.json"
