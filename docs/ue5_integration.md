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
    "coordinate_system": "UE5 左手系：X 前 / Y 右 / Z 上，地面 Z=0",
    "fps": 20.0,
    "frame_count": 480,
    "duration_sec": 24.0,
    "keyframe_step": 1,
    "npcs": 13
  },
  "npcs": [
    {
      "id": 1,
      "start_frame": 43,
      "end_frame": 460,
      "samples": [
        { "f": 43, "x": 835.9, "y": 119.9, "z": 0.0, "yaw": 0.0 },
        { "f": 44, "x": 835.9, "y": 120.6, "z": 0.0, "yaw": 0.0 }
      ]
    }
  ]
}
```

**坐标约定**（很重要，摆场景时必须对齐）：

- 单位 **cm**，`Z=0` 是地面，NPC 的 pivot 放在脚底
- `X` 指向**饭堂外墙方向**（也就是人"往店里走"的方向），墙贴 `X=0`
- `Y` 沿墙方向，指向画面右侧
- `yaw` 已经是 UE 的度数（绕 Z 轴，0=朝 +X），直接 `SetActorRotation(FRotator(0, yaw, 0))`
- 地面尺寸由 `meta` 里的 homography 决定，例如本门门廊平台 4.47m 宽 × 2.13m 深 = 447cm × 213cm
- 换算关系：`UE.X = (地面进深 H − y_m) × 100`，`UE.Y = x_m × 100`

> 在 UE 里搭门口场景时，把被拍这个门的外墙放在 `X=0`、左边界贴 `Y=0`，
> 门洞在 `Y` 方向的位置直接取配置里 `counters` 的 `p1/p2`，与人流数据天然对齐。
> 单机位只有一套坐标，不需要任何旋转/平移拼接。

---

## 2. 蓝图读取 JSON

UE5 有两条路，按项目情况选：

### 方案 A：内置 JSON Blueprint（推荐，零依赖）

编辑器 → 插件 → 搜索 **JSON Blueprint** → 启用 → 重启。

```
Event BeginPlay
 └─ Load String from File (Path = FPaths::ProjectContentDir() + "Data/npc_tracks.json")
     └─ Decode Json (String)
         └─ Get Json Object Field "npcs"      → 数组
             └─ ForEachLoop
                 ├─ Get "id"                  → int
                 ├─ Get "start_frame"         → int
                 └─ Get "samples"             → 数组，缓存到该 NPC 的 TArray<FSample>
```

`FSample` 建议做成 Blueprint Struct：`float X / float Y / float Yaw / int Frame`。

### 方案 B：VaRest 插件

如果项目已经用了 VaRest，`VaRestJsonObject::DecodeJson` 更顺手，能直接 `GetArrayField`。

两种方案都要注意：**把 json 放进 `Content/Data/` 并用 `FPaths::ProjectContentDir()` 拼路径**，打包后路径才不会丢。

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

### 3.3 每帧更新（关键逻辑）

```
Event Tick
 ├─ T = MediaPlayer.GetTime()            // 或 GetDisplayTime()，单位秒
 ├─ CurFrame = T * MetaFps               // MetaFps = 20.0
 ├─ ForEach (Id → Npc) in AllNpcs
 │   ├─ 若 CurFrame < Track.StartFrame 或 > Track.EndFrame → 隐藏
 │   ├─ 否则 → 二分查找得到 i，使 Samples[i].Frame <= CurFrame < Samples[i+1].Frame
 │   ├─ Alpha = (CurFrame - Samples[i].Frame) / (Samples[i+1].Frame - Samples[i].Frame)
 │   ├─ Pos = Lerp(Samples[i].XY, Samples[i+1].XY, Alpha)
 │   ├─ Yaw = LerpAngle(Samples[i].Yaw, Samples[i+1].Yaw, Alpha)   // 注意用最短角差
 │   └─ SetActorLocationAndRotation(Pos, FRotator(0, Yaw, 0), bSweep=false)
