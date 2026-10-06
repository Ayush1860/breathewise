# Contributing

## Before your first commit
1. `git config user.name` and `git config user.email` must match **your own** GitHub
   account (a verified email). Never commit under another member's identity.
2. `cp .env.example .env` and fill in your own keys. `.env` is never committed.
3. `uv sync` (Python 3.12 is installed automatically by uv).
4. Tool- or editor-specific local config stays local: add it to `.git/info/exclude`,
   not `.gitignore`.

## Workflow
- One feature = one issue = one branch = one PR. Branch: `<initials>/<area>-<short-desc>`
  (e.g. `as/ml-lightgbm-v1`). Use `git worktree` for parallel branches.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).
  `Co-authored-by:` only for genuine pair work between team members.
- `main` is protected: PR + green CI + 1 approval from the other member. No direct pushes.
- Merge with **rebase** only (`gh pr merge --rebase --delete-branch`), so each member's
  commits keep their author on `main`.
- PR description must include verification evidence (test output, curl, logs).
- Test-first for `naqi.py`, `advisory.py`, the best-window finder, feature engineering and
  API handlers.

## API contract
`backend/schemas.py` is the source of truth. After changing it:

    uv run python -m backend.scripts.make_fixtures
    uv run python -m backend.scripts.export_openapi

Contract changes after Phase 1 must be additive. Breaking changes need agreement from the
frontend owner.

## Cloud
Production runs only in the repo owner's AWS account (`breathewise-prod`). Other members
use fixtures, local runs, or a separately named dev stack (`breathewise-dev-<initials>`).
No `sam deploy` without a reviewed resource list and cost estimate.

## Freeze
No merges to `main` after Friday 2026-10-09 18:00 IST.
