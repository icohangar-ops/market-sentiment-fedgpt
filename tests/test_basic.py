"""Unit tests for market_sentiment_fedgpt core functionality."""

import json
import textwrap
from pathlib import Path

import pytest

from market_sentiment_fedgpt.core import (
    REQUIRED_INDICATORS,
    HAWKISH,
    DOVISH,
    IndicatorSignal,
    VerificationGate,
    MarketSentimentReport,
    analyze_market,
    report_json,
    _fed_score,
    _regime,
    _policy_path,
    _score_indicator,
    _verify,
)


# ---------------------------------------------------------------------------
# Import / package smoke tests
# ---------------------------------------------------------------------------

class TestPackageImports:
    def test_package_imports(self):
        import market_sentiment_fedgpt
        assert hasattr(market_sentiment_fedgpt, "analyze_market")

    def test_core_module_imports(self):
        from market_sentiment_fedgpt.core import analyze_market
        assert callable(analyze_market)

    def test_cli_module_imports(self):
        from market_sentiment_fedgpt.cli import main
        assert callable(main)

    def test_all_exports(self):
        from market_sentiment_fedgpt import analyze_market
        assert analyze_market is not None


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_indicator_signal_creation(self):
        signal = IndicatorSignal(
            name="vix", value=26.5, source_date="2025-05-08", bias="fearful", score=-2
        )
        assert signal.name == "vix"
        assert signal.value == 26.5
        assert signal.score == -2

    def test_verification_gate_default_violations(self):
        gate = VerificationGate(status="CLEAR", confidence=100)
        assert gate.violations == []

    def test_verification_gate_with_violations(self):
        gate = VerificationGate(
            status="REQUIRES_HUMAN_VERIFICATION",
            confidence=76,
            violations=["missing required indicators: vix"],
        )
        assert len(gate.violations) == 1
        assert gate.confidence == 76

    def test_report_to_dict(self):
        report = MarketSentimentReport(
            regime="FEARFUL",
            fed_tone="HAWKISH",
            sentiment_score=-5,
            fed_score=3,
            policy_path={"12_month_cut_probability": 0.35},
            indicators=[],
            portfolio_notes=["No portfolio file supplied."],
            verification=VerificationGate(status="CLEAR", confidence=100),
        )
        d = report.to_dict()
        assert d["regime"] == "FEARFUL"
        assert d["fed_tone"] == "HAWKISH"
        assert d["sentiment_score"] == -5
        assert isinstance(d["policy_path"], dict)
        assert isinstance(d["indicators"], list)

    def test_report_to_markdown(self):
        report = MarketSentimentReport(
            regime="NEUTRAL",
            fed_tone="BALANCED",
            sentiment_score=0,
            fed_score=0,
            policy_path={"3_month_cut_probability": 0.25},
            indicators=[],
            portfolio_notes=["No portfolio file supplied."],
            verification=VerificationGate(status="CLEAR", confidence=100),
        )
        md = report.to_markdown()
        assert "NEUTRAL" in md
        assert "BALANCED" in md
        assert "Policy Path" in md
        assert "Portfolio Notes" in md

    def test_report_to_markdown_with_violations(self):
        report = MarketSentimentReport(
            regime="NEUTRAL",
            fed_tone="BALANCED",
            sentiment_score=0,
            fed_score=0,
            policy_path={},
            indicators=[],
            portfolio_notes=[],
            verification=VerificationGate(
                status="REQUIRES_HUMAN_VERIFICATION",
                confidence=76,
                violations=["missing required indicators: vix"],
            ),
        )
        md = report.to_markdown()
        assert "Blocking Verification Issues" in md
        assert "missing required indicators: vix" in md


# ---------------------------------------------------------------------------
# Fed tone analysis tests
# ---------------------------------------------------------------------------

