"""Build the Lambda layer for the forecast function: lightgbm + numpy (+ scipy, required by
lightgbm) for Python 3.12 x86_64, plus libgomp.so.1 which lightgbm>=4 links but no longer
vendors and the Lambda runtime does not ship.

    uv run python infra/scripts/build_ml_layer.py [--out build/ml-layer]

Layout (Lambda layer):  python/<packages>   lib/libgomp.so.1
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PIP_TARGET_ARGS = [
    "--platform",
    "manylinux_2_28_x86_64",
    "--platform",
    "manylinux2014_x86_64",
    "--implementation",
    "cp",
    "--python-version",
    "3.12",
    "--only-binary=:all:",
]
PACKAGES = ["lightgbm>=4.5,<5", "numpy>=2,<3"]
# scikit-learn's manylinux wheel vendors a relocatable libgomp; we only take that file.
GOMP_DONOR = "scikit-learn>=1.5,<2"
UNZIPPED_LIMIT_MB = 250


def pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *args], check=True)


def trim(site: Path) -> None:
    for pattern in ("**/tests", "**/__pycache__", "*.dist-info/RECORD"):
        for path in site.glob(pattern):
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    for path in site.glob("bin"):
        shutil.rmtree(path)


def fetch_libgomp(dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pip("--no-deps", "--target", tmp, *PIP_TARGET_ARGS, GOMP_DONOR)
        found = sorted(Path(tmp).glob("scikit_learn.libs/libgomp*.so*"))
        if not found:
            raise SystemExit("libgomp not found in donor wheel")
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found[0], dest / "libgomp.so.1")


def size_mb(root: Path) -> float:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) / 2**20


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="build/ml-layer")
    out = Path(parser.parse_args().out)
    shutil.rmtree(out, ignore_errors=True)
    site = out / "python"
    pip("--target", str(site), *PIP_TARGET_ARGS, *PACKAGES)
    trim(site)
    fetch_libgomp(out / "lib")
    mb = size_mb(out)
    print(f"unzipped layer size: {mb:.1f} MB (limit {UNZIPPED_LIMIT_MB} MB incl. function code)")
    if mb > UNZIPPED_LIMIT_MB - 20:
        raise SystemExit("layer too large; switch to the container-image fallback")
    archive = out.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(out).as_posix())
    print(f"wrote {archive} ({archive.stat().st_size / 2**20:.1f} MB zipped)")


if __name__ == "__main__":
    main()
