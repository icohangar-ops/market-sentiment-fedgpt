from pathlib import Path

from market_sentiment_fedgpt.core import analyze_market

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def test_market_sentiment_sample_requires_no_missing_sources():
    report = analyze_market(
        EXAMPLES_DIR / "market_indicators.csv",
        EXAMPLES_DIR / "fed_speech.txt",
        EXAMPLES_DIR / "portfolio.csv",
    )
    assert report.regime == "FEARFUL"
    assert report.fed_tone in {"HAWKISH", "BALANCED"}
    assert report.verification.status == "CLEAR"
    assert report.policy_path["12_month_cut_probability"] > 0

