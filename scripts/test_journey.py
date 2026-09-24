#!/usr/bin/env python3
"""Behavior checks for place/time matching, cache isolation and route evidence."""
import copy, json, tempfile, unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import journey as j

class JourneyTests(unittest.TestCase):
    def setUp(self):self.plan=j.make_plan('gongga-small-loop-lenggacuo','2026-09-30')
    def raw(self):
        return {'hourly':{'time':['2026-09-30T07:00','2026-09-30T08:00'],**{k:[None,0] for k in j.VARIABLES}},'latitude':29.8,'longitude':101.8,'elevation':3900,'utc_offset_seconds':28800}
    def test_all_variants_contiguous_and_valid(self):
        for route in j.read(j.ROOT/'assets/catalog.json')['routes']:
            for variant in route['variants']:
                duration,direction=variant.split('-');p=j.make_plan(route['id'],'2026-09-30',duration,direction)
                self.assertEqual(j.validate(p),[],variant)
                self.assertEqual(p['days'][-1]['lodgingType'],'none',variant)
    def test_unknown_duration_not_invented(self):
        with self.assertRaises(ValueError):j.make_plan(self.plan['routeId'],'2026-09-30',end='2026-10-10')
    def test_requirements_are_conflicts_not_silent_changes(self):
        p=j.make_plan(self.plan['routeId'],'2026-09-30',requirements='不露营，每天徒步不超过 5 小时')
        self.assertFalse(p['constraints']['allowCamping']);self.assertEqual(p['constraints']['maxHikeHours'],5)
        self.assertGreaterEqual(len(j.check_constraints(p)),4)
    def test_validation_rejects_overlap_coordinates_and_date_gap(self):
        p=copy.deepcopy(self.plan);p['places']['kangding']['lat']=None;p['days'][0]['stops'][1]['arrival']='08:00';p['days'][1]['date']='2026-10-03'
        errors=j.validate(p);self.assertTrue(any('纬度' in x for x in errors));self.assertTrue(any('重叠' in x for x in errors));self.assertTrue(any('连续' in x for x in errors))
    def test_bad_input_shapes_return_errors(self):
        self.assertTrue(j.validate([]));p=copy.deepcopy(self.plan);p['days']='invalid';self.assertTrue(j.validate(p));p=copy.deepcopy(self.plan);p['days'][0]['stops'][0]['arrival']=None;self.assertTrue(j.validate(p))
    def test_null_not_zero_and_no_extrapolation(self):
        r=self.raw();points=j.normalize_model(r,['a'],'gfs_seamless');p=points['a'];self.assertIsNone(p['hourly']['temperature_2m'][0]);self.assertEqual(p['hourly']['temperature_2m'][1],0);self.assertEqual(p['availableFrom'],'2026-09-30T08:00')
        w={'points':{'a':{'models':{'gfs_seamless':p}}}};self.assertIsNone(j.value(w,'a','gfs_seamless','temperature_2m','2026-09-30',7));self.assertEqual(j.value(w,'a','gfs_seamless','temperature_2m','2026-09-30',8),0);self.assertIsNone(j.value(w,'a','gfs_seamless','temperature_2m','2026-10-10',8));self.assertIsNone(j.value(w,'other','gfs_seamless','temperature_2m','2026-09-30',8))
    def test_partial_response_not_accepted_as_complete(self):
        r=self.raw();r['hourly']['precipitation']=[1]
        with self.assertRaises(ValueError):j.normalize_model(r,['a'],'gfs_seamless')
        with self.assertRaises(ValueError):j.normalize_model(self.raw(),['a','b'],'gfs_seamless')
    def test_weather_code_is_optional_categorical_and_zero_is_clear(self):
        raw=self.raw();del raw['hourly']['weather_code']
        p=j.normalize_model(raw,['a'],'gfs_seamless')['a'];self.assertEqual(p['hourly']['weather_code'],[None,None]);self.assertEqual(p['hourly']['precipitation'],[None,0])
        raw['hourly']['weather_code_gfs_seamless']=[0,71]
        self.assertEqual(j.normalize_model(raw,['a'],'gfs_seamless')['a']['hourly']['weather_code'],[0,71])
        raw['hourly']['weather_code']=[999,61.5]
        self.assertEqual(j.normalize_model(raw,['a'],'gfs_seamless')['a']['hourly']['weather_code'],[None,None])
        raw['hourly']['weather_code']=[51]
        with self.assertRaises(ValueError):j.normalize_model(raw,['a'],'gfs_seamless')
    def test_cache_isolated_by_coordinate_elevation_and_timezone(self):
        a=j.forecast_key(self.plan)
        for change in ['coordinate','elevation','timezone']:
            p=copy.deepcopy(self.plan)
            if change=='coordinate':p['places']['gexi']['lon']+=.01
            elif change=='elevation':p['places']['gexi']['elevation']=3800
            else:p['timezone']='UTC'
            self.assertNotEqual(j.forecast_key(p),a)
        self.assertEqual(j.coordinate_key({'lat':1,'lon':2,'elevation':5000.0}),'1.000000,2.000000,5000')
    def test_unmatched_offline_cache_stays_empty(self):
        with tempfile.TemporaryDirectory() as t:
            w=j.fetch_weather(self.plan,t,True);self.assertEqual(w['status'],'unavailable');self.assertEqual(len(w['errors']),3);self.assertTrue(all(not p['models'] for p in w['points'].values()))
    def test_arrival_minute_keeps_sampled_hour(self):
        s=j.summarize(self.plan,{'points':{}})[1]['samples'][0];self.assertEqual(s['time'],'07:30');self.assertEqual(s['sampledAt'],'2026-10-01T07:00');self.assertIsNone(s['temperatureMedian'])
    def test_unresolved_stop_keeps_gap_and_never_requests_fake_coordinate(self):
        p=copy.deepcopy(self.plan);pid='laoyulin';p['places'][pid].update(lon=None,lat=None,coordinateStatus='unresolved',coordinateNote='同名地点待核对')
        self.assertEqual(j.validate(p),[])
        self.assertFalse(any(f['properties']['dayId']=='day-1' for f in j.build_geometry(p)['features']))
        requests=[]
        def fake_curl(args,**kwargs):
            qs=parse_qs(urlparse(args[-1]).query);lats=qs['latitude'][0].split(',');requests.append(qs)
            self.assertNotIn('None',lats);self.assertEqual(len(lats),len(p['places'])-1)
            return SimpleNamespace(returncode=0,stdout=json.dumps([self.raw() for _ in lats]))
        with tempfile.TemporaryDirectory() as t,patch.object(j.subprocess,'run',side_effect=fake_curl):
            w=j.fetch_weather(p,t);self.assertEqual(w['points'][pid]['models'],{});self.assertEqual(len(requests),3)
        p['places'][pid]['lon']=100;self.assertTrue(j.validate(p))
    def test_custom_path_evidence_and_endpoint_checks(self):
        p=copy.deepcopy(self.plan);p['pathGeometry']=j.build_geometry(p)
        p['pathGeometry']['features']=[f for f in p['pathGeometry']['features'] if f['properties']['verified']]
        self.assertEqual(j.validate(p),[])
        f=p['pathGeometry']['features'][0];f['geometry']['coordinates'][0]=[999,29];self.assertTrue(j.validate(p))
    def test_overnight_crosses_midnight_and_requires_full_coverage(self):
        p=copy.deepcopy(self.plan);pid=p['days'][0]['stops'][-1]['placeId'];date=p['days'][0]['date'];next_date=p['days'][1]['date']
        times=[f'{date}T{h:02d}:00' for h in range(18,24)]+[f'{next_date}T{h:02d}:00' for h in range(9)]
        point={'time':times,'hourly':{'temperature_2m':[3]*14+[-2],'wind_gusts_10m':[4]*15,'precipitation':[50]+[1]*14,'snowfall':[0]*15}}
        w={'points':{pid:{'models':{'gfs_seamless':point}}}}
        row=j.overnight_summaries(p,w)[0]['models']['gfs_seamless'];self.assertEqual(row['temperatureMin'],-2);self.assertEqual(row['precipitationSum'],14)
        point['hourly']['temperature_2m'][-1]=None;self.assertIsNone(j.overnight_summaries(p,w)[0]['models']['gfs_seamless']['temperatureMin'])
    def test_route_falls_back_when_source_endpoint_moves(self):
        before=j.build_geometry(self.plan)['features'];self.assertTrue(any(f['properties']['verified'] for f in before));p=copy.deepcopy(self.plan);p['places']['gexi']['lon']+=.1
        f=next(f for f in j.build_geometry(p)['features'] if f['properties']['from']=='gexi' and f['properties']['to']=='liangcha');self.assertFalse(f['properties']['verified']);self.assertEqual(len(f['geometry']['coordinates']),2)
    def test_gpx_segments_stay_separate(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'test.gpx';path.write_text('<gpx><trk><trkseg><trkpt lon="101" lat="29"/><trkpt lon="101.1" lat="29.1"/></trkseg><trkseg><trkpt lon="102" lat="30"/><trkpt lon="102.1" lat="30.1"/></trkseg></trk></gpx>')
            result=j.import_gpx(path,'day-1');self.assertEqual(len(result),2);self.assertEqual(len(result[0]['geometry']['coordinates']),2)
    def test_offline_render_is_portable_and_escapes_embedded_json(self):
        with tempfile.TemporaryDirectory() as t:
            p=copy.deepcopy(self.plan);p['title']='Test </script><script>alert(1)</script>';w=j.fetch_weather(p,Path(t)/'cache',True);j.render(p,w,t);s=(Path(t)/'index.html').read_text()
            self.assertIn('\\u003c/script',s);self.assertNotIn('__APP_JS__',s);self.assertIn('id="journey-data"',s);self.assertTrue((Path(t)/'行程与天气.md').exists())

if __name__=='__main__':unittest.main(verbosity=2)