class TestFedScore:
    def test_hawkish_speech(self):
        text = "Inflation is persistent and we need higher rates and tightening."
        score = _fed_score(text)
        assert score > 0

    def test_dovish_speech(self):
        text = "The economy is cooling and slowing, with cuts likely as disinflation continues."
        score = _fed_score(text)
        assert score < 0

    def test_balanced_speech(self):
        text = "The committee will monitor incoming data carefully."
        score = _fed_score(text)
        assert score == 0

    def test_keyword_counts(self):
        text = "Inflation is persistent. Wage pressure is a concern. Inflation remains high."
        score = _fed_score(text)
        # "inflation" appears 2 times, "persistent" 1 time, "wage pressure" 1 time
        assert score == 4

    def test_empty_speech(self):
        assert _fed_score("") == 0

    def test_hawkish_set_not_empty(self):
        assert len(HAWKISH) > 0
        assert "inflation" in HAWKISH

    def test_dovish_set_not_empty(self):
        assert len(DOVISH) > 0
        assert "cooling" in DOVISH


# ---------------------------------------------------------------------------
# Regime classification tests
# ---------------------------------------------------------------------------

class TestRegime:
    def test_exuberant(self):
        assert _regime(4) == "EXUBERANT"
        assert _regime(10) == "EXUBERANT"

    def test_fearful(self):
        assert _regime(-4) == "FEARFUL"
        assert _regime(-10) == "FEARFUL"

    def test_neutral(self):
        assert _regime(0) == "NEUTRAL"
        assert _regime(3) == "NEUTRAL"
        assert _regime(-3) == "NEUTRAL"


# ---------------------------------------------------------------------------
# Policy path tests
# ---------------------------------------------------------------------------

class TestPolicyPath:
    def test_returns_three_horizons(self):
        path = _policy_path(0, 0)
        assert "3_month_cut_probability" in path
        assert "6_month_cut_probability" in path
        assert "12_month_cut_probability" in path

    def test_hawkish_tone_reduces_cut_probability(self):
        hawkish_path = _policy_path(0, 5)
        dovish_path = _policy_path(0, -5)
        assert dovish_path["12_month_cut_probability"] > hawkish_path["12_month_cut_probability"]

    def test_fearful_sentiment_increases_cut_probability(self):
        fearful_path = _policy_path(-5, 0)
        exuberant_path = _policy_path(5, 0)
        assert fearful_path["12_month_cut_probability"] > exuberant_path["12_month_cut_probability"]

    def test_probabilities_bounded(self):
        path = _policy_path(100, 100)
        for prob in path.values():
            assert 0.0 <= prob <= 1.0
        path = _policy_path(-100, -100)
        for prob in path.values():
            assert 0.0 <= prob <= 1.0

    def test_monotonic_horizons(self):
        path = _policy_path(0, 0)
        assert path["3_month_cut_probability"] <= path["6_month_cut_probability"] <= path["12_month_cut_probability"]


# ---------------------------------------------------------------------------
# Indicator scoring tests
# ---------------------------------------------------------------------------

class TestScoreIndicator:
    def test_vix_high(self):
        row = {"indicator": "vix", "value": "30", "source_date": "2025-05-08"}
        signal = _score_indicator(row)
        assert signal.score == -2
        assert signal.bias == "fearful"

    def test_vix_low(self):
        row = {"indicator": "vix", "value": "12", "source_date": "2025-05-08"}
        signal = _score_indicator(row)
        assert signal.score == 1
        assert signal.bias == "exuberant"

    def test_vix_neutral(self):
        row = {"indicator": "vix", "value": "20", "source_date": "2025-05-08"}
        signal = _score_indicator(row)
        assert signal.score == 0
        assert signal.bias == "neutral"

    def test_aaii_bullish(self):
        row = {"indicator": "aaii_bull_bear", "value": "30", "source_date": "2025-05-08"}
        signal = _score_indicator(row)
        assert signal.score == 2

    def test_aaii_bearish(self):
        row = {"indicator": "aaii_bull_bear", "value": "-20", "source_date": "2025-05-08"}
        signal = _score_indicator(row)
        assert signal.score == -2

    def test_consumer_confidence_high(self):
        row = {"indicator": "consumer_confidence", "value": "95", "source_date": "2025-05-01"}
        signal = _score_indicator(row)
        assert signal.score == 1

    def test_consumer_confidence_low(self):
        row = {"indicator": "consumer_confidence", "value": "65", "source_date": "2025-05-01"}
        signal = _score_indicator(row)
        assert signal.score == -1

    def test_unknown_indicator_defaults_to_zero(self):
        row = {"indicator": "custom_metric", "value": "50", "source_date": "2025-05-08"}
        signal = _score_indicator(row)
        assert signal.score == 0


