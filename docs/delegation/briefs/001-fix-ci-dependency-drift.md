# Brief 001: Fresh installs pass the test suite again (CI green on main)

**Status:** todo · **Size:** S · **Touches:** `requirements.txt` (maybe `.github/workflows/ci.yml`)

## Goal
`pip install -r requirements.txt` into a clean Python 3.11 venv, then the CI test command, passes.
CI on `main` has been red since early June 2026 (every push and the weekly schedule); until
it's green, no delegated PR can be trusted.

## Context
- Reproduced on 2026-10-31 in a clean 3.11 venv: the suite fails at import, before any test runs.
  - `pydantic_ai/messages.py` → `from opentelemetry._events import Event` →
    `ModuleNotFoundError: No module named 'opentelemetry._events'` (resolved opentelemetry-api 1.45.2).
  - After downgrading only `opentelemetry-api`, `chromadb` import fails instead:
    `ImportError: cannot import name '_ON_EMIT_RECURSION_COUNT_KEY' from 'opentelemetry.context'`
    — the opentelemetry api / sdk / exporter packages are now on mismatched versions.
- Root cause: opentelemetry (pulled in transitively by pydantic-ai and chromadb) isn't pinned,
  and newer releases broke the versions of pydantic-ai (<1.0) and chromadb (<1.0) we allow.
- Last green CI run: 2026-06-02 (branch `whitj-pitwallai-7`). Compare its resolved versions if useful.
- Note `requirements.txt` already couples `anthropic<0.70` to pydantic-ai 0.8 — keep that intact.

## In scope
- Add the minimum pins / upper bounds needed so a clean install resolves to a working set,
  with a short comment explaining each pin (same style as the existing anthropic comment).
- If any tests then fail for reasons unrelated to imports, list them in the PR under Follow-ups
  and fix them only if the fix is a one-liner caused by the same dependency drift.

## Out of scope
- Upgrading pydantic-ai to 1.x or chromadb to 1.x (that's a separate brief).
- Changing the CI matrix, Python version, or test selection.
- Fixing the `ws-stress` job.

## Acceptance criteria
- [ ] In a brand-new Python 3.11 venv: `pip install -r requirements.txt` then
      `PYTHONPATH=. PITWALL_DECODE_BACKEND=rules pytest --ignore=tests/test_ws_stress.py -q` passes — paste the summary line in the PR
- [ ] The `test` job is green on the PR
- [ ] Every new pin has a one-line comment saying why
- [ ] PR lists the before/after versions of the opentelemetry packages

## How I'll review it
Check the CI run on the PR, read the `requirements.txt` diff (should be a handful of lines), merge.
