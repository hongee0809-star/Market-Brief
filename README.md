# Daily Market Sentiment Brief

A small automated tool that, once a day:

1. Pulls recent price data and news headlines for a watchlist of stocks (via `yfinance`).
2. Scores each headline as bullish/bearish/neutral using an AI model hosted on **GitHub Models**.
3. Combines that with the day's price move into a simple, transparent signal.
4. Emails you the summary.

**What this is not:** it does not connect to a broker, place trades, or manage
money. It's a research/monitoring aid — read the output and make your own
decisions. Headline sentiment is a noisy signal on its own; treat it as one
input, not a recommendation.

## Files

- `main.py` — orchestrates everything (fetch → score → signal → report → email)
- `sentiment.py` — calls the GitHub Models API for headline sentiment
- `notify.py` — sends the report by email (plain SMTP)
- `watchlist.txt` — your list of tickers, one per line
- `.github/workflows/daily-brief.yml` — runs it automatically every weekday morning

## Setup

### 1. Push this to a GitHub repo

Create a new repo and push these files as-is (the `.github/workflows/` folder
is what makes GitHub Actions pick it up automatically).

### 2. Edit your watchlist

Open `watchlist.txt` and put in whichever tickers you want to track, one per line.

### 3. Add repository secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add these:

| Secret | What it is |
|---|---|
| `SMTP_HOST` | Your email provider's SMTP server, e.g. `smtp.gmail.com` |
| `SMTP_PORT` | Usually `587` |
| `SMTP_USER` | The email address you're sending *from* |
| `SMTP_PASS` | An **app password** for that account (not your normal login password — Gmail, Outlook, etc. all let you generate one for this) |
| `EMAIL_TO` | The address you want the brief sent *to* |
| `EMAIL_FROM` | (optional) defaults to `SMTP_USER` if not set |

You do **not** need to add a secret for GitHub Models — the workflow's
built-in `GITHUB_TOKEN` handles that automatically, since the workflow
already requests `models: read` permission.

### 4. Run it

- It runs automatically at 07:00 UTC on weekdays (edit the `cron` line in
  `daily-brief.yml` to change the time — cron schedules are always in UTC).
- To test it immediately: go to the **Actions** tab in your repo → **Daily
  Market Sentiment Brief** → **Run workflow**.
- Every run's output is also printed to the Actions log, so you can check
  results there even before email delivery is working.

## Running it locally (optional, for testing)

```bash
pip install -r requirements.txt

export MODELS_TOKEN=<a GitHub personal access token with model access>
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=you@gmail.com
export SMTP_PASS=<app password>
export EMAIL_TO=you@gmail.com

python main.py
```

If you skip the `SMTP_*`/`EMAIL_TO` variables, it just prints the report
instead of emailing it — useful for a first test run.

## Extending it

- **More tickers / different assets**: just add lines to `watchlist.txt`.
- **Different AI model**: set `SENTIMENT_MODEL` (e.g. `meta/llama-3.1-70b-instruct`)
  — see the [GitHub Models catalog](https://github.com/marketplace/models) for options.
- **Better news source**: `yfinance`'s built-in news is limited; swapping in a
  dedicated news API would give richer headlines.
- **Actual trade execution**: deliberately not included here. If you ever want
  to go from "signal" to "action," that means integrating a broker API (e.g.
  Alpaca, Interactive Brokers) with its own credentials and risk controls —
  a much bigger and higher-stakes step than this tool takes.
