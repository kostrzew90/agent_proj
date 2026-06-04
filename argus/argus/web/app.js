const $ = (id) => document.getElementById(id);
let chart = null, series = null;

async function getJSON(url){ const r = await fetch(url); if(!r.ok) throw new Error(r.status); return r.json(); }

async function loadOverview(){
  const h = $('h').value;
  let assets = [], sources = [];
  try { assets = await getJSON(`/api/assets?horizon=${h}`); } catch(e){}
  try { sources = await getJSON(`/api/sources?horizon=${h}`); } catch(e){}

  $('assets').innerHTML = '<tr><th>Asset</th><th>Lean</th></tr>' + assets.map(a =>
    `<tr class="asset" data-sym="${a.asset}" data-kind="${a.kind}"><td>${a.asset} <span class="muted">${a.kind}</span></td>`+
    `<td class="${a.lean>=0?'bull':'bear'}">${a.lean}</td></tr>`).join('');

  $('sources').innerHTML = '<tr><th>Źródło</th><th>n</th><th>hit%</th><th>score</th></tr>' + sources.map(s =>
    `<tr><td>${s.display_name}</td><td>${s.n_claims}</td><td>${(s.hit_rate*100).toFixed(0)}</td><td>${s.decayed_score.toFixed(2)}</td></tr>`).join('');

  $('empty').textContent = sources.length === 0
    ? `Brak dojrzałych danych dla ${h} — potrzeba ~${h} od pierwszych claimów (1h dojrzewa najszybciej).`
    : '';

  document.querySelectorAll('tr.asset').forEach(tr =>
    tr.addEventListener('click', () => openDetail(tr.dataset.sym, tr.dataset.kind)));
}

async function openDetail(sym, kind){
  const h = $('h').value;
  $('detail').style.display = 'block';
  $('detailTitle').textContent = `${sym} — detal (${h})`;
  $('chartErr').textContent = '';
  $('chart').innerHTML = '';
  chart = LightweightCharts.createChart($('chart'), {
    layout:{background:{color:'#0f1115'},textColor:'#e6e6e6'},
    grid:{vertLines:{color:'#1c2128'},horzLines:{color:'#1c2128'}},
    timeScale:{timeVisible:true}
  });
  series = chart.addCandlestickSeries();

  let candles = [];
  try { candles = await getJSON(`/api/candles?asset=${sym}`); }
  catch(e){ $('chartErr').textContent = `Nie udało się pobrać świec dla ${sym}.`; }
  series.setData(candles);

  let detail = {claims:[], sources:[]};
  try { detail = await getJSON(`/api/asset/${sym}?horizon=${h}`); } catch(e){}

  const markers = detail.claims.map(c => {
    const t = Math.floor(new Date(c.entry_ts).getTime()/1000);
    const bull = c.direction === 'bull';
    const res = c.hit===true?' ✓':(c.hit===false?' ✗':'');
    return {time:t, position: bull?'belowBar':'aboveBar', color: bull?'#3fb950':'#f85149',
            shape: bull?'arrowUp':'arrowDown', text:`${c.source}${res}`};
  }).sort((a,b)=>a.time-b.time);
  series.setMarkers(markers);
  chart.timeScale().fitContent();

  $('detailSources').innerHTML = '<tr><th>Źródło</th><th>n</th><th>hit%</th><th>score</th></tr>' +
    detail.sources.map(s => `<tr><td>${s.display_name}</td><td>${s.n_claims}</td><td>${(s.hit_rate*100).toFixed(0)}</td><td>${s.decayed_score.toFixed(2)}</td></tr>`).join('');

  $('detailClaims').innerHTML = '<tr><th>Źródło</th><th>Dir</th><th>Conf</th><th>Kiedy</th><th>Wynik</th></tr>' +
    detail.claims.map(c => `<tr><td>${c.source}</td><td class="${c.direction==='bull'?'bull':'bear'}">${c.direction}</td><td>${c.confidence}</td><td>${c.entry_ts.slice(0,16)}</td><td>${c.hit===true?'✓':(c.hit===false?'✗':'—')}</td></tr>`).join('');
}

$('h').addEventListener('change', loadOverview);
$('closeDetail').addEventListener('click', ()=>{ $('detail').style.display='none'; });
loadOverview();
