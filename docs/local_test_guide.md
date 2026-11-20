# 本地联调操作手册（零基础，照着点）

适用：UE5.x + 本仓库 `demo/` 开箱包。**全程在你自己电脑上做，不需要把 UE 工程发给我。**

> **从 GitHub clone 下来做本地测试的，先读 [`demo/README.md`](../demo/README.md)**——
> 那里讲清了「clone 到哪、哪个文件放哪、URL 怎么填」。
> 简单说：**只复制 1 个 `npc_tracks.json` 到 UE 的 `Content/Data/`，HTML 和视频留在仓库原地。**
> 下面手册里凡出现 `out/` 的地方，都是「自己重跑管线」时的输出位置；
> 用开箱包时一律换成 `demo/entrance_a/`（或 `entrance_b/`）。

---

## 0. 建模文件不用发我

一个 UE 工程几百 MB 到几 GB，聊天窗口传不了，也**没必要**传。
我远程判断"对不对"只需要三样轻量东西（第 7 节有清单）：

| 给我什么 | 怎么拿 | 多大 |
|---|---|---|
| 3 个数字 | 在 UE 里选中物体，看 Details 面板的 `Location`：门洞墙的 X、左柱外沿的 Y、地面的 Z | 一行文字 |
| 2 张截图 | 视口切到 Top（顶视，带坐标轴箭头）截一张；Perspective（透视，能看到门和地面）截一张 | 两张图 |
| 1 段日志 | 运行后把 Output Log 里 `Print String` 打出的 NPC 数量复制给我 | 一行文字 |

真正要验的两件事在你本地就能看：**NPC 是不是踩在地面上**、**进店是不是朝 +X 走**。

---

## 1. 先认清 3 个文件（都在 `demo/entrance_a/`）

| 文件 | 开箱包里的位置 | 放到哪 | 谁用 |
|---|---|---|---|
| `npc_tracks.json` | `demo/entrance_a/npc_tracks.json` | `<UE项目>/Content/Data/` | **蓝图**：NPC 逐帧坐标 |
| `dashboard_live.html` | `demo/entrance_a/dashboard_live.html` | **不用动**，URL 指过去 | **Web Browser 控件** |
| `annotated_web.mp4` | `demo/entrance_a/annotated_web.mp4` | **不用动**，与 HTML 同目录 | 页面右侧视频 |

> clone 后目录长什么样、两个目录怎么摆、A/B 怎么切换，见
> [`demo/README.md`](../demo/README.md)。**不需要 `realtime.json`**——数据已内嵌进 HTML。

> 两段素材的真实参数（**填蓝图时要用，别用文档示例里的 20**）：
>
> | 素材 | fps | 总帧 | 时长 | NPC 数 | 进 / 出 |
> |---|---|---|---|---|---|
> | A（1080p） | **29.97** | 936 | 31.23 s | **58** | 74 / 37 |
> | B（720p） | **29.0** | 887 | 30.59 s | **34** | 22 / 8 |

<details>
<summary>想自己重新生成这三个文件（需要 Python 环境，可跳过）</summary>

放好原始视频到 `data/input/` 后 `bash tools/run_all.sh` 会产出到 `out/entrance_a/`；
或只重新生成页面：

```bash
python tools/build_ui.py --data examples/realtime_a_1080p.json \
       --video annotated_web.mp4 --label "素材 A · 门口监控" \
       --out out/entrance_a/dashboard_live.html
```

`--h264` 会把 OpenCV 输出的 `mp4v` 转成浏览器能播的 H.264。
对应关系表见 [`demo/README.md`](../demo/README.md) 第 6 节。

</details>

---

## 2. 第 1 步：先不打开 UE，自测成品页

**用开箱包的话这一步什么都不用生成**：直接双击
`demo/entrance_a/dashboard_live.html`，点「播放」。

