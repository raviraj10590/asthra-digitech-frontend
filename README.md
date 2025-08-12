# Asthra DigiTech - Dashboard App (Demo)

This is a simple demo dashboard app that includes:
- Node.js + Express backend
- Static frontend (HTML/JS) using Chart.js
- Sample JSON datasets and API endpoints

## Features
- /api/summary - returns basic KPIs (reach, engagement, campaigns, leads)
- /api/engagement-trend - time series of engagement
- /api/top-posts - top posts by engagement
- /api/competitors - competitor metrics
- /api/events - upcoming events
- Frontend at / shows a simple dashboard UI using the above endpoints

## Run locally
1. Install dependencies:
   ```
   npm install
   ```
2. Start the server:
   ```
   npm start
   ```
3. Open http://localhost:3000 in your browser.

## Deploy to Railway
1. Create a new project on Railway and connect a GitHub repo containing this project.
2. Set the `PORT` environment variable if needed (Railway provides one automatically).
3. Add other environment variables for real API keys.
4. Deploy and open the assigned Railway URL.

## Next steps for production
- Replace sample JSON data with real integrations (Facebook Graph API, YouTube Data API, Google Ads API).
- Add authentication (JWT/NextAuth).
- Move static frontend to React/Next.js for better UI and modularity.
- Add database (Postgres) for storing historical metrics, users, and settings.