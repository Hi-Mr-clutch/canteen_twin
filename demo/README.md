# 本地测试开箱包：文件放哪？

> **一句话答案**：把仓库 clone 到任意**纯英文、无空格**的目录，
> 然后**只复制 1 个文件**到 UE 工程（`npc_tracks.json` → `Content/Data/`）。
> HTML 和视频留在仓库原地不用动，UE 的 Web Browser 直接把 URL 指过来。

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
│   │   └── npc_tracks.json        ★ 唯一要复制进 UE 的文件
│   └── entrance_b\                       B 素材，结构完全相同
├── examples\                             真实数据样例（进阶用）
├── ui\  src\  tools\  configs\  docs\    源码 / 文档，测试不用动
└── docs\local_test_guide.md              ★ 零基础蓝图 + 插视频 + 验收清单

D:\UEProjects\CanteenTwin\                ← 你的 UE 工程
└── Content\
    ├── Data\
    │   └── npc_tracks.json        ← 从 demo\entrance_a\ 复制过来
    └── Movies\                          （仅"接法 B"才用；接法 A 空着即可）
```

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

### 第 2 步 · 只复制 1 个文件到 UE 工程

| 从 | 复制到 | 用途 |
|---|---|---|
| `D:\canteen_twin\demo\entrance_a\npc_tracks.json` | `D:\UEProjects\CanteenTwin\Content\Data\npc_tracks.json` | 蓝图读它生成 NPC |

`Content\Data\` 文件夹不存在就自己新建。文件名保持 `npc_tracks.json` 不变，
蓝图里写死的是 `FPaths::ProjectContentDir() + "Data/npc_tracks.json"`。

**A / B 二选一**：一次只放一份，别把两份都丢进 `Content\Data\`（同名会覆盖）。
先测 A（1080p，58 人），想换 B 就把 `entrance_b` 那份再复制过来覆盖。

### 第 3 步 · 让 UE 指到 HTML 和视频（**不用复制**）

在 `WBP_Hud` 的 Web Browser 控件里，`Initial URL` 填：

```text
file:///D:/canteen_twin/demo/entrance_a/dashboard_live.html
```

- 三个斜杠、用 `/` 不用 `\`
- `dashboard_live.html` 和 `annotated_web.mp4` 已经在同一个文件夹，
  页面用相对路径自动找到视频 → **右侧视频窗口直接出画面**
- 数据已内嵌进 HTML，所以也不需要 `realtime.json` 跟着放

> 换成 B 素材：把 URL 里的 `entrance_a` 改成 `entrance_b`，
> 同时把第 2 步的 `npc_tracks.json` 也换成 B 那份，**两边要一致**。

### 接法 A 与接法 B 放文件的区别

| | 页面内播放（**推荐，默认**） | UE Media Texture 播放（接法 B） |
|---|---|---|
| HTML | 留在仓库，URL 指过去 | 同左 |
| 视频 | 留在仓库、与 HTML 同目录 | **再复制一份**到 `Content\Movies\`，并建 File Media Source |
| `Content\Data\` | 放 `npc_tracks.json` | 同左 |
| 额外 | 无 | 蓝图调 `CanteenTwin.useExternalVideo(true)` |

接法 A 最省事：UE 里**只放 1 个 json**，视频由页面自己播。
两种接法的细节见 `docs/ue5_integration.md` 第 5.3 节。

---

## 4. 三个"别"

1. **别把 `dashboard_live.html` 和 `annotated_web.mp4` 分开** ——
   页面写的是相对路径 `annotated_web.mp4`，一分开右侧就黑屏/提示无视频。
2. **别改视频文件名** —— 想换视频就用 `tools/build_ui.py` 重新生成页面。
3. **别用 `out\` 里的路径写死在 UE 里** —— `out/` 不在仓库，
   本地 clone 后没有这个目录；用 `demo\` 里的成品。

另外：`annotated.mp4`（89 MiB，mp4v 编码）**不能用**，
Chrome / CEF 播不了。这里给的是转码后的 `annotated_web.mp4`（H.264，12 MiB）。

---

## 5. 放好之后怎么确认没放错

| 检查 | 期望 |
|---|---|
| 双击 `demo\entrance_a\dashboard_live.html` | 右侧出视频、顶部数字随时间跳（**不用 UE 就能验**） |
| UE 里 `Content\Data\npc_tracks.json` 存在 | 文件名和路径与蓝图一致 |
| UE Play 后 Output Log | `NPC 数 = 58`（A）/ `34`（B） |
| URL 粘贴到浏览器地址栏 | 能打开同一张看板 |

第一步在浏览器里过了，说明文件放对了、数据没缺；
剩下才需要开 UE 接蓝图。完整 10 条验收清单在
[`docs/local_test_guide.md`](../docs/local_test_guide.md) 第 7 节。

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
