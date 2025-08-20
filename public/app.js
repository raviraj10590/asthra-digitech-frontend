const API_BASE = "https://asthra-digitech-backend-production.up.railway.app";

/* ------------------- HELPERS ------------------- */
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (el) el.textContent = msg;
}

/* ------------------- SUMMARY ------------------- */
setText('reach', 'Loading...');
setText('engagement', 'Loading...');
setText('campaigns', 'Loading...');
setText('leads', 'Loading...');

fetch(`${API_BASE}/api/summary`)
  .then(res => res.json())
  .then(data => {
    setText('reach', data.reach);
    setText('engagement', data.engagement);
    setText('campaigns', data.campaigns);
    setText('leads', data.leads);
  })
  .catch(err => {
    console.error(err);
    showError('reach', 'Error');
    showError('engagement', 'Error');
    showError('campaigns', 'Error');
    showError('leads', 'Error');
  });

/* ------------------- TOP POSTS ------------------- */
const topPostsContainer = document.getElementById('top-posts');
if (topPostsContainer) topPostsContainer.textContent = 'Loading...';

fetch(`${API_BASE}/api/top-posts`)
  .then(res => res.json())
  .then(posts => {
    if (!topPostsContainer) return;
    topPostsContainer.innerHTML = '';
    posts.forEach(post => {
      const li = document.createElement('li');
      li.textContent = `${post.date} | ${post.platform} | ${post.post_type.toUpperCase()} | Engagement: ${post.engagement}`;
      topPostsContainer.appendChild(li);
    });
  })
  .catch(err => {
    console.error(err);
    if (topPostsContainer) topPostsContainer.textContent = 'Failed to load posts.';
  });

/* ------------------- ENGAGEMENT TREND CHART ------------------- */
const chartCanvas = document.getElementById('engagementChart');
if (chartCanvas) {
  const ctx = chartCanvas.getContext('2d');
  chartCanvas.parentNode.insertAdjacentHTML('beforeend', '<p id="chart-loading">Loading chart...</p>');
}

fetch(`${API_BASE}/api/engagement-trend`)
  .then(res => res.json())
  .then(trend => {
    if (!chartCanvas) return;
    document.getElementById('chart-loading')?.remove();
    new Chart(chartCanvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: trend.map(t => t.date),
        datasets: [{
          label: 'Engagement',
          data: trend.map(t => t.engagement),
          borderColor: 'blue',
          fill: false
        }]
      },
      options: { responsive: true }
    });
  })
  .catch(err => {
    console.error(err);
    document.getElementById('chart-loading')?.remove();
    if (chartCanvas) chartCanvas.insertAdjacentText('afterend', 'Failed to load chart.');
  });

/* ------------------- COMPETITORS ------------------- */
const competitorsTable = document.getElementById('competitors');
if (competitorsTable) competitorsTable.innerHTML = '<tr><td colspan="2">Loading...</td></tr>';

fetch(`${API_BASE}/api/competitors`)
  .then(res => res.json())
  .then(competitors => {
    if (!competitorsTable) return;
    competitorsTable.innerHTML = '';
    competitors.forEach(c => {
      const row = document.createElement('tr');
      row.innerHTML = `<td>${c.name}</td><td>${c.engagement || 0}</td>`;
      competitorsTable.appendChild(row);
    });
  })
  .catch(err => {
    console.error(err);
    if (competitorsTable) competitorsTable.innerHTML = '<tr><td colspan="2">Failed to load competitors.</td></tr>';
  });

/* ------------------- EVENTS ------------------- */
const eventsList = document.getElementById('events');
if (eventsList) eventsList.textContent = 'Loading...';

fetch(`${API_BASE}/api/events`)
  .then(res => res.json())
  .then(events => {
    if (!eventsList) return;
    eventsList.innerHTML = '';
    events.forEach(e => {
      const li = document.createElement('li');
      li.textContent = `${e.date} | ${e.name} | ${e.location || ''}`;
      eventsList.appendChild(li);
    });
  })
  .catch(err => {
    console.error(err);
    if (eventsList) eventsList.textContent = 'Failed to load events.';
  });

function fetchMetrics() {
  fetch("/api/metrics")
    .then(res => res.json())
    .then(data => {
      document.getElementById("totalReach").innerText = data.totalReach;
      document.getElementById("engagement").innerText = data.engagement;
      document.getElementById("campaigns").innerText = data.campaignsRunning;
      document.getElementById("conversions").innerText = data.leadConversions;

      // Last updated
      const now = new Date().toLocaleTimeString();
      document.querySelectorAll(".last-updated").forEach(el => el.innerText = now);

      // Top Posts
      const posts = document.getElementById("topPosts");
      posts.innerHTML = "";
      data.topPosts.forEach(p => {
        posts.innerHTML += `<tr><td>${p.id}</td><td>${p.platform}</td><td>${p.engagement}</td></tr>`;
      });

      // Events
      const events = document.getElementById("upcomingEvents");
      events.innerHTML = "";
      data.upcomingEvents.forEach(e => {
        events.innerHTML += `<tr><td>${e.date}</td><td>${e.event}</td><td>${e.location}</td></tr>`;
      });
    });
}

// Auto refresh every 3s
setInterval(fetchMetrics, 3000);
fetchMetrics();
