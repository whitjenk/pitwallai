# Brief 000: Get CI green without deleting anything

**Status:** todo · **Size:** S · **Touches:** `requirements.txt`, `intelligence/repository.py`
**Depends on:** nothing. **Do this first.** Every later brief relies on a green CI.
**Protected (must not be edited):** everything under `tests/`

## Goal
CI's `test` job passes on `main` again. It has failed on every run since early June 2026.

## Context
Reproduced on 2026-10-31 in a clean Python 3.11 venv. There are two separate causes:
1. **Dependency drift.** opentelemetry isn't pinned. pydantic-ai 0.8 imports `opentelemetry._events`,
   which opentelemetry-api 1.45 no longer has, and chromadb needs the opentelemetry sdk/exporter
   packages to match the api version. Pinning the whole family to **1.38.0** fixed it locally:
   `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-proto`,
   `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-exporter-otlp-proto-common`.
   The result was 331 passed, 1 failed, 13 errors. The 13 errors were radio tests that download a
   Hugging Face model, which the test sandbox couldn't reach. CI pre-downloads the model, so expect them to pass there.
2. **A real privacy bug.** `tests/test_erase_subscriber.py::test_erase_targets_cover_all_phone_columns`
   fails because the `locked_lineups` table (added with LOCK/SCORE) has a `phone` column that
   isn't in `_ERASE_PHONE_TARGETS` in `intelligence/repository.py`. So `DELETE` leaves a user's
   locked lineups behind.

## In scope
- Pin the five opentelemetry packages above to `==1.38.0` in `requirements.txt`, with a comment
  in the style of the existing anthropic pin: coupled to pydantic-ai 0.8 and chromadb <1.0, remove when brief 003 drops chromadb.
- Add `locked_lineups` to `_ERASE_PHONE_TARGETS`, and make sure the erase actually deletes those rows.

## Out of scope
- Removing radio code or chromadb (brief 003). Upgrading pydantic-ai. Changing CI workflow steps.

## Acceptance criteria
- [ ] CI `test` job is green on the PR. Link the run in the PR description
- [ ] `tests/test_erase_subscriber.py` passes with no edits to `tests/`
- [ ] Diff is under 30 lines (`git diff --shortstat main`)

## How I'll review it
Check that CI is green, read the short diff, merge.
