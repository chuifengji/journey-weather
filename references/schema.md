# 行程结构与扩展

坐标为 WGS84 十进制度，lon 是经度、lat 是纬度。行程时区内日期连续，跨夜活动拆为两天。mode 表示抵达该地点的方式。

```json
{
  "schemaVersion": 1,
  "id": "my-trip-2026-09-30",
  "title": "实际线路名称",
  "province": "四川",
  "region": "甘孜 · 贡嘎山域",
  "themes": ["高山湖泊", "徒步摄影"],
  "timezone": "Asia/Shanghai",
  "variant": "custom",
  "requirements": "用户的原始要求",
  "constraints": {"allowCamping": false, "maxHikeHours": 5},
  "assumptions": ["未确认事项和规划假设"],
  "access": {"status": "unconfirmed", "checkedAt": "2026-09-21", "note": "具体待核实路段及证据", "sourceUrl": "https://example.org/official-notice"},
  "sources": [{"title": "线路节点来源", "url": "https://example.org/route", "kind": "official", "checkedAt": "2026-09-21"}],
  "places": {
    "lake": {"name": "冷嘎措", "lon": 101.6848224, "lat": 29.6511172, "source": "https://www.openstreetmap.org/way/531486942", "coordinateStatus": "mapped", "checkedAt": "2026-09-21"}
  },
  "days": [{
    "id": "day-1", "date": "2026-09-30", "title": "冷嘎措", "shortTitle": "冷嘎措",
    "stops": [{"placeId": "lake", "arrival": "13:00", "departure": "14:30", "mode": "walk"}],
    "hikeHours": 0, "hikeKm": 0, "budgetBasis": "示例仅展示一个地点，尚未编排上下山路线",
    "lodging": "待安排", "lodgingType": "none", "note": "示例，不是完整可执行行程"
  }]
}
```

lodgingType 为 camp / lodge / none，mode 为 walk / drive / mixed。无可靠海拔时省略 elevation。自定义地点用 source: user，不可继承同名地点的旧天气。时间 HH:mm，每节点 arrival ≥ 上一节点 departure。

同名或位置未确认的节点可使用 `{"name":"实际垭口名","lon":null,"lat":null,"source":"user","coordinateStatus":"unresolved","coordinateNote":"具体待核实原因"}`。仍须有名称、来源、原因；不进入天气请求，不绘制相邻线段。仅缺失经纬度而不标明 unresolved 会校验失败。`reportedElevation` 可保留用户原始海拔，`coordinateNote` / `elevationNote` 用于说明与地图资料的差异。

## 新目的地

1. 地区与主题是交叉筛选标签，变体保存明确的每日节点。
2. 查官方开放、道路管理信息，再用官方路线图、运营方节点描述、OSM 或用户 GPX 核实路径。运营方安排不等于官方许可。
3. 坐标须可追溯。遇冲突继续查证，不从效果图位置反推精确经纬度。
4. 正反穿分别编排，时长、接车点、住宿可能不同，不能只反转数组。
5. 未知天数显式编排；脚本不会把未收录的天数伪装成现有变体。

## 路径

segments.geojson 每段属性：from、to（地点 ID）、endpoints（原始地点坐标）、verified、basis、source，可加 OSM wayIds 和 endpointOffsetMeters。verified: true 仅表示几何有地图或 GPX 依据，**不表示现场安全或开放**。更换坐标后旧段无效，降级虚线；车辆无道路轨迹也画虚线。

用户本次的新路线可在计划中附加 `pathGeometry`（GeoJSON FeatureCollection，LineString 使用上述属性）。它随 JSON 导出并用于重建，不必写入永久种子目录。当前自定义路线会加入该 HTML 自身的线路选择器，方便切换后返回。

用户 GPX 用 CLI 附加。网页重新编排会优先使用已知 OSM 段，独立 GPX 要在再次构建时重新附加。GPX 不改变地点或时刻，天气依旧按计划地点请求。

## 输出与持久化

HTML 内联行程、天气快照、地图数据、样式和脚本，联网用于瓦片及显式天气刷新。JSON 导出只保存规划，不含刷新后的天气；CLI 再构建重新获取。新增地点必须刷新或重建才有对应预报。