期望：右侧出视频画面、顶部数字随时间跳、能拖动进度条。
这一步过了，说明 UI + 数据 + 视频全都没问题，后面只剩 UE 接线。

> ⚠️ 唯一容易踩的坑：管线直接输出的 `annotated.mp4` 是 `mp4v` 编码，
> Chrome 和 UE 的 CEF **都播不了**，右侧会黑屏。开箱包里给的是已经转好的
> `annotated_web.mp4`（H.264），**必须与 HTML 放在同一个文件夹**。

---

## 3. 第 2 步：UE 项目准备

1. 打开你已经建好模的那个关卡。
2. 菜单 `编辑 Edit → 插件 Plugins`，搜出两个插件并 **Enable**，然后**重启编辑器**：
   - `JSON Blueprint` —— 读 `npc_tracks.json`
   - `Web Browser` —— 显示 UI
3. 在 **Windows 资源管理器**（不是 UE 内容浏览器）里，到 `<项目>/Content/` 下新建
   `Data` 和 `Movies` 两个文件夹：
   - 把 `demo/entrance_a/npc_tracks.json` 复制进 `Content/Data/`
   - 接法 A（默认）**不需要**往 `Movies` 放东西；接法 B 才把 `annotated_web.mp4` 复制进去
   - json / mp4 不是 UE 资产，**别用 Import**，直接文件管理器复制
4. 建模自检（选中物体看右下角 Details → Transform → Location）：

| 物体 | 应该是 |
|---|---|
| 门洞那面墙 | `X = 0` |
| 左柱外沿 | `Y = 0` |
| 地面 | `Z = 0` |
| 柱脚线（室外、靠相机） | `X = −213` |
| 室内 | 朝 **+X** 延伸 |

地面**铺大一圈**：门外 ≥ 4.5 m、门内 ≥ 8 m、左右各外扩 ≥ 6 m
（见 `docs/modeling_spec.md`）。机位偏平会让部分脚点外推到十几米外，
地面不够大，那些 NPC 会"走在空中"。

---

## 4. 第 3 步：插视频

### 4.1 先做「主时钟」MediaPlayer（必须有，哪怕画面不显示）

1. 内容浏览器右键 → `Media` → **Media Player**，命名 `MP_Clock`
2. 新建时**勾上 "Video output Media Texture asset"**，会自动多出 `MP_Clock_Video`
3. 再建一个 **File Media Source**：右键 → `Media` → `File Media Source`，
   命名 `MS_Clock`，`File Path` 指向 `Content/Movies/annotated_web.mp4`
   （接法 A 若不往 Movies 放文件，也可直接指向仓库 `demo/` 里那份的绝对路径）
4. 打开 `BP_Manager`（下一步会建）的 BeginPlay，接：

```
Event BeginPlay
 ├─ MP_Clock → Open Source (MS_Clock)
 ├─ MP_Clock → Set Looping (true)       // 循环演示
 └─ MP_Clock → Play
```

> 本地偷懒版：可以不建 File Media Source，直接用 `MP_Clock → Open URL`，
> 填视频的完整路径（例如 `D:/canteen_twin/demo/entrance_a/annotated_web.mp4`）。
> 但打包后会失效，正式用还是走 File Media Source。

**这个 MediaPlayer 唯一的职责是提供 `GetTime()`**。视频画面由谁显示都行，
但它必须真的在播，否则 `T` 恒为 0，NPC 和面板都不动。

### 4.2 视频画面放到右侧：两种接法

**接法 A（推荐，最省事）：页面自己播**

右侧视频窗口已经写在 `dashboard_live.html` 里了。只要 mp4 和 html 同目录、
且是 H.264，页面加载后就会自己播；收到 `onVideoTime(T)` 后还会把
`<video>.currentTime` 对齐到 `T`，所以画面和 NPC 同步。

→ **UE 侧不用建 Media Texture、不用放 Plane、不用摆位置。**
你的布局要求（顶部 + 右侧 UI、左下 3D、视频在右侧）已经由页面实现了。

