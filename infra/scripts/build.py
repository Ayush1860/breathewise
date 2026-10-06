"""Stage Lambda code and build both layers into build/ for `sam build`/`sam deploy`.

    uv run --with pip python infra/scripts/build.py [--skip-ml]

build/code          backend/, ingest/, ml/ packages (no tests, no scripts)
build/common-layer  python/ with pydantic (manylinux, py3.12 x86_64)
build/ml-layer      see build_ml_layer.py
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
PACKAGES = ("backend", "ingest", "ml")
SKIP = shutil.ignore_patterns("tests", "scripts", "__pycache__", "*.pyc")
COMMON = ["pydantic>=2.9,<3"]
sys.path.insert(0, str(Path(__file__).parent))

from build_ml_layer import PIP_TARGET_ARGS  # noqa: E402
from build_ml_layer import main as build_ml_layer  # noqa: E402


def stage_code() -> None:
    dest = BUILD / "code"
    shutil.rmtree(dest, ignore_errors=True)
    for package in PACKAGES:
        shutil.copytree(ROOT / package, dest / package, ignore=SKIP)
    print(f"staged code -> {dest}")


def build_common_layer() -> None:
    dest = BUILD / "common-layer"
    shutil.rmtree(dest, ignore_errors=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--target",
            str(dest / "python"),
            *PIP_TARGET_ARGS,
            *COMMON,
        ],
        check=True,
    )
    print(f"built common layer -> {dest}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-ml", action="store_true")
    args = parser.parse_args()
    stage_code()
    build_common_layer()
    if not args.skip_ml:
        sys.argv = [sys.argv[0], "--out", str(BUILD / "ml-layer")]
        build_ml_layer()


if __name__ == "__main__":
    main()
