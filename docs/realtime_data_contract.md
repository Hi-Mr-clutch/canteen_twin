# 实时数据契约（给 UI 协作者）

> 本文档是**视频分析管线与 UI 侧的接口约定**。UI 页面由协作者实现，
> 本仓库不提供、也不绑定任何实时页面实现。协作者只需要读 `realtime.json` 一个文件。

---

## 0. 边界（先看这个）

| 谁 | 负责 | 不负责 |
|---|---|---|
| 本仓库（视频分析管线） | 检测人、跟踪、透视换算、统计、**导出数据** | 任何 UI / 页面 / 样式 |
| UI 协作者 | 读 `realtime.json`，做面板、图表、动画、交互 | 不改管线、不自己重算人数 |
| UE5 | 播视频、生成 NPC、**把视频时间喂给 UI** | 统计算法 |

---

## 1. 「实时」的准确含义

视频是提前录好的，所以这里的实时 = **回放时间轴驱动**：
视频播到 T 秒，UI 就显示「截至 T 秒」的累计统计。不是摄像头在线推理。

**单一时钟原则**：UE5 同一个 Tick 读一次 `MediaPlayer.GetTime()` 得到 `T`，
一路算 NPC 的 `CurFrame`，一路交给 UI 定位帧号。所以「有人进门 → UE5 里出现
这个 NPC → 面板数字 +1」必然是同一帧发生，不需要任何对时或消息同步。

---

## 2. 你要读哪些文件

| 文件 | 用途 | 必需 |
|---|---|---|
| `realtime.json` | **UI 唯一数据源**：逐帧快照 + 事件流 + 区域几何 | ✅ |
| `examples/realtime_sample.json` | 没有真实视频时的联调样例 | 建议 |
| `npc_tracks.json` | 只在「点 UI 高亮某个 UE NPC」时用来查 UE 坐标 | 可选 |
| `analytics.json` | 最终汇总（写报告用），UI 不用 | ❌ |
| `tracks.json` / `tracks.csv` | 原始逐帧数据 | ❌ |
| `dashboard.html` | 管线自带的**离线占位看板**，正式 UI 可直接替换 / 忽略 | ❌ |

---

## 3. `realtime.json` 顶层结构

```json
{
  "schema": "canteen-twin/realtime@1.0",
  "generated_at": "2026-11-19T08:00:00",
  "meta": { "...": "..." },
  "ground_m": [4.47, 2.13],
  "zone_names": ["porch"],
  "zones": [],
  "counters": [],
  "frames": [],
  "events": []
}
```

### 3.1 `meta`

| 字段 | 类型 | 说明 |
|---|---|---|
| `fps` | float | **处理后帧率**，定位帧号必须用它，不是源视频 fps |
| `frame_count` | int | 总帧数 N，等于 `frames` 数组长度 |
| `duration_sec` | float | N / fps |
| `time_offset_sec` | float | 视频起始偏移（`video.start_sec`），见第 4 节 |
| `source_video` / `detector` | string | 溯源信息，可放页脚 |
| `frame_width` / `frame_height` | int | 原始画面尺寸 |
| `length_unit` | string | 固定 `"m"`，地面坐标单位是米 |

### 3.2 `frames[f]`（核心，UI 只渲染这一帧）

| 字段 | 类型 | 说明 |
|---|---|---|
| `f` | int | 帧号，**等于数组下标** |
| `t` | float | 该帧对应时间（秒，从处理后起点算） |
| `count` | int | **当前画面内人数**（瞬时值，会上下波动） |
| `in` | int | **截至此刻累计进店人次**（只增不减）。管线侧已对穿线做防抖，脚点在门线附近抖动不会重复计数 |
| `out` | int | 截至此刻累计出店人次（同上，已防抖） |
| `people` | int | 截至此刻累计出现的独立人数 |
| `peak` | int | 截至此刻峰值同框 |
| `net` | int | `in - out`，净流入，可能为负 |
| `zones` | object | `{区域名: 该区域当前人数}`，key 见 `zone_names` |
| `actors` | array | 当前帧在场的人 `[{id, x_m, y_m}]`，画俯视点位图用 |
| `events` | array | **本帧新发生的事件**（子集，做动画用），结构同 3.4 |

> ⚠️ **所有 `in / out / people / peak` 都是「截至该帧」的累计快照。**
> UI 直接显示 `frames[f]` 里的值即可，**不要在前端自己累加** ——
> 否则拖动进度条、视频循环播放时数字会错乱。

### 3.3 `ground_m` / `zones` / `counters`

- `ground_m = [宽, 高]`：地面米制平面尺寸（本门廊 4.47m × 2.13m）
- `zones[i].polygon_m`：区域多边形（地面米制坐标），画俯视底图时用
- `counters[i]`：`{name, p1, p2, inward_sign}`，门洞计数线，可在底图标出

坐标约定：地面平面 `x` 向右、`y` 向门（远离相机）；`y = 0` 是柱脚近边，
`y = 2.13` 是门洞。UE5 世界坐标换算见 `docs/ue5_integration.md`。

### 3.4 `events`（事件流）

