from market_sentiment_fedgpt.core import analyze_market


def test_market_sentiment_sample_requires_no_missing_sources():
    report = analyze_market(
        "examples/market_indicators.csv",
        "examples/fed_speech.txt",
        "examples/portfolio.csv",
    )
    assert report.regime == "FEARFUL"
    assert report.fed_tone in {"HAWKISH", "BALANCED"}
    assert report.verification.status == "CLEAR"
    assert report.policy_path["12_month_cut_probability"] > 0

