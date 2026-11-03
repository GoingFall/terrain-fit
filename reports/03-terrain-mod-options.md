# 03 · 想要「图里那种山谷」：地形生成模组选型与兼容性

## 先说清楚：图里的地形不是生成器产物

那张《静谧山谷·拉斐丽》是**手搓地形图**（地图站分类「地形」），存档里只有 `region/*.mca`，
没有任何 worldgen 配置。所以：

- **没有任何地形模组能 1:1 生成那一帧**——那是作者用 WorldPainter / WorldMachine 这类工具
  雕出来、再导入存档的地形。
- 能做的只有两件事：**(a)** 用生成器得到「大落差 + 河谷 + 雪线」的近似感；**(b)** 真的去雕地形。

## 能接近的生成器（1.20.1 都有 Forge 构建，已实测）

| 模组 | 1.20.1 Forge 最新构建 | 作用 | 体量 |
|---|---|---|---|
| **Tectonic** | `3.0.17`（2025-11-08） | 抬升地形起伏：巨型山脉、深谷、断崖、地下河——**最接近图里那种落差** | 1,805 万下载 |
| **Terralith** | `2.5.4`（2024-07-07） | 近 100 个写实/轻幻想群系，纯原版方块，山谷与雪原观感好 | 2,540 万下载 |
| **Continents** | `1.1.14` | 大陆/海洋宏观布局，解决「到处是陆地」 | 140 万下载 |
| **Biomes O' Plenty** | `19.0.0.96` | 50+ 群系，含雪山/温泉/红木林 | 3,987 万下载 |
| **Regions Unexplored** | `F-0.5.6+1.20.1` | 群系扩充，风格偏写实 | — |
| **Oh The Biomes We've Gone** | 1.20.1 支持 | 群系扩充（BWG 团队） | — |
| **William Wythers' Overworld** | 1.20.1 支持 | 写实向群系/地形微调 | — |
| **Geophilic** | 1.20.1 支持 | 轻量原版增强，最保守 | — |
| **Distant Horizons** | `3.3.3-1.20.1`（2026-09-29） | **不是生成器**，但决定「能不能看见几十公里外的雪山」 | 3,913 万下载 |

> 不推荐：**No Man's Land** 没有 1.20.1 构建（仅 NeoForge 新版）。

## 兼容性（这是重点，都是官方正文里写明的）