| 字段 | 说明 |
|---|---|
| `f` | 发生帧号 |
| `t` | 发生时间（秒） |
| `type` | `"new"` 新目标出现 / `"in"` 进店 / `"out"` 出店 |
| `id` | 人的稳定 ID，与 `npc_tracks.json` 的 `npcs[].id` 一致 |
| `counter` | 触发的计数线名（一般是 `door`）；`new` 时为空字符串 |

顶层 `events` 是全局按时间正序的列表；`frames[f].events` 是它在该帧的子集。
做「数字跳动 / 事件流追加」时，判断 `frames[f].events` 是否非空即可。

---

## 4. 由视频时间定位帧（唯一公式）

```js
const f = Math.max(0, Math.min(meta.frame_count - 1,
              Math.floor((T - meta.time_offset_sec) * meta.fps)));
const snap = frames[f];
```

- `T` = UE5 `MediaPlayer.GetTime()` 返回的秒数（视频播放时间原值）
- 视频循环播放时 `T` 归零，`f` 自动回到 0，面板和 NPC 一起重置
- **不要**用 `requestAnimationFrame` 自己累计秒数，那会和视频逐渐漂移

---

## 5. UI 侧最小实现（框架无关）

```js
let lastF = -1;
function onVideoTime(T) {
  const f = clamp(Math.floor((T - meta.time_offset_sec) * meta.fps),
                 0, meta.frame_count - 1);
  if (f === lastF) return;                  // 同一帧不重复重绘
  lastF = f;
  const s = frames[f];
  renderKPI(s);                              // count / in / out / people / peak / net
  renderCurve(frames.slice(0, f + 1));         // 曲线只画到 f，后面留灰
  renderPlan(s.actors, zones);                 // 俯视点位
  renderZones(s.zones);
  if (s.events.length) flashAndAppend(s.events);  // 有人进门就跳一下 / 追加一条
}
```

`onVideoTime(T)` 由 UE5 每 Tick 调用（见第 7 节）；本地联调时可用定时器模拟 `T`。
框架随意（原生 JS / Vue / React / UMG Web Browser 均可），数据格式不变。

---

## 6. 与 `npc_tracks.json` 对齐

| | `realtime.json` | `npc_tracks.json` |
|---|---|---|
| 帧号 | `frames[f].f` | `npcs[].samples[].f` |
| 人的 ID | `actors[].id` / `events[].id` | `npcs[].id` |
| 坐标 | 地面米制 `x_m, y_m` | UE 世界 cm `x, y, z` |
| 朝向 | 无 | `yaw`（度） |

同一个 `id` + 同一个 `f`，UI 上的人和 UE5 里的 NPC 就是同一个对象。
做「点击 UI 里的某个人 → 高亮 UE 里对应 NPC」用 `id` 关联即可。

---

## 7. UE5 侧要配合的一件事

UI 自己不知道视频播到哪，需要 UE5 把时间推进来。蓝图只需一个节点串：

```
Event Tick
 ├─ T = MediaPlayer.GetTime()
 └─ WebBrowser → Execute Javascript("onVideoTime(" + T + ")")
```

`onVideoTime` 是 UI 页面暴露的全局函数名，名称由 UI 协作者定，约定好即可。
若 UI 不在 UE5 内嵌而用独立网页，改成 WebSocket / HTTP 轮询推 `T`，
数据格式完全不变。详见 `docs/ue5_integration.md` 第 5 节。

---

## 8. 体积与性能

- `frames` 是逐帧对象数组；20fps / 5 分钟约 6000 帧，文件约 1~3 MB
- 一次性加载常驻内存，按 `f` 做 O(1) 索引即可，不需要流式
- 太大时 UI 侧可只取 `count/in/out/people/peak` 几列；事件流是稀疏的，
  做动画优先用 `frames[f].events` 而不是遍历顶层 `events`
- 同一个 Tick 里 `f` 没变就跳过重绘，60fps 的 Tick 不会带来 60 次重绘

---

## 9. 常见坑

| 坑 | 后果 | 正确做法 |
|---|---|---|
| 前端自己累加 `in/out` | 拖进度条 / 循环后数字错乱 | 直接显示 `frames[f]` 的累计快照 |
| 用了源视频 fps | 帧号偏一倍 | 用 `meta.fps`（处理后帧率） |
| 忽略 `time_offset_sec` | 整体快 / 慢几秒 | 按第 4 节公式减掉 |
| 用 Tick 累计时间 | 和视频逐渐漂移 | 一律用 `MediaPlayer.GetTime()` |
| 在蓝图里重算人数 | 口径和报告不一致 | 人数只认 `realtime.json` |
| 改管线代码适配页面 | 双人协作冲突 | 只改 UI 侧；字段不够就在本契约提需求 |

---

## 10. 协作约定

- 需要新增字段时，在本文件登记并升级 `schema` 版本号（如 `@1.1`）
- `examples/realtime_sample.json` 是**示例轨迹**生成的联调样例，不是真实视频结果，
  `meta.source_video` 里有明确标注
- 正式数据：`python3 -m src.run_pipeline --config configs/entrance_measured.json`
  → `out/entrance/realtime.json`（`out/` 不进仓库）
- `dashboard.html` 只是管线自带的离线占位看板，与实时 UI 无关，可随时替换
