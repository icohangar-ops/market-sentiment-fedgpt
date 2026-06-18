"""
Airbyte-enhanced data providers for market-sentiment-fedgpt.

Automates the manual CSV/TXT data pipeline by fetching market indicators
from live data sources. Falls back to CSV files when live sources are unavailable.

Setup:
    export AIRBYTE_CLIENT_ID=<your_client_id>
    export AIRBYTE_CLIENT_SECRET=<your_client_secret>
    export FRED_API_KEY=<your_fred_api_key>  # Optional: for direct FRED calls

The Airbyte SDK provides credential management, retry logic, and a unified
interface for data connectors. When financial data connectors (FRED, Alpha Vantage)
are added to Airbyte's catalog, they can be wired in without code changes.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FRED indicator mappings (CSV column name -> FRED series ID)
# ---------------------------------------------------------------------------

FRED_SERIES_MAP = {
    "aaii_bull_bear": "AAII_BULL_BEAR",       # Not directly in FRED -- derived
    "naaim_exposure": None,                      # NAAIM -- not in FRED
    "vix": "VIXCLS",                             # CBOE Volatility Index
    "put_call": "CBOE_PC",                       # CBOE Total Put/Call Ratio (discontinued) or use PC
    "consumer_confidence": "UMCSENT",            # UMich (closest in FRED; Conference Board is not free)
    "umich_sentiment": "UMCSENT",                # University of Michigan Consumer Sentiment
}

# Fallback CSV file paths
FALLBACK_INDICATORS_CSV = "examples/market_indicators.csv"
FALLBACK_SPEECH_TXT = "examples/fed_speech.txt"

# ---------------------------------------------------------------------------
# Airbyte SDK bridge
# ---------------------------------------------------------------------------

_airbyte_available = False
try:
    from airbyte_agent_sdk import connect, Workspace, AirbyteError
    _airbyte_available = True
except ImportError:
    logger.info("airbyte-agent-sdk not installed; using direct API or CSV fallback")


def is_airbyte_available() -> bool:
    """Check if Airbyte SDK is installed and credentials are configured."""
    if not _airbyte_available:
        return False
    return bool(os.environ.get("AIRBYTE_CLIENT_ID") and os.environ.get("AIRBYTE_CLIENT_SECRET"))


# ---------------------------------------------------------------------------
# Direct FRED API client (bridge until Airbyte adds FRED connector)
# ---------------------------------------------------------------------------

FRED_BASE_URL = "https://api.stlouisfed.org/fred"


def _fred_series_url(series_id: str, api_key: str, **params: Any) -> str:
    query = urlencode({**params, "api_key": api_key, "file_type": "json", "series_id": series_id})
    return f"{FRED_BASE_URL}/series/observations?{query}"


def fetch_fred_indicator(series_id: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest observation for a FRED series."""
    try:
        url = _fred_series_url(
            series_id=series_id,
            api_key=api_key,
            sort_order="desc",
            limit=1,
        )
        with urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        obs = data.get("observations", [])
        if obs:
            return {
                "indicator": series_id,
                "value": float(obs[0].get("value", 0)) if obs[0].get("value", ".") != "." else None,
                "source_date": obs[0].get("date", ""),
            }
    except Exception as exc:
        logger.warning("FRED fetch failed for %s: %s", series_id, exc)
    return None


# ---------------------------------------------------------------------------
# Live indicator fetching
# ---------------------------------------------------------------------------

