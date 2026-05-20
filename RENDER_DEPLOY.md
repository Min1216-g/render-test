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
