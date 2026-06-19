"""
market-sentiment-fedgpt — Delta Lake Sentiment Pipeline

Medallion architecture for Fed speech sentiment and market indicators:

  Bronze: Raw FRED series, Fed speech transcripts, portfolio CSVs
  Silver: Scored indicators, classified Fed tone, regime detection
  Gold:   Time-series sentiment index, policy path projections, risk alerts

Integrates with the existing core.py scoring logic while adding
lakehouse-scale storage and historical trend analysis.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql.window import Window
from delta.tables import DeltaTable
import mlflow
import requests
import os
from datetime import datetime, timezone


CATALOG = os.environ.get("DATABRICKS_CATALOG", "market_sentiment")
SCHEMA = os.environ.get("DATABRICKS_SCHEMA", "sentiment_data")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

FRED_SERIES = {
    "vix": "VIXCLS",
    "consumer_confidence": "UMCSENT",
    "fed_funds_rate": "FEDFUNDS",
    "unemployment": "UNRATE",
    "cpi_yoy": "CPIAUCSL",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "sp500": "SP500",
    "aaii_bullish": "AAII_BULLISH_SENTIMENT",
}

HAWKISH_KEYWORDS = [
    "inflation", "restrictive", "tightening", "price stability",
    "rate increase", "hawkish", "overheating", "persistent",
]
DOVISH_KEYWORDS = [
    "cooling", "cuts", "accommodative", "easing", "slowdown",
    "labor market softening", "dovish", "disinflation",
]


def get_spark() -> SparkSession:
    return SparkSession.builder.getOrCreate()


# ---------------------------------------------------------------------------
# Bronze Layer — Raw Ingestion
# ---------------------------------------------------------------------------


def ingest_fred_series(series_id: str, label: str) -> DataFrame:
    """Fetch a FRED time series and write to Bronze."""
    spark = get_spark()

    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1000,
    }
    resp = requests.get(url, params=params, timeout=15)
    observations = resp.json().get("observations", [])

    rows = []
    for obs in observations:
        if obs.get("value", ".") != ".":
            rows.append({
                "series_id": series_id,
                "indicator_label": label,
                "date": obs["date"],
                "value": float(obs["value"]),
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            })

    df = spark.createDataFrame(rows)
    df = df.withColumn("date", F.to_date("date"))
    df = df.withColumn("ingested_at", F.to_timestamp("ingested_at"))

    bronze_table = f"{CATALOG}.{SCHEMA}.bronze_fred"
    df.write.format("delta").mode("append").saveAsTable(bronze_table)

    print(f"[Bronze] FRED {series_id} ({label}): {len(rows)} observations")
    return df


def ingest_all_fred() -> dict[str, int]:
    """Ingest all configured FRED series."""
    counts = {}
    for label, series_id in FRED_SERIES.items():
        try:
            df = ingest_fred_series(series_id, label)
            counts[label] = df.count()
        except Exception as e:
            print(f"[WARN] Failed to ingest {label} ({series_id}): {e}")
            counts[label] = 0
    return counts


def ingest_fed_speech(speech_text: str, speaker: str, date: str) -> DataFrame:
    """Store a Fed speech transcript in Bronze."""
    spark = get_spark()

    row = {
        "speaker": speaker,
        "date": date,
        "text": speech_text,
        "word_count": len(speech_text.split()),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }

    df = spark.createDataFrame([row])
    df = df.withColumn("date", F.to_date("date"))
    df = df.withColumn("ingested_at", F.to_timestamp("ingested_at"))

    bronze_table = f"{CATALOG}.{SCHEMA}.bronze_fed_speeches"
    df.write.format("delta").mode("append").saveAsTable(bronze_table)

    print(f"[Bronze] Fed speech by {speaker} on {date}: {row['word_count']} words")
    return df


# ---------------------------------------------------------------------------
# Silver Layer — Scoring + Classification
# ---------------------------------------------------------------------------


def score_fed_tone_udf():
    """UDF that replicates the core.py _fed_score() keyword counting logic."""

    @F.udf(
        T.StructType([
            T.StructField("tone", T.StringType()),
            T.StructField("hawkish_count", T.IntegerType()),
            T.StructField("dovish_count", T.IntegerType()),
            T.StructField("net_score", T.IntegerType()),
        ])
    )
    def _score(text):
        if not text:
            return ("UNKNOWN", 0, 0, 0)
        text_lower = text.lower()
        hawk = sum(1 for kw in HAWKISH_KEYWORDS if kw in text_lower)
        dove = sum(1 for kw in DOVISH_KEYWORDS if kw in text_lower)
        net = hawk - dove
        if net > 0:
            tone = "HAWKISH"
        elif net < 0:
            tone = "DOVISH"
        else:
            tone = "BALANCED"
        return (tone, hawk, dove, net)

    return _score


def build_silver_speeches() -> DataFrame:
    """Score Fed speeches and write to Silver."""
    spark = get_spark()

    bronze = spark.read.format("delta").table(f"{CATALOG}.{SCHEMA}.bronze_fed_speeches")

    score_udf = score_fed_tone_udf()

    silver = (
        bronze
        .withColumn("tone_analysis", score_udf(F.col("text")))
        .withColumn("tone", F.col("tone_analysis.tone"))
        .withColumn("hawkish_count", F.col("tone_analysis.hawkish_count"))
        .withColumn("dovish_count", F.col("tone_analysis.dovish_count"))
        .withColumn("net_score", F.col("tone_analysis.net_score"))
        .drop("tone_analysis", "text")
    )

    silver_table = f"{CATALOG}.{SCHEMA}.silver_fed_tone"
    silver.write.format("delta").mode("overwrite").saveAsTable(silver_table)

    print(f"[Silver] Fed tone scores -> {silver_table}")
    return silver


def build_silver_indicators() -> DataFrame:
    """
    Score market indicators and detect regime.
    Replicates the core.py indicator scoring: each indicator scored -2 to +2.
    Sum >= 4 = EXUBERANT, <= -4 = FEARFUL, else NEUTRAL.
    """
    spark = get_spark()

    bronze = spark.read.format("delta").table(f"{CATALOG}.{SCHEMA}.bronze_fred")

    latest = (
        bronze
        .withColumn("rn", F.row_number().over(
            Window.partitionBy("indicator_label").orderBy(F.desc("date"))
        ))
        .filter(F.col("rn") == 1)
        .drop("rn")
    )

    indicator_scores = (
        latest
        .withColumn(
            "score",
            F.when(F.col("indicator_label") == "vix",
                F.when(F.col("value") > 30, -2)
                .when(F.col("value") > 20, -1)
                .when(F.col("value") < 12, 2)
                .when(F.col("value") < 15, 1)
                .otherwise(0))
            .when(F.col("indicator_label") == "consumer_confidence",
                F.when(F.col("value") > 100, 2)
                .when(F.col("value") > 80, 1)
                .when(F.col("value") < 60, -2)
                .when(F.col("value") < 70, -1)
                .otherwise(0))
            .otherwise(0)
        )
    )

    silver_table = f"{CATALOG}.{SCHEMA}.silver_indicators"
    indicator_scores.write.format("delta").mode("overwrite").saveAsTable(silver_table)

    # Compute regime
    total_score = indicator_scores.agg(F.sum("score")).collect()[0][0] or 0
    if total_score >= 4:
        regime = "EXUBERANT"
    elif total_score <= -4:
        regime = "FEARFUL"
    else:
        regime = "NEUTRAL"

    regime_df = spark.createDataFrame([{
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "regime": regime,
        "total_score": int(total_score),
        "indicator_count": indicator_scores.count(),
    }])
    regime_table = f"{CATALOG}.{SCHEMA}.silver_regime"
    regime_df.write.format("delta").mode("append").saveAsTable(regime_table)

    print(f"[Silver] Regime: {regime} (score: {total_score}) -> {regime_table}")
    return indicator_scores


# ---------------------------------------------------------------------------
# Gold Layer — Aggregated Time Series
# ---------------------------------------------------------------------------


def build_gold_sentiment_index() -> DataFrame:
    """
    Build a composite sentiment time series at the Gold layer.
    Combines FRED indicators + Fed tone into a daily sentiment score.
    """
    spark = get_spark()

    indicators = spark.read.format("delta").table(f"{CATALOG}.{SCHEMA}.silver_indicators")
    regime = spark.read.format("delta").table(f"{CATALOG}.{SCHEMA}.silver_regime")
    tone = spark.read.format("delta").table(f"{CATALOG}.{SCHEMA}.silver_fed_tone")

    latest_tone = (
        tone
        .orderBy(F.desc("date"))
        .limit(1)
        .select(
            F.col("tone").alias("latest_fed_tone"),
            F.col("net_score").alias("fed_net_score"),
        )
    )

    gold = (
        regime
        .crossJoin(latest_tone)
        .withColumn(
            "composite_sentiment",
            F.col("total_score") + F.col("fed_net_score") * 2
        )
        .withColumn(
            "risk_level",
            F.when(F.col("composite_sentiment") <= -6, "HIGH")
            .when(F.col("composite_sentiment") <= -2, "ELEVATED")
            .when(F.col("composite_sentiment") >= 6, "EUPHORIC")
            .otherwise("NORMAL")
        )
        .withColumn(
            "rate_cut_3m_prob",
            F.when(F.col("latest_fed_tone") == "DOVISH", 0.65)
            .when(F.col("latest_fed_tone") == "HAWKISH", 0.15)
            .otherwise(0.40)
        )
        .withColumn(
            "rate_cut_12m_prob",
            F.when(F.col("latest_fed_tone") == "DOVISH", 0.85)
            .when(F.col("latest_fed_tone") == "HAWKISH", 0.35)
            .otherwise(0.55)
        )
    )

    gold_table = f"{CATALOG}.{SCHEMA}.gold_sentiment_index"
    gold.write.format("delta").mode("append").saveAsTable(gold_table)

    print(f"[Gold] Sentiment index -> {gold_table}")
    return gold


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------


def run_full_pipeline():
    """Execute the complete Bronze → Silver → Gold sentiment pipeline."""
    with mlflow.start_run(run_name="sentiment_pipeline"):
        mlflow.set_tag("pipeline", "market_sentiment_fedgpt")

        # Bronze
        counts = ingest_all_fred()
        total_fred = sum(counts.values())
        mlflow.log_metric("fred_observations_ingested", total_fred)

        # Silver
        indicators = build_silver_indicators()
        mlflow.log_metric("indicator_count", indicators.count())

        speeches = build_silver_speeches()
        mlflow.log_metric("speeches_scored", speeches.count())

        # Gold
        gold = build_gold_sentiment_index()
        row = gold.collect()[0] if gold.count() > 0 else None
        if row:
            mlflow.log_metric("composite_sentiment", row["composite_sentiment"])
            mlflow.set_tag("regime", row["regime"])
            mlflow.set_tag("risk_level", row["risk_level"])
            mlflow.set_tag("fed_tone", row["latest_fed_tone"])

        print("Sentiment pipeline complete")


if __name__ == "__main__":
    run_full_pipeline()
