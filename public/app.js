async function fetchJSON(url) {
  const res = await fetch(url);
  return res.json();
}

async function init() {
  const sum = await fetchJSON('/api/summary');
  document.getElementById('kpi-reach').innerText = sum.reach.toLocaleString();
  document.getElementById('kpi-engagement').innerText = sum.engagement.toLocaleString();
  document.getElementById('kpi-campaigns').innerText = sum.campaigns;
  document.getElementById('kpi-leads').innerText = sum.leads;

  const trend = await fetchJSON('/api/engagement-trend');
  const labels = trend.map(r=>r.date);
  const data = trend.map(r=>r.engagement);
  const ctx = document.getElementById('chartTrend').getContext('2d');
  new Chart(ctx, { type:'line', data:{ labels, datasets:[{ label:'Engagement', data, fill:true, tension:0.3 }] }, options:{ responsive:true }});

  const top = await fetchJSON('/api/top-posts');
  const tbody = document.querySelector('#topPostsTable tbody');
  top.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${r.post_id || r.video_id || ''}</td><td>${r.platform || 'YouTube'}</td><td>${r.engagement || r.likes || 0}</td>`;
    tbody.appendChild(tr);
  });

  const comp = await fetchJSON('/api/competitors');
  const compLabels = comp.map(c=>c.competitor);
  const compData = comp.map(c=>c.reach);
  const ctx2 = document.getElementById('chartCompetitor').getContext('2d');
  new Chart(ctx2, { type:'bar', data:{ labels:compLabels, datasets:[{ label:'Reach', data:compData }] }, options:{ responsive:true }});

  const events = await fetchJSON('/api/events');
  const etbody = document.querySelector('#eventsTable tbody');
  events.forEach(e=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${e.event_date}</td><td>${e.event_name}</td><td>${e.location}</td>`;
    etbody.appendChild(tr);
  });
}

init();