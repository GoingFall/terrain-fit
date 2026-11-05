# 05 · 程序化生成「震撼地形」：规律拆解与实现路线（1.20.1）

> 目标：不还原某张地图，而是把「让人震撼的地形」背后的规律编码进生成器——
> 先做数据包，必要时再写自定义 `DensityFunction` / `ChunkGenerator`。

## 一、震撼感的来源：6 条可编码的规律

| # | 规律 | 为什么震撼 | 生成器里的对应物 |
|---|---|---|---|
| 1 | **尺度层级（分形）** | 大山有小的皱褶，小的皱褶还有更小的；单一频率的噪声看起来像"馒头" | 多倍频噪声（octave 4–6）+ 不同波长叠加 |
| 2 | **山脊线（ridged）** | 刀刃状山脊 + 雪线，是"雪山感"的核心 | `1 - abs(noise)` 的 ridged multifractal，再 `pow` 调制 |
| 3 | **侵蚀与谷地** | 好看的谷地是 V 型/河漫滩，有"被水切过"的方向感 | 低频"河谷场"对高度做 `min()`/smooth-min 切割（不是简单减高度） |
| 4 | **构图（盆地 + 环山 + 水面 + 开口）** | 人眼喜欢"被环抱又在某处透出远景"；地图作者几乎都这么摆 | 用低频控制场：盆地中心 → 碗状下陷，边缘 → 环形山脊，留一条低鞍部当"视线走廊" |
| 5 | **垂直比例（坡度）** | 落差/水平距离决定"压迫感"；默认 384 格高把山压扁了 | 放大垂直尺度（Big Globe 思路）或抬升山脊振幅 |
| 6 | **材质分区（雪线/林线/草甸/裸岩）** | 同样的高度，雪线以上和以下是两种气质 | `surface_rule` + 高度梯度 + 湿度/坡度近似 |

> 第 4 条是最容易被忽略、也最决定"是否震撼"的一条：**先有构图，再堆细节**。
> 手绘地图好看，往往不是因为噪声多复杂，而是因为作者摆了一个"盆地 + 环山 + 一汪水 + 一个豁口"。

## 二、Minecraft 1.20.1 的原语

| 原语 | 位置 | 用途 |
|---|---|---|
| `noise_settings`（noise router） | `data/<ns>/worldgen/noise_settings/*.json` | 整套地形密度函数树，**纯数据包即可改** |
| `density_function` 节点 | 同上 | `noise` / `shifted_noise` / `spline` / `add` / `mul` / `min` / `max` / `clamp` / `range_choice` / `interpolate` / `cache_2d` / `y_clamped_gradient` |
| `spline` | 同上 | 把"高度→密度"做成非线性曲线：台地、断崖、海岸线全靠它 |
| `surface_rule` | 同上 | 表层方块：雪线、草甸、沙、裸岩 |
| `multi_noise` biome source | 同上 | 用气候参数（温度/湿度/侵蚀/大陆性）分配群系 |
| 自定义 `DensityFunction` | Java | 真正的 domain warp、河流网络、盆地控制场 |
| 自定义 `ChunkGenerator` | Java | 生成后的全局后处理（真正的 carve / 结构适配） |
| `structure_set` / jigsaw | 数据包 | 让建筑自然生成 |

**关键判断**：先只用 `noise_settings`（数据包）能做出 ridged + spline + min/max 切割，
已经能到"很像"；真正欠缺的是 **domain warp（域扭曲）** 和 **全局盆地图层**，这两个建议上 Java。

## 三、三阶段路线

### 阶段 1：数据包（零 Java，1–2 天出效果）
1. 复制一份 vanilla `noise_settings/overworld.json` 作底
2. 把 `final_density` 换成自建的 ridged 树：
   ```
   final_density = clamp( add( base, mul( ridge, amplitude ) ), -1, 1 )
   ridge = spline( 1 - abs( noise(ridge_noise) ) )   ← spline 做非线性陡化
   ```
3. 用 `min(final_density, valley_field)` 切出河谷
4. `multi_noise` 里把"侵蚀/大陆性"参数调出「盆地 vs 山脊」分布
5. 用 `surface_rule` 按 `y_clamped_gradient` 铺雪线/草甸

### 阶段 2：自定义 `DensityFunction`（Java，1 周级）
解决阶段 1 的两个硬伤：
- **Domain warp**：`warp(p) = p + A * noise(p * f)`，让所有形状"手捏感"消失（这是"自然"的最大来源）
- **盆地控制场**：用 Poisson-disk 撒盆地中心，`height = bowl(dist) + rim(dist)`，把构图规律直接编码

注册入口（Forge 1.20.1）：
```java
DeferredRegister<Codec<? extends DensityFunction>> DF =
    DeferredRegister.create(Registries.DENSITY_FUNCTION_TYPE, MODID);
```
> 具体注册表名以 1.20.1 官方映射为准；`DensityFunction` 需要实现 `Codec` 才能进 JSON。

### 阶段 3：自定义 `ChunkGenerator`（可选）
只有需要"生成后再全局处理"时才做：真正的河流 carve、湖面整平、结构朝向适配。
代价：性能与兼容性（会被大多数结构/群系模组假定为 vanilla 生成器）。

