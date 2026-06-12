# Market Sentiment FedGPT

**Fed tone, macro sentiment analysis, and portfolio risk briefing -- deterministic, auditable, and verification-gated.**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![CI](https://img.shields.io/badge/CI-passing-brightgreen.svg)](.github/workflows/ci.yml)

## Overview

Market Sentiment FedGPT is a deterministic analysis engine that turns Federal Reserve speech transcripts, market sentiment indicators, and portfolio holdings into a unified research briefing. Unlike single-model commentary generators that can mix stale indicators with unsupported macro views, this system enforces a strict verification gate before any report is treated as decision-ready.

The engine reads structured CSV data for market indicators (AAII bull/bear spread, NAAIM exposure index, VIX, put/call ratio, consumer confidence, University of Michigan sentiment) and portfolio positions, then scores Fed speech text for hawkish or dovish tone using targeted keyword analysis. Outputs include a regime classification (EXUBERANT / NEUTRAL / FEARFUL), a policy probability path projecting 3, 6, and 12-month rate cut likelihood, and portfolio-specific risk notes that flag rate-sensitive, beta-sensitive, or oversized positions.

Every report passes through an adversarial verification layer inspired by CHP (Chain-of-Human-Preference) evaluation. The gate checks for missing required indicators, absent source dates, insufficient speech length, and unsourced portfolio rows. Reports with violations are marked `REQUIRES_HUMAN_VERIFICATION` with an explicit confidence score, ensuring no output is consumed blindly.

## Architecture

```
+-------------------+     +------------------+     +-------------------+
|  Market           |     |  Fed Speech      |     |  Portfolio        |
|  Indicators CSV   |     |  Transcript (.txt)|     |  Holdings CSV     |
+--------+----------+     +--------+---------+     +--------+----------+
         |                         |                       |
         v                         v                       v
+--------+----------+  +----------+---------+  +-----------+----------+
|  Indicator Scorer |  |  Fed Tone Analyzer  |  |  Portfolio Noter   |
|  (6 indicators)   |  |  (hawkish/dovish)   |  |  (sector/weight)   |
+--------+----------+  +----------+---------+  +-----------+----------+
         |                         |                       |
         +------------+------------+-----------+-----------+
                      |                        |
                      v                        v
           +----------+-----------+   +--------+--------+
           |  Regime Classifier   |   |  Policy Path    |
           |  + Sentiment Score   |   |  (cut probs)    |
           +----------+-----------+   +--------+--------+
                      |                        |
                      +-----------+------------+
                                  |
                                  v
                    +-------------+-------------+
                    |   Verification Gate      |
                    |   (CHP-style adversarial)|
                    +-------------+-------------+
                                  |
                                  v
                    +-------------+-------------+
                    |  MarketSentimentReport   |
                    |  (Markdown / JSON)       |
                    +--------------------------+
```

## Tech Stack

| Component           | Technology                                          |
|---------------------|-----------------------------------------------------|
| Language            | Python 3.10+                                        |
| Dependencies        | Zero external dependencies (stdlib only)            |
| Build System        | setuptools (via pyproject.toml)                     |
| Testing             | pytest                                              |
| CI                  | GitHub Actions                                      |
| Data Input          | CSV (indicators, portfolio), plain text (speech)    |
| Data Output         | Markdown report, JSON export                        |

## Key Features

- **Fed Tone Analysis** -- Scores Federal Reserve speech text using curated hawkish and dovish keyword sets. Produces a HAWKISH, BALANCED, or DOVISH classification with a numeric score.
- **Market Regime Detection** -- Aggregates six standard sentiment indicators into a composite score and classifies the current market regime as EXUBERANT, NEUTRAL, or FEARFUL.
- **Policy Probability Path** -- Models 3-month, 6-month, and 12-month rate cut probabilities based on the interaction between sentiment score and Fed tone.
- **Portfolio Risk Notes** -- Scans holdings for rate-sensitive sector exposure (Real Estate, Utilities), beta-sensitive exposure (Technology, Consumer Discretionary), and oversized positions in fearful regimes.
- **CHP-Style Verification Gate** -- Blocks decision-ready status when required indicators are missing, source dates are absent, the speech is too short, or portfolio rows lack sourcing. Reports confidence as a percentage and lists specific violations.
- **Dual Output Format** -- Generates both human-readable Markdown and machine-parsable JSON from the same report object.
- **CLI Interface** -- Provides a command-line tool with `--indicators`, `--speech`, `--portfolio`, and `--json` flags for scriptable integration.
- **Zero External Dependencies** -- Runs entirely on the Python standard library, making it trivial to deploy and audit.

## Getting Started

### Prerequisites

- Python 3.10 or later
- pytest (for running tests)

### Installation

Clone the repository and install in development mode:

```bash
git clone https://github.com/icohangar-ops/market-sentiment-fedgpt.git
cd market-sentiment-fedgpt
pip install -e .
```

Or install the test dependencies alongside the package:

```bash
pip install -e ".[dev]"
```

### Quick Start

Run the analysis using the included example data:

```bash
PYTHONPATH=src python -m market_sentiment_fedgpt.cli analyze \
  --indicators examples/market_indicators.csv \
  --speech examples/fed_speech.txt \
  --portfolio examples/portfolio.csv
```

For JSON output, add the `--json` flag:

```bash
PYTHONPATH=src python -m market_sentiment_fedgpt.cli analyze \
  --indicators examples/market_indicators.csv \
  --speech examples/fed_speech.txt \
  --portfolio examples/portfolio.csv \
  --json
```

## Usage

### Python API

```python
from market_sentiment_fedgpt import analyze_market

report = analyze_market(
    indicators_path="examples/market_indicators.csv",
    speech_path="examples/fed_speech.txt",
    portfolio_path="examples/portfolio.csv",
)

# Human-readable Markdown
print(report.to_markdown())

# Key fields
print(f"Regime:   {report.regime}")
print(f"Fed Tone: {report.fed_tone}")
print(f"Score:    {report.sentiment_score}")
print(f"Verified: {report.verification.status} ({report.verification.confidence}%)")

# Policy probability path
for horizon, probability in report.policy_path.items():
    print(f"  {horizon}: {probability:.1%}")
```

### JSON Export

```python
from market_sentiment_fedgpt.core import analyze_market, report_json

report = analyze_market("examples/market_indicators.csv", "examples/fed_speech.txt")
print(report_json(report))
```

### CLI

```bash
# Full analysis with portfolio risk notes
market-sentiment-fedgpt analyze \
  --indicators data/indicators.csv \
  --speech data/fed_speech.txt \
  --portfolio data/portfolio.csv

# Analysis without portfolio (omits risk notes)
market-sentiment-fedgpt analyze \
  --indicators data/indicators.csv \
  --speech data/fed_speech.txt

# Machine-readable JSON
market-sentiment-fedgpt analyze \
  --indicators data/indicators.csv \
  --speech data/fed_speech.txt \
  --json
```

### Input Data Format

**Market Indicators CSV** (`indicator,value,source_date,source`):

```csv
indicator,value,source_date,source
aaii_bull_bear,-18,2025-05-08,AAII
naaim_exposure,42,2025-05-08,NAAIM
vix,26.5,2025-05-08,CBOE
put_call,1.18,2025-05-08,CBOE
consumer_confidence,68,2025-05-01,Conference Board
umich_sentiment,66,2025-05-01,University of Michigan
```

**Portfolio CSV** (`ticker,sector,weight,source`):

```csv
ticker,sector,weight,source
NVDA,Technology,0.14,Google Finance
PLD,Real Estate,0.07,Google Finance
```

### Verification Gate

The verification gate enforces data quality before a report is considered actionable. It checks:

1. All six required indicators are present in the CSV
2. Every indicator row includes a `source_date`
3. The Fed speech text contains at least 40 words
4. Every portfolio row includes a `source` field (when a portfolio is provided)

Reports with violations are marked `REQUIRES_HUMAN_VERIFICATION` with a confidence penalty of 12 points per violation (minimum 50%).

## Project Structure

```
market-sentiment-fedgpt/
+-- .github/
|   +-- workflows/
|       +-- ci.yml              # GitHub Actions CI pipeline
+-- demos/
|   +-- market-sentiment-fedgpt_demo.mp4
+-- examples/
|   +-- fed_speech.txt          # Sample Fed speech transcript
|   +-- market_indicators.csv   # Sample sentiment indicator data
|   +-- portfolio.csv           # Sample portfolio holdings
+-- src/
|   +-- market_sentiment_fedgpt/
|       +-- __init__.py          # Package init, exports analyze_market
|       +-- cli.py               # CLI entry point (argparse)
|       +-- core.py              # Analysis engine, data classes, verification
+-- tests/
|   +-- test_basic.py            # Unit tests for core functions
|   +-- test_market_sentiment.py # Integration tests with example data
+-- LICENSE                      # MIT License
+-- pyproject.toml               # Build configuration
+-- README.md                    # This file
+-- requirements.txt             # Development dependencies
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for any new functionality
4. Ensure all tests pass (`pytest tests/ -v`)
5. Commit with a descriptive message (`git commit -m "Add new analysis feature"`)
6. Push to your branch (`git push origin feature/my-feature`)
7. Open a Pull Request

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

This is not investment advice. It is an auditable research workflow template.
