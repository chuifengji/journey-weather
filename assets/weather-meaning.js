/* Weather categories are supplied by the API, never inferred from hourly totals. */
(function(root) {
  'use strict';
  function createWeatherMeaning(codes) {
    const valid = Number.isFinite;
    const describe = code => Number.isInteger(code) && Object.hasOwn(codes, code) ? codes[code] : null;
    const amount = value => valid(value) ? (value > 0 && value < 0.001 ? '<0.001' : value.toFixed(3).replace(/0{1,2}$/, '')) : '—';
    function condition(row) {
      const known = describe(row.code);
      if (known) return known;
      if (valid(row.snowfall) && row.snowfall > 0) return {label:'有降雪信号', icon:'cloud-snow'};
      if (valid(row.precipitation) && row.precipitation > 0) return {label:'降水类型待确认', icon:'cloud'};
      return {label: valid(row.temperature) || valid(row.precipitation) ? '天气类型待确认' : '暂无预报', icon:'cloud-off'};
    }
    function summarize(rows) {
      const known = rows.map(r => describe(r.code)).filter(Boolean);
      const labels = [...new Set(known.map(r => r.label))];
      if (labels.length === 1) return {...known[0], count:known.length, disagreement:false};
      if (labels.length > 1) return {label:labels.length === 2 ? labels.join(' / ') : '天气类型有分歧', icon:'cloud', count:known.length, disagreement:true};
      const snow = rows.find(r => valid(r.snowfall) && r.snowfall > 0);
      const rain = rows.find(r => valid(r.precipitation) && r.precipitation > 0);
      const row = snow || rain || rows.find(r => valid(r.temperature) || valid(r.precipitation)) || {};
      return {...condition(row), count:0, disagreement:false};
    }
    function interval(date, hour) {
      const pad = h => String(h).padStart(2, '0') + ':00';
      const previous = new Date(date + 'T12:00:00Z');
      previous.setUTCDate(previous.getUTCDate() - 1);
      const startDate = hour === 0 ? previous.toISOString().slice(0, 10) : date;
      return {startDate, endDate:date, start:pad((hour + 23) % 24), end:pad(hour), short:(hour === 0 ? '前日 ' : '') + pad((hour + 23) % 24) + '—' + pad(hour)};
    }
    return {describe, condition, summarize, amount, interval};
  }
  if (typeof module === 'object' && module.exports) module.exports = createWeatherMeaning;
  else root.createWeatherMeaning = createWeatherMeaning;
})(typeof globalThis === 'object' ? globalThis : this);
