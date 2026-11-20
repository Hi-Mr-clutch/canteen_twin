# 与 UE5 对接说明

本文件说明管线输出怎么喂给 UE5：读 JSON、复现人群、视频同步、UI 嵌入。

---

## 1. 三份数据的分工

| 文件 | 谁用 | 内容 |
|---|---|---|
| `npc_tracks.json` | **蓝图首选** | 每个 NPC 一条轨迹，cm 坐标 + 朝向，逐帧采样 |
| `tracks.json` | 需要帧维度的逻辑（如按时间刷统计） | 按帧组织，含全部字段与元信息 |
| `analytics.json` | UI / 报表 | 人数、峰值、区域停留、进出计数 |

`npc_tracks.json` 结构：

```json
{
  "schema": "canteen-twin/npc@1.0",
  "meta": {
    "unit": "cm",
    "coordinate_system": "UE5 左手系：X 前（进店 = +X，门洞墙 X=0）/ Y 右 / Z 上，地面 Z=0",
    "fps": 29.97,
    "frame_count": 936,
    "duration_sec": 31.23,
    "keyframe_step": 1,
    "npcs": 58
  },
  "npcs": [
    {
      "id": 1,
      "start_frame": 43,
      "end_frame": 460,
      "samples": [
        { "f": 43, "x": -320.0, "y": 226.8, "z": 0.0, "yaw": 6.0 },
        { "f": 44, "x": -312.0, "y": 227.6, "z": 0.0, "yaw": 6.0 }
      ]
    }
  ]
}
```

> 上面是**素材 A 的真实元数据**；素材 B 为 `fps 29.0 / 887 帧 / 34 人`。
> 蓝图里请从 `meta.fps` 读，不要写死数字。零基础逐步操作见
> [`local_test_guide.md`](local_test_guide.md)。

**坐标约定**（很重要，摆场景时必须对齐）：

- 单位 **cm**，`Z=0` 是地面，NPC 的 pivot 放在脚底
- `X` 指向**店内**（也就是人进店的方向，与 UE 的"前"同向）：门洞墙贴 `X=0`，室外在 `X<0`（柱脚线 `X=−213`），店内 `X>0`
- `Y` 沿墙方向，指向**画面右侧**（与 UE 的"右"同向）
- `yaw` 已经是 UE 的度数（绕 Z 轴，0=朝 +X），直接 `SetActorRotation(FRotator(0, yaw, 0))`；进店接近 0°，出店接近 180°
- 地面尺寸由 `meta` 里的 homography 决定，例如本门门廊平台 4.47m 宽 × 2.13m 深 = 447cm × 213cm
- 换算关系：`UE.X = (y_m − 地面进深 H) × 100`，`UE.Y = x_m × 100`

> 在 UE 里搭门口场景时，把被拍这个门的门洞墙放在 `X=0`、左柱外沿贴 `Y=0`，
> 室内朝 `+X` 延伸——和编辑器默认的 X 正方向一致，不需要旋转也不需要镜像。
> 门洞在 `Y` 方向的位置直接取配置里 `counters` 的 `p1/p2`，与人流数据天然对齐。
> 单机位只有一套坐标，不需要任何旋转/平移拼接。详细尺寸与轴向见 [`modeling_spec.md`](modeling_spec.md)。

---

## 2. 蓝图读取 JSON

UE5 有两条路，按项目情况选：

### 方案 A：内置 JSON Blueprint（推荐，零依赖）

编辑器 → 插件 → 搜索 **JSON Blueprint** → 启用 → 重启。

```
Event BeginPlay
 └─ Load Json from File
      File = 本地测试: "D:/canteen_twin/demo/entrance_a/npc_tracks.json"   // File Path 结构，拆引脚填
             打包发布: "<ProjectContentDir>/Data/npc_tracks.json"          // 见下方说明
         └─ Return Value（已是 Json 对象，不用再 Decode）
             ├─ Get Array Field "npcs"            → 数组
             │   └─ ForEachLoop
             │       ├─ Get Integer Field "id"            → int
             │       ├─ Get Integer Field "start_frame"   → int
             │       └─ Get Array Field "samples"         → 数组，缓存到该 NPC 的 TArray<FSample>
             └─ Get Object Field "meta" → Get Number Field "fps" → MetaFps
```

