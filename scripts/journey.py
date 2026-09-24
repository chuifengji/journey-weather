#!/usr/bin/env python3
"""Journey Weather: validated itineraries, independent forecast models and portable HTML."""
from __future__ import annotations
import argparse, copy, datetime as dt, hashlib, html, http.server, json, math, re, shutil, statistics, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MODELS = [
    {"id":"ecmwf_ifs025","name":"ECMWF","detail":"IFS 0.25°","provider":"ECMWF","color":"#aecbd8","nominalDays":15},
    {"id":"gfs_seamless","name":"GFS","detail":"NOAA GFS Seamless","provider":"NOAA","color":"#e0bf87","nominalDays":16},
    {"id":"icon_global","name":"ICON","detail":"DWD ICON Global","provider":"DWD","color":"#aabd9e","nominalDays":7.5}
]
VARIABLES = ["temperature_2m","apparent_temperature","precipitation","wind_speed_10m","wind_gusts_10m","cloud_cover","snowfall","weather_code"]
WEATHER_CODES = json.loads((ROOT/"assets/weather-codes.json").read_text())
def read(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def write(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def today(zone="Asia/Shanghai"):return dt.datetime.now(ZoneInfo(zone)).date()
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()
def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
def located(place):return finite(place.get('lon')) and finite(place.get('lat')) and place.get('coordinateStatus')!='unresolved'
def median(values):
    values=[v for v in values if finite(v)]
    return statistics.median(values) if values else None
def haversine(a,b):
    x,y=math.radians(a[1]),math.radians(b[1]);d=math.sin((y-x)/2)**2+math.cos(x)*math.cos(y)*math.sin(math.radians(b[0]-a[0])/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(d)))

def validate(plan):
    errors=[]
    if not isinstance(plan,dict):return ["行程必须是 JSON 对象"]
    for key in ["id","title","timezone","places","days"]:
        if not plan.get(key):errors.append(f"缺少 {key}")
    if errors:return errors
    try:ZoneInfo(plan["timezone"])
    except Exception:errors.append("无效 IANA 时区")
    places=plan["places"]
    if not isinstance(places,dict):return ["places 必须是以 ID 为键的对象"]
    if not isinstance(plan["days"],list):return ["days 必须是数组"]
    for pid,p in places.items():
        if not isinstance(p,dict):errors.append(f"{pid}: 地点必须是对象");continue
        if not p.get("name"):errors.append(f"{pid}: 地点缺少名称")
        if p.get('coordinateStatus')=='unresolved':
            if p.get('lon') is not None or p.get('lat') is not None or not p.get('coordinateNote'):errors.append(f"{pid}: 未定位地点需留空坐标并说明原因")
        else:
            if not finite(p.get("lon")) or not -180<=p.get("lon",999)<=180:errors.append(f"{pid}: 经度无效")
            if not finite(p.get("lat")) or not -85<=p.get("lat",999)<=85:errors.append(f"{pid}: 纬度无效")
        if not p.get("source"):errors.append(f"{pid}: 缺少坐标来源；用户提供坐标请标记 user")
        if p.get("elevation") is not None and (not finite(p["elevation"]) or not -500<=p["elevation"]<=9000):errors.append(f"{pid}: 海拔无效")
    dates=[];ids=[]
    for i,day in enumerate(plan["days"]):
        if not isinstance(day,dict):errors.append(f"第 {i+1} 天必须是对象");continue
        label=f"第 {i+1} 天";ids.append(day.get("id"))
        try:dates.append(dt.date.fromisoformat(day["date"]))
        except (ValueError,KeyError,TypeError):errors.append(f"{label}: 日期无效")
        if not isinstance(day.get("stops"),list) or not day["stops"]:errors.append(f"{label}: stops 需至少一个真实地点");continue
        for field in ["hikeHours","hikeKm"]:
            if day.get(field) is not None and (not finite(day[field]) or day[field]<0):errors.append(f"{label}: {field} 需非负数")
        previous="00:00"
        for s in day.get("stops",[]):
            if not isinstance(s,dict):errors.append(f"{label}: 地点行必须是对象");continue
            if s.get("placeId") not in places:errors.append(f"{label}: 未知地点 {s.get('placeId')}")
            arrival,departure=s.get("arrival",""),s.get("departure",s.get("arrival",""))
            if not isinstance(arrival,str) or not isinstance(departure,str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",arrival) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",departure):errors.append(f"{label}: 无效时间");continue
            elif arrival<previous or departure<arrival:errors.append(f"{label}: 地点的到达/离开时间必须递增且不重叠")
            previous=departure
    if len(set(ids))!=len(ids) or None in ids:errors.append("每一天需要唯一 id")
    if len(dates)==len(plan["days"]):
        if any(b-a!=dt.timedelta(days=1) for a,b in zip(dates,dates[1:])):errors.append("日期必须逐日连续；休整日请保留当天地点")
    paths=plan.get('pathGeometry',{'type':'FeatureCollection','features':[]})
    if not isinstance(paths,dict) or paths.get('type')!='FeatureCollection' or not isinstance(paths.get('features'),list):errors.append('pathGeometry 需为 GeoJSON FeatureCollection')
    else:
        for f in paths['features']:
            try:
                prop=f['properties'];g=f['geometry'];coords=g['coordinates'];ends=prop['endpoints']
                assert g['type']=='LineString' and len(coords)>=2 and len(ends)==2
                assert prop.get('source') and prop.get('basis') and prop['from'] in places and prop['to'] in places
                assert all(len(c)>=2 and finite(c[0]) and finite(c[1]) and -180<=c[0]<=180 and -85<=c[1]<=85 for c in coords+ends)
            except (AssertionError,KeyError,TypeError,IndexError):errors.append('pathGeometry 存在无效线段或缺少路径来源与端点')
    return errors

def requirement_constraints(text, supplied=None):
    constraints=copy.deepcopy(supplied or {})
    if re.search(r"不露营|不要露营|住酒店|全程客栈",text):constraints["allowCamping"]=False
    number=re.search(r"(?:每天|每日|单日).*?(?:不超过|最多|上限|≤)\s*(\d+(?:\.\d+)?)\s*(?:个)?小时",text)
    if number:constraints["maxHikeHours"]=float(number[1])
    return constraints

def check_constraints(plan):
    problems=[];c=plan.get("constraints",{})
    for i,d in enumerate(plan["days"]):
        if c.get("allowCamping") is False and d.get("lodgingType")=="camp":problems.append(f"第 {i+1} 天为露营，与不露营要求冲突")
        if finite(c.get("maxHikeHours")) and finite(d.get("hikeHours")) and d["hikeHours"]>c["maxHikeHours"]:problems.append(f"第 {i+1} 天徒步预算 {d['hikeHours']} 小时，超过 {c['maxHikeHours']} 小时上限")
    return problems

def make_plan(route_id,start,variant="6d",direction="forward",requirements="",end=None):
    cat=read(ROOT/"assets/catalog.json")
    route=next((r for r in cat["routes"] if r["id"]==route_id),None)
    if not route:raise ValueError("路线尚未收录；先查证地点后按 schema 新建计划，或选择 catalog 中的路线")
    if end:
        n=(dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days+1
        variant=f"{n}d"
    key=f"{variant}-{direction}"
    if key not in route["variants"]:raise ValueError(f"没有 {key} 变体，可用：{', '.join(route['variants'])}；请显式编排新变体")
    template=route["variants"][key]
    plan={"schemaVersion":1,"id":route_id+"-"+start,"routeId":route_id,"title":route["name"],"province":route["province"],"region":route["region"],"themes":route["themes"],"timezone":"Asia/Shanghai","variant":key,"requirements":requirements,"constraints":requirement_constraints(requirements),"assumptions":copy.deepcopy(template.get("assumptions",[])),"access":copy.deepcopy(route.get("access",{})),"sources":copy.deepcopy(route.get("sources",[])),"places":{},"days":copy.deepcopy(template["days"]),"createdAt":stamp()}
    for i,day in enumerate(plan["days"]):
        day["id"]=f"day-{i+1}";day["date"]=(dt.date.fromisoformat(start)+dt.timedelta(days=i)).isoformat()
        for s in day["stops"]:plan["places"][s["placeId"]]=copy.deepcopy(cat["places"][s["placeId"]])
    return plan

def coordinate_key(p):
    if not located(p):return 'unresolved'
    elevation=format(p['elevation'],'g') if finite(p.get('elevation')) else 'auto'
    return f"{p['lat']:.6f},{p['lon']:.6f},{elevation}"
def forecast_key(plan):
    return hashlib.sha256(json.dumps({"points":{k:coordinate_key(v) for k,v in sorted(plan["places"].items())},"timezone":plan["timezone"]},sort_keys=True).encode()).hexdigest()[:16]

def normalize_model(raw,place_ids,model_id):
    records=raw if isinstance(raw,list) else [raw]
    if len(records)!=len(place_ids):raise ValueError(f"API 返回 {len(records)} 个地点，预期 {len(place_ids)}")
    points={}
    for pid,record in zip(place_ids,records):
        hours=record.get("hourly",{});times=hours.get("time",[])
        if not isinstance(times,list):raise ValueError("API time 序列无效")
        normalized={}
        for metric in VARIABLES:
            series=hours.get(metric,hours.get(f"{metric}_{model_id}",[None]*len(times) if metric=='weather_code' else []))
            normalized[metric]=[x if finite(x) else None for x in series]
            if metric=='weather_code':
                normalized[metric]=[int(x) if finite(x) and x==int(x) and str(int(x)) in WEATHER_CODES else None for x in series]
            if len(normalized[metric])!=len(times):raise ValueError(f"{model_id} {metric}: 时间轴与数值长度不匹配")
        usable=[t for t,v in zip(times,normalized["temperature_2m"]) if finite(v)]
        points[pid]={"time":times,"hourly":normalized,"availableFrom":usable[0] if usable else None,"availableTo":usable[-1] if usable else None,"grid":{"lat":record.get("latitude"),"lon":record.get("longitude"),"elevation":record.get("elevation")},"utcOffsetSeconds":record.get("utc_offset_seconds")}
    return points

def fetch_weather(plan,cache_dir,offline=False):
    cache_dir=Path(cache_dir);cache_dir.mkdir(parents=True,exist_ok=True)
    current=today(plan["timezone"])
    ids=[pid for pid,p in plan['places'].items() if located(p)];key=forecast_key(plan)
    bundle={"retrievedAt":stamp(),"provider":"Open-Meteo","timezone":plan["timezone"],"coordinateKey":key,"models":copy.deepcopy(MODELS),"points":{},"errors":[],"requests":[],"status":"live","dateChecked":current.isoformat()}
    for pid,p in plan["places"].items():bundle["points"][pid]={"coordinateKey":coordinate_key(p),"models":{}}
    if not ids:bundle['status']='unavailable';return bundle
    def one(model):
        path=cache_dir/f"{key}-{model['id']}.json"
        if offline:
            if not path.exists():return model,None,"没有坐标匹配的缓存",None
            old=read(path);return model,old["points"],None,{**old["request"],"cache":True}
        params={"latitude":','.join(str(plan["places"][p]["lat"]) for p in ids),"longitude":','.join(str(plan["places"][p]["lon"]) for p in ids),"hourly":','.join(VARIABLES),"models":model["id"],"timezone":plan["timezone"],"wind_speed_unit":"ms","forecast_days":16}
        # Supply target elevation only if every point has a sourced value; otherwise
        # preserve Open-Meteo's documented automatic DEM downscaling for all points.
        if all(finite(plan["places"][p].get("elevation")) for p in ids):params["elevation"]=','.join(str(plan["places"][p]["elevation"]) for p in ids)
        url="https://api.open-meteo.com/v1/forecast?"+urlencode(params)
        try:
            run=subprocess.run(["curl","-fsSL","--max-time","50",url],capture_output=True,text=True,timeout=55)
            if run.returncode:raise ValueError(run.stderr.strip()[-250:])
            raw=json.loads(run.stdout)
            if isinstance(raw,dict) and raw.get("error"):raise ValueError(raw.get("reason","API error"))
            points=normalize_model(raw,ids,model["id"])
            request={"model":model["id"],"url":url,"retrievedAt":stamp(),"cache":False}
            write(path,{"points":points,"request":request})
            return model,points,None,request
        except (ValueError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
            if path.exists():
                old=read(path);return model,old["points"],str(exc),{**old["request"],"cache":True}
            return model,None,str(exc),{"model":model["id"],"url":url,"retrievedAt":stamp(),"cache":False}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for model,points,error,request in pool.map(one,MODELS):
            if error:bundle["errors"].append({"model":model["id"],"reason":error})
            if request:bundle["requests"].append(request)
            if points:
                for pid,data in points.items():bundle["points"][pid]["models"][model["id"]]=data
    if any(r.get("cache") for r in bundle["requests"]):bundle["status"]="cached" if all(r.get("cache") for r in bundle["requests"]) else "partial-cache"
    if not any(p["models"] for p in bundle["points"].values()):bundle["status"]="unavailable"
    return bundle

def value(weather,pid,model,metric,date,hour):
    point=weather.get("points",{}).get(pid,{}).get("models",{}).get(model,{})
    target=f"{date}T{hour:02d}:00"
    try:i=point.get("time",[]).index(target)
    except ValueError:return None
    values=point.get("hourly",{}).get(metric,[])
    return values[i] if i<len(values) and finite(values[i]) else None

def summarize(plan,weather):
    result=[]
    for day in plan["days"]:
        samples=[]
        for stop in day["stops"]:
            hour=int(stop["arrival"][:2]);row={"placeId":stop["placeId"],"name":plan["places"][stop["placeId"]]["name"],"time":stop["arrival"],"sampledAt":f"{day['date']}T{hour:02d}:00","models":{}}
            for model in MODELS:
                mid=model["id"]
                row["models"][mid]={k:value(weather,stop["placeId"],mid,k,day["date"],hour) for k in VARIABLES}
            temps=[x["temperature_2m"] for x in row["models"].values() if finite(x["temperature_2m"])]
            row["temperatureMedian"]=median(temps);row["availableModels"]=len(temps)
            row["temperatureRange"]=[min(temps),max(temps)] if temps else None
            samples.append(row)
        result.append({"id":day["id"],"date":day["date"],"title":day["title"],"samples":samples})
    return result

def overnight_summaries(plan,weather):
    result=[]
    for day in plan['days']:
        if day.get('lodgingType')!='camp':continue
        pid=day['stops'][-1]['placeId'];next_date=(dt.date.fromisoformat(day['date'])+dt.timedelta(days=1)).isoformat()
        slots=[(day['date'],h) for h in range(18,24)]+[(next_date,h) for h in range(9)]
        row={'date':day['date'],'placeId':pid,'name':plan['places'][pid]['name'],'window':f"{day['date']}T18:00/{next_date}T08:00",'models':{}}
        for m in MODELS:
            data={k:[value(weather,pid,m['id'],k,d,h) for d,h in slots] for k in ['temperature_2m','wind_gusts_10m','precipitation','snowfall']}
            # Temperature includes both endpoints. Accumulations omit 18:00,
            # since that API hour describes precipitation before the window.
            full=lambda a:all(finite(v) for v in a)
            row['models'][m['id']]={'temperatureMin':min(data['temperature_2m']) if full(data['temperature_2m']) else None,'gustMax':max(data['wind_gusts_10m']) if full(data['wind_gusts_10m']) else None,'precipitationSum':round(sum(data['precipitation'][1:]),2) if full(data['precipitation'][1:]) else None,'snowfallSum':round(sum(data['snowfall'][1:]),2) if full(data['snowfall'][1:]) else None,'temperatureHours':sum(finite(v) for v in data['temperature_2m']),'expectedTemperatureHours':len(slots)}
        result.append(row)
    return result

def build_geometry(plan):
    catalog_paths=ROOT/"assets/segments.geojson"
    known=read(catalog_paths)["features"] if catalog_paths.exists() else []
    known+=plan.get('pathGeometry',{}).get('features',[])
    lookup={(f["properties"]["from"],f["properties"]["to"]):f for f in known}
    features=[]
    for day in plan["days"]:
        for a,b in zip(day["stops"],day["stops"][1:]):
            start,end=a["placeId"],b["placeId"];pa,pb=plan["places"][start],plan["places"][end]
            if not located(pa) or not located(pb):continue
            if start==end:continue
            coords=[[pa["lon"],pa["lat"]],[pb["lon"],pb["lat"]]]
            reverse=False;record=lookup.get((start,end))
            if not record:record=lookup.get((end,start));reverse=bool(record)
            if record:
                original=record["properties"].get("endpoints",[])
                test=coords[::-1] if reverse else coords
                if len(original)!=2 or any(haversine(x,y)>.03 for x,y in zip(original,test)):record=None
            if record:
                feature=copy.deepcopy(record)
                if reverse:feature["geometry"]["coordinates"].reverse()
                feature["properties"].update({"dayId":day["id"],"from":start,"to":end,"mode":b.get("mode","walk")})
            else:feature={"type":"Feature","properties":{"dayId":day["id"],"from":start,"to":end,"mode":b.get("mode","walk"),"verified":False,"basis":"地点间的行程连线示意，不是道路或步道轨迹"},"geometry":{"type":"LineString","coordinates":coords}}
            features.append(feature)
    return {"type":"FeatureCollection","features":features}

def import_gpx(path,day_id):
    root=ET.parse(path).getroot();features=[]
    for segment in root.findall('.//{*}trkseg'):
        coords=[]
        for p in segment.findall('{*}trkpt'):
            lon,lat=float(p.attrib['lon']),float(p.attrib['lat'])
            if not(-180<=lon<=180 and -85<=lat<=85):raise ValueError("GPX 坐标无效")
            coords.append([lon,lat])
        if len(coords)>1:features.append({"type":"Feature","properties":{"dayId":day_id,"verified":True,"mode":"walk","basis":"用户提供 GPX；独立轨迹段保持断开"},"geometry":{"type":"LineString","coordinates":coords}})
    if not features:raise ValueError("GPX 没有至少两个点的 trkseg；不会臆造轨迹")
    return features

def render(plan,weather,out,gpx=None,gpx_day=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    geometry=build_geometry(plan)
    if gpx:
        day_id=gpx_day or plan["days"][0]["id"]
        if day_id not in [d["id"] for d in plan["days"]]:raise ValueError("GPX day id 不属于此行程")
        geometry["features"]=[f for f in geometry["features"] if f["properties"]["dayId"]!=day_id]+import_gpx(gpx,day_id)
    payload={"version":1,"plan":plan,"weather":weather,"geometry":geometry,"summary":summarize(plan,weather),"constraints":check_constraints(plan),"catalog":read(ROOT/"assets/catalog.json"),"paths":read(ROOT/"assets/segments.geojson")}
    payload['weatherCodes']=WEATHER_CODES
    payload['paths']['features']+=plan.get('pathGeometry',{}).get('features',[])
    if plan.get('routeId') and not any(r['id']==plan['routeId'] for r in payload['catalog']['routes']):
        payload['catalog']['places'].update(copy.deepcopy(plan['places']))
        payload['catalog']['routes'].insert(0,{'id':plan['routeId'],'name':plan['title'],'province':plan.get('province','自定义'),'region':plan.get('region',''),'themes':plan.get('themes',[]),'variants':{'custom':{'label':f"{len(plan['days'])} 天 · 当前自定义行程",'days':copy.deepcopy(plan['days']),'assumptions':plan.get('assumptions',[])}},'sources':plan.get('sources',[]),'access':plan.get('access',{}),'pathGeometry':plan.get('pathGeometry',{'type':'FeatureCollection','features':[]})})
    if (ROOT/"assets/contours.geojson").exists():payload["contours"]=read(ROOT/"assets/contours.geojson")
    template=(ROOT/"assets/template.html").read_text()
    replacements={"__TITLE__":html.escape(plan["title"]),"__MAP_CSS__":(ROOT/"assets/vendor/maplibre-gl.css").read_text(),"__APP_CSS__":(ROOT/"assets/app.css").read_text(),"__MAP_JS__":(ROOT/"assets/vendor/maplibre-gl.js").read_text(),"__ICONS_JS__":(ROOT/"assets/vendor/lucide.js").read_text(),"__APP_JS__":(ROOT/"assets/app.js").read_text(),"__DATA__":json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')}
    replacements["__APP_CSS__"]+='\n'+(ROOT/"assets/journey.css").read_text()
    replacements["__APP_JS__"]=(ROOT/"assets/weather-meaning.js").read_text()+'\n'+replacements["__APP_JS__"]
    for token,content in replacements.items():
        if token.endswith("JS__"):content=re.sub(r"</script",r"<\\/script",content,flags=re.I)
        template=template.replace(token,content)
    (out/"index.html").write_text(template,encoding="utf-8")
    write(out/"plan.json",plan);write(out/"weather.json",weather);write(out/"route.geojson",geometry);write(out/"summary.json",payload["summary"])
    nights=overnight_summaries(plan,weather);write(out/'overnights.json',nights)
    lines=[f"# {plan['title']}","",f"{plan['days'][0]['date']} — {plan['days'][-1]['date']} · {len(plan['days'])} 天 · {plan['timezone']}","",f"页面生成时间：{stamp()}。状态：{weather['status']}。以下按计划到达所在小时匹配预报（例如 07:30 对应 07:00），不是每日最高/最低温。","",*[f"- {r['model']} 实际获取：{r['retrievedAt']}" for r in weather.get('requests',[])],"", "| 日期 | 地点与计划时刻 | 多模型气温范围 | 可用模型 |","|---|---|---|---|"]
    lines[-2:]=["| 日期 | 地点与计划时刻 | 多模型气温范围 | 小时降水中位数 | 阵风最高值 | 可用模型 |","|---|---|---|---|---|---|"]
    for day in payload["summary"]:
        for row in day["samples"]:
            values=row["temperatureRange"];text=f"{values[0]:.1f}–{values[1]:.1f} °C" if values else "尚无覆盖预报"
            names=' / '.join(m["name"] for m in MODELS if finite(row["models"][m["id"]]["temperature_2m"])) or "—"
            rain=median([m['precipitation'] for m in row['models'].values()]);gust=[m['wind_gusts_10m'] for m in row['models'].values() if finite(m['wind_gusts_10m'])]
            rain_text=f"{rain:.2f} mm" if finite(rain) else '—';gust_text=f"{max(gust):.1f} m/s" if gust else '—'
            lines.append(f"| {day['date']} | {row['name']} {row['time']} | {text} | {rain_text} | {gust_text} | {names} |")
    lines+=['','小时降水是所标时刻之前一小时的累计量（mm，含雪的水当量），不是降雨概率或瞬时雨强。1 mm 相当于每平方米 1 升水。小雨、中雨、阵雨等名称来自模型 weather_code，不用小时雨量套用 24 小时雨量等级；天气类型对应所标时刻，不代表前一小时全程相同。网页可查看各模型的类型和原始雨量。']
    if nights:
        lines+=['','## 营地夜间','当日 18:00 至次日 08:00。各模型整段覆盖才汇总；降水为 14 小时累计，不是降雨概率。','| 夜晚 / 营地 | 模型 | 最低温 °C | 累计降水 mm | 最大阵风 m/s |','|---|---|---|---|---|']
        for n in nights:
            for m in MODELS:
                r=n['models'][m['id']];values=[f'{r[k]:.1f}' if finite(r[k]) else '覆盖不足' for k in ['temperatureMin','precipitationSum','gustMax']]
                lines.append(f"| {n['date']} / {n['name']} | {m['name']} | "+' | '.join(values)+' |')
    lines+=["","## 每日安排",*[f"- {d['date']}：{d['title']}。{d.get('lodging','住宿待定')}；徒步预算 {d.get('hikeHours') if finite(d.get('hikeHours')) else '待核对'} 小时 / {d.get('hikeKm') if finite(d.get('hikeKm')) else '待核对'} km。{d.get('note','')}" for d in plan['days']],"","提前超过 7 天只作为远期趋势；模型间分歧不是置信区间。ECMWF、GFS、ICON 的缺测不补零，不以城市预报替代山地坐标。出发前需更新天气及当地管控信息。"]
    lines+=["","## 规划假设",*[f"- {x}" for x in plan.get('assumptions',[])],"","## 路线开放状态",plan.get('access',{}).get('note','需按出发日核实当地开放状态。'),"","## 来源",*[f"- [{s['title']}]({s['url']})" for s in plan.get('sources',[])],"- [Open-Meteo 多模型预报](https://open-meteo.com/en/docs)"]
    (out/"行程与天气.md").write_text('\n'.join(lines),encoding="utf-8")
    return payload

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("catalog");p.add_argument('--province');p.add_argument('--theme')
    p=sub.add_parser("plan");p.add_argument('--route',required=True);p.add_argument('--start',required=True);p.add_argument('--end');p.add_argument('--variant',default='6d');p.add_argument('--direction',choices=['forward','reverse'],default='forward');p.add_argument('--requirements',default='');p.add_argument('--out',required=True)
    p=sub.add_parser("validate");p.add_argument('plan')
    p=sub.add_parser("build");p.add_argument('--plan',required=True);p.add_argument('--out',required=True);p.add_argument('--offline',action='store_true');p.add_argument('--cache-dir');p.add_argument('--gpx');p.add_argument('--gpx-day')
    p=sub.add_parser("serve");p.add_argument('--dir',required=True);p.add_argument('--port',type=int,default=4174)
    args=parser.parse_args()
    if args.command=='catalog':
        cat=read(ROOT/'assets/catalog.json');routes=[r for r in cat['routes'] if (not args.province or args.province==r['province']) and (not args.theme or args.theme in r['themes'])]
        print(json.dumps([{k:r[k] for k in ['id','name','province','themes']}|{'variants':list(r['variants'])} for r in routes],ensure_ascii=False,indent=2));return
    if args.command=='plan':
        plan=make_plan(args.route,args.start,args.variant,args.direction,args.requirements,args.end);errors=validate(plan)
        if errors:raise ValueError('; '.join(errors))
        write(args.out,plan);print(json.dumps({'plan':str(Path(args.out).resolve()),'days':len(plan['days']),'constraintIssues':check_constraints(plan)},ensure_ascii=False));return
    if args.command in ['validate','build']:
        plan=read(args.plan);errors=validate(plan)
        if errors:raise ValueError('; '.join(errors))
        if args.command=='validate':print(json.dumps({'valid':True,'constraintIssues':check_constraints(plan)},ensure_ascii=False));return
        cache=args.cache_dir or Path(args.out)/'cache';weather=fetch_weather(plan,cache,args.offline)
        payload=render(plan,weather,args.out,args.gpx,args.gpx_day)
        print(json.dumps({'html':str(Path(args.out).resolve()/'index.html'),'weatherStatus':weather['status'],'modelErrors':weather['errors'],'constraintIssues':payload['constraints']},ensure_ascii=False));return
    if args.command=='serve':
        from functools import partial
        server=http.server.ThreadingHTTPServer(('127.0.0.1',args.port),partial(http.server.SimpleHTTPRequestHandler,directory=str(Path(args.dir).resolve())))
        print(f"http://127.0.0.1:{args.port}/",flush=True);server.serve_forever()

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,FileNotFoundError) as e:print(str(e),file=sys.stderr);sys.exit(2)
