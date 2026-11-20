# 学校饭堂门口 · 人流量视频分析管线

数字孪生项目的**第一环**：把门口监控视频变成 UE5 能直接消费的逐帧人群轨迹 + 统计数据。

```
video.mp4 ─▶ 检测(人) ─▶ 跟踪(稳定ID) ─▶ 四点透视(像素→地面米制) ─▶ 统计+导出
                                                                  ├─ npc_tracks.json     给 UE5 蓝图（NPC 轨迹）
                                                                  ├─ realtime.json       实时数据源（看板唯一输入）
                                                                  ├─ dashboard_live.html 实时看板（单文件，UE 直接用）
                                                                  └─ analytics.json / tracks.csv / 热力图 / 核对视频
```

> **场景范围**：只做**饭堂门口外**的人流量（经过、进店、出店、门前滞留），不涉及饭堂内部功能。
> **场景建模与视频素材由你提供**，这里只有管线的代码，不含任何渲染/合成场景。
> **UI 已内置**：`ui/index.html` + `tools/build_ui.py` 生成单文件实时看板。
> 布局为 L 型：顶部横条 + 右侧竖栏是 UI，左下透明露出 UE5 的 3D 画面，视频放在右侧栏。
> **仓库地址**：https://github.com/Hi-Mr-clutch/canteen_twin

---

> ### 只想本地跑 UE 测试？从这里开始
>
> `git clone https://github.com/Hi-Mr-clutch/canteen_twin.git` 后先看
> **[`demo/README.md`](demo/README.md)**：仓库已附带 A / B 两套**开箱成品**
> （`npc_tracks.json` + `dashboard_live.html` + H.264 视频），不用装 Python、不用重跑管线。
> **一个文件都不用复制进 UE 工程**：蓝图 `Load Json from File` 直接读仓库里
> `demo/entrance_a/npc_tracks.json` 的绝对路径，HTML 和视频留在原地、
> Web Browser 的 URL 指过去即可。**别把 json 放进 `Content/`**（会反复弹
> 「数据表选项」导入框）。零基础的蓝图接线 / 插视频 / 验收清单见
> [`docs/local_test_guide.md`](docs/local_test_guide.md)。

---

## 1. 你要准备的东西

**一台机位、一个门口**，录一段视频就够。单机位能算出这个门口的全部指标
（进出人次、峰值同框、人均停留、区域占用、热力图动线），不需要第二视角来"拼"数据。

| 素材 | 要求 | 放哪里 |
|---|---|---|
| 门口视频 | 固定机位、俯角 25°~45°、画面里有**门洞 + 门前地面 + 柱子/门框** | `data/input/door_front.mp4` |

> **两段最终素材已定稿**（A 1080p / B 720p），不再重录。已标定的可复现配置
> `configs/final_a_1080p.json`、`configs/final_b_720p.json`，放好素材后直接跑；
> 参数、标定点、最终统计与已知局限见 [`docs/final_footage.md`](docs/final_footage.md)。
> 原始视频体积大（A 98 MiB）不进仓库，请用网盘/U 盘交给协作者；
> 但 [`demo/`](demo/README.md) 里附带了转码后的小体积网页视频（约 12 MiB / 段），
> **本地测试 clone 仓库即有**，不需要另外传视频。

> 相比两机位方案，单机位省掉了：两路对时、转角墙出镜、画面不重叠、90° 坐标旋转、
> 结果合并，以及"累计人数不能相加"这个口径坑。**不需要第二台设备，也不需要合并脚本。**

**尺寸已经量好了，不用再测，也不需要摆任何标记物**——柱子、门框本身就是最好的参照点：
边缘锐利、永久固定、不会被人踩走。`configs/entrance_measured.json` 里的地面梯形、
门洞计数线、门前平台区域都已按实测数据（柱距 4.47m / 门宽 3.27m / 进深 2.13m）算好，
你只要在首帧上点 4 下：

![标定四点示意](docs/calib_points_demo.png)

```bash
# 协作者从这里开始（本地已有项目可跳过）
git clone https://github.com/Hi-Mr-clutch/canteen_twin.git
cd canteen_twin

pip install -r requirements.txt

# 1) 标定：首帧上依次点 左柱脚 → 右柱脚 → 右门框底 → 左门框底（都是建筑角点，不摆标记）
#    --apply 会把结果直接写回配置，不用手工复制粘贴
python3 tools/calibrate_homography.py --video data/input/door_front.mp4 \
        --entrance-geometry 4.47,3.27,2.13 --apply configs/entrance_measured.json

# 2) 跑
python3 -m src.run_pipeline --config configs/entrance_measured.json
```

