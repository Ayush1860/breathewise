## What
<!-- One or two sentences. -->

Closes #

## Why

## Verification
<!-- Paste evidence: test output, curl, CloudWatch screenshot. -->
- [ ] `uv run pytest -q` passes
- [ ] `uv run ruff check . && uv run black --check .` clean
- [ ] Contract unchanged, or fixtures + `docs/openapi.json` regenerated and change is additive
- [ ] No secrets, data dumps or model binaries added

## Reviewer focus
