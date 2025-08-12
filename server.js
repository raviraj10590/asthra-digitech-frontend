const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Load sample data from data folder
function loadJSON(fname) {
  const p = path.join(__dirname, 'data', fname);
  if (fs.existsSync(p)) {
    return JSON.parse(fs.readFileSync(p));
  }
  return [];
}

const fb_ig = loadJSON('facebook_instagram_sample.json');
const youtube = loadJSON('youtube_sample.json');
const google_ads = loadJSON('google_ads_sample.json');
const whatsapp = loadJSON('whatsapp_sample.json');
const competitor = loadJSON('competitor_sample.json');
const events = loadJSON('events_sample.json');

function sum(arr, key) {
  return arr.reduce((s, r) => s + (r[key] || 0), 0);
}

// Simple KPI endpoint
app.get('/api/summary', (req, res) => {
  const reach = sum(fb_ig, 'reach') + sum(youtube, 'views') + sum(google_ads, 'impressions');
  const engagement = sum(fb_ig, 'engagement') + sum(youtube, 'likes');
  const campaigns = google_ads.length;
  const leads = sum(google_ads, 'conversions');
  res.json({
    reach,
    engagement,
    campaigns,
    leads
  });
});

// Endpoint for time series (mock)
app.get('/api/engagement-trend', (req, res) => {
  // create simple daily trend from fb_ig dates
  const map = {};
  fb_ig.forEach(r => {
    map[r.date] = (map[r.date] || 0) + (r.engagement || 0);
  });
  youtube.forEach(r => {
    map[r.date] = (map[r.date] || 0) + (r.likes || 0);
  });
  const arr = Object.keys(map).sort().map(d => ({ date: d, engagement: map[d] }));
  res.json(arr);
});

app.get('/api/top-posts', (req, res) => {
  // return top 5 posts by engagement from fb_ig
  const top = fb_ig.concat().sort((a,b) => (b.engagement||0)-(a.engagement||0)).slice(0,5);
  res.json(top);
});

app.get('/api/competitors', (req, res) => {
  res.json(competitor);
});

app.get('/api/events', (req, res) => {
  res.json(events);
});

// Fallback to index.html
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log('Server running on port', PORT);
});