结果固定输出到 `out/entrance/`。

> 录之前必须确认什么（机位 2.5~4m、俯角 25°~45°、全程不动、避免逆光），
> 见 [`data/input/README.md`](data/input/README.md)。
>
> 若画面里门洞位置与配置预置的对不上，用 `tools/pick_zones.py` 在画面上重点一遍计数线/区域
> （叠加 1m 网格，点完生成校验图）。

> **统计口径**：单机位下"累计人数"就是被拍这个门这一时段的人数，没有重复计数问题；
> 但报告里别写成"全饭堂总人数"，建议标题用「第一食堂正门 · 人流量分析」。

一键脚本（标定之后用）：`bash tools/run_all.sh`

---

## 2. 输出文件

固定输出到 `out/entrance/`：

| 文件 | 给谁用 | 内容 |
|---|---|---|
| `npc_tracks.json` | **UE5 蓝图** | 每个 NPC 一条轨迹：帧号 + UE 世界坐标(cm) + 朝向 |
| `realtime.json` | **UI（实时）** | 逐帧累计快照 + 事件流 + 人员点位；字段见 `docs/realtime_data_contract.md` |
| `dashboard_live.html` | **正式实时看板** | 单文件自包含，双击可看；UE 里用 Web Browser 加载 |
| `dashboard.html` | 离线快照（非实时） | 管线生成的静态看板，写报告 / 自查用 |
| `annotated.mp4` | 人工核对 | 叠加了检测框、ID、区域、计数线的视频 |
| `calibration_check.png` | 标定自查 | 1m 网格反投影回画面，网格贴地就说明标对了 |
| `heatmap.png` | 报告配图 | 门前地面人流密度（0.25m 栅格） |
| `tracks.json` | 二次开发 | 逐帧全量数据（含元信息、标定参数、区域定义） |
| `analytics.json` | 二次开发 | 统计汇总（人数/进出/区域停留/逐帧曲线） |
| `tracks.csv` | Excel | 同上，表格版 |

### 2.1 实时看板（UI 已内置）

> **第一次在 UE 里接线**：直接照 [`docs/local_test_guide.md`](docs/local_test_guide.md) 一步步点，
> 里面是插件、蓝图节点、插视频、验收清单的零基础流程，不用先读下面的原理。

看板在 `ui/index.html`，用 `tools/build_ui.py` 把 `realtime.json` 内嵌进去，生成单文件：

```bash
python3 tools/build_ui.py --data out/entrance_a/realtime.json \
        --video annotated.mp4 --h264 --out out/entrance_a/dashboard_live.html
```

布局是 L 型的，专为 UE5 全屏叠加设计：

- **顶部横条**：标题、当前人数 / 进店 / 出店 / 累计人数、时钟与帧号
- **右侧竖栏**：视频窗口、补充指标、人数曲线、门前俯视点位、实时事件流
- **左下大块透明**：露出 UE5 的 3D 场景；收到 `onVideoTime(T)` 自动切换

浏览器直接打开成品页就能预览（自带播放 / 暂停 / 拖动）；UE5 里怎么摆见
[`docs/ue5_integration.md`](docs/ue5_integration.md) 第 5 节。

`realtime.json` 是看板唯一数据源，每一帧都是「截至该帧」的累计快照，直接取用、不要自己累加。
字段契约见 [`docs/realtime_data_contract.md`](docs/realtime_data_contract.md)；
要换一套自己的 UI 时，照契约实现即可，不影响管线。

| 需要 | 在哪 |
|---|---|
| 数据契约（字段表 / 定位公式 / 示例） | [`docs/realtime_data_contract.md`](docs/realtime_data_contract.md) |
| 看板源码 / 构建脚本 | `ui/index.html`、`tools/build_ui.py` |
| **真实视频数据样例（联调用）** | `examples/realtime_a_1080p.json`、`examples/realtime_b_720p.json` |
| 无需真实视频的联调样例 | `examples/realtime_sample.json` |
| 素材参数 / 最终统计结果 | [`docs/final_footage.md`](docs/final_footage.md) |
| UE5 侧接线（透明控件 / 视频 / 推时间） | [`docs/ue5_integration.md`](docs/ue5_integration.md) 第 5 节 |
| **零基础本地联调（逐步操作 + 验收清单）** | [`docs/local_test_guide.md`](docs/local_test_guide.md) |