`FSample` 建议做成 Blueprint Struct：`float X / float Y / float Yaw / int Frame`。

> 用 `Load Json from File` 而不是 `Load String From File`：后者在部分 UE5 版本的
> 蓝图搜索里搜不到（分类被挪走），前者来自同一个 **Json Blueprint Utilities**
> 插件，一步直接拿到 Json，还省掉 `Decode Json`。若搜索里什么都找不到，
> 先把搜索面板右上角的 **「上下文关联」关掉**再搜。

### 方案 B：VaRest 插件

如果项目已经用了 VaRest，`VaRestJsonObject::DecodeJson` 更顺手，能直接 `GetArrayField`。

两种方案都要注意路径怎么给，本地测试和打包发布不一样：

- **本地 PIE 测试（推荐）**：`Load Json from File` 能读任意磁盘路径，直接把仓库里
  json 的绝对路径填进 `File Path` 即可，**不要把 json 放进 `Content/`**。`Content/` 下的 `.json`
  会被 UE 当成「待导入的 DataTable 源文件」，反复弹「数据表选项」对话框；
  点取消后内容浏览器里看不到它（正常），但弹窗每次都来。
  详见 [`../demo/README.md`](../demo/README.md) 开头的说明与清理步骤。
- **打包发布**：绝对路径会失效，改成把 json 纳入项目、用
  `FPaths::ProjectContentDir() + "Data/npc_tracks.json"` 拼路径，
  并在 Project Settings → Packaging 里把该目录加入
  **Additional Non-Asset Directories to Package**，否则打包后读不到。

> 无论哪种，`Load Json from File` 路径写错时都会**静默失败**（返回一个空 Json，
> 不报错），所以务必先打印 `Get Array Field "npcs"` 的长度。素材 A 应为 58，B 应为 34。

---

## 3. NPC 按真实轨迹逐帧插值移动

核心思路：**用"视频时间"驱动，而不是用游戏 Tick 累积时间**。这样即使帧率抖动、卡顿，NPC 也不会跑偏。

### 3.1 数据结构

```
Struct FNpcSample { float X; float Y; float Yaw; int Frame; }
Struct FNpcTrack { int Id; int StartFrame; int EndFrame; TArray<FNpcSample> Samples; }
```

### 3.2 生成 NPC

```
自定义事件 SpawnAllNpcs
 ├─ ForEach NPC track
 │   ├─ Spawn Actor from Class (BP_Npc)  at (Track.Samples[0].X, .Y, 0)
 │   ├─ Set NpcTrack = Track
 │   └─ 存入 TMap<int, BP_Npc> AllNpcs
```

NPC 数量一般十几到几十，直接 Spawn 即可；上百人时建议改用 Instanced Static Mesh + 手动更新 Transform。

`BP_Npc` 必须基于 **Actor**（不是 Character）、pivot 在脚底、关掉碰撞与自身 Tick，
并且自带一个 `NpcTrack`（`FNpcTrack`）变量供 `Set NpcTrack` 和逐帧插值读取。
逐项设置见 [`local_test_guide.md`](local_test_guide.md) 5.2b。

### 3.3 每帧更新（关键逻辑）

```
Event Tick
 ├─ T = MediaPlayer.GetTime()            // 或 GetDisplayTime()，单位秒
 ├─ CurFrame = T * MetaFps               // 从 meta.fps 读：A=29.97，B=29.0；别写死 20
 ├─ ForEach (Id → Npc) in AllNpcs
 │   ├─ 若 CurFrame < Track.StartFrame 或 > Track.EndFrame → 隐藏
 │   ├─ 否则 → 二分查找得到 i，使 Samples[i].Frame <= CurFrame < Samples[i+1].Frame
 │   ├─ Alpha = (CurFrame - Samples[i].Frame) / (Samples[i+1].Frame - Samples[i].Frame)
 │   ├─ Pos = Lerp(Samples[i].XY, Samples[i+1].XY, Alpha)
 │   ├─ Yaw = LerpAngle(Samples[i].Yaw, Samples[i+1].Yaw, Alpha)   // 注意用最短角差
 │   └─ SetActorLocationAndRotation(Pos, FRotator(0, Yaw, 0), bSweep=false)
```

