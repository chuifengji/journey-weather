const assert=require('node:assert/strict');
const codes=require('../assets/weather-codes.json');
const W=require('../assets/weather-meaning.js')(codes);

// Preserve genuine zero code/amount, but never turn missing or unknown into clear weather.
assert.equal(W.describe(0).label,'晴');
for(const code of [null,undefined,999,61.5,'61',false]) assert.equal(W.describe(code),null);
assert.equal(W.condition({code:null,precipitation:0}).label,'天气类型待确认');
assert.equal(W.condition({code:null,precipitation:null}).label,'暂无预报');
assert.equal(W.condition({precipitation:10}).label,'降水类型待确认');
assert.equal(W.condition({snowfall:0.1,precipitation:1}).label,'有降雪信号');

// A preceding-hour amount does not override the indicated-time categorical forecast.
assert.equal(W.condition({code:0,precipitation:3}).label,'晴');
assert.equal(W.condition({code:51,precipitation:0.4}).label,'弱毛毛雨');
assert.equal(W.condition({code:80,precipitation:0.4}).label,'弱阵雨');
assert.equal(W.condition({code:71,precipitation:0.4}).label,'小雪');
assert.equal(W.summarize([{code:61},{code:71}]).label,'小雨 / 小雪');
assert.equal(W.summarize([{code:51},{code:51},{code:null}]).count,2);
assert.equal(W.summarize([{code:0},{code:51},{code:71}]).disagreement,true);
assert.equal(W.summarize([{precipitation:0},{precipitation:2}]).label,'降水类型待确认');
assert.equal(W.amount(0.05),'0.05');
assert.equal(W.amount(0.125),'0.125');
assert.equal(W.amount(null),'—');
assert.equal(W.amount(0),'0.0');
assert.notEqual(W.amount(0.0001),'0.0');

assert.deepEqual(W.interval('2026-09-26',19),{startDate:'2026-09-26',endDate:'2026-09-26',start:'18:00',end:'19:00',short:'18:00—19:00'});
assert.deepEqual(W.interval('2026-01-01',0),{startDate:'2025-12-31',endDate:'2026-01-01',start:'23:00',end:'00:00',short:'前日 23:00—00:00'});
console.log('Weather interpretation checks passed (missing values, rain/snow disagreement, amounts and midnight intervals).');
