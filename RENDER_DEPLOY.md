# Render Deploy

## What This Deploys

This deploys a small FastAPI server that exposes the generated scanner CSV to the iPhone app or a browser client.

Protected endpoints:

- `/api/status`
- `/api/results`
- `/api/top-movers`

Public endpoint:

- `/api/health`

## Render Settings

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn server:app --host 0.0.0.0 --port $PORT
```

Environment variables:

```text
MARKET_API_TOKEN=make-this-long-and-private
MARKET_RESULTS_FILE=market_scanner_results.csv
MARKET_RATE_LIMIT_PER_MINUTE=90
MARKET_RESULTS_CACHE_TTL=20
```

## Scheduled Updates

Render cron schedules use UTC. The repo includes `render_cron_runner.py` so the job can wake at both daylight-saving candidates and only run when the current Vancouver hour matches.

Configured in `render.yaml` as one cron service:

- `market-scanner-vancouver-schedule`
  - Wakes at UTC candidates for Vancouver 16:00 and 17:00.
  - Runs `python render_cron_runner.py --mode auto`.
  - Vancouver 16:00: quick scanner refresh and upload to the mobile API.
  - Vancouver 17:00: second mobile refresh and upload to the mobile API.

The job skips Friday and Saturday in Vancouver time.

Required cron environment variables:

```text
MARKET_API_TOKEN=your-existing-api-token
MARKET_SCANNER_REMOTE_UPLOAD_URL=https://market-scanner-api-fo2m.onrender.com/api/results/upload
MARKET_RESULTS_FILE=market_scanner_results.csv
```

Important:

- Pushing `render.yaml` does not always create a new Cron Job by itself.
- In Render, open **Blueprints** and sync this repo, or create a Cron Job manually with:
  - Name: `market-scanner-vancouver-schedule`
  - Runtime: Python
  - Build Command: `pip install -r requirements.txt`
  - Command: `python render_cron_runner.py --mode auto`
  - Schedule: `0 23,0,1 * * *`
- If the Cron Job log says `missing MARKET_API_TOKEN`, add the same API token used by the web service to the Cron Job's Environment Variables.
- A successful run should print `remote upload ok` in the logs. Without that line, the iPhone app will keep showing the previous CSV.
- Render cron currently runs the mobile-safe refresh path only: `market_scanner_update` + `mobile_intelligence_feed` + final CSV upload. Do not point Render at local-only scripts unless those files are committed and secrets are moved to environment variables.

## Test

```bash
curl https://YOUR-RENDER-APP.onrender.com/api/health
curl -H "X-Market-Token: YOUR_TOKEN" https://YOUR-RENDER-APP.onrender.com/api/status
curl -H "X-Market-Token: YOUR_TOKEN" https://YOUR-RENDER-APP.onrender.com/api/results
curl -H "X-Market-Token: YOUR_TOKEN" https://YOUR-RENDER-APP.onrender.com/api/top-movers
```

## Security Notes

- Do not commit real tokens.
- Put `MARKET_API_TOKEN` only in Render Environment Variables.
- Keep scanner/bot Telegram tokens out of Render unless this server actually needs them.
- This server is read-only. It does not modify local files or run trades.