`SetActorLocationAndRotation` 建议关掉 Sweep（`bSweep=false`），人群密集时开扫掠会互相推挤，反而偏离真实轨迹。

`CurFrame` 与 UI 的帧号 `f` 都从视频 0 秒起算（本仓库两段素材 `time_offset_sec = 0`）。
若以后改了 offset，两边要一起减，别只改一处。

**Yaw 插值要处理环绕**：从 179° 到 -179° 直接 Lerp 会转 358°，应该走 2° 的近路。蓝图里用 `Lerp (Rotator)` 节点即可，引擎内部已处理最短路径。

### 3.4 如果 keyframe_step > 1

导出时用 `--npc-keyframe-step 3` 可以抽稀到每 3 帧一个关键点，文件小 2/3。
此时上面的 Alpha 计算不变（关键帧之间的插值仍然是线性的），只是转弯处会略微变成折线。
人走路基本是直线，视觉上无差别。

---

## 4. 视频与孪生同步

### 4.1 播放视频

1. 把 `annotated.mp4`（或原始视频）放进 `Content/Movies/`
2. 新建 **Media Player** 资产，勾选 **Video output Media Texture asset**
3. 场景里放一个 Plane，材质用该 Media Texture —— 当作"监控画面墙"
4. 蓝图里 `MediaPlayer.Open Source` → `Play`

### 4.2 同步策略

| 策略 | 做法 | 适用 |
|---|---|---|
| **时间驱动（推荐）** | 每 Tick 读 `MediaPlayer.GetTime()`，换算帧号驱动 NPC | 通用，自动纠正漂移 |
| 帧回调 | 绑 `OnMediaPlayerVideoFrame`，按帧更新 | 精度最高，但解码线程回调，注意线程安全 |
| 手动同步 | 按键触发一次性对齐 | 答辩演示足够 |

**关键点：永远以 MediaPlayer 的时间为准**。游戏 Tick 和视频解码是两个时钟，各走各的必然漂移；让 NPC 追着视频时间走，漂移就自动消除了。

如果视频循环播放（Loop=true），`GetTime()` 会回到 0，NPC 也应该瞬移回起点 —— 上面的逻辑天然支持，因为一切由 `CurFrame` 推导。

> **这个 `T` 还同时驱动统计 UI（见第 5 节）。** 同一个 Tick 读一次 `T`，一路给 NPC 算 `CurFrame`，
> 一路推给 UI 定位帧号。两边共用一个时钟，所以「有人进门 → NPC 出现 → 面板数字 +1」必然同步，
> 不需要任何额外的对时或消息。

### 4.3 视频里"加框"的问题

`annotated.mp4` 上已经画了检测框、ID、区域颜色。如果不想让观众看到"AI 痕迹"，跑管线时加 `--no-video` 只用原始视频；或者用 `tracks.json` 在 UE 里用 Widget 自己画框（更灵活，可开关）。

---

## 5. 统计分析 UI：已内置，UE5 只负责「喂时间」

> **UI 由本仓库提供**：`ui/index.html` 是实时看板，`tools/build_ui.py` 把
> `realtime.json` 内嵌进去，生成单文件 `dashboard_live.html`（双击可看）。
> 数据契约见 [`realtime_data_contract.md`](realtime_data_contract.md)。
> UE5 侧只做三件事：透明 Web Browser 铺满、视频放右侧、每 Tick 推一次 `T`。

### 5.0 布局：L 型 HUD

```text
┌──────────────────────────────────────┬──────────────┐
│ 顶部横条：标题 / 核心指标 / 时钟        │              │
├──────────────────────────────────────┤  右侧竖栏     │
│                                      │  · 视频窗口   │
│   左下：UE5 3D 画面（页面完全透明）    │  · 补充指标   │
│                                      │  · 人数曲线   │
│                                      │  · 俯视点位   │
│                                      │  · 事件流     │
└──────────────────────────────────────┴──────────────┘
```