### Tectonic
- 与 **Terralith**：mod 版 Tectonic **内置 Terralith 兼容版**；如果两边都用 datapack 版，
  必须用 [Terratonic](https://modrinth.com/datapack/terratonic) **替代** Tectonic。
- 与 **BOP / Regions Unexplored / Nature's Spirit / BWG**：兼容（只要对方走 Terrablender/Biolith）。
- 与 **Clifftree**：**1.20 上不兼容**（1.21 才修）。
- ⚠️ 官方明说目前只维护 **1.21.1 与 26.1**，1.20.1 能跑但**不再修 bug**。

### Terralith
- 与 **群系类 datapack** 通常**不兼容**；要用 **mod 版**（走 Terrablender）。
- **2.6.0 起 mod 版与 datapack 版内容不同**，不要在两者间来回换，会伤存档。
- 与 **Tectonic mod 版**：完全兼容。

### Continents
- 与多数 worldgen datapack 兼容，**包括 Terralith**。
- 但 **Large Biomes 与 Terralith 不能同开**。

### 群系模组叠加（BOP + RU + BWG 同开）
能装，但都通过 Terrablender 抢生物群系分布，会出现「同一片区域被几套群系争夺」，
结构生成位置也会跟着偏。**建议只选一套**，或按 Terrablender 的区域权重手工调。

### Distant Horizons × 光影（这条最容易踩）
- DH 正文：**DH 2.1.0+ 只支持 Iris 1.7+，且光影必须内置 DH 支持**；Optifine 只是部分可用。
- **Bliss 的正文只写了 Iris / Optifine，没有声明 DH 支持**——所以「Bliss + DH」远景会露馅
  （远处 LOD 没有大气透视/雾，和近处断层）。要两者兼得，换**声明支持 DH 的光影**
  （Complementary 系、BSL 等）。
- DH 会额外占磁盘（LOD 库常见几个 GB），首次探索时 CPU 也吃紧。

### 通用注意
- **worldgen 只影响新生成的区块**：老存档加进去会出现明显「地形断层」。要么开新世界，
  要么用 **Chunky** 预生成。
- 结构模组（YUNG's 系列、Towns & Towers 等）依赖生物群系标签，Terralith/BOP 下**部分结构不生成**。
- 你的实例是 **Forge 1.20.1 + Oculus**：上表 Forge 构建都能直接用；DH 也有 1.20.1 Forge 版。

## 推荐组合（按目的）

| 目的 | 组合 |
|---|---|
| **最像图里**（大落差 + 远景） | Tectonic `3.0.17` + Terralith `2.5.4`（mod 版）+ Continents + DH `3.3.3` + 支持 DH 的光影 |
| **稳一点、少折腾** | Terralith `2.5.4` 单独 + Geophilic |
| **只要宏观好看** | Continents + BOP |
| **真要 1:1 复刻** | WorldPainter / WorldMachine 雕地形 → 导入存档；局部用 Axiom 修 |

## 维护状态：有没有「非官方维护版」

查了 Modrinth（`tectonic` 34 个结果）和 GitHub（官方仓库 forks + releases）：

| 结论 | 说明 |
|---|---|
| **没有现成的 1.20.1 非官方维护版** | Modrinth 上没有「Tectonic 1.20.1 backport / unofficial」这类项目 |
| 官方 1.20.1 构建仍在发 | `3.0.17`（2025-11-08），能下载能跑，只是官方声明**不再修 bug** |
| 源码是 **MIT** | `github.com/Apollounknowndev/tectonic`，10+ 个活跃 fork（`tectonic-bigcontinents`、`tectonic_latitude`、海洋神殿修复等），理论上可自行回移 |
| 同名异物（搜的时候别拿错） | `tekton` = 2015 年的**资源包**，不是地形模组；`GeoTectonic`（Alkeari）= 独立**洞穴重做**项目，不是 Tectonic 分支 |
| Terralith 不可随意分支 | 自定义 Stardust Labs License，官方明确限制再分发，别指望非官方回移 |

**实用建议**：1.20.1 就用官方 `3.0.17` 锁死版本 + Chunky 预生成；要「仍在维护」的地形，用 Terralith
`2.5.4` 或升 1.21.1。若问的是 **Bliss + Distant Horizons**，那不是维护问题——是 Bliss 没实现 DH
渲染管线，没有非官方补丁，换声明支持 DH 的光影更实际。

## 附：Distant Horizons vs Voxy（LOD 层）

| 项 | Distant Horizons | Voxy |
|---|---|---|
| 版本 | 1.16.5–1.21.11，Fabric/Forge/NeoForge | **Fabric only**；构建见于 **1.20.4** 与 **1.21.6+**（**无 1.20.1**） |
| 硬件门槛 | 较低 | **OpenGL 4.6**（GTX 10 系 / RX 5000+ 起） |
| LoD 生成 | CPU 为主，自动生成 + 内置预生成器 | GPU 驱动，开销低，但只转换**已探索**区块，需 Chunky 预生成或 `/voxy import world` |
| 光影 | Iris 1.7+ + 声明支持 DH 的光影（Complementary、BSL 等，生态广） | 0.2.4 起支持，但**光影必须显式实现 Voxy 支持**（目前实现很少，社区常提 Photon 系分支） |
| 多人 | 有服务端流送（DH Server） | 纯客户端缓存 |
| 成熟度 | beta 但多年迭代 | alpha，迭代快 |
| 再分发 | — | 作者**明文禁止非官方移植/回移** |

**结论**：论纯性能 Voxy 一般更快（GPU 端、开销低、远景更干净），但代价是版本/加载器/光影/多人四条硬约束。
**对 1.20.1 Forge 实例：Voxy 装不上，DH `3.3.3-1.20.1` 是唯一选项。** 两者的 LOD 数据互不通用，切换要各自删库重建。

## 附：麦浪平原（金色的山丘）怎么复现

一帧「满山金色麦浪 + 远山 + 风车」其实是四层叠加，**没有单一模组能全给**：

| 层 | 做法 | 候选 |
|---|---|---|
| 地形起伏 + 远山 | 地形生成器 | Tectonic `3.0.17` / Terralith `2.5.4` / Continents |
| 麦田覆盖 | **麦田生物群系模组** | **Wild Wheat**（`wild-wheat`，1.20.1 Forge/NeoForge）——官方画廊就是齐胸金色麦浪铺满山丘，与本帧高度一致 |
| 麦田覆盖（替代） | **资源包**把 `tall_grass`/`short_grass` 换成麦子模型 | 零模组、任何地形都能铺满；但只是视觉，不能收割 |
| 风车 | 结构模组 | **Villager's Windmill**（`villagers-windmill`，1.20.1）、**CTOV**（`ct-overhaul-village`，1.20.1，1112 万下载） |

**注意**：vanilla 的小麦是作物（要农田、矮、稀疏），世界生成直接铺小麦会在更新时掉落，所以「满山麦浪」要么用
专门的麦田生物群系模组，要么用资源包替换草，要么手工铺——地图作者基本走前两条。

Wild Wheat 的短板：MCreator 制作、单生物群系、下载量不足 1k、作者明说基本不再更新（但允许任意移植）。

### 核对：哪些「BOP 系」模组真的有麦田群系

查了各家**完整群系表**，结论是**没有**：

| 模组 | 群系数 | 有麦田吗 | 「田野」类实际叫什么 |
|---|---|---|---|
| Oh The Biomes You'll Go（Legacy） | 76 | ❌ | Amaranth Fields / Allium Fields / Flowering Plains / Prairie / Pasture |
| Biomes O' Plenty | 50+ | ❌ | Lavender Field / Pasture / Grassland |
| Regions Unexplored | — | ❌ | 无 wheat 字段 |
| Oh The Biomes We've Gone | — | ❌ | Prairie 等 |
| Terralith | 近 100 | ❌ | 无 wheat 字段 |

**真有「麦田」的只有两个**（都是小体量新项目）：

| 模组 | 平台 | 版本 | 体量 | 说明 |
|---|---|---|---|---|
| **Wild Wheat** `wild-wheat` | Modrinth | 1.20.1 Forge/NeoForge | 868 | 「adds a wheat field biome」，画廊即齐胸麦浪 |
| **Golden Plains** | CurseForge | 1.21.10 / 1.21.11 Fabric | 235 | 「huge rolling wheat fields around villages」，村庄周围起伏麦田——**观感最贴近本帧**，但 2026-03 才发布，1.20.1 用不了 |

**为什么 BOP 系都不做麦田**：世界生成直接铺 `wheat` 作物不可靠——作物要农田、要水，方块更新就会掉落，
所以群系模组宁可用花/草做「田野」（Amaranth、Lavender、Allium），麦田只能靠专门的群系模组
（自带可自然生成的小麦植株）或资源包替换草。

## 参考

- <https://modrinth.com/mod/tectonic> · <https://modrinth.com/mod/terralith>
- <https://modrinth.com/mod/continents> · <https://modrinth.com/mod/distanthorizons>
- <https://modrinth.com/datapack/terratonic>
- Terralith / Tectonic 正文的「Compatibility」段落（本文引用均出自此处）
