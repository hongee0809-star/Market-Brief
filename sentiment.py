"""
Headline sentiment scoring using a local, lexicon-based analyzer (VADER),
augmented with finance-specific vocabulary.

GitHub Models — which this file originally called out to — was fully
retired by GitHub on July 30, 2026 (the playground, model catalog,
inference API, and BYOK were all shut down for every customer). Rather
than depend on another external AI provider and its own token/rate-limit
risk, this scores headlines entirely locally: no network call, no auth,
no rate limits, nothing that can be retired out from under this project
again.

Trade-off to be aware of: this is a rules-based lexicon, not an LLM. It
catches common finance vocabulary (beats, surges, downgrade, plunge,
etc.) reasonably well, but it's less nuanced than a real language model
on subtle or sarcastic headlines. If you later want LLM-quality scoring,
this function's signature (list[str] in, list[str] out) is a drop-in
point to swap in a different provider (OpenRouter, Groq, Gemini, etc.)
without touching main.py.
"""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# VADER's compound score already ranges roughly -1..+1; these thresholds
# are VADER's own documented convention for pos/neg/neutral cutoffs.
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05

# Finance-specific words VADER's general-purpose lexicon doesn't know.
# Values follow VADER's -4..+4 valence scale.
FINANCE_LEXICON = {
    # bullish
    "beats": 2.5, "beat": 2.0, "surge": 3.0, "surges": 3.0, "surged": 3.0,
    "rally": 2.5, "rallies": 2.5, "soar": 3.0, "soars": 3.0, "soared": 3.0,
    "upgrade": 2.0, "upgrades": 2.0, "upgraded": 2.0, "outperform": 2.0,
    "bullish": 3.0, "buyback": 1.5, "breakthrough": 2.0, "tops": 1.8,
    "exceeds": 2.0, "expands": 1.2, "raises guidance": 2.5,
    # bearish
    "misses": -2.5, "miss": -2.0, "plunge": -3.0, "plunges": -3.0,
    "plunged": -3.0, "downgrade": -2.0, "downgrades": -2.0,
    "downgraded": -2.0, "underperform": -2.0, "bearish": -3.0,
    "slump": -2.5, "slumps": -2.5, "slumped": -2.5, "crash": -3.0,
    "crashes": -3.0, "crashed": -3.0, "layoffs": -2.0, "lawsuit": -1.8,
    "investigation": -1.8, "warns": -1.5, "warning": -1.5,
    "disappointing": -2.0, "disappoints": -2.0, "falls short": -2.0,
    "cuts guidance": -2.5, "lowers guidance": -2.5, "recall": -1.8,
}

_analyzer = SentimentIntensityAnalyzer()
_analyzer.lexicon.update(FINANCE_LEXICON)


def _classify_one(headline: str) -> str:
    compound = _analyzer.polarity_scores(headline)["compound"]
    if compound >= POSITIVE_THRESHOLD:
        return "bullish"
    if compound <= NEGATIVE_THRESHOLD:
        return "bearish"
    return "neutral"


def score_headlines(headlines: list[str]) -> list[str]:
    return [_classify_one(h) for h in headlines]
