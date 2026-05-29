"""
Multi-client WebSocket stress tests.

Requires the server to be running before execution:
    python main.py --mode rehearsal --speed 10.0 &

Run with:
    pytest tests/test_ws_stress.py -v --timeout=120
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import websockets

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws/stream"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _health_ok_sync() -> bool:
    """Return True when the PitWallAI health endpoint responds 200."""
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=1.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


SERVER_ALREADY_RUNNING = _health_ok_sync()


@pytest.fixture(scope="module")
def server_process():
    """
    Start the server subprocess unless one is already listening on port 8000.

    Yields:
        subprocess.Popen instance, or None when using an external server.
    """
    proc: subprocess.Popen[str] | None = None

    if not SERVER_ALREADY_RUNNING:
        proc = subprocess.Popen(
            [sys.executable, "main.py", "--mode", "rehearsal", "--speed", "10.0"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        async def wait_for_health() -> None:
            deadline = time.time() + 10.0
            async with httpx.AsyncClient() as client:
                while time.time() < deadline:
                    try:
                        response = await client.get(f"{BASE_URL}/health", timeout=1.0)
                        if response.status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.25)
            raise RuntimeError("Server did not become healthy within 10 seconds")

        try:
            asyncio.run(wait_for_health())
        except RuntimeError:
            proc.kill()
            raise

    yield proc

    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _decoded_count(events: list[dict[str, Any]]) -> int:
    """Count TRANSMISSION_DECODED events in a collected list."""
    return sum(1 for event in events if event.get("event_type") == "TRANSMISSION_DECODED")


async def _collect_until_complete(
    url: str,
    *,
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    """
    Collect WebSocket events until REHEARSAL_COMPLETE or timeout.

    Args:
        url: WebSocket URL.
        timeout: Maximum seconds to wait.

    Returns:
        Parsed event dicts.
    """
    events: list[dict[str, Any]] = []
    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            event = json.loads(raw)
            events.append(event)
            if event.get("event_type") == "REHEARSAL_COMPLETE":
                break
    return events


async def _run_connected_client(
    ws: websockets.WebSocketClientProtocol,
    *,
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    """Read from an already-connected WebSocket until REHEARSAL_COMPLETE or timeout."""
    events: list[dict[str, Any]] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        except asyncio.TimeoutError:
            continue
        event = json.loads(raw)
        events.append(event)
        if event.get("event_type") == "REHEARSAL_COMPLETE":
            break
    return events


@pytest.mark.asyncio
async def test_three_simultaneous_clients_all_receive_events(server_process) -> None:
    """Three concurrent clients each receive transmissions and competitor intel."""
    async with (
        websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws_a,
        websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws_b,
        websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws_c,
    ):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{BASE_URL}/api/rehearsal/start",
                json={"scenario": "monaco_2024"},
            )

        results = await asyncio.gather(
            _run_connected_client(ws_a, timeout=60.0),
            _run_connected_client(ws_b, timeout=60.0),
            _run_connected_client(ws_c, timeout=60.0),
        )

    for events in results:
        assert _decoded_count(events) >= 10
        intel = [e for e in events if e.get("event_type") == "COMPETITOR_INTEL_UNVERIFIED"]
        assert len(intel) >= 1


@pytest.mark.asyncio
async def test_mid_session_disconnect_and_reconnect(server_process) -> None:
    """Client 2 continues through client 1 disconnect; client 1 reconnects and resumes."""
    events_c2: list[dict[str, Any]] = []
    stop_c2 = asyncio.Event()

    async def collect_client2(ws: websockets.WebSocketClientProtocol) -> None:
        while not stop_c2.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                break
            events_c2.append(json.loads(raw))

    async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws2:
        task_c2 = asyncio.create_task(collect_client2(ws2))

        events_c1: list[dict[str, Any]] = []
        events_c1_late: list[dict[str, Any]] = []
        ws1 = await websockets.connect(WS_URL, ping_interval=20, ping_timeout=10)
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{BASE_URL}/api/rehearsal/start",
                    json={"scenario": "monaco_2024"},
                )

            while len(events_c1) < 3:
                raw = await asyncio.wait_for(ws1.recv(), timeout=30.0)
                events_c1.append(json.loads(raw))

            count_c2_at_disconnect = len(events_c2)
            await ws1.close()

            deadline = time.time() + 60.0
            while time.time() < deadline and len(events_c2) < count_c2_at_disconnect + 3:
                await asyncio.sleep(0.05)

            assert len(events_c2) >= count_c2_at_disconnect + 3

            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws1b:
                start = time.time()
                while time.time() - start < 60.0 and len(events_c1_late) < 2:
                    raw = await asyncio.wait_for(ws1b.recv(), timeout=10.0)
                    events_c1_late.append(json.loads(raw))
        finally:
            await ws1.wait_closed()
            stop_c2.set()
            await task_c2

    assert len(events_c1_late) >= 2


@pytest.mark.skip(
    reason="requires in-process server — run via test_resilience.py patterns"
)
@pytest.mark.asyncio
async def test_queue_full_does_not_drop_other_subscribers(server_process) -> None:
    """
    Fan-out QueueFull behaviour cannot be reproduced reliably via external HTTP.

    The unit-level consumer fan-out is covered by patterns in test_resilience.py;
    monkeypatching subscriber queue maxsize requires in-process server access.
    """
    pass