```

`SetActorLocationAndRotation` 建议关掉 Sweep（`bSweep=false`），人群密集时开扫掠会互相推挤，反而偏离真实轨迹。

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

## 5. 统计分析 UI：UE5 侧只负责「喂时间」

> **分工**：UI 页面由协作者实现，本仓库不提供、也不绑定任何实时页面。
> 数据契约见 [`realtime_data_contract.md`](realtime_data_contract.md)，
> 管线只导出 `realtime.json`。UE5 侧唯一要做的事是把视频时间推给页面。

### 5.0 「实时」怎么成立

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

### 5.1 UE5 侧要做的三件事

1. 启用 **Web Browser** 插件（Plugins → Web Browser），重启编辑器
2. UMG 里拖一个 **Web Browser** 控件（勾 **Is Variable**），加载 UI 协作者提供的页面
   - `file:///` 常被 CEF 拦成白屏，推荐起本地服务：
     `python3 -m http.server 8000 --directory <UI 目录>`
   - 把 `realtime.json` 放到页面能读到的位置（同目录，或页面自行 fetch）
3. 每 Tick 把视频时间推进页面：

```
Event Tick
 ├─ T  = MediaPlayer.GetTime()                        // 秒，和 NPC 同一个值
 ├─ Js = "onVideoTime(" + FString::SanitizeFloat(T) + ")"
 └─ WebBrowser → Execute Javascript (Js)
```

- `onVideoTime` 是 UI 页面暴露的全局函数名，**由 UI 协作者定名**，双方约定好即可
- 最终执行的字符串形如 `onVideoTime(12.34)`
- 60 Tick/s 调用没有压力；也可只在 `T` 变化超过 `1/fps` 时调
- 视频循环时 `T` 归零，UI 和 NPC 一起回到开头

### 5.2 页面怎么由 T 找到数据

```js
const f = Math.max(0, Math.min(meta.frame_count - 1,
              Math.floor((T - meta.time_offset_sec) * meta.fps)));
const snap = frames[f];     // 直接渲染这一帧的累计值，不要在前端累加
```

完整字段表、事件类型、坐标约定与示例片段见
[`realtime_data_contract.md`](realtime_data_contract.md)。

### 5.3 与 UI 协作者的接口清单

| 项目 | 约定 |
|---|---|
| 数据文件 | `out/entrance/realtime.json`（`out/` 不进仓库；联调用 `examples/realtime_sample.json`） |
| 时间推送 | UE5 每 Tick 调页面全局函数 `onVideoTime(秒)` |
| 时间值 | `MediaPlayer.GetTime()` 原值；`start_sec` 偏移由页面内部处理 |
| 帧号 | `f` 与 `npc_tracks.json` 的 `samples[].f` 一致 |
| 人员 ID | `actors[].id` / `events[].id` 与 `npcs[].id` 一致 |
| 页面函数名 | 由 UI 侧定，改名要同步告诉 UE5 侧 |
| 不做什么 | UE5 不统计人数、不解析 `npc_tracks.json` 去驱动 UI |

### 5.4 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面一直停在 0.0s | `Execute Javascript` 没调用 / 函数名对不上 | 核对函数名、控件 Is Variable、拼出来的字符串 |
| 白屏 | `file:///` 被 CEF 拦 | 改 `http://localhost:8000/...` |
| 数字不动但 NPC 在动 | 推的是 Tick 累计时间 | 统一用第 4 节同一个 `T` |
| 面板比视频快/慢 | 用了源视频 fps 或漏了 offset | 用 `meta.fps`，按 5.2 公式减 `time_offset_sec` |
| 数字和报告对不上 | 页面缓存了旧 json | 重跑管线后刷新 / 加 no-cache |

### 5.5 想要「摄像头在线分析」怎么办

当前是回放驱动。若以后要真正边拍边出数，把检测/跟踪/统计改成流式
（逐帧读 RTSP + 滑动窗口累计），再由服务端推增量给 UI，
数据契约升级到 `@2.0`。那是另一个工程量，本应付项目用回放驱动就够。

---

## 6. 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| NPC 全部挤在原点 | json 解析失败，Samples 为空 | 检查 `Content/Data/` 路径、`Decode Json` 是否返回 true |
| NPC 朝反方向走 | 场景 X/Y 轴没对齐 | 让场景远墙贴 X=0、左墙贴 Y=0；或导出时用 `flip_x` |
| NPC 抖 | 没做插值，直接取整帧位置 | 按上面的 Alpha 做 Lerp |
| 人和视频不同步 | 用 Tick 累积时间驱动 | 改成读 `MediaPlayer.GetTime()` |
| Web Browser 白屏 | 本地文件被 CEF 拦 | 改用 `http://localhost` |
| 视频卡顿 | mp4v 编码在部分机器上软解吃力 | 转 H.264：`ffmpeg -i in.mp4 -c:v libx264 -pix_fmt yuv420p out.mp4` |
