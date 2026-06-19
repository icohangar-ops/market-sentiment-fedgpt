# Databricks notebook source
# MAGIC %md
# MAGIC # Market Sentiment FedGPT — Databricks Dashboard
# MAGIC
# MAGIC Scheduled pipeline for Fed speech scoring, market regime detection,
# MAGIC and sentiment time-series analysis on Delta Lake.

# COMMAND ----------

# MAGIC %pip install requests

# COMMAND ----------

import mlflow
from pyspark.sql import functions as F

CATALOG = "market_sentiment"
SCHEMA = "sentiment_data"

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

mlflow.set_experiment("/Shared/MarketSentiment/pipeline")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Ingest FRED Data

# COMMAND ----------

# MAGIC %run ../pipelines/sentiment_lakehouse

# COMMAND ----------

counts = ingest_all_fred()
print(f"Ingested {sum(counts.values())} total FRED observations")
for label, count in counts.items():
    print(f"  {label}: {count}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Ingest Fed Speech (Example)

# COMMAND ----------

sample_speech = """
The Committee remains strongly committed to returning inflation to its
2 percent objective. In considering additional adjustments to the target range
for the federal funds rate, the Committee will carefully assess incoming data,
the evolving outlook, and the balance of risks. The Committee does not expect
it will be appropriate to reduce the target range until it has gained greater
confidence that inflation is moving sustainably toward 2 percent. In addition,
the Committee will continue reducing its holdings of Treasury securities and
agency debt and agency mortgage-backed securities. The Committee is strongly
committed to supporting maximum employment and returning inflation to its
2 percent objective. In assessing the appropriate stance of monetary policy,
the Committee will continue to monitor the implications of incoming information
for the economic outlook. The Committee would be prepared to adjust the stance
of monetary policy as appropriate if risks emerge that could impede the
attainment of the Committee's goals.
"""

ingest_fed_speech(sample_speech, "FOMC Statement", "2024-06-12")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Run Silver Scoring

# COMMAND ----------

indicators = build_silver_indicators()
display(indicators.select("indicator_label", "value", "score", "date").orderBy("indicator_label"))

# COMMAND ----------

speeches = build_silver_speeches()
display(speeches)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Build Gold Sentiment Index

# COMMAND ----------

gold = build_gold_sentiment_index()
display(gold)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Historical Regime Trend

# COMMAND ----------

regime_history = spark.read.format("delta").table(f"{CATALOG}.{SCHEMA}.silver_regime")
display(
    regime_history
    .orderBy(F.desc("date"))
    .select("date", "regime", "total_score")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Yield Curve (10Y - 2Y Spread)

# COMMAND ----------

fred = spark.read.format("delta").table(f"{CATALOG}.{SCHEMA}.bronze_fred")
t10 = fred.filter(F.col("series_id") == "DGS10").select(F.col("date"), F.col("value").alias("t10y"))
t2 = fred.filter(F.col("series_id") == "DGS2").select(F.col("date"), F.col("value").alias("t2y"))

spread = t10.join(t2, "date").withColumn("spread", F.col("t10y") - F.col("t2y"))
display(spread.orderBy(F.desc("date")).limit(252))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Pipeline Summary

# COMMAND ----------

print("=== Pipeline Summary ===")
for table in ["bronze_fred", "bronze_fed_speeches", "silver_indicators", "silver_fed_tone", "silver_regime", "gold_sentiment_index"]:
    try:
        count = spark.read.format("delta").table(f"{CATALOG}.{SCHEMA}.{table}").count()
        print(f"  {table}: {count} rows")
    except Exception:
        print(f"  {table}: not yet created")