# ---------------------------------------------------------------------------
# Verification gate tests
# ---------------------------------------------------------------------------

class TestVerify:
    def test_all_indicators_present_clears(self):
        rows = [
            {"indicator": ind, "value": "50", "source_date": "2025-05-08"}
            for ind in REQUIRED_INDICATORS
        ]
        speech = "This is a sufficiently long Fed speech with enough words to pass the forty word minimum requirement for reliable tone analysis."
        gate = _verify(rows, speech, None)
        assert gate.status == "CLEAR"
        assert gate.confidence == 100
        assert gate.violations == []

    def test_missing_indicators_flagged(self):
        rows = [
            {"indicator": "vix", "value": "20", "source_date": "2025-05-08"},
        ]
        speech = "This is a sufficiently long Fed speech with enough words to pass the forty word minimum requirement for reliable tone analysis."
        gate = _verify(rows, speech, None)
        assert gate.status == "REQUIRES_HUMAN_VERIFICATION"
        assert any("missing required indicators" in v for v in gate.violations)

    def test_short_speech_flagged(self):
        rows = [
            {"indicator": ind, "value": "50", "source_date": "2025-05-08"}
            for ind in REQUIRED_INDICATORS
        ]
        speech = "Too short."
        gate = _verify(rows, speech, None)
        assert any("too short" in v for v in gate.violations)

    def test_missing_source_date_flagged(self):
        rows = [
            {"indicator": "vix", "value": "20", "source_date": ""},
        ]
        speech = "This is a sufficiently long Fed speech with enough words to pass the forty word minimum requirement for reliable tone analysis."
        gate = _verify(rows, speech, None)
        assert any("source_date" in v for v in gate.violations)

    def test_portfolio_missing_source_flagged(self, tmp_path):
        rows = [
            {"indicator": ind, "value": "50", "source_date": "2025-05-08"}
            for ind in REQUIRED_INDICATORS
        ]
        speech = "This is a sufficiently long Fed speech with enough words to pass the forty word minimum requirement for reliable tone analysis."
        portfolio_file = tmp_path / "portfolio.csv"
        portfolio_file.write_text("ticker,sector,weight,source\nNVDA,Technology,0.14,\n")
        gate = _verify(rows, speech, portfolio_file)
        assert any("portfolio" in v.lower() or "source" in v.lower() for v in gate.violations)


# ---------------------------------------------------------------------------
# Integration tests with temporary files
# ---------------------------------------------------------------------------

