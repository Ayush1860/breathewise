"""Write docs/openapi.json from the FastAPI app.

uv run python -m backend.scripts.export_openapi
"""

import json
from pathlib import Path

from backend.app import app

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    OPENAPI_PATH.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