`dashboard.html` 是管线直接生成的离线快照（非实时），写报告或快速自查时用。

---

## 3. 管线各部分怎么做的

```
              ┌────────────────┐
 video ──────▶│ 检测 Detector   │  yolo / motion / auto（自动降级）
              └───────┬────────┘
                      │ bbox
              ┌───────▼────────┐
              │ 跟踪 Tracker    │  SimpleSORT：IoU + 中心距 + 衣色直方图
              └───────┬────────┘
                      │ 稳定 ID
              ┌───────▼────────┐
              │ 透视 Homography │  bbox 底边中点（脚点）→ 地面米制坐标
              └───────┬────────┘
                      │ (x_m, y_m) + 速度 + 朝向
              ┌───────▼────────┐
              │ 统计 + 导出      │  区域停留 / 进出计数 / 热力图 / 轨迹拼接
              └────────────────┘
```

### 3.1 检测：三档可切

| 模式 | 适用 | 说明 |
|---|---|---|
| `yolo` | **真实监控视频（推荐）** | ultralytics + COCO person 类，遮挡/并排分离能力强 |
| `motion` | 无权重、纯固定机位兜底 | MOG2 背景差分 + 连通域过滤，零权重依赖 |
| `auto`（默认） | 不确定时 | 先跑 12 帧 YOLO，检不到人自动切 `motion` 并打印原因 |

仓库已随附 `yolov8n.pt`（约 6MB），clone 下来就能直接跑 `yolo` / `auto`，不用另外下载权重。
若本地删掉了权重，把 `detector.yolo.weights` 改成**绝对路径**指向你自己的权重——
写成路径但文件不存在会立刻报错，不会卡住。`motion` 模式零权重依赖，固定机位也能跑。

### 3.2 跟踪：为了一件事——ID 不断

UE5 里一个 ID 就是一个 NPC，ID 断了就"消失重生"。所以做了三层保护：

- **中心距辅助匹配**：远处小目标 IoU 会掉到 0，此时靠中心距续 ID（`center_weight`）
- **衣色直方图**：两人并排/交叉时颜色比位置可靠，以乘子形式参与（位置不合理时不影响结果）
- **轨迹拼接后处理**：把"时间相邻 + 空间可达"的碎片接回同一个人（`src/postprocess.py`）

### 3.3 透视换算：四点标定

**用建筑自身的角点当标记即可**（柱子、门框、台阶沿），不需要摆任何东西——
把 4 个角点的**像素坐标**与已知的**米制坐标**（这里是一个等腰梯形）配对，解单应矩阵：

```bash
python3 tools/calibrate_homography.py --video data/input/你的视频.mp4 \
        --entrance-geometry 4.47,3.27,2.13
```

人的**脚点取 bbox 底边中点**（斜视下它就是人与地面的接触点），不是框中心。
跑完一定看 `calibration_check.png`：1m 网格贴住地面才算标对。**四个点的位置**决定计数和动线
准不准；W/H 填得差不改变人数、进出、峰值、停留，只影响速度数值和 UE 里 NPC 的绝对距离
（后者在 UE 里整体缩放即可对齐）。

> 门框底比柱脚高 0.2m（本门实测），四点因此略不共面，纵深比例会偏一成——**直接点门框底就行**，
> 想更准再沿门框竖边下移 0.2m 到与柱脚齐平处。两者都不影响人数和进出人次。

坐标转 UE5：`UE.X = (y_m − 地面进深)×100`（**进店 = +X**，门洞墙 `X=0`，室外柱脚线 `X=−213`），`UE.Y = x_m×100`，`Z=0`，单位 cm；朝向 `yaw` 已换算成 UE 角度。

### 3.4 统计口径（门口场景）

| 指标 | 定义 | 用途 |
|---|---|---|
| 累计人数 | 拼接去重后的轨迹数 | 这一时段来了多少人 |
| 进店 / 出店 | 轨迹穿越门洞计数线的方向（**带防抖**） | 双向人流、净流入 |
| 峰值同框 | 逐帧画面内人数的最大值 | 门口最挤的时刻 |
| 门前区域占用 | 轨迹落在「门前缓冲区 / 门前通道」的帧数 | 门口是否拥堵、滞留多久 |
| 热力图 | 地面 0.25m 栅格累积人数 | 动线走向，报告里最好看的一张图 |

