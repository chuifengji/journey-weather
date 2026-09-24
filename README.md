# 旅迹天气 · Journey Weather

将旅行和徒步行程转换为可编辑的天气地图：按真实地点和每日时间安排，对比 ECMWF、GFS、ICON 模型预报，生成 HTML 页面与可复用的行程 JSON。

An agent skill for itinerary-based weather planning, with real locations, multi-model forecasts, GPX support, and an editable terrain map.

## 安装

需要 Node.js / npm 才能运行安装命令：

```sh
npx skills add chuifengji/journey-weather --skill journey-weather
```

按提示选择使用的 Agent 和安装范围。查看可安装的 skill：

```sh
npx skills add chuifengji/journey-weather --list
```

也可以克隆完整仓库，将整个目录放入所用 Agent 的 skills 目录。请保留 `scripts/`、`assets/`、`references/` 和 `agents/`，运行时需要这些文件。

## 使用示例

安装后向 Agent 描述目的地、起止日期和要求，例如：

> 使用 journey-weather，规划 2026 年 9 月 30 日出发的贡嘎小环线与冷嘎措 6 天行程。列出每日真实地点、交通和住宿，对比多个天气模型，生成可编辑的天气地图，并说明路线证据与预报缺测。

也支持自定义路线、正反穿、GPX 轨迹和额外行程要求。内置目录目前以贡嘎与冷嘎措为种子数据；其他目的地需要由 Agent 查证地点并编排行程。

## 运行环境

- Python 3.10+；核心 Python 脚本只使用标准库。
- `curl`，用于请求天气数据。
- 支持 WebGL 的现代浏览器。
- 获取预报和加载在线地图瓦片需要网络连接。
- Node.js 用于 Skills CLI 安装及 JavaScript 测试。

## 直接运行

```sh
git clone https://github.com/chuifengji/journey-weather.git
cd journey-weather

python3 scripts/journey.py catalog

python3 scripts/journey.py plan \
  --route gongga-small-loop-lenggacuo \
  --start 2026-09-30 \
  --variant 6d \
  --direction forward \
  --out output/plan.json

python3 scripts/journey.py validate output/plan.json
python3 scripts/journey.py build --plan output/plan.json --out output
python3 scripts/journey.py serve --dir output --port 4174
```

将示例日期替换为实际出发日期，在浏览器打开 `http://127.0.0.1:4174/`。主要交付物是 `index.html`、`plan.json` 和 `行程与天气.md`，同时生成预报、路线与营地夜间统计等数据文件。

离线构建可添加 `--offline`，仅使用匹配坐标和时区的缓存；没有缓存时天气显示为缺测。地图瓦片仍需在线加载。

## 数据与解释

- 天气来自 Open-Meteo 提供的独立模式预报；模型不是观测，模型分歧也不是置信区间。
- 超出模型覆盖的日期保留缺测，不填零、不编造小时预报。
- 虚线表示地点连接示意；OSM 路径和 GPX 均不代表通行许可。
- 未查明坐标的地点保留未定位状态，不借用同名地点的预报。
- 自然语言要求可能与种子行程冲突，命令会列出已识别的冲突，复杂调整需由 Agent 处理。

详细规则见 [SKILL.md](SKILL.md)、[行程结构](references/schema.md) 和 [预报与证据规则](references/weather-and-evidence.md)。

## 验证

```sh
python3 scripts/test_journey.py
node scripts/test_weather_meaning.js
```

## 版本与第三方资源

本仓库首次发布基于 journey-weather 1.0.0 发布包，保留原有 skill 文件，并补充 GitHub 安装说明。

MapLibre GL JS、Lucide 的许可证保存在 [`assets/vendor/`](assets/vendor/)。地图数据、瓦片和天气服务的来源及使用说明见 [资源来源](references/asset-sources.md) 和 [预报与证据规则](references/weather-and-evidence.md)。这些第三方资源分别遵循各自的许可与服务条款。