**接法 B（备选）：UE 解码，Media Texture 透出**

只有在"视频必须由 UE 解码"或要做画中画特效时才用：

1. 用 `MP_Clock_Video` 建一个材质，Material Domain 设 **User Interface**
2. UMG 里在右侧栏对应位置放一个 `Image`，Brush 用这个材质
3. 蓝图里调一次 `CanteenTwin.useExternalVideo(true)`，让页面右侧视频区变透明
4. 缺点：Image 的位置要手动对齐页面 CSS 的右侧栏，分辨率一变就要重调

### 4.3 关键：同一个 T 喂两处

```
同一个 Event Tick 里只读一次 T = MP_Clock.GetTime()
 ├─ 一路 → NPC 的 CurFrame（第 5 步）
 └─ 一路 → UI 的 onVideoTime(T)（第 6 步）
```

**不要**用 `DeltaSeconds` 自己累加时间。游戏 Tick 和视频解码是两个时钟，
各走各的必然漂移；让 NPC 和面板一起追视频时间，漂移自动消除。

---

## 5. 第 4 步：蓝图接 NPC

### 5.1 建两个结构体

内容浏览器右键 → `Blueprint` → `Structure`：

```
FNpcSample : float X;  float Y;  float Yaw;  int Frame;
FNpcTrack  : int Id;   int StartFrame;  int EndFrame;  TArray<FNpcSample> Samples;
```

### 5.2 建 `BP_Manager`（Actor Blueprint），加这些变量

| 变量 | 类型 | 用途 |
|---|---|---|
| `MetaFps` | float | 从 json 读，**A=29.97 / B=29.0** |
| `Tracks` | TArray\<FNpcTrack\> | 所有轨迹 |
| `AllNpcs` | TMap\<int, BP_Npc\> | id → 场景里的小人 |
| `MP_Clock` | Media Player 引用 | 主时钟 |
| `WB_Hud` | Web Browser 引用 | 第 6 步的控件 |

`BP_Npc` 随便放个 Capsule + 人形 Mesh 即可，**pivot 放在脚底**（Z=0 时脚贴地）。

### 5.3 BeginPlay：读 JSON

```
Event BeginPlay
 ├─ Path      = FPaths::ProjectContentDir() + "Data/npc_tracks.json"
 ├─ JsonStr   = Load String From File (Path)
 ├─ JsonObj   = Decode Json (JsonStr)              // 返回 bool，false 就 Print "JSON 解析失败"
 ├─ MetaObj   = Get Object Field ("meta")
 ├─ MetaFps   = MetaObj → Get Number Field ("fps")
 ├─ Arr       = JsonObj → Get Array Field ("npcs")
 ├─ Print String ("NPC 数 = " + Length(Arr))       // 素材 A 应显示 58，B 应显示 34
 └─ ForEachLoop (Arr) → 每个元素 JsonValue → As Object:
      ├─ Id         = Get Integer Field ("id")
      ├─ StartFrame = Get Integer Field ("start_frame")
      ├─ EndFrame   = Get Integer Field ("end_frame")
      ├─ SamplesArr = Get Array Field ("samples")
      └─ ForEachLoop (SamplesArr) → 组装 FNpcSample:
           Frame = Get Integer Field ("f")
           X     = Get Number  Field ("x")
           Y     = Get Number  Field ("y")
           Yaw   = Get Number  Field ("yaw")
         → Track.Samples.Add(...)
      → Tracks.Add(Track)
```

> 不同版本 JSON Blueprint 的节点名略有差别，认准 `Get ... Field` 系列即可。
> `Print String` 出来不是 58 / 34，说明路径或 json 放错了，先别往下做。

### 5.4 自定义事件 `SpawnAllNpcs`（BeginPlay 末尾调用）

