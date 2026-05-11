# Market Sentiment FedGPT

Market Sentiment FedGPT turns Fed speech analysis, market sentiment, and portfolio briefing workflows into a deterministic CFO/investor research system.

It combines:

- Fed speech hawkish/dovish NLP
- market sentiment indicators
- portfolio exposure impact
- policy probability path
- CHP-style adversarial verification before the report can be treated as decision-ready

## Quick Start

```bash
PYTHONPATH=src python3 -m market_sentiment_fedgpt.cli analyze \
  --indicators examples/market_indicators.csv \
  --speech examples/fed_speech.txt \
  --portfolio examples/portfolio.csv \
  --json
```

## Why This Exists

Single-model market commentary can sound precise while mixing stale indicators, unsourced macro views, and unsupported portfolio implications. This app keeps the workflow grounded by requiring every report to pass a finance-grade verification gate.

## Output

The CLI returns:

- market regime: `FEARFUL`, `NEUTRAL`, or `EXUBERANT`
- Fed tone: `HAWKISH`, `BALANCED`, or `DOVISH`
- indicator scorecard
- portfolio risk notes
- 3, 6, and 12-month policy probability path
- `REQUIRES_HUMAN_VERIFICATION` when the evidence package is incomplete

## CHP Verification

The built-in verifier blocks decision-ready status if:

- required indicators are missing
- source dates are missing
- Fed speech text is too thin
- portfolio rows are not source-linked
- confidence is below 100

This is not investment advice. It is an auditable research workflow template.
