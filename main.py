"""
Daily market sentiment brief.

Pulls recent price action and news headlines for a focused watchlist,
plus general Federal Reserve / macro headlines, scores sentiment locally
(see sentiment.py), flags anything notable, and emails an HTML report.

This is a research / monitoring tool. It does not place trades, connect
to a broker, or give investment advice — it just flags things for you
to look at yourself.
"""

import math
import os
import time

import yfinance as yf

from sentiment import score_headlines
from notify import send_email

WATCHLIST_FILE = os.getenv("WATCHLIST_FILE", "watchlist.txt")
FED_SEARCH_QUERIES = ["Federal Reserve", "Kevin Warsh Federal Reserve"]
VOLUME_SPIKE_THRESHOLD = 2.0  # today's volume vs. 20-day average, to flag as unusual


def load_watchlist(path: str) -> list[dict]:
    """Each line is TICKER or TICKER,Display Name."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "," in line:
                ticker, display_name = line.split(",", 1)
            else:
                ticker, display_name = line, line
            entries.append({"ticker": ticker.strip().upper(), "display_name": display_name.strip()})
    if not entries:
        raise ValueError(f"No tickers found in {path}")
    return entries


def get_currency_symbol(ticker: str) -> str:
    if ticker.endswith(".KS"):
        return "\u20a9"  # Korean won
    return "$"


def _nan_safe(value):
    """Yahoo occasionally returns NaN instead of a missing value entirely.
    NaN is not None, so a plain `is not None` check lets it slip through
    and get printed as the literal text 'nan'. Normalize it to None here,
    once, so every formatter downstream can trust 'not None' actually
    means 'usable number'."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _fetch_clean_history(tk: "yf.Ticker", period: str = "2mo", attempts: int = 2):
    """Fetch price history, repairing and retrying against Yahoo's
    occasional bad rows (valid volume but a missing/NaN close is a known
    upstream glitch, not something we can prevent at the source)."""
    hist = None
    for attempt in range(attempts):
        try:
            hist = tk.history(period=period, repair=True)
        except Exception:
            hist = None
        if hist is not None and not hist.empty:
            hist = hist.dropna(subset=["Close", "Volume"])
            if not hist.empty:
                return hist
        if attempt < attempts - 1:
            time.sleep(2)  # brief pause before retrying a transient glitch
    return hist


def fetch_ticker_data(ticker: str, display_name: str) -> dict:
    """Pull recent price/volume history and news headlines."""
    tk = yf.Ticker(ticker)

    # 2 months gives enough trading days for a 20-day volume average,
    # while still being a light, fast pull.
    hist = _fetch_clean_history(tk, period="2mo")
    if hist is None or hist.empty or len(hist) < 2:
        last_close = None
        pct_change = None
    else:
        last_close = _nan_safe(float(hist["Close"].iloc[-1]))
        prev_close = _nan_safe(float(hist["Close"].iloc[-2]))
        pct_change = (last_close - prev_close) / prev_close * 100 if last_close is not None and prev_close else None

    volume_ratio = None
    if hist is not None and not hist.empty and len(hist) >= 2:
        last_volume = _nan_safe(float(hist["Volume"].iloc[-1]))
        # Average of the 20 trading days *before* today, so today doesn't
        # water down its own comparison baseline.
        lookback = hist["Volume"].iloc[-21:-1] if len(hist) >= 21 else hist["Volume"].iloc[:-1]
        avg_volume = _nan_safe(float(lookback.mean())) if len(lookback) > 0 else None
        if avg_volume and last_volume is not None:
            volume_ratio = last_volume / avg_volume

    headlines = []
    try:
        news_items = tk.news or []
    except Exception:
        news_items = []

    for item in news_items[:10]:
        title = item.get("title") or item.get("content", {}).get("title")
        if title:
            headlines.append(title)

    # Some tickers (e.g. foreign listings) have thin native news feeds.
    # Fall back to a name search so those don't show up empty every day.
    if len(headlines) < 3:
        try:
            search_results = yf.Search(display_name, news_count=5).news or []
        except Exception:
            search_results = []
        for item in search_results:
            title = item.get("title") or item.get("content", {}).get("title")
            if title and title not in headlines:
                headlines.append(title)

    return {
        "ticker": ticker,
        "display_name": display_name,
        "currency": get_currency_symbol(ticker),
        "last_close": last_close,
        "pct_change": pct_change,
        "volume_ratio": volume_ratio,
        "headlines": headlines[:5],  # cap to keep things readable
    }


