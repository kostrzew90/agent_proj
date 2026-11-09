const $ = (id) => document.getElementById(id);
let chart = null, series = null;

async function getJSON(url){ const r = await fetch(url); if(!r.ok) throw new Error(r.status); return r.json(); }

const pctOrDash = v => (v==null) ? '—' : (v*100).toFixed(0);
const excessOrDash = v => (v==null) ? '—' : (v>=0?'+':'') + (v*100).toFixed(1);

function sourcesRows(sources){
  return sources.map(s => `<tr><td>${s.display_name}</td><td>${s.n_claims}</td><td>${(s.hit_rate*100).toFixed(0)}</td>`+
    `<td>${pctOrDash(s.cohort_rate)}</td><td>${excessOrDash(s.excess)}</td><td>${s.decayed_score.toFixed(2)}</td></tr>`).join('');
}

async function loadOverview(){
  const h = $('h').value;
  const dir = $('dir').value;
  let assets = [], sources = [];
  try { assets = await getJSON(`/api/assets?horizon=${h}`); } catch(e){}
  try { sources = await getJSON(`/api/sources?horizon=${h}&direction=${dir}`); } catch(e){}

  $('assets').innerHTML = '<tr><th>Asset</th><th>Lean</th></tr>' + assets.map(a =>
    `<tr class="asset" data-sym="${a.asset}" data-kind="${a.kind}"><td>${a.asset} <span class="muted">${a.kind}</span></td>`+
    `<td class="${a.lean>=0?'bull':'bear'}">${a.lean}</td></tr>`).join('');

  $('sources').innerHTML = '<tr><th>Źródło</th><th>n</th><th>hit%</th><th>kohorta</th><th>nadwyżka</th><th>score</th></tr>' + sourcesRows(sources);

  $('empty').textContent = sources.length === 0
    ? `Brak dojrzałych danych dla ${h} — potrzeba ~${h} od pierwszych claimów (1h dojrzewa najszybciej).`
    : '';

  document.querySelectorAll('tr.asset').forEach(tr =>
    tr.addEventListener('click', () => openDetail(tr.dataset.sym, tr.dataset.kind)));
  loadWallets();
  loadLiquidations();
  loadLlmUsage();
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

  $('detailSources').innerHTML = '<tr><th>Źródło</th><th>n</th><th>hit%</th><th>kohorta</th><th>nadwyżka</th><th>score</th></tr>' +
    sourcesRows(detail.sources);

  $('detailClaims').innerHTML = '<tr><th>Źródło</th><th>Dir</th><th>Conf</th><th>Kiedy</th><th>Wynik</th></tr>' +
    detail.claims.map(c => `<tr><td>${c.source}</td><td class="${c.direction==='bull'?'bull':'bear'}">${c.direction}</td><td>${c.confidence}</td><td>${c.entry_ts.slice(0,16)}</td><td>${c.hit===true?'✓':(c.hit===false?'✗':'—')}</td></tr>`).join('');
}

async function loadWallets(){
  let rows = [];
  try { rows = await getJSON('/api/wallets'); } catch(e){}
  const pct = v => v==null ? '—' : (v*100).toFixed(0)+'%';
  $('wallets').innerHTML = '<tr><th>Portfel</th><th>Acc 24h</th><th>Acc 7d</th><th>Acc 30d</th><th>Pozycje</th><th></th></tr>' +
    rows.map(w => `<tr><td title="${w.handle}">${w.display_name}${w.active?'':' (off)'}</td>`+
      `<td>${pct(w.acc_24h)}</td><td>${pct(w.acc_7d)}</td><td>${pct(w.acc_30d)}</td>`+
      `<td>${w.active_positions}</td>`+
      `<td><button data-wid="${w.id}" class="deact">deactivate</button></td></tr>`).join('');
  document.querySelectorAll('button.deact').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/wallets/${b.dataset.wid}/deactivate`, {method:'POST'}); loadWallets();
  }));
}

async function previewWallet(){
  const addr = $('wAddr').value.trim();
  $('wPreviewOut').textContent = 'Ładowanie...';
  try {
    const d = await getJSON(`/api/wallets/preview?address=${addr}`);
    $('wPreviewOut').innerHTML = (`equity $${d.equity.toFixed(0)} — ` +
      d.positions.map(p => `${p.side==='long'?'LONG':'SHORT'} ${p.coin}`).join(', ')) || 'brak pozycji';
    $('wSave').style.display = 'inline';
  } catch(e){ $('wPreviewOut').textContent = 'Błędny adres lub brak danych.'; $('wSave').style.display='none'; }
}

async function saveWallet(){
  const addr = $('wAddr').value.trim(), label = $('wLabel').value.trim();
  const r = await fetch('/api/wallets', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({address:addr, label})});
  if(r.ok){ $('wAddr').value=''; $('wLabel').value=''; $('wPreviewOut').textContent='Dodano.';
    $('wSave').style.display='none'; loadWallets(); }
  else { $('wPreviewOut').textContent = 'Nie zapisano (zły adres?).'; }
}

async function loadLiquidations(){
  const w = document.getElementById('liqWin').value;
  let rows = [];
  try { rows = await getJSON(`/api/liquidations?window=${w}`); } catch(e){}
  const usd = v => '$' + Math.round(v).toLocaleString();
  document.getElementById('liquidations').innerHTML =
    '<tr><th>Asset</th><th>Long liq</th><th>Short liq</th><th>#</th></tr>' + rows.map(r =>
      `<tr><td>${r.asset}</td>`+
      `<td class="bear" title="${usd(r.long_liq_usd)}">${usd(r.long_liq_usd)}</td>`+
      `<td class="bull" title="${usd(r.short_liq_usd)}">${usd(r.short_liq_usd)}</td>`+
      `<td>${r.count}</td></tr>`).join('');
}

async function loadLlmUsage(){
  const w = document.getElementById('llmWin').value;
  let rows = [];
  try { rows = await getJSON(`/api/llm/usage?window=${w}`); } catch(e){}
  document.getElementById('llmusage').innerHTML =
    '<tr><th>Provider</th><th>Model</th><th>Calls</th><th>OK%</th><th>Tok in</th><th>Tok out</th><th>Cost $</th><th>ms</th></tr>' +
    rows.map(r => `<tr><td>${r.provider}</td><td>${r.model}</td><td>${r.calls}</td>`+
      `<td>${r.calls?Math.round(100*r.ok/r.calls):0}</td><td>${r.tokens_in}</td><td>${r.tokens_out}</td>`+
      `<td>${r.cost_usd.toFixed(4)}</td><td>${r.avg_latency_ms}</td></tr>`).join('');
}

$('h').addEventListener('change', loadOverview);
$('dir').addEventListener('change', loadOverview);
$('closeDetail').addEventListener('click', ()=>{ $('detail').style.display='none'; });
$('wPreview').addEventListener('click', previewWallet);
$('wSave').addEventListener('click', saveWallet);
document.getElementById('liqWin').addEventListener('change', loadLiquidations);
document.getElementById('llmWin').addEventListener('change', loadLlmUsage);
loadOverview();