def fetch_live_indicators(api_key: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Fetch market indicators from FRED API, with fallback to CSV file.

    Returns a list of dicts with keys: indicator, value, source_date
    Compatible with the format expected by core._score_indicator().
    """
    fred_key = api_key or os.environ.get("FRED_API_KEY")
    indicators: List[Dict[str, str]] = []

    if fred_key:
        for name, series_id in FRED_SERIES_MAP.items():
            if series_id is None:
                logger.debug("Skipping %s: no FRED series mapping", name)
                continue
            result = fetch_fred_indicator(series_id, fred_key)
            if result and result.get("value") is not None:
                indicators.append({
                    "indicator": name,
                    "value": str(result["value"]),
                    "source_date": result.get("source_date", ""),
                })

    # Fall back to CSV for any missing indicators
    if len(indicators) < 4:  # We need at least 4 of 6
        csv_path = Path(FALLBACK_INDICATORS_CSV)
        if csv_path.exists():
            logger.info("Falling back to CSV for missing indicators")
            existing_names = {i["indicator"] for i in indicators}
            with csv_path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    name = row.get("indicator", "").strip().lower()
                    if name not in existing_names:
                        indicators.append(row)

    return indicators


def fetch_fed_speech_latest(fallback_path: Optional[str] = None) -> str:
    """
    Fetch the latest Fed speech/transcript.

    Currently falls back to a local file. When Airbyte adds a Federal Reserve
    or SEC EDGAR connector, this can be replaced with:

        fed = connect("sec_edgar")
        result = await fed.execute("filings", "search", params={
            "query": "Federal Reserve speech monetary policy",
        })

    Or use the Airbyte MCP server for real-time access.
    """
    path = Path(fallback_path or FALLBACK_SPEECH_TXT)
    if path.exists():
        return path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"No Fed speech text found at {path}. "
        "Provide a speech file or configure an Airbyte connector for SEC EDGAR."
    )


# ---------------------------------------------------------------------------
# Airbyte MCP configuration
# ---------------------------------------------------------------------------

MCP_SERVER_URL = "https://mcp.airbyte.ai/mcp"


def get_mcp_config() -> Dict[str, Any]:
    """
    Return MCP server configuration for connecting AI agents to data sources.

    Use with Claude Desktop, Claude Code, Cursor, or VS Code:
        claude mcp add --transport http airbyte-agent https://mcp.airbyte.ai/mcp
    """
    return {
        "mcp_server_url": MCP_SERVER_URL,
        "setup": {
            "claude_code": "claude mcp add --transport http airbyte-agent https://mcp.airbyte.ai/mcp",
            "cursor": '{"mcpServers": {"Agent MCP": {"url": "https://mcp.airbyte.ai/mcp"}}}',
            "vscode": '{"servers": {"Agent MCP": {"type": "http", "url": "https://mcp.airbyte.ai/mcp"}}}',
        },
        "recommended_connectors": [
            "google_drive (for speech/transcript documents)",
            "notion (for research notes)",
            "slack (for Fed announcement alerts)",
        ],
    }


# ---------------------------------------------------------------------------
# Async Airbyte-powered analysis (for agent/automation use)
# ---------------------------------------------------------------------------

async def analyze_market_via_airbyte(
    api_key: Optional[str] = None,
    portfolio_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full analysis pipeline using Airbyte where available.

    This is the async, Airbyte-native version of analyze_market().
    It fetches indicators from FRED (direct API), loads the Fed speech,
    and runs the core analysis -- all without manual CSV files.
    """
    from market_sentiment_fedgpt.core import (
        _fed_score,
        _portfolio_notes,
        _policy_path,
        _read_csv,
        _regime,
        _score_indicator,
        _verify,
        MarketSentimentReport,
    )

    # Step 1: Fetch live indicators
    indicators = fetch_live_indicators(api_key=api_key)
    scored = [_score_indicator(row) for row in indicators]
    sentiment_score = sum(item.score for item in scored)
    regime = _regime(sentiment_score)

    # Step 2: Load Fed speech
    speech = fetch_fed_speech_latest()
    fed_score = _fed_score(speech)
    fed_tone = "HAWKISH" if fed_score > 1 else "DOVISH" if fed_score < -1 else "BALANCED"

    # Step 3: Policy path
    policy_path = _policy_path(sentiment_score, fed_score)

    # Step 4: Portfolio notes
    portfolio_notes = ["No portfolio file supplied."]
    portfolio_rows = []
    if portfolio_path:
        portfolio_rows = _read_csv(portfolio_path)
        portfolio_notes = _portfolio_notes(portfolio_path, regime, fed_tone)

    # Step 5: Verification
    verification = _verify(indicators, speech, portfolio_path)

    report = MarketSentimentReport(
        regime=regime,
        fed_tone=fed_tone,
        sentiment_score=sentiment_score,
        fed_score=fed_score,
        policy_path=policy_path,
        indicators=scored,
        portfolio_notes=portfolio_notes,
        verification=verification,
    )

    result = report.to_dict()
    result["data_source"] = "airbyte_fred_live" if api_key else "csv_fallback"
    result["airbyte_available"] = is_airbyte_available()
    return result