```
ForEachLoop (Tracks)
 ├─ Spawn Actor from Class (BP_Npc)
 │     Spawn Transform = (Track.Samples[0].X, Track.Samples[0].Y, 0)
 │     Rotation        = (0, Track.Samples[0].Yaw, 0)
 ├─ 把 Track 存到该 Actor 的变量 NpcTrack
 └─ AllNpcs.Add(Track.Id, 生成的 Actor)
```

### 5.5 Event Tick：插值移动（核心）

```
Event Tick
 ├─ T        = MP_Clock → Get Time (Seconds)      // 不要累加 DeltaSeconds
 ├─ CurFrame = T * MetaFps                        // A=29.97 / B=29.0
 ├─ ForEach (Id → Npc) in AllNpcs
 │   ├─ 若 CurFrame < NpcTrack.StartFrame 或 > NpcTrack.EndFrame
 │   │     → Npc.SetActorHiddenInGame(true)
 │   ├─ 否则
 │   │   ├─ SetActorHiddenInGame(false)
 │   │   ├─ i = 找到最后一个 Samples[i].Frame <= CurFrame
 │   │   ├─ Alpha = (CurFrame − Samples[i].Frame) / (Samples[i+1].Frame − Samples[i].Frame)
 │   │   ├─ Pos = Lerp( (Samples[i].X,   Samples[i].Y,   0),
 │   │   │             (Samples[i+1].X, Samples[i+1].Y, 0), Alpha )
 │   │   ├─ Rot = Lerp( Rotator(0, Samples[i].Yaw,   0),
 │   │   │             Rotator(0, Samples[i+1].Yaw, 0), Alpha )
 │   │   └─ Npc.SetActorLocationAndRotation(Pos, Rot, bSweep = false)
 └─ （接 5.6）
```

要点：

- `bSweep = false`：人群密集时开扫掠会互相推挤，反而偏离真实轨迹
- 朝向用 **`Lerp (Rotator)`** 节点，引擎内部处理 179° → −179° 的最短路径；
  别对裸 float 做 Lerp，会转 358°
- `Z` 固定 0，pivot 在脚底，NPC 才会踩在地面上

### 5.6 Event Tick 末尾：把 T 推给 UI

```
 ├─ Js = "onVideoTime(" + FString::SanitizeFloat(T) + ")"
 └─ WB_Hud → Execute Javascript (Js)
```

拼出来形如 `onVideoTime(10.5)`。页面收到第一次调用就切到 UE 模式，
左下变全透明，之后完全跟着这个 `T` 走。

---

## 6. 第 5 步：把 HUD 铺满屏幕

1. 新建 **Widget Blueprint** `WBP_Hud`
2. 拖一个 **Web Browser** 控件进 Canvas Panel，命名 `WB_Hud`，勾 **Is Variable**
3. Anchors 选**四边拉伸**（左上角图标），Offsets 全填 0 → 控件铺满全屏
4. **勾 `Supports Transparency`**（有的版本叫 `Enable Transparency`）
   —— 不勾，左下就是一块黑，看不见 3D 场景
5. `Initial URL` 填成品页路径（**clone 后就是这个路径，文件不用挪**）：

```
file:///D:/canteen_twin/demo/entrance_a/dashboard_live.html
```

> 三个斜杠；路径用 `/` 不要用 `\`；**目录名别带中文和空格**，CEF 容易解析失败。
> 换 B 素材就把 `entrance_a` 改成 `entrance_b`，同时把 `Content/Data/` 的 json 也换成 B。

6. 在 `BP_Manager` 的 BeginPlay 里（或关卡蓝图）：

```
Create Widget (Class = WBP_Hud) → Add to Viewport (ZOrder = 10)
 → 存到 HudRef → 把 HudRef.WB_Hud 赋给 BP_Manager 的 WB_Hud 变量
