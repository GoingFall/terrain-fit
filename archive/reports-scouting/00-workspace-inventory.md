# 00 · 工作区基线盘点（版本包 1.20.1-Liminalism）

> 读取时间：2026-11-03 16:11（Asia/Shanghai）。
> **这个工作区是活的**：盘点过程中 `oculus-mc1.20.1-1.8.0.jar` 在 16:09 被放进 `mods/`，
> 所以下面的结论都带时间戳。改动 mods 后请重跑文末的命令，不要直接引用旧结论。
>
> 本文件是「截图 → 模组方块」识别任务的**先验**：先确定这个安装里究竟有哪些模组可能产生画面，
> 之后每张截图都先过一遍这张表，避免把光影/材质包认成模组。

## 结论先行

1. 这是 HMCL 的 **Minecraft 1.20.1 + Forge 47.4.28** 版本包。`mods/` 里 **17 个 jar**
   （jar 内 `META-INF/mods.toml` 实证），其中**唯一产生方块与物品的是
   Farmer's Delight `1.20.1-1.3.4`**（modId `farmersdelight`，声明 MC `[1.20,1.20.1]`）。
2. 其余 16 个全部是性能、UI、配方查询、输入法或前置库，**没有任何家具 / 装饰 / 建筑 /
   生物 / 女仆类内容模组**。因此画面里的「3D 家具、可坐座椅、壁挂置物架、酒桶吧台」优先
   判给 **资源包（可替换方块模型）+ 光影**。
