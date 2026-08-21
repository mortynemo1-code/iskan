#!/usr/bin/env python3
"""Создаёт демонстрационные устройства и отправляет heartbeat + активность."""

import argparse
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit


DEMO_HOSTNAMES = [
    "anna-design",
    "ivan-backend",
    "olga-sales",
    "max-support",
    "elena-finance",
    "pavel-qa",
    "maria-hr",
    "sergey-devops",
    "dmitry-product",
    "alina-marketing",
]


def hostnames(count: int) -> list[str]:
    """Return stable unique names; the first ten stay human-friendly for demos."""
    return DEMO_HOSTNAMES[:count] + [f"load-agent-{index:04d}" for index in range(11, count + 1)]

ACTIVITIES = [
    ("PRODUCTIVE", "Visual Studio Code", "Code.exe", None),
    ("PRODUCTIVE", "Microsoft Excel", "EXCEL.EXE", None),
    ("NEUTRAL", "Google Chrome", "chrome.exe", "docs.google.com"),
    ("UNPRODUCTIVE", "YouTube Shorts", "chrome.exe", "youtube.com"),
    ("IDLE", None, None, None),
    ("LOCKED", None, None, None),
    ("BREAK", None, None, None),
]

METRICS: dict[str, list[float]] = {}
METRICS_LOCK = threading.Lock()


@dataclass
class Agent:
    hostname: str
    device_id: str
    token: str


def post_json(url: str, payload: dict, bearer: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        endpoint = urlsplit(url).path
        with METRICS_LOCK:
            METRICS.setdefault(endpoint, []).append(elapsed_ms)


def print_metrics() -> None:
    """Print request latency summary suitable for the acceptance protocol."""
    print("\nlatency_summary_ms:", flush=True)
    with METRICS_LOCK:
        snapshot = {key: values[:] for key, values in METRICS.items()}
    for endpoint, values in sorted(snapshot.items()):
        ordered = sorted(values)
        p50 = statistics.median(ordered)
        p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95 + 0.9999) - 1))
        print(
            f"  {endpoint}: count={len(ordered)} p50={p50:.1f} p95={ordered[p95_index]:.1f} max={max(ordered):.1f}",
            flush=True,
        )


def register(server: str, installation_token: str, hostname: str) -> Agent:
    response = post_json(
        f"{server}/api/v1/agent/register",
        {
            "installation_token": installation_token,
            "hostname": hostname,
            "machine_guid": f"simulator-{hostname}",
            "os_version": "Windows 11 Simulator",
            "agent_version": "0.1.0-simulator",
        },
    )
    return Agent(hostname, response["device_id"], response["device_token"])


def demo_events(agent: Agent, now: datetime) -> list[dict]:
    rng = random.Random(agent.hostname + now.date().isoformat())
    cursor = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if cursor > now:
        cursor = now - timedelta(hours=8)
    result: list[dict] = []
    while cursor < now:
        state, app_name, process_name, domain = rng.choices(
            ACTIVITIES,
            weights=[38, 12, 18, 8, 12, 5, 7],
            k=1,
        )[0]
        duration = timedelta(minutes=rng.randint(8, 35))
        end = min(cursor + duration, now)
        stable_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{agent.device_id}:{cursor.isoformat()}:{end.isoformat()}:{state}",
        )
        result.append(
            {
                "event_uuid": str(stable_id),
                "ts_start": cursor.isoformat(),
                "ts_end": end.isoformat(),
                "state": state,
                "process_name": process_name,
                "app_name": app_name,
                "window_title": app_name,
                "url_domain": domain,
                "url_path": "/shorts" if domain == "youtube.com" else None,
                "windows_session_id": 1,
                "is_remote": False,
                "keystrokes": rng.randint(0, 240) if state not in {"IDLE", "LOCKED", "BREAK"} else 0,
                "clicks": rng.randint(0, 45) if state not in {"IDLE", "LOCKED", "BREAK"} else 0,
                "mouse_distance": rng.randint(0, 5000) if state not in {"IDLE", "LOCKED", "BREAK"} else 0,
            }
        )
        cursor = end
    return result


def send_history(server: str, agent: Agent) -> str:
    now = datetime.now(UTC)
    events = demo_events(agent, now)
    response = post_json(
        f"{server}/api/v1/agent/activity/batch",
        {"sent_at": now.isoformat(), "events": events},
        agent.token,
    )
    return f"{agent.hostname}: accepted={response['accepted']}, duplicates={response['duplicates']}"


def send_heartbeat(server: str, agent: Agent, state: str) -> None:
    post_json(
        f"{server}/api/v1/agent/heartbeat",
        {
            "agent_version": "0.1.0-simulator",
            "activity_state": state,
            "cpu_percent": round(random.uniform(0.2, 3.8), 1),
            "ram_mb": random.randint(55, 130),
        },
        agent.token,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://localhost:8080")
    parser.add_argument("--installation-token", required=True)
    parser.add_argument("--agents", type=int, default=5, choices=range(1, 501))
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--once", action="store_true", help="Отправить один heartbeat и завершиться")
    parser.add_argument("--duration", type=int, default=0, help="Остановиться через N секунд; 0 — работать до Ctrl+C")
    parser.add_argument("--workers", type=int, default=20, choices=range(1, 101), help="Параллельные HTTP-запросы")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = args.server.rstrip("/")
    with ThreadPoolExecutor(max_workers=min(args.workers, args.agents)) as executor:
        agents = list(executor.map(lambda name: register(server, args.installation_token, name), hostnames(args.agents)))
        for future in as_completed([executor.submit(send_history, server, agent) for agent in agents]):
            print(future.result(), flush=True)
        list(executor.map(lambda agent: send_heartbeat(server, agent, "PRODUCTIVE"), agents))
    print(f"registered={len(agents)} state=PRODUCTIVE", flush=True)
    if args.once:
        return

    started = time.monotonic()
    while not args.duration or time.monotonic() - started < args.duration:
        time.sleep(args.interval)
        updates = []
        for agent in agents[:-1]:  # Последний агент намеренно становится offline после TTL.
            state = random.choices(
                ["PRODUCTIVE", "NEUTRAL", "UNPRODUCTIVE", "IDLE", "LOCKED", "BREAK"],
                weights=[45, 18, 8, 16, 6, 7], k=1,
            )[0]
            updates.append((agent, state))
        with ThreadPoolExecutor(max_workers=min(args.workers, len(updates) or 1)) as executor:
            list(executor.map(lambda item: send_heartbeat(server, item[0], item[1]), updates))
        print(f"heartbeat={len(updates)} elapsed={int(time.monotonic() - started)}s", flush=True)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        print(f"HTTP {error.code}: {error.read().decode()}")
        raise SystemExit(1)
    finally:
        print_metrics()
