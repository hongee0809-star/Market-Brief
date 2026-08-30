"""
Thin wrapper around the GitHub Models inference API for headline sentiment.

Requires a token with 'models: read' permission. Inside a GitHub Actions
workflow, the built-in GITHUB_TOKEN works automatically as long as the
workflow grants that permission (see .github/workflows/daily-brief.yml).
For local runs, create a personal access token with model access and set
it as MODELS_TOKEN instead.
"""

import os
import sys

import requests

MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
MODEL_NAME = os.getenv("SENTIMENT_MODEL", "openai/gpt-4o-mini")

VALID_LABELS = {"bullish", "bearish", "neutral"}


def _classify_one(headline: str, token: str) -> str:
    response = requests.post(
        MODELS_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL_NAME,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You classify financial news headlines. Reply with "
                        "exactly one word: bullish, bearish, or neutral. "
                        "No punctuation, no explanation."
                    ),
                },
                {"role": "user", "content": headline},
            ],
            "temperature": 0,
        },
        timeout=20,
    )
    response.raise_for_status()
    label = response.json()["choices"][0]["message"]["content"].strip().lower()
    return label if label in VALID_LABELS else "neutral"


def score_headlines(headlines: list[str]) -> list[str]:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("MODELS_TOKEN")
    if not token:
        raise RuntimeError(
            "No token found for GitHub Models. Set GITHUB_TOKEN (inside "
            "Actions, with 'models: read' permission) or MODELS_TOKEN "
            "(locally, a personal access token with model access)."
        )

    labels = []
    for h in headlines:
        try:
            labels.append(_classify_one(h, token))
        except Exception as e:
            print(f"  (sentiment call failed for {h!r}: {e})", file=sys.stderr)
            labels.append("neutral")
    return labels
