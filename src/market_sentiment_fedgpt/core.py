"""Deterministic Fed tone and market sentiment analysis."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List


REQUIRED_INDICATORS = {
    "aaii_bull_bear",
    "naaim_exposure",
    "vix",
    "put_call",
    "consumer_confidence",
    "umich_sentiment",
}

HAWKISH = {"inflation", "restrictive", "tightening", "higher", "overheating", "wage pressure", "persistent"}
DOVISH = {"cooling", "slowing", "cuts", "accommodative", "disinflation", "softening", "weakness"}


@dataclass
class IndicatorSignal:
    name: str
    value: float
    source_date: str
    bias: str
    score: int


@dataclass
class VerificationGate:
    status: str
    confidence: int
    violations: List[str] = field(default_factory=list)


@dataclass
class MarketSentimentReport:
    regime: str
    fed_tone: str
    sentiment_score: int
    fed_score: int
    policy_path: Dict[str, float]
    indicators: List[IndicatorSignal]
    portfolio_notes: List[str]
    verification: VerificationGate

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            "# Market Sentiment FedGPT Report",
            f"- Regime: {self.regime}",
            f"- Fed Tone: {self.fed_tone}",
            f"- Sentiment Score: {self.sentiment_score}",
            f"- Verification: {self.verification.status}",
            "",
            "## Policy Path",
        ]
        lines.extend(f"- {key}: {value:.1%}" for key, value in self.policy_path.items())
        lines.append("")
        lines.append("## Portfolio Notes")
        lines.extend(f"- {note}" for note in self.portfolio_notes)
        if self.verification.violations:
            lines.append("")
            lines.append("## Blocking Verification Issues")
            lines.extend(f"- {item}" for item in self.verification.violations)
        return "\n".join(lines)


def analyze_market(indicators_path: str | Path, speech_path: str | Path, portfolio_path: str | Path | None = None) -> MarketSentimentReport:
    rows = _read_csv(indicators_path)
    indicators = [_score_indicator(row) for row in rows]
    sentiment_score = sum(item.score for item in indicators)
    regime = _regime(sentiment_score)

    speech = Path(speech_path).read_text(encoding="utf-8")
    fed_score = _fed_score(speech)
    fed_tone = "HAWKISH" if fed_score > 1 else "DOVISH" if fed_score < -1 else "BALANCED"
    policy_path = _policy_path(sentiment_score, fed_score)
    portfolio_notes = _portfolio_notes(portfolio_path, regime, fed_tone) if portfolio_path else ["No portfolio file supplied."]
    verification = _verify(rows, speech, portfolio_path)
    return MarketSentimentReport(
        regime=regime,
        fed_tone=fed_tone,
        sentiment_score=sentiment_score,
        fed_score=fed_score,
        policy_path=policy_path,
        indicators=indicators,
        portfolio_notes=portfolio_notes,
        verification=verification,
    )


def _read_csv(path: str | Path) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _score_indicator(row: Dict[str, str]) -> IndicatorSignal:
    name = row["indicator"].strip().lower()
    value = float(row["value"])
    score = 0
    bias = "neutral"
    if name == "aaii_bull_bear":
        score = 2 if value > 25 else -2 if value < -15 else 0
    elif name == "naaim_exposure":
        score = 2 if value > 85 else -2 if value < 45 else 0
    elif name == "vix":
        score = -2 if value > 25 else 1 if value < 15 else 0
    elif name == "put_call":
        score = -2 if value > 1.1 else 1 if value < 0.75 else 0
    elif name in {"consumer_confidence", "umich_sentiment"}:
        score = 1 if value > 90 else -1 if value < 70 else 0
    bias = "exuberant" if score > 0 else "fearful" if score < 0 else "neutral"
    return IndicatorSignal(name=name, value=value, source_date=row.get("source_date", ""), bias=bias, score=score)


def _fed_score(text: str) -> int:
    lowered = text.lower()
    hawkish = sum(lowered.count(term) for term in HAWKISH)
    dovish = sum(lowered.count(term) for term in DOVISH)
    return hawkish - dovish


def _regime(score: int) -> str:
    if score >= 4:
        return "EXUBERANT"
    if score <= -4:
        return "FEARFUL"
    return "NEUTRAL"


def _policy_path(sentiment_score: int, fed_score: int) -> Dict[str, float]:
    cut_probability = 0.45 - (fed_score * 0.04) - (sentiment_score * 0.02)
    cut_probability = min(0.9, max(0.05, cut_probability))
    return {
        "3_month_cut_probability": cut_probability * 0.55,
        "6_month_cut_probability": cut_probability * 0.8,
        "12_month_cut_probability": cut_probability,
    }


def _portfolio_notes(path: str | Path, regime: str, fed_tone: str) -> List[str]:
    rows = _read_csv(path)
    notes: List[str] = []
    for row in rows:
        ticker = row.get("ticker", "UNKNOWN")
        sector = row.get("sector", "UNKNOWN")
        weight = float(row.get("weight", 0))
        if fed_tone == "HAWKISH" and sector.lower() in {"real estate", "utilities"}:
            notes.append(f"{ticker}: rate-sensitive {sector} exposure needs stress test at {weight:.1%} weight.")
        elif regime == "FEARFUL" and weight > 0.1:
            notes.append(f"{ticker}: large position in fearful tape, verify downside liquidity and thesis durability.")
        elif regime == "EXUBERANT" and sector.lower() in {"technology", "consumer discretionary"}:
            notes.append(f"{ticker}: beta-sensitive exposure could be vulnerable if sentiment mean-reverts.")
    return notes or ["No material portfolio concentration flags from supplied rows."]


def _verify(rows: Iterable[Dict[str, str]], speech: str, portfolio_path: str | Path | None) -> VerificationGate:
    rows = list(rows)
    supplied = {row.get("indicator", "").strip().lower() for row in rows}
    violations: List[str] = []
    missing = sorted(REQUIRED_INDICATORS - supplied)
    if missing:
        violations.append(f"missing required indicators: {', '.join(missing)}")
    if any(not row.get("source_date") for row in rows):
        violations.append("one or more indicators are missing source_date")
    if len(speech.split()) < 40:
        violations.append("Fed speech text is too short for reliable tone analysis")
    if portfolio_path:
        portfolio_rows = _read_csv(portfolio_path)
        if any(not row.get("source") for row in portfolio_rows):
            violations.append("one or more portfolio rows are missing source")
    confidence = 100 if not violations else max(50, 100 - 12 * len(violations))
    return VerificationGate(
        status="CLEAR" if confidence == 100 else "REQUIRES_HUMAN_VERIFICATION",
        confidence=confidence,
        violations=violations,
    )


def report_json(report: MarketSentimentReport) -> str:
    return json.dumps(report.to_dict(), indent=2)

