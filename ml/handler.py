"""Lambda entry point for the hourly forecast (invoked asynchronously by ingest)."""

import logging
import os
from datetime import UTC, datetime

import boto3

from backend.store import Store
from ingest.stations import load_stations
from ml.forecast_run import run_forecast

_MODEL = None


def _model():
    """Load the packaged model once per container (MODEL_DIR); None -> baseline only."""
    global _MODEL
    model_dir = os.environ.get("MODEL_DIR")
    if _MODEL is None and model_dir and os.path.isdir(model_dir):
        from ml.model import ForecastModel

        _MODEL = ForecastModel.load(model_dir)
    return _MODEL


logging.getLogger().setLevel(logging.INFO)


def handler(event, context):
    store = Store(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    summary = run_forecast(datetime.now(UTC), load_stations(), store, model=_model())
    logging.info("forecast summary %s", summary)
    if not any(summary.values()):
        raise RuntimeError(f"no forecast produced: {summary}")
    return summary
