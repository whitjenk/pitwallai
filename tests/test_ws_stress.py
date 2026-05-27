"""WebSocket stress tests (requires running server subprocess)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from typing import Any

import httpx
import pytest
import websockets

BASE_URL = "http://127.0.0.1:8765"
WS_URL = "ws://127.0.0.1:8765/ws/stream"


@pytest.fixture(scope="module")
def server_process():
    """
    Start uvicorn in a subprocess for integration tests.

    Yields:
        subprocess.Popen handle; terminates after module.
    """
    proc = subprocess.Popen(
        [
            sys.executable,
            "main.py",
            "--mode",
            "rehearsal",
            "--port",
            "8765",
            "--speed",
            "10",
        ],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            response = httpx.get(f"{BASE_URL}/health", timeout=2.0)
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    else:
        proc.kill()
        pytest.fail("Server did not become healthy within 90s")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


async def _collect_events(
    url: str,
    *,
    until_complete: bool = True,
    min_transmissions: int = 0,
    timeout: float = 90.0,
    stop_after: int | None = None,
) -> list[dict[str, Any]]:
    """
    Connect to WebSocket and collect parsed events.

    Args:
        url: WebSocket URL.
        until_complete: Stop after REHEARSAL_COMPLETE.
        min_transmissions: Unused placeholder for API compatibility.
        timeout: Max wait seconds.
        stop_after: Stop after N events if set.

    Returns:
        List of parsed event dicts.
    """
    events: list[dict[str, Any]] = []
    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
        start = time.time()
        while time.time() - start < timeout:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            event = json.loads(raw)
            events.append(event)
            if stop_after is not None and len(events) >= stop_after:
                break
            if until_complete and event.get("event_type") == "REHEARSAL_COMPLETE":
                break
            if len([e for e in events if e.get("event_type") == "TRANSMISSION_DECODED"]) >= min_transmissions and not until_complete:
                break
    return events


@pytest.mark.asyncio
async def test_three_simultaneous_clients_all_receive_events(server_process) -> None:
    """Three concurrent clients each receive transmissions and intel events."""
    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE_URL}/api/rehearsal/start", json={"scenario": "monaco_2024"})

    async def client_run() -> list[dict[str, Any]]:
        return await _collect_events(WS_URL, until_complete=True, timeout=120.0)

    results = await asyncio.gather(client_run(), client_run(), client_run())
    for events in results:
        decoded = [e for e in events if e.get("event_type") == "TRANSMISSION_DECODED"]
        intel = [e for e in events if e.get("event_type") == "COMPETITOR_INTEL_UNCONFIRMED"]
        assert len(decoded) >= 10
        assert len(intel) >= 1


@pytest.mark.asyncio
async def test_mid_session_disconnect_and_reconnect(server_process) -> None:
    """Client 2 uninterrupted; client 1 reconnects and receives later events."""
    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE_URL}/api/rehearsal/start", json={"scenario": "monaco_2024"})

    events_c2: list[dict[str, Any]] = []

    async def run_client2() -> None:
        nonlocal events_c2
        events_c2 = await _collect_events(WS_URL, until_complete=True, timeout=120.0)

    task2 = asyncio.create_task(run_client2())

    events_c1_first: list[dict[str, Any]] = []
    async with websockets.connect(WS_URL) as ws1:
        for _ in range(3):
            raw = await asyncio.wait_for(ws1.recv(), timeout=30.0)
            events_c1_first.append(json.loads(raw))

    await asyncio.sleep(8.0)

    events_c1_late: list[dict[str, Any]] = []
    async with websockets.connect(WS_URL) as ws1b:
        start = time.time()
        while time.time() - start < 60.0:
            raw = await asyncio.wait_for(ws1b.recv(), timeout=10.0)
            event = json.loads(raw)
            events_c1_late.append(event)
            if event.get("event_type") == "REHEARSAL_COMPLETE":
                break

    await task2

    assert len([e for e in events_c2 if e.get("event_type") == "TRANSMISSION_DECODED"]) >= 10
    assert len(events_c1_late) >= 1


@pytest.mark.asyncio
async def test_queue_full_does_not_drop_other_subscribers(server_process) -> None:
    """Slow client 1 does not prevent client 2 from receiving the full stream."""
    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE_URL}/api/rehearsal/start", json={"scenario": "monaco_2024"})

    async def slow_client() -> int:
        count = 0
        async with websockets.connect(WS_URL) as ws:
            for _ in range(3):
                await asyncio.wait_for(ws.recv(), timeout=30.0)
                count += 1
            await asyncio.sleep(45.0)
        return count

    results = await asyncio.gather(
        slow_client(),
        _collect_events(WS_URL, until_complete=True, timeout=120.0),
    )
    events_c2 = results[1]
    decoded_c2 = [e for e in events_c2 if e.get("event_type") == "TRANSMISSION_DECODED"]
    assert len(decoded_c2) >= 10
