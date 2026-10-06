"""Lambda entry point for hourly ingest (EventBridge Scheduler)."""

import json
import logging
import os
from datetime import UTC, datetime

import boto3

from backend.schemas import Source
from backend.store import Store
from ingest.run import cams_fetcher, force_fail, run_ingest
from ingest.stations import load_stations

logging.getLogger().setLevel(logging.INFO)


def handler(event, context):
    s3 = boto3.client("s3")
    bucket = os.environ["BUCKET_NAME"]
    store = Store(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    fetchers = [(Source.CAMS_MODEL, cams_fetcher())]  # CPCB, OpenAQ prepend here once keyed
    fetchers = force_fail(fetchers, os.environ.get("FORCE_FAIL", ""))

    def raw_sink(key, payload):
        s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(payload).encode())

    def trigger_forecast():
        boto3.client("lambda").invoke(
            FunctionName=os.environ["FORECAST_FUNCTION"], InvocationType="Event"
        )

    summary = run_ingest(
        datetime.now(UTC), load_stations(), fetchers, store, raw_sink, trigger_forecast
    )
    logging.info("ingest summary %s", summary)
    if not any(summary.values()):
        raise RuntimeError(f"no station ingested any data: {summary}")  # trips the alarm
    return summary