def fetch_fed_headlines(max_headlines: int = 6) -> list[str]:
    """General Fed / FOMC / Warsh headlines, not tied to any one ticker."""
    headlines = []
    for query in FED_SEARCH_QUERIES:
        try:
            results = yf.Search(query, news_count=6).news or []
        except Exception:
            results = []
        for item in results:
            title = item.get("title") or item.get("content", {}).get("title")
            if title and title not in headlines:
                headlines.append(title)
    return headlines[:max_headlines]


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


def build_notices(results: list[dict], fed_sentiments: list[str]) -> list[str]:
    """A short, human-readable list of things worth a second look today."""
    notices = []
    for r in results:
        pct = r["pct_change"]
        if pct is not None and abs(pct) >= 3:
            direction = "up" if pct > 0 else "down"
            notices.append(f"{r['display_name']} ({r['ticker']}) moved sharply {direction}: {pct:+.2f}%")
        if r["signal"].startswith("Notable"):
            notices.append(f"{r['display_name']} ({r['ticker']}): {r['signal']}")
        ratio = r.get("volume_ratio")
        if ratio is not None and ratio >= VOLUME_SPIKE_THRESHOLD:
            notices.append(
                f"{r['display_name']} ({r['ticker']}) volume is {ratio:.1f}x its 20-day average \u2014 unusual activity."
            )

    bearish = fed_sentiments.count("bearish")
    bullish = fed_sentiments.count("bullish")
    if bearish:
        notices.append(f"{bearish} Fed-related headline(s) skewed bearish today \u2014 worth a closer read.")
    if bullish:
        notices.append(f"{bullish} Fed-related headline(s) skewed bullish today.")

    if not notices:
        notices.append("Nothing stood out beyond normal day-to-day moves.")
    return notices


def _fmt_price(currency: str, value: float | None) -> str:
    value = _nan_safe(value)
    return f"{currency}{value:,.2f}" if value is not None else "n/a"


def _fmt_pct(value: float | None) -> str:
    value = _nan_safe(value)
    return f"{value:+.2f}%" if value is not None else "n/a"


def _fmt_volume_ratio(ratio: float | None) -> str:
    ratio = _nan_safe(ratio)
    return f"{ratio:.1f}x avg" if ratio is not None else "n/a"


def _sentiment_color(label: str) -> str:
    return {"bullish": "#1a7f37", "bearish": "#cf222e"}.get(label, "#57606a")


def _pct_color(value: float | None) -> str:
    value = _nan_safe(value)
    if value is None:
        return "#57606a"
    return "#1a7f37" if value > 0 else "#cf222e" if value < 0 else "#57606a"


def _volume_style(ratio: float | None) -> str:
    ratio = _nan_safe(ratio)
    if ratio is not None and ratio >= VOLUME_SPIKE_THRESHOLD:
        return "color:#9a6700;font-weight:bold;"
    return "color:#57606a;"


def build_report_text(results: list[dict], fed_headlines: list[str], fed_sentiments: list[str], notices: list[str]) -> str:
    """Plain-text version, used for the Actions log."""
    lines = ["Daily Market Sentiment Brief", "=" * 30, ""]
    for r in results:
        lines.append(f"{r['display_name']} ({r['ticker']})  "
                      f"last close: {_fmt_price(r['currency'], r['last_close'])}, "
                      f"change: {_fmt_pct(r['pct_change'])}, "
                      f"volume: {_fmt_volume_ratio(r['volume_ratio'])}")
        lines.append(f"  Signal: {r['signal']}")
        for h, s in zip(r["headlines"], r["sentiments"]):
            lines.append(f"    [{s:>8}] {h}")
        if not r["headlines"]:
            lines.append("    (no recent headlines found)")
        lines.append("")

    lines.append("Federal Reserve / Macro")
    lines.append("-" * 30)
    if fed_headlines:
        for h, s in zip(fed_headlines, fed_sentiments):
            lines.append(f"  [{s:>8}] {h}")
    else:
        lines.append("  (no Fed-related headlines found today)")
    lines.append("")

    lines.append("Things to Notice")
    lines.append("-" * 30)
    for n in notices:
        lines.append(f"  - {n}")
    lines.append("")

    lines.append("This is an automated research summary, not investment advice.")
    return "\n".join(lines)


