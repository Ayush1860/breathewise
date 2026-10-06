"""Lambda entry point for the API (HTTP API -> Mangum -> FastAPI)."""

from mangum import Mangum

from backend.app import app

_asgi = Mangum(app, lifespan="off")


def handler(event, context):
    if isinstance(event, dict) and event.get("warmup"):
        return {"warmup": "ok"}  # scheduled keep-warm ping
    return _asgi(event, context)