页面只有顶部和右侧有实体面板，**左下整块透明**，UE 的 3D 视口从底下透出来。
`body` 默认透明；页面一旦收到 `onVideoTime(T)` 就切到 `ue` 模式，隐藏预览提示、左下全透明。

### 5.1 「实时」怎么成立

视频是提前录好的，实时 = **回放时间轴驱动**：视频播到 T 秒，
UI 显示「截至 T 秒」的统计。不是摄像头在线推理。

**单一时钟**：同一个 Tick 读一次 `MediaPlayer.GetTime()` 得到 `T`，
一路算 NPC 的 `CurFrame`，一路推给 UI 定位帧号 `f`。
所以「有人进门 → NPC 出现 → 面板数字 +1」必然同帧发生。

管线导出 `realtime.json`：每帧的累计人数 / 进出 / 峰值 / 区域占用 + 事件流 +
在场人员地面点位。它与 `npc_tracks.json` 来自同一次统计重放，帧号 `f`
和人员 `id` 两边完全对齐，最终值也和 `analytics.json` 一致。

> 别在蓝图里自己数 NPC：要在蓝图里重写计数线判定，口径容易和 Python 侧不一致，
> 而且遮挡时 NPC 消失重生会让数字抖动。

### 5.2 三步接入

**第一步：生成成品页**

```bash
python3 tools/build_ui.py --data out/entrance/realtime.json \
        --video annotated.mp4 --h264 --out out/entrance/dashboard_live.html
```

产物是**单文件自包含**（数据内嵌），`file://` 直接能开，不受 CEF 的 fetch / CORS 限制。
`--h264` 会把 OpenCV 输出的 mp4v 转成浏览器能播的 H.264（没装 ffmpeg 会跳过并提示）。

**第二步：UMG 铺满全屏 + 开透明**

1. 启用 **Web Browser** 插件（Plugins → Web Browser），重启编辑器
2. UMG 里放一个 **Web Browser** 控件，锚点四边拉满（0,0 → 1,1），勾 **Is Variable**
3. 勾选 **Supports Transparency**（有的版本叫 Enable Transparency）——不勾，左下就是一块黑
4. `Initial URL` 填 `file:///.../dashboard_live.html`（单文件，不需要起 http 服务）

**第三步：每 Tick 推时间**

```text
Event Tick
 ├─ T  = MediaPlayer.GetTime()                        // 秒，和 NPC 同一个值
 ├─ Js = "onVideoTime(" + FString::SanitizeFloat(T) + ")"
 └─ WebBrowser → Execute Javascript (Js)
```

- 页面收到第一次调用就切到 `ue` 模式，之后完全跟随这个 `T`，不再自己计时
- 60 Tick/s 调用没有压力；也可只在 `T` 变化超过 `1/fps` 时调
- 视频循环时 `T` 归零，UI 和 NPC 一起回到开头

### 5.3 视频放右侧：两种接法

| 接法 | 做法 | 适用 |
|---|---|---|
| **A 页面内播放**（默认） | 右侧自带 `<video>`，加载同目录视频；`--h264` 自动转码 | 最省事，UMG 里只有一个控件 |
| **B UE Media Texture 透出** | 右侧视频区保持透明；UMG 里放 Image + Media Texture 叠在该位置；蓝图调 `CanteenTwin.useExternalVideo(true)` | 视频必须由 UE 解码，或要做画中画特效 |

**编码坑（很重要）**：管线用 OpenCV 写出的 `annotated.mp4` 通常是 **`mp4v`**，Chrome/CEF **不能播**。

- 接法 A：用 `--h264` 生成 `annotated_web.mp4`（脚本按 libx264 → openh264 → VP9 自动选可用的）
- 接法 B：不受影响，UE 的 MediaPlayer 自己能解 mp4v
- 手机原始视频一般是 H.264，直接放页面里也能播