3. 光影链路齐全：`mods/` 有 **Oculus 1.8.0**，`.minecraft\shaderpacks\` 有 14 个光影包
   （Complementary Unbound/Reimagined、BSL、Photon、iterationT、SEUS、Spooklementary…）。
   「这光影是模组吗」这类问题，答案几乎必然是「不是，是光影包」。

## 版本基线

| 项 | 值 |
|---|---|
| 版本 id | `1.20.1-Liminalism` |
| 游戏版本 | 1.20.1 |
| 加载器 | Forge **47.4.28**（mcp 20230612.114412） |
| Java | 17（`java-runtime-gamma`） |
| 主类 | `cpw.mods.bootstraplauncher.BootstrapLauncher` |
| 版本 jar | `1.20.1-Liminalism.jar` |

> 「Liminalism」未检索到同名公开整合包，判断为**自建实例名**。
> 该实例的 `.hmcl/config/instance-game-settings.json` 覆盖了 `runningDirectory`。

## 两套 mods 目录（会改变结论，必须分清）

| 位置 | 数量 | 生效条件 |
|---|---|---|
| `versions\1.20.1-Liminalism\mods\` | **17** | 该实例开启**版本隔离**时加载这一组 |
| `.minecraft\mods\1.20.1\` | **24** | **未隔离**时 HMCL 按 MC 版本自动加载这一组 |

- 两套内容不同：共享目录的 Xaero 小地图/世界地图、Curios、GeckoLib、Controllable 系列
  在版本目录里没有；版本目录的 Farmer's Delight 在共享目录里没有。
- **共享目录的 24 个 jar 内容读不出来**（`PermissionError: [Errno 13]`，文件级权限/占用），
  只能按文件名登记，未做 jar 内元数据校验；版本目录 17 个已全部读取成功。
- 由此可推定：若截图里同时出现「Farmer's Delight 的锅/砧板」与「小地图」，那是两套混用或
  另一个实例，值得先确认隔离设置。

## 版本目录 17 个模组（jar 内元数据已校验）

| jar | modId | version | 声明 MC | 作用 | 产生方块/物品 |
|---|---|---|---|---|---|
| `FarmersDelight-1.20.1-1.3.4.jar` | `farmersdelight` | 1.20.1-1.3.4 | `[1.20,1.20.1]` | 农业 / 烹饪 / 厨房家具 / 可摆放食物 | **是** |
| `jei-1.20.1-forge-15.74.0.233.jar` | `jei` | 15.74.0.233 | `[1.20.1, 1.20.2)` | 配方查看 | 否 |
| `Jade-1.20.1-Forge-11.13.3.jar` | `jade` | `${file.jarVersion}` | - | 准星方块信息 HUD | 否 |
| `appleskin-forge-mc1.20.1-2.5.1.jar` | `appleskin` | `${file.jarVersion}` | - | 饥饿/饱和度显示 | 否 |
| `MouseTweaks-forge-mc1.20.1-2.25.1.jar` | `mousetweaks` | `${file.jarVersion}` | - | 物品栏拖拽 | 否 |
| `mezz_config-1.20.1-forge-0.6.10.jar` | `mezz_config` | 0.6.10 | `[1.20.1]` | 配置库（JEI 依赖） | 否 |
| `mezz_config_gui-1.20.1-forge-mc1.20.1-0.5.11.jar` | `mezz_config_gui` | 0.5.11 | `[1.20.1]` | 配置界面 | 否 |
| `embeddium-0.3.31+mc1.20.1.jar` | `embeddium` / `rubidium`(别名) | 0.3.31+mc1.20.1 / 0.7.1 | - | 渲染优化（Forge 版 Sodium） | 否 |
| `oculus-mc1.20.1-1.8.0.jar` | `oculus` | 1.8.0 | `[1.20.1]` | **光影加载器** | 否 |
| `modernfix-forge-5.27.91+mc1.20.1.jar` | `modernfix` | 5.27.91+mc1.20.1 | `[1.20, 1.21)` | 启动 / 内存优化 | 否 |
| `ImmediatelyFast-Forge-1.5.5+1.20.4.jar` | `immediatelyfast` | 1.5.5+1.20.4 | `[1.20,1.20.4]` | 渲染批处理 | 否 |
| `entityculling-forge-1.11.3-mc1.20.1.jar` | `entityculling` | 1.11.3 | `1.20.1` | 实体剔除 | 否 |
| `ferritecore-6.0.1-forge.jar` | `ferritecore` | `${file.jarVersion}` | `[1.20,1.21)` | 内存优化 | 否 |
| `Clumps-forge-1.20.1-12.0.0.4.jar` | `clumps` | `${file.jarVersion}` | - | 经验球合并 | 否 |
| `AttributeFix-Forge-1.20.1-21.0.5.jar` | `attributefix` | 21.0.5 | - | 属性上限修复 | 否 |
| `I18nUpdateMod-3.7.0-all.jar` | `i18nupdatemod` | 3.7.0 | - | 中文翻译自动更新（jar 为 Fabric 结构） | 否 |
| `jecharacters-1.20.1-forge-4.6.12.jar` | `jecharacters` | 4.6.12 | - | 中文输入补丁 | 否 |

> `${file.jarVersion}` 是 Forge 的占位符，运行时由 jar 清单填充，不是错误。
> `ImmediatelyFast` 的 jar 名带 `+1.20.4` 但声明区间是 `[1.20,1.20.4]`，**能在 1.20.1 运行**——
> 这正是「文件名不能当证据」的例子。

## 共享目录 24 个（仅文件名，内容不可读）

Xaero's Minimap / WorldMap、Controlling、Searchables、Bookshelf、Curios、Caelus、
EnchantmentDescriptions、Just Enough Resources、Polymorph、GeckoLib、Player Animator、
Bendy Lib、Forge Config Screens、JEI 15.20、Jade 11.13.1、AppleSkin、Clumps、FerriteCore、
Embeddium、ModernFix、I18nUpdateMod、jecharacters —— **同样没有任何内容模组**。
动画库（GeckoLib / Player Animator / Bendy Lib）本身不添加方块，只给别的模组提供模型能力。

## 决策表：画面元素 → 本安装下的最可能解释

| 画面元素 | 判断 | 依据 |
|---|---|---|
| 3D 书架书脊、彩色书堆 | 资源包 | 无装饰模组；原版书架可被替换模型 |
| 可坐的椅子 / 长凳 / 柜台 | 资源包或原版错位 | 无家具模组，原版无坐姿交互 |
| 悬挂草药、酒桶、壁挂杯架 | **不是本实例** | 无对应模组，资源包也做不出可交互形态 |
| 可放置 3D 饮品 / 餐盘 | FD（盛宴、派、饮料）或资源包 | FD 有可摆放取食的 Feast / Pie |
| 烹饪锅、炉灶、砧板、篮子、橱柜 | **FD** | 官方画廊与 changelog 均列出 |
| 雾、体积光、暖色点光、接触阴影 | 光影 | Oculus + `shaderpacks/` 14 个包 |
| 奇异坐姿 / 二次元比例角色 | 不是本实例 | 无女仆/角色类模组 |

## Farmer's Delight 1.3.4 形态清单（唯一内容模组的「是模组」证据）

- 作物：卷心菜、番茄（藤/绳）、洋葱、水稻；富饶土壤（Rich Soil）、稻草/绳/堆肥
- 厨具：**烹饪锅**（Cooking Pot，带 GUI）、**炉灶**（Stove，顶部煎烤区）、**平底锅**（Skillet，可手持/可放置）、**砧板**（Cutting Board，可堆叠物品）
- 储物与装饰：篮子 / 竹篮、各木材**橱柜**、画布告示牌（Canvas Sign，含悬挂式）、挂幅
- 食物展示：**盛宴**（Feast，可摆放并按份取食）、**馅饼**（Pie，可切分摆放）、闪耀沙拉（会发光）
- 网格特征：FD 方块严格对齐 1 格；砧板是半格平面；盛宴/派有专用碰撞箱（吃一份变小）
- 版本核对：Modrinth `farmers-delight` 的 `1.20.1-1.3.4`（2026-08-29 发布，886,834 次下载）
  存在且列于 1.20/1.20.1 Forge —— 与本机 jar 内的 `1.20.1-1.3.4` 一致

## 10 秒确认法（针对本安装，优先级从高到低）

1. **Jade**：准星对准方块，屏幕上方显示 `命名空间:方块ID`（如 `farmersdelight:cooking_pot`）——最快。
2. **F3** 的 `Targeted Block` 行。
3. **JEI**：本安装只有 FD 一个内容模组，若某方块在 JEI 里搜不到，它多半是资源包模型或属于别的实例。
4. **资源包 / 光影**：看 `.minecraft\shaderpacks\`（14 个）与资源包列表，先排除光影再谈模组。

## 工具链状态（已实测可用）

| 项 | 状态 |
|---|---|
| `bash` / `pwsh` | ✅ 可用（本会话早期曾被工作区 ACL 拦住，现已解除） |
| Python | 3.13.7，Pillow 12.3.0 ✅ |
| `zoom_crops.py` | ✅ 实测通过（`crops/selftest/` 4 张） |
| `annotate.py` | ✅ 实测通过（`_selftest/probe-annotated.png`，中文字体正常） |
| `mod_search.py` | ✅ 实测通过（`search "farmers delight"` 返回 190 条） |
| 网络 | ✅ Modrinth API 可直连 |
| 共享 mods 目录 jar | ❌ 内容不可读（`Errno 13`），只登记文件名 |

## 复现 / 刷新基线

```bash
cd "G:\HMCL\.minecraft\versions\1.20.1-Liminalism"
python dsh-artifacts/tools/read_mod_metadata.py mods ../../mods/1.20.1 \
  --out-json dsh-artifacts/reports/mod-metadata.json \
  --out-md  dsh-artifacts/reports/01-mod-metadata.md
```

## 数据来源

- 本机 jar 内 `META-INF/mods.toml`（版本目录 17 个全部读取）
- 本机 `.minecraft\shaderpacks\`、`.minecraft\mods\1.20.1\` 目录清单
- Modrinth：<https://modrinth.com/mod/farmers-delight>（项目页 + 版本 API）
