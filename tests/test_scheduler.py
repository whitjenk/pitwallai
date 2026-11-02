"""The in-process scheduler and the cache-warming jobs (brief 012).

Frozen clock + temp DB, no network: the warm-up job bodies aren't run here (we
drive ``run_due_jobs`` with our own jobs), and the warm-up builder is checked by
its keys and due times only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import store
from core import calendar as cal
from slack_app import scheduler
from slack_app.scheduler import Job, build_warmup_jobs, run_due_jobs
from store import db as store_db

_NOW = datetime(2026, 11, 7, 17, 0, tzinfo=UTC)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    engine = store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)
    if engine is not None:
        engine.sync_engine.dispose()


def _counting_job(key="job-1", *, due_at=_NOW, grace=timedelta(hours=6), fail=False):
    calls = {"n": 0}

    async def run():
        calls["n"] += 1
        if fail:
            raise RuntimeError("job blew up")

    return Job(key=key, due_at=due_at, run=run, grace=grace), calls


async def test_due_job_runs_once_and_is_recorded(tmp_db):
    await store.init_db()
    job, calls = _counting_job()
    await run_due_jobs([job], _NOW)
    assert calls["n"] == 1
    assert await store.job_has_run("job-1") is True


async def test_second_instance_against_same_db_does_not_rerun(tmp_db):
    await store.init_db()
    job, calls = _counting_job()
    await run_due_jobs([job], _NOW)
    # A fresh list of the same job (as a restart would build) must not re-run it.
    job_again, calls_again = _counting_job()
    await run_due_jobs([job_again], _NOW + timedelta(minutes=1))
    assert calls["n"] == 1 and calls_again["n"] == 0


async def test_job_past_its_grace_is_skipped(tmp_db):
    await store.init_db()
    job, calls = _counting_job(due_at=_NOW - timedelta(hours=7), grace=timedelta(hours=6))
    await run_due_jobs([job], _NOW)
    assert calls["n"] == 0
    assert await store.job_has_run("job-1") is False


async def test_failing_job_is_not_marked_and_retries_next_tick(tmp_db):
    await store.init_db()
    job, calls = _counting_job(fail=True)
    await run_due_jobs([job], _NOW)
    assert calls["n"] == 1
    assert await store.job_has_run("job-1") is False  # failure isn't "done"
    # Next tick, still inside grace: it runs again.
    await run_due_jobs([job], _NOW + timedelta(minutes=1))
    assert calls["n"] == 2


async def test_job_before_its_due_time_waits(tmp_db):
    await store.init_db()
    job, calls = _counting_job(due_at=_NOW + timedelta(minutes=5))
    await run_due_jobs([job], _NOW)
    assert calls["n"] == 0


def test_scheduler_off_starts_no_loop(monkeypatch):
    monkeypatch.setenv("PITWALL_SCHEDULER", "off")
    assert scheduler.scheduler_enabled() is False
    assert scheduler.start_scheduler(lambda: []) is None


# ── warm-up jobs for São Paulo ────────────────────────────────────────────────
def test_warmup_jobs_for_sao_paulo_have_expected_keys_and_times():
    weekend = cal.get_race_weekend("2026_interlagos")
    jobs = {j.key: j.due_at for j in build_warmup_jobs(weekend)}

    def at(y, mo, d, h, mi):
        return datetime(y, mo, d, h, mi, tzinfo=UTC)

    expected = {
        # Each session: reopen (end + 30 min) + 5 and + 40 min.
        "warmup:2026_interlagos:FP1:5": at(2026, 11, 6, 17, 5),
        "warmup:2026_interlagos:FP1:40": at(2026, 11, 6, 17, 40),
        "warmup:2026_interlagos:FP2:5": at(2026, 11, 6, 20, 35),
        "warmup:2026_interlagos:FP2:40": at(2026, 11, 6, 21, 10),
        "warmup:2026_interlagos:FP3:5": at(2026, 11, 7, 16, 5),
        "warmup:2026_interlagos:FP3:40": at(2026, 11, 7, 16, 40),
        "warmup:2026_interlagos:Qualifying:5": at(2026, 11, 7, 19, 35),
        "warmup:2026_interlagos:Qualifying:40": at(2026, 11, 7, 20, 10),
        "warmup:2026_interlagos:Race:5": at(2026, 11, 8, 19, 35),
        "warmup:2026_interlagos:Race:40": at(2026, 11, 8, 20, 10),
    }
    assert jobs == expected
