async function load() {
  const h = document.getElementById('h').value;
  const assets = await (await fetch(`/api/assets?horizon=${h}`)).json();
  document.getElementById('assets').innerHTML =
    '<tr><th>Asset</th><th>Lean</th></tr>' + assets.map(a =>
      `<tr><td>${a.asset}</td><td class="${a.lean>=0?'bull':'bear'}">${a.lean}</td></tr>`).join('');
  const sources = await (await fetch(`/api/sources?horizon=${h}`)).json();
  document.getElementById('sources').innerHTML =
    '<tr><th>Źródło</th><th>n</th><th>hit%</th><th>score</th></tr>' + sources.map(s =>
      `<tr><td>${s.display_name}</td><td>${s.n_claims}</td><td>${(s.hit_rate*100).toFixed(0)}</td><td>${s.decayed_score.toFixed(2)}</td></tr>`).join('');
  const claims = await (await fetch('/api/claims?limit=30')).json();
  document.getElementById('claims').innerHTML =
    '<tr><th>Asset</th><th>Dir</th><th>Conf</th><th>Kiedy</th><th>Status</th></tr>' + claims.map(c =>
      `<tr><td>${c.asset}</td><td class="${c.direction==='bull'?'bull':'bear'}">${c.direction}</td><td>${c.confidence}</td><td>${c.entry_ts.slice(0,16)}</td><td>${c.status}</td></tr>`).join('');
}
document.getElementById('h').addEventListener('change', load);
load();