### 5.4 页面接口

| 接口 | 说明 |
|---|---|
| `onVideoTime(T)` | UE 每 Tick 调用，单位秒；调用后进入 UE 模式 |
| `CanteenTwin.setData(json)` | 换数据，不用重新生成页面 |
| `CanteenTwin.useExternalVideo(true)` | 隐藏页面内 video，让 UE 的 Media Texture 透出 |
| `CanteenTwin.setVideoSrc(url)` | 换视频源 |
| `CanteenTwin.getState()` | 调试用，返回当前 mode / T / f |

独立预览（浏览器直接打开）时，页面自己播放视频或内部计时，播放/暂停/进度条都能用；
一旦收到 `onVideoTime` 就完全交给 UE 时钟。

### 5.5 页面怎么由 T 找到数据

```js
const f = Math.max(0, Math.min(meta.frame_count - 1,
              Math.floor((T - meta.time_offset_sec) * meta.fps)));
const snap = frames[f];     // 直接渲染这一帧的累计值，不要在前端累加
```

帧号 `f` 与 `npc_tracks.json` 的 `samples[].f` 一致，`actors[].id` 与 `npcs[].id` 一致。
同一个 `id` + 同一个 `f`，UI 上的人和 UE 里的 NPC 就是同一个对象。

完整字段表、事件类型与坐标约定见
[`realtime_data_contract.md`](realtime_data_contract.md)。

### 5.6 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 左下是一块黑，看不见 3D 场景 | Web Browser 没开透明 | 勾 `Supports Transparency`；确认页面是成品页且已进入 `ue` 模式 |
| 页面一直停在 0.0s | `Execute Javascript` 没调用 | 核对控件 Is Variable、拼出来的字符串 |
| 白屏 | 用了模板页且 `file://` 被 CEF 拦 | 改用 `build_ui.py` 生成的成品页，或起 `http://localhost:8000` |
| 视频区提示"编码不支持" | `annotated.mp4` 是 mp4v | 重新用 `--h264` 生成，或换接法 B（UE Media Texture） |
| 数字不动但 NPC 在动 | 推的是 Tick 累计时间 | 统一用第 4 节同一个 `T` |
| 面板比视频快/慢 | 用了源视频 fps 或漏了 offset | 用 `meta.fps`，按 5.5 公式减 `time_offset_sec` |
| 数字和报告对不上 | 页面内嵌的是旧数据 | 重跑管线后重新 `build_ui.py` |

### 5.7 想要「摄像头在线分析」怎么办

当前是回放驱动。若以后要真正边拍边出数，把检测/跟踪/统计改成流式
（逐帧读 RTSP + 滑动窗口累计），再由服务端推增量给 UI，
数据契约升级到 `@2.0`。那是另一个工程量，本应付项目用回放驱动就够。

---

## 6. 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| NPC 全部挤在原点 | json 没读到，Samples 为空 | 先打印 `Get Array Field("npcs")` 的 `Length`（应为 58/34）；检查蓝图 `File` 引脚里的绝对路径 |
| UE 反复弹「数据表选项 / 导入为 DataTable」 | json 被放进了 `Content/` | 从 `Content/` 删掉，蓝图改读仓库里的绝对路径；点「取消」不影响蓝图读取 |
| NPC 朝反方向走 | 场景 X/Y 轴没对齐，或还按旧图纸（进店 = −X）建 | 门洞墙贴 X=0、左柱贴 Y=0、室内朝 +X；见 `modeling_spec.md` §1.1 |
| NPC 抖 | 没做插值，直接取整帧位置 | 按上面的 Alpha 做 Lerp |
| 人和视频不同步 | 用 Tick 累积时间驱动 | 改成读 `MediaPlayer.GetTime()` |
| Web Browser 白屏 | 本地文件被 CEF 拦 | 改用 `http://localhost` |
| 视频卡顿 | mp4v 编码在部分机器上软解吃力 | 转 H.264：`ffmpeg -i in.mp4 -c:v libx264 -pix_fmt yuv420p out.mp4` |
