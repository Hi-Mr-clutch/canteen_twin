# 本地测试开箱包：文件放哪？

> **一句话答案**：**一个文件都不用复制进 UE 工程。**
> clone 到纯英文路径后，蓝图 `Load Json from File` 直接读仓库里
> `demo/entrance_a/npc_tracks.json` 的绝对路径；Web Browser 的 URL 指到同目录的
> `dashboard_live.html`。三个文件原地不动，UE 里不需要出现它们。

---

## ⚠️ 别把 json 放进 `Content/`（会一直弹导入框）

很多人第一反应是把 `npc_tracks.json` 复制到 `<UE项目>/Content/Data/`。**不要这么做。**

UE 的内容浏览器只监控 `Content/` 目录，发现 `.json` 会认为它是
**待导入的 DataTable 源文件**，于是弹「数据表选项」对话框要求选行类型：

```
当前文件 /Game/Data/npc_tracks
导入为  DataTable
选择DataTable的行类型 ...
```

- 点**取消** → 不生成 `.uasset`，内容浏览器里自然看不到这个文件，
  但**磁盘上的 json 还在**，蓝图照样能读 → 这其实是正常状态，不是失败。
- 点**应用** → 会生成一个错误的空 DataTable 资产，必须删掉。
- 只要文件还留在 `Content/` 下，这个弹窗**每次都会再出现**，很烦且有误点风险。

我们的数据是**嵌套结构**（`npcs[].samples[]`），DataTable 表达不了，
而且本来就是靠蓝图 `Load Json from File` 运行时直接解析，
**根本不需要变成 UE 资产**。

**根治办法：让 json 待在 `Content/` 之外。** 蓝图路径填绝对路径即可，
UE 完全不会扫描它，弹窗彻底消失。

> 如果你已经放进 `Content/Data/` 了：
> 1. 内容浏览器里若有 `npc_tracks` 资产（误点过「应用」），右键 **Delete**；
> 2. 用资源管理器删掉 `<UE项目>/Content/Data/npc_tracks.json`；
> 3. 重启编辑器，弹窗不再出现；
> 4. 蓝图 Path 按下面第 2 步改成绝对路径。

---

## 0. 为什么会有这个目录

仓库的 `.gitignore` 排除了 `out/`（每次跑管线重新生成的产物）和 `data/input/`
（原始视频，A 就有 98 MiB）。但**本地 UE 测试恰恰需要这些产物**：
蓝图要读 `npc_tracks.json`、Web Browser 要加载成品页、右侧要播视频。

所以这里放了**已经跑好、可直接用**的两套成品（A / B），clone 下来就有：

- 不用装 Python、不用装依赖、不用重跑管线
- 不用找网盘或 U 盘要原始视频
- 不用先读懂源码

`ui/`、`src/`、`tools/`、`configs/`、`docs/` 是源码和文档，
**测试阶段可以完全不碰**；想重新生成页面或改口径时再看。

---

## 1. 两个目录，别混在一起

| | 是什么 | 示例路径 |
|---|---|---|
| **仓库目录** | 从 GitHub clone 下来的这份代码 | `D:\canteen_twin\` |
| **UE 工程目录** | 你已经建好模的那个 UE 项目 | `D:\UEProjects\CanteenTwin\` |

两者是**分开的两个文件夹**。不要把整个仓库拖进 UE 的 `Content/`，
也不要把 UE 工程放进仓库里。

---

## 2. clone 后长这样（只列和测试相关的）

```text
D:\canteen_twin\                          ← 仓库根
├── demo\                                 ★ 开箱包在这里
│   ├── README.md                         本文件
│   ├── entrance_a\
│   │   ├── dashboard_live.html    ★ Web Browser 的 URL 指它
│   │   ├── annotated_web.mp4      ★ 必须与 HTML 同目录，别改名
│   │   └── npc_tracks.json        ★ 蓝图直接读它的绝对路径
│   └── entrance_b\                       B 素材，结构完全相同
├── examples\                             真实数据样例（进阶用）
├── ui\  src\  tools\  configs\  docs\    源码 / 文档，测试不用动
└── docs\local_test_guide.md              ★ 零基础蓝图 + 插视频 + 验收清单

D:\UEProjects\CanteenTwin\                ← 你的 UE 工程
└── Content\
    └── （不需要 Data 文件夹，不需要放任何 json）