## 四、伪代码：一套「震撼山谷」的组合

```
// 1) 基底：低频大陆性
base = noise(CONTINENTAL, freq=1/1200) * 0.35

// 2) 山脊：ridged multifractal（4 个倍频）
ridge = 0
for i in 0..3:
    ridge += (1 - abs(noise(RIDGE, freq=1/600 * 2^i))) * 0.5^i
ridge = pow(normalize(ridge), 1.8)      // 陡化：制造刀刃状

// 3) 盆地构图：中心低、边缘高的"碗"
basin = smoothstep(dist_to_nearest_basin_center / R)   // 0=中心, 1=边缘
mask  = smoothstep(basin / 0.35)
height = base + ridge * amplitude * mask

// 4) 河谷切割：低频河谷场做 smooth-min
valley = noise(VALLEY, freq=1/300)
height = smooth_min(height, valley_level, k=8)

// 5) 视线走廊：在盆地某个方位角开一个低鞍部
if angle_from_corridor < 15°: height -= ramp(angle) * 30
```
第 5 步就是"从观景点看出去有远景"的秘密——**它不是一个模组该做的事，而是构图参数**。

## 五、性能与调试

| 事项 | 建议 |
|---|---|
| 噪声求值 | 每 chunk 每 4×8×4 个 cell 求一次 DF；重噪声必须 `cache_2d` / `interpolate`，否则 TPS 崩 |
| 倍频数 | 4–6 足够；超过 8 只增加成本不增加观感 |
| 种子筛选 | [jacobsjo Datapack Map](https://map.jacobsjo.eu/) 预览构图；Chunky 预生成 |
| 构图验证 | 固定种子 + 固定机位截图，和参考帧对比；改一个参数出一张图，做成对照表 |
| 远景 | Distant Horizons 看"几十公里"的层次是否成立（这是构图对不对的最快反馈） |

## 六、起步文件树

```
data/<ns>/worldgen/
  noise_settings/ridge_valley.json      ← 主体
  density_function/                      ← 可复用节点（ridge / valley / basin）
  biome/multi_noise.json
  dimension_type/overworld_like.json
  worldgen/structure_set/*.json          ← 建筑自然生成
```
先拿 `Tectonic` 与 `Terralith` 的 `noise_settings` 当教材——它们是"ridged + spline"最好的现成范例。

## 七、不开游戏也能看地形：预览器

`tools/terrain_preview.py` —— 参数进，**画面**出（不是高度图），顺便给可量化的构图指标。

```bash
# 单张
python tools/terrain_preview.py --preset valley --seed 7 --out preview/v.png
# 覆盖参数
python tools/terrain_preview.py --preset valley --seed 7 \
  --set basin_radius=0.45 ridge_amp=190 ridge_sharp=2.0 corridor_drop=40
# 和目标帧并排对比
python tools/terrain_preview.py --preset valley --ref input/scene-01-valley-desk.png --out preview/cmp.png
```

### 关键参数（改这几个就够）

| 参数 | 作用 | 观感影响 |
|---|---|---|
| `basin_radius` | 盆地半径（占地图比例） | 小 = 峡谷幽闭；大 = 开阔 |
| `basin_centers` | 盆地中心个数 | 多个 = 复杂山群 |
| `ridge_amp` | 山脊高度 | 决定压迫感 |
| `ridge_sharp` | 山脊陡化指数 | >1.8 出刀刃状 |
| `ridge_octaves` | 山脊倍频 | 4–6，多了只变碎 |
| `valley_level` / `valley_amp` | 河床高度与摆动 | 决定谷底宽窄 |
| `carve_strength` | 河切割强度 | 太低没谷，太高出断壁 |
| `warp_amp` | 域扭曲强度 | **最影响"自然感"**，0 = 一眼假 |
| `corridor_deg` / `corridor_drop` | 视线走廊宽/深 | 决定有没有"远景" |
| `sea_level` | 水面高度 | 湖面大小 |
| `yaw_deg` / `pitch_deg` / `eye_height` | 机位 | 构图视角 |

### 输出指标（用来"看图说话"）

```
composition: sky=29.5%  land=33.8%  water=36.7%  horizon=37.8%
95p visible distance=584 blocks   eye=(860, 110, 685)
relief y=43..297 (span 254)
```

- `sky%` / `land%` / `water%`：画面三块的比例——目标帧通常是 sky 35–45%、water 10–25%
- `horizon%`：地平线在画面中的高度——超过 60% 说明相机太低或对面太高（会被"墙"挡住）
- `95p visible distance`：95% 的像素能看到多远——< 300 基本是"贴墙"，> 1500 才有"辽阔"
- `relief span`：起伏落差——< 150 缺压迫感，> 280 容易出不合理断崖

### 已知局限

- 噪声是**参数兼容的替身**，不是 Minecraft 逐位一致；它只用来判断构图与比例
- 不模拟方块材质、生物群系（雪线只是高度近似）
- 强切割时会出现"纸片状"断壁（`s44` 那种），属 carve 参数过冲，调 `carve_strength`/`valley_amp`

### 性能（2026-11-03 优化后）

存档提取原先是纯 Python 逐方块循环（4096 × 24 段 × 1024 区块 ≈ 1 亿次迭代），一个 region 要 **112 秒**。
改 numpy 位解包 + 沿 y 轴 `max` 后：**2.0 秒 / region**（约 56×，132k 列/秒），且与逐方块实现对拍**逐位一致**。
再加一层 `ProcessPoolExecutor` 按 region 并行：整张图 36 个 region 串行 32.1s → **5.5s**（8 进程，1.71M 列/秒）。
生成一个全图可交互查看器（3072×3072 纹理、3.3 MB 单文件 HTML）现在 **8.7 秒**。

同时修正一处统计错误：旧代码把"缺失层"填成该层均值，导致水/树覆盖率虚高（曾报 2.7% / 15.5%），
真实值是 **0.5% / 0.7%**——这张地形图本身树就很稀。

参考实现（查过 PyPI）：`amulet-core` 1.9.51（2026-10 更新，完整的世界格式支持，重）、
`amulet-nbt` 2.1.8（Cython NBT，可作替换）、`nbtlib` 2.0.4（2021，已停更）、
`anvil-parser` 0.9.0（2021，不支持 1.18+）。只读提取场景下自写 numpy 路径更划算。

## 八、校准：真实地图 vs 程序生成（同一把尺子）

`tools/world_preview.py` 能把**任意存档**渲染成同构图、同光照、同指标的画面，
于是「手绘地图」和「程序生成」可以直接对表。

实测（拉斐丽 r.0.0 深谷 vs `valley` preset seed 7，坡度为相邻块高度差的梯度模长）：

| 指标 | 真实地图 | 程序生成 | 含义 |
|---|---|---|---|
| 起伏跨度 | 234 | 254 | 尺度相当 ✅ |
| 坡度 p50 | **0.71** | 0.36 | 真实地形**整体更陡** |
| 坡度 p90 | **1.50** | 2.49 | 程序生成中频起伏更多 |
| 坡度 p99 | **2.50** | 11.05 | 程序生成有**尖刺** |
| 最大坡度 | **9.0** | 22.9 | 同上 |
| 坡度>2 占比 | **2.3%** | 12.0% | 差 5 倍 |
| 坡度>4 占比 | **0.1%** | 5.9% | 差 59 倍 |

**结论（反直觉但重要）**：手绘地图是**平滑而连续**的雕塑面——中位坡度不低，但几乎没有局部尖刺；
程序生成则是**又平又尖**——平均更缓，却散布着 20 度以上的陡坎。要拟合，方向是：

1. 砍高频：`ridge_octaves` 5 → 3~4，或给高频项降权，消除尖刺
2. 抬中频：把权重从高频移到 2–3 倍频，`ridge_amp` 不动
3. 加一道**坡度限制/平滑**后处理（限斜率 + 轻微 blur）——这是手绘地形最大的"手感"来源

## 九、拟合尝试（2026-11-03）与一个教训

给生成器加了 6 个旋钮：`ridge_persistence`（高频权重）、`mid_amp/mid_freq`（中频带）、
`blur_passes`（平滑）、`slope_limit/slope_iters`（坡度扩散限幅）、`carve_width`（河谷过渡宽度）、`rim_start`（山脊环起点）。

用 `tools/fit_metrics.py` 按「与真实地图的坡度分布误差」打分（对数比误差，越低越好）：

| 版本 | score | p50 | p90 | p99 | gt2 |
|---|---|---|---|---|---|
| 初始 | 9.64 | 0.36 | 2.49 | 11.05 | 12.0% |
| 拟合后 | **3.76** | 0.62 | 1.80 | 3.39 | 7.8% |
| 目标（真实图） | — | 0.71 | 1.50 | 2.50 | 2.3% |

**但渲染出来一眼就不对**：数值接近了，画面却变得**又软又空**——真实地图是密集小脊线 + 树冠纹理，
拟合结果成了几个大而平滑的包，水面还占了 48%。

**教训：单尺度坡度分布不足以描述"地形长相"。** 真实地图的特征是「**中等坡度 + 高特征密度**」，
而我的模糊/限幅把高频削掉后，坡度分布确实向目标靠拢，但特征密度崩了——两者被同一个旋钮反向拉扯。

**下一步应该用多尺度指标**：分别对 blur r=1 / r=4 / r=16 后的高度场求梯度分布，
再补一个「脊线密度」（单位面积内局部极大值个数）。这样才能同时约束"坡有多陡"和"褶有多密"。

## 十、结论

- **规律是存在的、可编码的**：分形层级、山脊线、侵蚀谷地、盆地构图、垂直比例、材质分区。
- **性价比最高的路径**：数据包改 `noise_settings`（阶段 1）→ 加 domain warp 与盆地控制场（阶段 2）→ 需要时再上自定义 ChunkGenerator（阶段 3）。
- **决定成败的不是噪声函数，是构图参数**：盆地半径、环山振幅、水面高度、视线走廊角度——这四个数决定"震撼"。