def build_report_html(results: list[dict], fed_headlines: list[str], fed_sentiments: list[str], notices: list[str]) -> str:
    """HTML version with real tables, used for the emailed report."""
    cell = "padding:6px 10px;border:1px solid #ddd;"

    summary_rows = "".join(
        f"<tr>"
        f"<td style='{cell}'>{r['display_name']} ({r['ticker']})</td>"
        f"<td style='{cell}text-align:right;'>{_fmt_price(r['currency'], r['last_close'])}</td>"
        f"<td style='{cell}text-align:right;color:{_pct_color(r['pct_change'])};'>{_fmt_pct(r['pct_change'])}</td>"
        f"<td style='{cell}text-align:right;{_volume_style(r['volume_ratio'])}'>{_fmt_volume_ratio(r['volume_ratio'])}</td>"
        f"<td style='{cell}'>{r['signal']}</td>"
        f"</tr>"
        for r in results
    )

    headline_rows = ""
    for r in results:
        if not r["headlines"]:
            headline_rows += (
                f"<tr><td style='{cell}'>{r['display_name']}</td>"
                f"<td style='{cell}' colspan='2'>(no recent headlines found)</td></tr>"
            )
        for h, s in zip(r["headlines"], r["sentiments"]):
            headline_rows += (
                f"<tr><td style='{cell}'>{r['display_name']}</td>"
                f"<td style='{cell}color:{_sentiment_color(s)};text-transform:capitalize;'>{s}</td>"
                f"<td style='{cell}'>{h}</td></tr>"
            )

    fed_rows = "".join(
        f"<tr><td style='{cell}color:{_sentiment_color(s)};text-transform:capitalize;'>{s}</td>"
        f"<td style='{cell}'>{h}</td></tr>"
        for h, s in zip(fed_headlines, fed_sentiments)
    ) or f"<tr><td style='{cell}' colspan='2'>(no Fed-related headlines found today)</td></tr>"

    notice_items = "".join(f"<li style='margin-bottom:4px;'>{n}</li>" for n in notices)

    return f"""
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;">
      <h2 style="margin-bottom:4px;">Daily Market Sentiment Brief</h2>
      <p style="color:#57606a;margin-top:0;">Automated research summary — not investment advice.</p>

      <h3>Snapshot</h3>
      <table style="border-collapse:collapse;width:100%;max-width:600px;">
        <tr style="background:#f6f8fa;">
          <th style='{cell}text-align:left;'>Ticker</th>
          <th style='{cell}text-align:right;'>Last Close</th>
          <th style='{cell}text-align:right;'>Change</th>
          <th style='{cell}text-align:right;'>Volume</th>
          <th style='{cell}text-align:left;'>Signal</th>
        </tr>
        {summary_rows}
      </table>

      <h3>Headlines &amp; Sentiment</h3>
      <table style="border-collapse:collapse;width:100%;max-width:700px;">
        <tr style="background:#f6f8fa;">
          <th style='{cell}text-align:left;'>Ticker</th>
          <th style='{cell}text-align:left;'>Sentiment</th>
          <th style='{cell}text-align:left;'>Headline</th>
        </tr>
        {headline_rows}
      </table>

      <h3>Federal Reserve / Macro</h3>
      <table style="border-collapse:collapse;width:100%;max-width:700px;">
        <tr style="background:#f6f8fa;">
          <th style='{cell}text-align:left;'>Sentiment</th>
          <th style='{cell}text-align:left;'>Headline</th>
        </tr>
        {fed_rows}
      </table>

      <h3>Things to Notice</h3>
      <ul>
        {notice_items}
      </ul>

      <p style="color:#57606a;font-size:0.9em;">
        This is an automated research summary, not investment advice.
      </p>
    </body>
    </html>
    """


def main():
    watchlist = load_watchlist(WATCHLIST_FILE)
    results = []

    for entry in watchlist:
        data = fetch_ticker_data(entry["ticker"], entry["display_name"])
        sentiments = score_headlines(data["headlines"]) if data["headlines"] else []
        signal = build_signal(data["pct_change"], sentiments)
        results.append({**data, "sentiments": sentiments, "signal": signal})

    fed_headlines = fetch_fed_headlines()
    fed_sentiments = score_headlines(fed_headlines) if fed_headlines else []
    notices = build_notices(results, fed_sentiments)

    text_report = build_report_text(results, fed_headlines, fed_sentiments, notices)
    print(text_report)  # always visible in the Actions run log

    if os.getenv("EMAIL_TO"):
        html_report = build_report_html(results, fed_headlines, fed_sentiments, notices)
        send_email(subject="Daily Market Sentiment Brief", text_body=text_report, html_body=html_report)
    else:
        print("\n(EMAIL_TO not set — skipping email, printed report above only.)")


if __name__ == "__main__":
    main()