```

**注意**：UE 工程里什么都不放。`Content/Movies/` 也只有"接法 B"才需要。

---

## 3. 放置清单（照着做，只有 3 步）

### 第 1 步 · 把仓库拉到本地

```bash
git clone https://github.com/Hi-Mr-clutch/canteen_twin.git D:\canteen_twin
```

没装 Git 也行：浏览器打开 https://github.com/Hi-Mr-clutch/canteen_twin
→ 绿色 **Code** → **Download ZIP** → 解压到 `D:\canteen_twin\`。

> ⚠️ 路径**不要带中文、空格、括号**。UE 内置浏览器（CEF）对
> `file:///` 里的中文路径容易解析失败，白屏很难查。
> `D:\canteen_twin\` 可以，`D:\我的项目\饭堂 孪生\` 不行。

### 第 2 步 · 记下 json 的绝对路径（**不用复制文件**）

蓝图 `BP_Manager` 的 BeginPlay 里，`Load Json from File` 的 `File` 引脚
（**File Path 结构**，右键 → `Split Struct Pin` 拆开）直接填：

```text
D:/canteen_twin/demo/entrance_a/npc_tracks.json
```

- 用 `/`，不要 `\`；**不要** `FPaths::ProjectContentDir()` 拼接
- 这是纯磁盘路径，UE 不会把它当资产，也不会弹导入框
- 文件内容约 **988 KB**（1,011,771 字节）；接上 `Get Array Field("npcs")` → `Length`
  → `Print String`，应打印 **58**（A）/ **34**（B）

**A / B 二选一**：想换 B，把路径里的 `entrance_a` 改成 `entrance_b`，
同时把第 3 步 URL 里的 `entrance_a` 也改成 `entrance_b`，**两边要一致**。

> 这只是**本地 PIE 测试**的做法，最省事。将来要把游戏**打包发布**时，
> 绝对路径会失效，那时再按 [`docs/ue5_integration.md`](../docs/ue5_integration.md)
> 第 2 节改用 `FPaths::ProjectContentDir()` 并把 json 纳入打包内容。

### 第 3 步 · 让 UE 指到 HTML 和视频（**不用复制**）

在 `WBP_Hud` 的 Web Browser 控件里，`Initial URL` 填：

```text
file:///D:/canteen_twin/demo/entrance_a/dashboard_live.html
```

- 三个斜杠、用 `/` 不用 `\`
- `dashboard_live.html` 和 `annotated_web.mp4` 已经在同一个文件夹，
  页面用相对路径自动找到视频 → **右侧视频窗口直接出画面**
- 数据已内嵌进 HTML，所以也不需要 `realtime.json` 跟着放

### 接法 A 与接法 B 放文件的区别

| | 页面内播放（**推荐，默认**） | UE Media Texture 播放（接法 B） |
|---|---|---|
| HTML | 留在仓库，URL 指过去 | 同左 |
| `npc_tracks.json` | **留在仓库，蓝图读绝对路径** | 同左 |
| 视频 | 留在仓库、与 HTML 同目录 | **再复制一份**到 `Content\Movies\`，并建 File Media Source |
| `Content\Data\` | **不需要，不要建** | 同左 |
| 额外 | 无 | 蓝图调 `CanteenTwin.useExternalVideo(true)` |

接法 A 最省事：UE 工程里**一个文件都不用放**，视频由页面自己播。
两种接法的细节见 `docs/ue5_integration.md` 第 5.3 节。

---

## 4. 三个"别"

1. **别把 `dashboard_live.html` 和 `annotated_web.mp4` 分开** ——
   页面写的是相对路径 `annotated_web.mp4`，一分开右侧就黑屏/提示无视频。
2. **别改视频文件名** —— 想换视频就用 `tools/build_ui.py` 重新生成页面。
3. **别把 `npc_tracks.json` 放进 `Content/`** —— 会反复弹「数据表选项」，
   而且取消导入后内容浏览器里看不到它（正常，蓝图读的是磁盘文件）。
4. **别用 `out\` 里的路径写死在 UE 里** —— `out/` 不在仓库，
   本地 clone 后没有这个目录；用 `demo\` 里的成品。

另外：`annotated.mp4`（89 MiB，mp4v 编码）**不能用**，
Chrome / CEF 播不了。这里给的是转码后的 `annotated_web.mp4`（H.264，12 MiB）。

---

## 5. 放好之后怎么确认没放错

| 检查 | 期望 |
|---|---|
| 双击 `demo\entrance_a\dashboard_live.html` | 右侧出视频、顶部数字随时间跳（**不用 UE 就能验**） |
| 蓝图 `Load Json from File` → `Get Array Field("npcs")` → `Length` | `58`（A）/ `34`（B） |
| UE Play 后 Output Log | `NPC 数 = 58`（A）/ `34`（B） |
| URL 粘贴到浏览器地址栏 | 能打开同一张看板 |
| UE 编辑器 | 不再弹「数据表选项」 |

第一步在浏览器里过了，说明文件放对了、数据没缺；
剩下才需要开 UE 接蓝图。完整 10 条验收清单在
[`docs/local_test_guide.md`](../docs/local_test_guide.md) 第 7 节。

> 内容浏览器里**看不到** `npc_tracks.json` 是正确的，别去 Import、别拖拽。

---

## 6. 文件从哪来 / 对应关系

| 本地开箱文件 | 原本由谁生成 | 想自己重新生成 |
|---|---|---|
| `npc_tracks.json` | 管线 `run_pipeline.py` | 放好视频后 `bash tools/run_all.sh`（需 Python 环境） |
| `dashboard_live.html` | `tools/build_ui.py` 注入数据 | `python tools/build_ui.py --data examples/realtime_a_1080p.json --video annotated_web.mp4 --out ...` |
| `annotated_web.mp4` | `build_ui.py --h264` 转码 | `ffmpeg -i annotated.mp4 -c:v libx264 -pix_fmt yuv420p annotated_web.mp4` |

> 统计口径已固化：A = 58 人 / 74 进 / 37 出（29.97 fps，936 帧），
> B = 34 人 / 22 进 / 8 出（29.0 fps，887 帧）。
> 蓝图里的 `MetaFps` 从 `npc_tracks.json` 的 `meta.fps` 读，别写死 20。

---

## 7. 下一步

按 [`docs/local_test_guide.md`](../docs/local_test_guide.md) 走：
启用插件 → 建 `MP_Clock` 主时钟 → 蓝图读 JSON / Tick 插值 / 推 `onVideoTime(T)`
→ UMG 全屏透明 Web Browser → 验收。

卡住了不用打包工程，把「门洞墙/左柱/地面三个 `Location` 数字 +
顶视和透视两张截图 + `NPC 数 = ...` 那行日志」发过来即可。
