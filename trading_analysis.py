"""
Deep multi-agent trading analysis via TradingAgents (Tauric Research),
using Claude as the reasoning backbone.

Unlike main.py (the daily sentiment brief, which is free and runs
entirely locally), this script makes real, paid Anthropic API calls --
several per ticker per run: one or more per analyst, per debate round,
and per manager decision. Because of that, this workflow is wired to
run only on manual trigger (workflow_dispatch), not a recurring
schedule -- a run only happens when you deliberately ask for one.
"""

import os
from datetime import date

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

from notify import send_email

WATCHLIST_FILE = os.getenv("WATCHLIST_FILE", "watchlist.txt")
EXCERPT_LENGTH = 500  # characters of the manager's reasoning to include per ticker


def load_watchlist(path: str) -> list[dict]:
    """Same TICKER or TICKER,Display Name format as the sentiment brief's
    watchlist.txt. Kept as its own small copy here (rather than importing
    main.py) so this script's dependencies stay independent of the daily
    brief's."""
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


def build_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "anthropic"
    # Cheaper/faster model for the many analyst + debate-round calls;
    # the stronger model is reserved for the two single "judge" calls
    # (Research Manager, Portfolio Manager) where reasoning quality
    # matters most per dollar spent.
    config["quick_think_llm"] = "claude-haiku-4-5"
    config["deep_think_llm"] = "claude-sonnet-5"
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    return config


def analyze_ticker(ta: "TradingAgentsGraph", ticker: str, analysis_date: str) -> dict:
    try:
        final_state, signal = ta.propagate(ticker, analysis_date)
        excerpt = (final_state.get("final_trade_decision") or "").strip()
        if len(excerpt) > EXCERPT_LENGTH:
            excerpt = excerpt[:EXCERPT_LENGTH].rsplit(" ", 1)[0] + "..."
        return {"signal": signal, "excerpt": excerpt, "error": None}
    except Exception as e:
        return {"signal": "ERROR", "excerpt": "", "error": str(e)}


def build_report_text(results: list[dict], analysis_date: str) -> str:
    lines = [f"TradingAgents Deep Analysis \u2014 {analysis_date}", "=" * 40, ""]
    for r in results:
        lines.append(f"{r['display_name']} ({r['ticker']}): {r['signal']}")
        if r["error"]:
            lines.append(f"  (analysis failed: {r['error']})")
        elif r["excerpt"]:
            lines.append(f"  {r['excerpt']}")
        lines.append("")
    lines.append("Research tool output from a multi-agent LLM debate, not investment advice.")
    return "\n".join(lines)


_SIGNAL_COLORS = {
    "Buy": "#1a7f37", "Overweight": "#1a7f37",
    "Sell": "#cf222e", "Underweight": "#cf222e",
    "Hold": "#57606a",
}


def _signal_color(signal: str) -> str:
    return _SIGNAL_COLORS.get(signal, "#9a6700")  # amber for REVIEW/ERROR/unrecognized


def build_report_html(results: list[dict], analysis_date: str) -> str:
    cell = "padding:8px 10px;border:1px solid #ddd;vertical-align:top;"
    rows = ""
    for r in results:
        detail = f"(analysis failed: {r['error']})" if r["error"] else r["excerpt"]
        rows += (
            f"<tr>"
            f"<td style='{cell}'>{r['display_name']} ({r['ticker']})</td>"
            f"<td style='{cell}color:{_signal_color(r['signal'])};font-weight:bold;'>{r['signal']}</td>"
            f"<td style='{cell}'>{detail}</td>"
            f"</tr>"
        )
    return f"""
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;">
      <h2 style="margin-bottom:4px;">TradingAgents Deep Analysis</h2>
      <p style="color:#57606a;margin-top:0;">{analysis_date} \u2014 multi-agent LLM debate output, not investment advice.</p>
      <table style="border-collapse:collapse;width:100%;max-width:700px;">
        <tr style="background:#f6f8fa;">
          <th style='{cell}text-align:left;'>Ticker</th>
          <th style='{cell}text-align:left;'>Signal</th>
          <th style='{cell}text-align:left;'>Reasoning (excerpt)</th>
        </tr>
        {rows}
      </table>
    </body>
    </html>
    """


def main():
    watchlist = load_watchlist(WATCHLIST_FILE)
    config = build_config()
    ta = TradingAgentsGraph(debug=False, config=config)

    analysis_date = date.today().isoformat()
    results = []
    for entry in watchlist:
        outcome = analyze_ticker(ta, entry["ticker"], analysis_date)
        results.append({**entry, **outcome})

    text_report = build_report_text(results, analysis_date)
    print(text_report)

    if os.getenv("EMAIL_TO"):
        html_report = build_report_html(results, analysis_date)
        send_email(subject="TradingAgents Deep Analysis", text_body=text_report, html_body=html_report)
    else:
        print("\n(EMAIL_TO not set \u2014 skipping email, printed report above only.)")


if __name__ == "__main__":
    main()