```

7. 视口里确认：顶部横条 + 右侧竖栏是 UI，左下能看见你的 3D 门廊。

---

## 7. 第 6 步：本地测试验收清单

按顺序做，每一步都有明确的"对/不对"：

| # | 操作 | 期望结果 | 不对时查 |
|---|---|---|---|
| 1 | 双击 `demo/entrance_a/dashboard_live.html` | 右侧出视频、顶部数字随时间变 | mp4 与 html 分开 / 用了 `annotated.mp4` |
| 2 | UE 里 Play，看 Output Log | `NPC 数 = 58`（A）/ `34`（B） | `Content/Data/` 路径、Decode Json 返回值 |
| 3 | 看小人出现的位置 | 在门外 `X < 0` 一侧，不在店里 | 场景 X 轴反了 → 见 `modeling_spec.md` §1.1 |
| 4 | 看小人进门方向 | 朝 **+X** 走（进店），出店朝 −X | 还按旧图纸建的 → 整体绕门洞中点转 180° |
| 5 | 看脚底 | 贴着地面，不悬空不陷地 | NPC pivot 要在脚底；地面 Z=0 |
| 6 | 看门洞处 | 人从门洞穿过，不撞墙 | 门洞 `Y` 范围取配置 `counters.p1/p2` |
| 7 | 看左下 | 透明，能看见 3D 场景 | 没勾 `Supports Transparency` |
| 8 | 视频播到约 10 s | 面板数字变化，且与视频里过门的人对得上 | 推的不是 `MediaPlayer.GetTime()` |
| 9 | 等视频循环回 0 | NPC 和面板一起回到开头 | 全都由 `T` 推导，天然支持 |
| 10 | 对照最终统计 | 播完累计 **58 人 / 74 进 / 37 出**（A） | 页面内嵌的是旧数据 → 重新 `build_ui.py` |

> 第 3～5 条就是我远程没法替你验、需要你截图告诉我的部分。

---

## 8. 常见坑速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 右侧视频黑屏 / 提示编码不支持 | 用了 `annotated.mp4`（mp4v）或视频与 html 分开了 | 用 `annotated_web.mp4`，且与 html 同目录 |
| 左下整块黑 | Web Browser 没开透明 | 勾 `Supports Transparency` |
| 页面白屏 | URL 路径带中文 / 空格 / 反斜杠 | 纯英文路径、三个斜杠、用 `/` |
| 页面一直 0.0 s | `Execute Javascript` 没调 / 控件没勾 Is Variable | 核对变量名和拼出的字符串 |
| 数字不动但小人在动 | 推的是 Tick 累计时间 | 统一用 `MP_Clock.GetTime()` |
| 小人和视频差半秒 | `MetaFps` 填成 20 了 | 从 `meta.fps` 读：A=29.97，B=29.0 |
| 小人全挤在原点 | json 没解析出来，Samples 为空 | 看第 2 条日志 |
| 小人抖动 | 没插值，直接取整帧位置 | 按 5.5 做 Alpha / Lerp |
| 小人朝反方向走 | 场景还按旧坐标（进店 = −X）建 | 门洞墙 X=0、左柱 Y=0、室内朝 +X |

---

## 9. 真卡住了，发我这 3 样就够了

1. 门洞墙 / 左柱 / 地面的 `Location` 三个数字
2. Top 顶视图 + Perspective 透视图两张截图
3. Output Log 里 `NPC 数 = ...` 那一行，加上卡在哪一步（第 7 节表里的编号）

不用打包工程、不用发视频、不用发 .uasset。

---

相关文档：
- [`demo/README.md`](../demo/README.md) — **clone 到哪 / 文件放哪 / URL 怎么填**
- [`modeling_spec.md`](modeling_spec.md) — 建模尺寸与轴向（含旧图迁移）
- [`ue5_integration.md`](ue5_integration.md) — 数据格式、同步策略、UI 契约
- [`realtime_data_contract.md`](realtime_data_contract.md) — `realtime.json` 字段表