class TestAnalyzeMarket:
    @pytest.fixture
    def indicators_csv(self, tmp_path):
        path = tmp_path / "indicators.csv"
        path.write_text(textwrap.dedent("""\
            indicator,value,source_date,source
            aaii_bull_bear,-18,2025-05-08,AAII
            naaim_exposure,42,2025-05-08,NAAIM
            vix,26.5,2025-05-08,CBOE
            put_call,1.18,2025-05-08,CBOE
            consumer_confidence,68,2025-05-01,Conference Board
            umich_sentiment,66,2025-05-01,University of Michigan
        """))
        return path

    @pytest.fixture
    def speech_txt(self, tmp_path):
        path = tmp_path / "speech.txt"
        path.write_text(
            "Inflation remains persistent and the committee is prepared to keep policy "
            "restrictive for longer if wage pressure and services inflation do not cool. "
            "Growth is slowing in some interest-sensitive areas, but the labor market "
            "remains resilient. The path ahead depends on incoming data, and officials "
            "will not declare victory until disinflation is more durable."
        )
        return path

    @pytest.fixture
    def portfolio_csv(self, tmp_path):
        path = tmp_path / "portfolio.csv"
        path.write_text(textwrap.dedent("""\
            ticker,sector,weight,source
            NVDA,Technology,0.14,Google Finance
            AMZN,Consumer Discretionary,0.09,Google Finance
            PLD,Real Estate,0.07,Google Finance
        """))
        return path

    def test_fearful_regime(self, indicators_csv, speech_txt):
        report = analyze_market(indicators_csv, speech_txt)
        assert report.regime == "FEARFUL"

    def test_hawkish_tone(self, indicators_csv, speech_txt):
        report = analyze_market(indicators_csv, speech_txt)
        assert report.fed_tone == "HAWKISH"

    def test_sentiment_score(self, indicators_csv, speech_txt):
        report = analyze_market(indicators_csv, speech_txt)
        assert report.sentiment_score < 0

    def test_policy_path_present(self, indicators_csv, speech_txt):
        report = analyze_market(indicators_csv, speech_txt)
        assert "12_month_cut_probability" in report.policy_path
        assert 0 < report.policy_path["12_month_cut_probability"] < 1

    def test_indicators_count(self, indicators_csv, speech_txt):
        report = analyze_market(indicators_csv, speech_txt)
        assert len(report.indicators) == 6

    def test_verification_clear(self, indicators_csv, speech_txt, portfolio_csv):
        report = analyze_market(indicators_csv, speech_txt, portfolio_csv)
        assert report.verification.status == "CLEAR"
        assert report.verification.confidence == 100

    def test_portfolio_notes_present(self, indicators_csv, speech_txt, portfolio_csv):
        report = analyze_market(indicators_csv, speech_txt, portfolio_csv)
        assert len(report.portfolio_notes) > 0

    def test_no_portfolio(self, indicators_csv, speech_txt):
        report = analyze_market(indicators_csv, speech_txt)
        assert "No portfolio file supplied" in report.portfolio_notes[0]

    def test_report_json_output(self, indicators_csv, speech_txt):
        report = analyze_market(indicators_csv, speech_txt)
        output = report_json(report)
        parsed = json.loads(output)
        assert parsed["regime"] == "FEARFUL"
        assert parsed["fed_tone"] == "HAWKISH"
        assert isinstance(parsed["policy_path"], dict)
        assert isinstance(parsed["indicators"], list)

    def test_dovish_speech(self, indicators_csv, tmp_path):
        dovish_speech = tmp_path / "dovish.txt"
        dovish_speech.write_text(
            "The economy is cooling and slowing significantly. We see clear disinflation "
            "and softening in key sectors. Accommodative policy and cuts may be appropriate "
            "as weakness emerges in consumer demand and manufacturing output continues to decline."
        )
        report = analyze_market(indicators_csv, dovish_speech)
        assert report.fed_tone == "DOVISH"
        assert report.fed_score < -1

    def test_balanced_speech(self, indicators_csv, tmp_path):
        balanced_speech = tmp_path / "balanced.txt"
        balanced_speech.write_text(
            "The committee continues to monitor a range of economic indicators. Labor "
            "market conditions remain stable and inflation is moving gradually toward "
            "our target. We will continue to assess incoming data and adjust policy as needed "
            "to sustain economic expansion and price stability over the medium term."
        )
        report = analyze_market(indicators_csv, balanced_speech)
        assert report.fed_tone == "BALANCED"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_returns_zero(self, tmp_path):
        indicators = tmp_path / "indicators.csv"
        indicators.write_text(textwrap.dedent("""\
            indicator,value,source_date,source
            aaii_bull_bear,0,2025-05-08,AAII
            naaim_exposure,65,2025-05-08,NAAIM
            vix,18,2025-05-08,CBOE
            put_call,0.9,2025-05-08,CBOE
            consumer_confidence,80,2025-05-01,Conference Board
            umich_sentiment,80,2025-05-01,University of Michigan
        """))
        speech = tmp_path / "speech.txt"
        speech.write_text(
            "The committee continues to monitor a range of economic indicators. "
            "Labor market conditions remain stable and inflation is moving gradually "
            "toward our target. We will assess incoming data carefully over the coming months."
        )
        from market_sentiment_fedgpt.cli import main
        result = main([
            "--indicators", str(indicators),
            "--speech", str(speech),
        ])
        assert result == 0

    def test_cli_missing_args_returns_nonzero(self):
        from market_sentiment_fedgpt.cli import main
        with pytest.raises(SystemExit):
            main([])


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_required_indicators_six(self):
        assert len(REQUIRED_INDICATORS) == 6

    def test_required_indicators_content(self):
        expected = {"aaii_bull_bear", "naaim_exposure", "vix", "put_call", "consumer_confidence", "umich_sentiment"}
        assert REQUIRED_INDICATORS == expected

    def test_hawkish_and_dovish_disjoint(self):
        assert HAWKISH.isdisjoint(DOVISH)
