"""
Daily market sentiment brief.

Pulls recent price action and news headlines for a watchlist of tickers,
scores headline sentiment using a GitHub Models-hosted LLM, combines that
with the day's price move into a simple transparent signal, and emails
a summary.

This is a research / monitoring tool. It does not place trades, connect
to a broker, or give investment advice — it just flags things for you
to look at yourself.
"""

import os
from datetime import datetime, timedelta

import yfinance as yf

from sentiment import score_headlines
from notify import send_email

WATCHLIST_FILE = os.getenv("WATCHLIST_FILE", "watchlist.txt")


def load_watchlist(path: str) -> list[str]:
    with open(path) as f:
        tickers = [
            line.strip().upper()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]
    if not tickers:
        raise ValueError(f"No tickers found in {path}")
    return tickers


def fetch_ticker_data(ticker: str) -> dict:
    """Pull the last few days of price data and recent news headlines."""
    tk = yf.Ticker(ticker)

    hist = tk.history(period="5d")
    if hist.empty or len(hist) < 2:
        last_close = None
        pct_change = None
    else:
        last_close = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2])
        pct_change = (last_close - prev_close) / prev_close * 100

    headlines = []
    try:
        news_items = tk.news or []
    except Exception:
        news_items = []

    # yfinance's news payload shape has shifted between versions; handle both.
    for item in news_items[:10]:
        title = item.get("title") or item.get("content", {}).get("title")
        if title:
            headlines.append(title)

    return {
        "ticker": ticker,
        "last_close": last_close,
        "pct_change": pct_change,
        "headlines": headlines[:5],  # cap to keep AI calls small
    }


def build_signal(pct_change: float | None, sentiments: list[str]) -> str:
    """A deliberately simple, transparent rule — not a real trading strategy."""
    bullish = sentiments.count("bullish")
    bearish = sentiments.count("bearish")

    if pct_change is None:
        price_direction = "unknown"
    elif pct_change > 1:
        price_direction = "up"
    elif pct_change < -1:
        price_direction = "down"
    else:
        price_direction = "flat"

    if bullish > bearish and price_direction == "up":
        return "Notable: price up + bullish headlines"
    if bearish > bullish and price_direction == "down":
        return "Notable: price down + bearish headlines"
    if bullish != bearish and price_direction not in ("unknown", "flat"):
        return "Mixed: price move and headline sentiment disagree"
    return "No strong signal"


def build_report(results: list[dict]) -> str:
    lines = ["Daily Market Sentiment Brief", "=" * 30, ""]
    for r in results:
        pct = r["pct_change"]
        pct_str = f"{pct:+.2f}%" if pct is not None else "n/a"
        close_str = f"{r['last_close']:.2f}" if r["last_close"] is not None else "n/a"
        lines.append(f"{r['ticker']}  (last close: {close_str}, change: {pct_str})")
        lines.append(f"  Signal: {r['signal']}")
        for h, s in zip(r["headlines"], r["sentiments"]):
            lines.append(f"    [{s:>8}] {h}")
        if not r["headlines"]:
            lines.append("    (no recent headlines found)")
        lines.append("")
    lines.append("This is an automated research summary, not investment advice.")
    return "\n".join(lines)


def main():
    tickers = load_watchlist(WATCHLIST_FILE)
    results = []

    for ticker in tickers:
        data = fetch_ticker_data(ticker)
        sentiments = score_headlines(data["headlines"]) if data["headlines"] else []
        signal = build_signal(data["pct_change"], sentiments)
        results.append({**data, "sentiments": sentiments, "signal": signal})

    report = build_report(results)
    print(report)  # always visible in the Actions run log, even if email fails

    if os.getenv("EMAIL_TO"):
        send_email(subject="Daily Market Sentiment Brief", body=report)
    else:
        print("\n(EMAIL_TO not set — skipping email, printed report above only.)")


if __name__ == "__main__":
    main()