计数线方向：`counters[].p1 → p2` 的左手法向为"进"。方向反了就把 `inward_sign` 改成 `-1`，
或者把 p1/p2 对调。看 `annotated.mp4` 里计数线的 `in: x out: y` 是不是跟着人变就知道对不对。

> **计数防抖**：脚点在门线附近抖动几厘米，叉积符号就会反复翻转，若每次都记会让人次虚高
> （真实视频实测高估 60%~80%）。`CounterLine` 要求同一人两次有效穿线同时满足
> `间隔 ≥ debounce_sec`（默认 0.5s）且 `脚点移动 ≥ min_travel_m`（默认 0.15m），
> 两个阈值在 `counters[]` 里配置，设 0 可关闭。仅影响进 / 出人次，
> 不影响累计人数、峰值、停留、热力图（`realtime.json` 结构不变，UI 侧无感）。

---

## 4. 配置速查（`configs/entrance_measured.json`）

实测版配置里**只有 `image_points` 需要你填**，其余都已按门廊尺寸算好。字段含义如下：

```jsonc
{
  "video": { "path": "../data/input/door_front.mp4", "frame_step": 1, "max_frames": null },

  "detector": {
    "type": "auto",                          // auto | yolo | motion
    "yolo": { "weights": "yolov8n.pt", "conf": 0.25, "imgsz": 960, "device": "cpu" },
    "motion": {
      "min_area": 140, "min_height": 22,     // 按人像实际像素大小调（远处人小就调小）
      "foot_offset_ratio": -0.10             // 负数=脚点上移，用来剔除影子
    }
  },

  "tracker": {
    "iou_threshold": 0.15, "center_weight": 0.55, "center_gate": 0.8,
    "appearance_weight": 0.6, "max_age": 45, "min_hits": 2, "smooth": 0.45
  },

  "homography": {
    "image_points":  [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],          // ← 只填这一项，标定工具点出来
    "ground_points": [[0,0],[4.47,0],[3.87,2.13],[0.6,2.13]],    // 米，等腰梯形：近边柱距 / 远边门宽 / 进深
    "ground_size_m": [4.47, 2.13],
    "ue_origin_cm": [0, 0, 0], "flip_x": false                   // 整体平移 cm；flip_x 会把 UE.Y 取反（左右镜像），正常别开
  },

  "zones":    [ {"name":"porch","polygon":[[0,0],[4.47,0],[3.87,2.13],[0.6,2.13]]} ],
  "counters": [ {"name":"door","p1":[0.6,2.13],"p2":[3.87,2.13],"inward_sign":1,
                 "debounce_sec":0.5,"min_travel_m":0.15} ]
}
```

`zones` / `counters` 里的坐标都是**地面米制坐标**，和 homography 同一套坐标系。
门洞计数线就是梯形的远边（两门框之间），`inward_sign` 控制哪边算"进"——
看 `annotated.mp4` 里线的 `in: x out: y` 是否跟人变就知道对不对，反了就改 `-1`。

调参顺序：**先标定 → 再 `min_area`/`min_height` 让框不漏不碎 → 最后 `max_age`/`appearance_weight` 治 ID 断裂**。

---

## 5. 已验证到什么程度

| 项 | 状态 |
|---|---|
| 单应/坐标映射/UE 换算 | 单元测试通过（往返误差 < 1e-3 像素） |
| 跟踪器 ID 保持 | 单元测试通过（单人保持 ID、两人交叉不串） |
| 检测器出框 | 单元测试通过（内存移动色块） |
| 导出 schema | 单元测试通过（tracks / npc_tracks 字段齐全） |
| 实时数据 | 单元测试通过（逐帧累计与最终汇总一致、事件类型 / 帧号契约齐全） |
| 全链路 | 用临时片段 + 两段真实门口视频跑通，各产出 9 个文件 |
| 真实门口视频 | **素材已定稿**：A(1080p) 58 人 / 进 74 出 37，B(720p) 34 人 / 进 22 出 8，见 [`docs/final_footage.md`](docs/final_footage.md) |
| 计数防抖 | 真实视频实测把虚高人次压掉 38%（A）/ 23%（B）；`analytics.json` = `realtime.json` = 画面计数线，三处一致 |

`python3 tests/test_smoke.py` 可随时复跑；`data/input/` 里有视频时会自动加跑一次端到端。

---

