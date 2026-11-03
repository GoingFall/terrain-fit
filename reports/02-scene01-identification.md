# 02 · 截图识别（修订版）：静谧山谷 · 拉斐丽

> **修订记录（2026-11-03）**：初版判「资源包模型，不是模组」，作者回复后**推翻**——
> 布景来自整合包 **[UJ]乌托邦探险之旅**，花瓶是 **Cluttered** 的 `glass flower vase`。
> 保留原判定过程，是因为「为什么错」本身有用（见「复盘」）。

- 画面：`input/scene-01-valley-desk.png`（2325×1323，4K 视频帧下采样）
- 来源：B 站 [BV1weyuYmEJ3](https://www.bilibili.com/video/BV1weyuYmEJ3/)，西西弗柿Sisyphus，2024-10-18
- 地图：[静谧山谷 · 拉斐丽（La vallée）](https://goto.pixelmap.cc/maps/Hongmeng35_lavalle)，Hongmeng35（虹梦）
- 光影：Bliss **2.0.4**
- 布景：**乌托邦探险之旅（Utopian Journey）** 整合包里的装饰模组

## 结论

1. **花瓶 = Cluttered 的 `glass flower vase`**（作者确认 + 你独立找到，双来源）。
2. **桌面、书本是同一套布景**：乌托邦整合包 430 个模组里有一整排装饰/摆放类模组，
   书本最可能是 **物品陈列（Items Displayed）** 或 Cluttered 系模型，桌面的确切归属仍未定。
3. **地图本体仍是纯原版地形**（扫描 36,864 区块，非原版方块 ID = 0）。这点没变：
   布景是作者在地图上后摆的，不在存档里。
4. 光影 **Bliss 2.0.4** 不变；注意整合包是 **Fabric**，所以光影走 **Iris** 而不是 Oculus。

## 确认链

| 环节 | 证据 |
|---|---|
| 作者说法 | 「乌托邦里的模组」 |
| 整合包页 | [mcmod 1337](https://www.mcmod.cn/modpack/1337.html) = **[UJ]乌托邦探险之旅 (Utopian Journey)**，Fabric，**1.20.1**，430 个模组，作者 Limit小火柴 |
| 包内有 Cluttered | 模组表「装饰」分类：**Cluttered 2.1.0+1.20.1** |
| Cluttered 本体 | Modrinth `cluttered`，807 万次下载，1.16.5–1.21.1，Fabric/Forge/NeoForge，官方画廊同为 16x 柔和色家具（草莓厨房、粉彩卧室、扶手椅） |
| 具体方块 | `glass flower vase`（你找到的名字） |

## 三级判定（更新）

| # | 物品 | 判断 | 依据 |
|---|---|---|---|
| 1 | 蓝玻璃瓶 + 白标签 + 花束 | **模组（已确认）** | Cluttered `glass flower vase`；16x、非整格、带纸标签正是它的做法 |
| 2 | 摊开的大书 | **模组（高概率）** | 约 1 格宽的落地书本，原版做不到；包内有物品陈列/装饰类模组 |
| 3 | 红 / 白 / 紫书本堆 | **模组（同上）** | 与 2 同一套布景 |
| 4 | 木桌面格纹 | **模组（高概率）** | 包内装饰家具众多（Cluttered / Another Furniture / Handcrafted / Convenient Decor…），具体哪一款待定 |
| 5 | 山谷地形 | **原版** | 区块扫描：只有原版方块 |
| 6 | 云、雾、体积光 | **光影** | Bliss 2.0.4 |

## 复盘：为什么初版判成了资源包

错的不是事实，是**先验**。当时我的判断链是：

1. 地图存档扫描 → 非原版方块 0 个 ✅（这步是对的，也仍然是关键事实）
2. 「道具不在存档里 ⇒ 作者摆的」✅
3. 「作者摆的道具是 16x 非整格 ⇒ 多半是资源包」❌ —— **这一步跳过了「大型装饰模组」这一类**

我的候选表里只有 Farmer's Delight、Kaleidoscope、Beautify、Another Furniture 这一档，
而 **Cluttered 这种「几百件 16x 装饰道具的大合集」不在表里**；Modrinth 搜 `desk furniture`
0 命中又加固了「没有这种模组」的错觉——实际上它叫 Cluttered，不叫 furniture。

教训：**「搜不到」只能证明「不是这个名字」，不能证明「不存在」**；遇到「一桌子小道具」
首选应该是装饰大合集（Cluttered / DecoCraft 血统），而不是资源包。

## 光影（不变）

| 项 | 值 |
|---|---|
| 名称 | Bliss Shaders（Chocapic13 v9 改版，X0nk） |
| 版本 | **2.0.4**（2023-08 至 2025-09 之间唯一版本，视频发布 2024-10 只能用它） |
| 页面 | <https://modrinth.com/shader/bliss-shader> · <https://github.com/X0nk/Bliss-Shader> |
| 本机 | `shaderpacks/Bliss_v2.0.4_(Chocapic13_Shaders_edit).zip`（文件名与官方一致） |
| 加载器 | 视频用 Fabric + **Iris**；本机 1.20.1 Forge + **Oculus** 也能跑 |

## 想复刻

- **直接装 Cluttered**（Modrinth `cluttered`，支持 1.20.1，Fabric/Forge/NeoForge 通吃）：
  花瓶、桌子、书本、厨房小物一起解决，风格比 Kaleidoscope 更「粉彩居家」。
- 想要「物品随手摆」的交互：**物品陈列 Items Displayed**（包内版本 1.3，CurseForge 发布；
  Modrinth 同名项目目前只列 1.21.5+）。
- 想一整套：直接下 [乌托邦探险之旅](https://www.mcmod.cn/modpack/1337.html)（Fabric 1.20.1）。

## 数据与命令

- 存档扫描：`python tools/scan_world_blocks.py "_map/world/<地图目录>"`
- 标注图：`annotated/scene-01-annotated.png`（spec：`reports/spec-scene01.json`）
- Cluttered 画廊：`gallery/cluttered/`（10 张，用于比对贴图风格）
- 放大裁切：`crops/scene01/`（7x 瓶身 `bottle_zoom.png`）