## 6. 目录结构

```
canteen_twin/
├── demo/                         # ★ 本地测试开箱包（clone 即有，不用跑管线）
│   ├── README.md                 # clone 到哪 / 文件放哪 / URL 怎么填
│   ├── entrance_a/               # A 素材：npc_tracks.json + dashboard_live.html + 视频
│   └── entrance_b/               # B 素材：同上
├── ui/
│   └── index.html                # ★ 实时看板（L 型 HUD：顶部+右侧 UI，左下透明）
├── src/
│   ├── run_pipeline.py      # 主入口：CLI + 主循环 + 可视化 + 汇总
│   ├── detector.py          # YOLO / 前景差分 / auto 降级
│   ├── tracker.py           # SimpleSORT（IoU + 中心距 + 外观）
│   ├── homography.py        # 四点标定、像素↔地面、UE 映射
│   ├── analytics.py         # 区域/停留/计数线/热力图
│   ├── postprocess.py       # 轨迹拼接
│   ├── exporter.py          # JSON / CSV / realtime.json / 离线快照看板
│   └── config.py            # 配置加载
├── tools/
│   ├── calibrate_homography.py   # 四点标定（交互点选 / 或用 --image-points）
│   ├── pick_zones.py             # 点选计数线/区域，自动换算成米（不用卷尺）
│   ├── make_modeling_plan.py     # 生成建模俯视图（改尺寸后重跑，图和文档不脱节）
│   ├── build_ui.py               # realtime.json 注入 UI，生成单文件实时看板
│   └── run_all.sh                # 一键：测试 → 跑管线 → 生成看板
├── configs/
│   ├── entrance.json             # 门口场景通用配置（示例坐标，按需改）
│   ├── entrance_measured.json    # 第一食堂正门 · 实测参数版（待填 4 个像素点）
│   ├── final_a_1080p.json        # ★ 最终素材 A：已标定，直接跑
│   └── final_b_720p.json         # ★ 最终素材 B：已标定，直接跑
├── data/input/                   # ← 你的视频放这里（附标定与录制说明）
├── examples/
│   ├── realtime_sample.json     # 无真实视频时的合成联调样例
│   ├── realtime_a_1080p.json    # ★ 真实视频 A 产出的实时数据
│   └── realtime_b_720p.json     # ★ 真实视频 B 产出的实时数据
├── out/                          # 输出（不进仓库）
├── yolov8n.pt                    # YOLOv8n 权重（已随仓库附带）
├── tests/test_smoke.py           # 冒烟测试（含计数防抖）
└── docs/
    ├── calib_points_demo.png     # 标定四点示意：点建筑角点，不用摆标记物
    ├── final_footage.md          # ★ 最终素材参数 / 标定点 / 结果 / 已知局限
    ├── modeling_spec.md          # UE5 建模规格：尺寸表 / 轴向 / 自检
    ├── modeling_plan.png         # 门廊俯视平面图（tools/make_modeling_plan.py 生成）
    ├── local_test_guide.md       # ★ 零基础本地联调手册：蓝图接线 / 插视频 / 验收清单
    ├── realtime_data_contract.md # ★ realtime.json 字段契约（换 UI 时看）
    └── ue5_integration.md        # UE5 蓝图读 JSON / NPC 插值 / 视频同步 / UI 接线
```

---

## 7. 已知局限

| 局限 | 影响 | 补法 |
|---|---|---|
| 单目 2D 透视 | 只能算地面位置，算不出身高/姿态 | 门口人流量统计不需要 |
| 遮挡后 ID 会断 | UE5 里表现为 NPC 重生 | YOLO 能大幅缓解；`max_age` 调大可容忍更久 |
| 固定机位假设 | 机位一动标定作废，要重标 | 云台机位本期不支持 |
| 无 GPU 时较慢 | 1080p 大约 10~15fps | 上 GPU，或 `imgsz` 降到 640 / `frame_step` 抽帧 |
| 进出计数依赖轨迹穿线 | 贴线徘徊曾会重复计数（高估 6~8 成） | 已加防抖：`counters[].debounce_sec` / `min_travel_m` 可调；画面拥挤时调大 |
| **单机位只覆盖一个门** | 结论不能代表"全饭堂总人流" | 报告写明采样的是哪个门；要全覆盖再加第二路 |

下一步是 UE5 侧，接口和蓝图写法见 [`docs/ue5_integration.md`](docs/ue5_integration.md)。
