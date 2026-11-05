"""Open-loop failover prober (PLAN step 4, ARCHITECTURE.md 8.3).

Sends GET requests on a fixed schedule (default 20/s), whether or not earlier
requests have answered, and writes one CSV row per request. Each request
resolves the host through the system resolver and opens a new TCP connection
(`Connection: close`), so keep-alive and DNS caching inside the client cannot
hide a failover.

    python tests/prober.py http://localhost:8080/ --run-id e1-r01-az-a --duration 180 \\
        --action 30 inject_start "docker compose -f local/docker-compose.yml stop app-a" \\
        --action 150 restore "docker compose -f local/docker-compose.yml start app-a"

Output, in the layout from CONTRIBUTING.md:

    results/<experiment>/<run_id>/prober.csv   one row per request
    results/<experiment>/<run_id>/events.csv   injections and restores (UTC ms)
    results/<experiment>/<run_id>/meta.json    settings, versions, summary

Standard library only, so it runs on any laptop with Python 3.11+.
"""

import argparse
import csv
import json
import math
import platform
import queue
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

PROBER_VERSION = "3"
REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_ID_RE = re.compile(r"^(?P<experiment>[a-z0-9]+)-r\d{2}-[a-z0-9][a-z0-9-]*$")

# Columns from ARCHITECTURE.md 8.3, plus `seq` (schedule slot, to check the
# open loop kept up), `error_detail` (what exactly failed), and
# `active_url` (the base URL this request went to; constant in single-URL
# mode, flips in --urls client-side failover mode used by E6a/E6b).
PROBER_COLUMNS = [
    "seq", "t_send_utc_ms", "t_recv_utc_ms", "latency_ms", "status", "error_class",
    "error_detail", "instance_id", "az", "region", "resolved_ip", "active_url",
    "run_id",
]
EVENT_COLUMNS = ["t_utc_ms", "event", "detail", "run_id"]
MAX_RESPONSE_BYTES = 64 * 1024


def utc_ms() -> int:
    return time.time_ns() // 1_000_000


def run_dir_for(results_dir: Path, run_id: str) -> Path:
    m = RUN_ID_RE.match(run_id)
    if not m:
        raise ValueError(
            f"run id {run_id!r} must look like <experiment>-r<NN>-<target>, e.g. e1-r01-az-a"
        )
    return results_dir / m["experiment"] / run_id


def append_event(run_dir: Path, run_id: str, event: str, detail: str = "", t_ms: int | None = None) -> int:
    """Append one row to events.csv, creating it with a header if needed."""
    t_ms = utc_ms() if t_ms is None else t_ms
    path = run_dir / "events.csv"
    new = not path.exists()
    run_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(EVENT_COLUMNS)
        w.writerow([t_ms, event, detail, run_id])
    return t_ms


@dataclass
class Target:
    scheme: str
    host: str
    port: int
    path: str

    @classmethod
    def parse(cls, url: str) -> "Target":
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError(f"need an http:// or https:// URL, got {url!r}")
        port = u.port or (443 if u.scheme == "https" else 80)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        return cls(u.scheme, u.hostname, port, path)

    def request_bytes(self) -> bytes:
        default_port = 443 if self.scheme == "https" else 80
        host = self.host if self.port == default_port else f"{self.host}:{self.port}"
        return (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: aadhaar-prober/{PROBER_VERSION}\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode()


@dataclass
class Result:
    seq: int
    t_send_utc_ms: int
    t_recv_utc_ms: int = 0
    latency_ms: float = 0.0
    status: int | None = None
    error_class: str = ""
    error_detail: str = ""
    headers: dict = field(default_factory=dict)
    resolved_ip: str = ""
    active_url: str = ""

    def row(self, run_id: str) -> list:
        return [
            self.seq, self.t_send_utc_ms, self.t_recv_utc_ms, f"{self.latency_ms:.1f}",
            "" if self.status is None else self.status, self.error_class, self.error_detail,
            self.headers.get("x-instance-id", ""), self.headers.get("x-az", ""),
            self.headers.get("x-region", ""), self.resolved_ip, self.active_url, run_id,
        ]


class _Deadline(Exception):
    pass


def _parse_head(head: bytes) -> tuple[int, dict]:
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
        raise ValueError(f"bad status line {lines[0][:60]!r}")
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    return int(parts[1]), headers


def _read_response(sock: socket.socket, deadline: float) -> tuple[int, dict]:
    """Read until the full response has arrived (or EOF), within the deadline."""
    buf = b""
    head_end = -1
    content_length = None
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise _Deadline()
        sock.settimeout(remaining)
        chunk = sock.recv(8192)
        if not chunk:
            break
        buf += chunk
        if head_end < 0:
            head_end = buf.find(b"\r\n\r\n")
            if head_end >= 0:
                status, headers = _parse_head(buf[:head_end])
                if "content-length" in headers:
                    content_length = int(headers["content-length"])
        if head_end >= 0 and content_length is not None and len(buf) - head_end - 4 >= content_length:
            break
        if len(buf) > MAX_RESPONSE_BYTES:
            break
    if head_end < 0:
        raise ConnectionError("empty_response" if not buf else "truncated_headers")
    return status, headers


def probe_once(target: Target, seq: int, connect_timeout: float, total_timeout: float,
               active_url: str = "") -> Result:
    """One request on a fresh connection. Never raises; errors go in the Result."""
    start = time.perf_counter()
    deadline = start + total_timeout
    res = Result(seq=seq, t_send_utc_ms=utc_ms(), active_url=active_url)
    sock = None
    phase = "dns"
    try:
        # The system resolver on every request; Python keeps no DNS cache (5.4.4).
        family, type_, proto, _, addr = socket.getaddrinfo(
            target.host, target.port, type=socket.SOCK_STREAM)[0]
        res.resolved_ip = addr[0]
        phase = "connect"
        sock = socket.socket(family, type_, proto)
        sock.settimeout(max(0.001, min(connect_timeout, deadline - time.perf_counter())))
        sock.connect(addr)
        phase = "read"
        if target.scheme == "https":
            sock.settimeout(max(0.001, deadline - time.perf_counter()))
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=target.host)
        sock.settimeout(max(0.001, deadline - time.perf_counter()))
        sock.sendall(target.request_bytes())
        res.status, res.headers = _read_response(sock, deadline)
        if 200 <= res.status < 300:
            pass
        elif 500 <= res.status < 600:
            res.error_class = "http_5xx"
        else:
            res.error_class = "http_other"
    except (_Deadline, TimeoutError) as exc:
        res.error_class = "timeout"
        res.error_detail = f"{phase}_timeout" if isinstance(exc, TimeoutError) else "total_timeout"
    except socket.gaierror as exc:
        res.error_class = "conn_error"
        res.error_detail = f"dns: {exc.strerror or exc}"
    except (OSError, ValueError) as exc:
        res.error_class = "conn_error"
        res.error_detail = f"{phase}: {type(exc).__name__}" + (f" {exc}" if str(exc) else "")
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    res.t_recv_utc_ms = utc_ms()
    res.latency_ms = (time.perf_counter() - start) * 1000
    return res


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1)]


class Prober:
    def __init__(self, targets: list[tuple[Target, str]], run_id: str, run_dir: Path,
                 rate: float, duration: float | None,
                 connect_timeout: float, total_timeout: float, actions: list[tuple[float, str, str]],
                 switch_after: int = 3, quiet: bool = False):
        # targets: [(Target, original_url), ...]. In single-URL mode (E1, E2,
        # ...) there is one entry. In --urls mode (E6a/E6b) there are two:
        # [primary, secondary]. The active target starts at index 0 and flips
        # to 1 - index after `switch_after` consecutive errors; active_url is
        # recorded on every CSV row so the switch is visible.
        self.targets = targets
        self.run_id = run_id
        self.run_dir = run_dir
        self.rate = rate
        self.duration = duration
        self.connect_timeout = connect_timeout
        self.total_timeout = total_timeout
        self.actions = sorted(actions)
        self.switch_after = switch_after
        self.quiet = quiet
        self.results: "queue.Queue[Result | None]" = queue.Queue()
        self.lags_ms: list[float] = []
        self.counts = {"sent": 0, "ok": 0, "timeout": 0, "conn_error": 0, "http_5xx": 0, "http_other": 0}
        self.action_threads: list[threading.Thread] = []
        # Shared switch state, read by the submit path and written by the
        # writer thread as results come in. A lock keeps the compound
        # read-modify-write atomic.
        self._active_idx = 0
        self._consecutive_errors = 0
        self._switches: list[dict] = []
        self._lock = threading.Lock()

    @property
    def target(self) -> Target:
        """Back-compat shim for one-URL callers/tests."""
        return self.targets[0][0]

    def _writer(self) -> None:
        with (self.run_dir / "prober.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(PROBER_COLUMNS)
            last_flush = time.perf_counter()
            while True:
                res = self.results.get()
                if res is None:
                    break
                w.writerow(res.row(self.run_id))
                self.counts[res.error_class or "ok"] += 1
                self._update_switch_state(res)
                if time.perf_counter() - last_flush > 1:
                    f.flush()
                    last_flush = time.perf_counter()

    def _update_switch_state(self, res: Result) -> None:
        """In --urls mode, flip the active target after N consecutive errors.

        Switch decisions use the URL the request actually went to
        (res.active_url), NOT whatever is currently active when the result
        arrives. With the open loop plus a 5 s total timeout, a burst of
        in-flight requests to a failing target returns as timeouts AFTER
        the first switch; counting those against the new active target
        would thrash (see E6b-r01 for an actual example of this bug).
        Results from a non-active target now only feed into their own
        counter, which is reset on every successful result and discarded
        when the active target flips again.

        Serialised on the writer thread; the submit path reads active_idx
        under the same lock.
        """
        if len(self.targets) < 2:
            return
        with self._lock:
            # Only results from the currently-active URL can trigger a
            # switch. Late results from the previous target are logged in
            # the CSV but ignored here.
            active_url = self.targets[self._active_idx][1]
            if res.active_url != active_url:
                return
            if res.error_class:
                self._consecutive_errors += 1
            else:
                self._consecutive_errors = 0
            if self._consecutive_errors >= self.switch_after:
                prev = self._active_idx
                self._active_idx = 1 - prev
                self._consecutive_errors = 0
                prev_url = self.targets[prev][1]
                new_url = self.targets[self._active_idx][1]
                t = utc_ms()
                detail = f"{prev_url} -> {new_url} after {self.switch_after} consecutive errors"
                self._switches.append({"t_utc_ms": t, "from_url": prev_url, "to_url": new_url, "at_seq": res.seq})
                append_event(self.run_dir, self.run_id, "switch_target", detail, t)
                self._log(f"[{t}] switch_target: {detail}")

    def _active_target(self) -> tuple[Target, str]:
        with self._lock:
            return self.targets[self._active_idx]

    def _run_action(self, event: str, command: str) -> None:
        # The timestamp is taken when the command returns (ARCHITECTURE.md 8.3).
        try:
            proc = subprocess.run(command, shell=True, cwd=REPO_ROOT, capture_output=True, text=True)
            detail = f"{command} (exit {proc.returncode})"
            if proc.returncode != 0:
                detail += f": {(proc.stderr or proc.stdout).strip()[:200]}"
        except OSError as exc:
            detail = f"{command} (failed: {exc})"
        t = append_event(self.run_dir, self.run_id, event, detail)
        self._log(f"[{t}] {event}: {detail}")

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg, file=sys.stderr, flush=True)

    def _progress(self, elapsed: float) -> None:
        c = self.counts
        errors = c["timeout"] + c["conn_error"] + c["http_5xx"] + c["http_other"]
        self._log(f"t={elapsed:6.1f}s sent={c['sent']} ok={c['ok']} errors={errors} "
                  f"(timeout={c['timeout']} conn={c['conn_error']} 5xx={c['http_5xx']} other={c['http_other']})")

    def run(self) -> dict:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        writer = threading.Thread(target=self._writer, name="csv-writer")
        writer.start()
        # Enough threads that a full total-timeout's worth of hung requests never
        # delays the next send: that is what keeps the loop open.
        workers = math.ceil(self.rate * (self.total_timeout + 1)) + 4
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="probe")
        interval = 1.0 / self.rate
        pending_actions = list(self.actions)
        started_utc = utc_ms()
        if len(self.targets) == 1:
            start_detail = f"{self.rate}/s to {self.targets[0][0].host}"
        else:
            hosts = ", ".join(f"{i}:{t.host}" for i, (t, _) in enumerate(self.targets))
            start_detail = f"{self.rate}/s to [{hosts}], switch_after={self.switch_after}"
        append_event(self.run_dir, self.run_id, "probe_start", start_detail, started_utc)
        t0 = time.perf_counter()
        next_progress = 5.0
        seq = 0

        def submit(n: int, scheduled: float) -> None:
            lag = (time.perf_counter() - scheduled) * 1000
            target, active_url = self._active_target()
            res = probe_once(target, n, self.connect_timeout, self.total_timeout, active_url)
            self.lags_ms.append(lag)
            self.results.put(res)

        try:
            while True:
                scheduled = t0 + seq * interval
                elapsed = scheduled - t0
                if self.duration is not None and elapsed >= self.duration:
                    break
                while pending_actions and pending_actions[0][0] <= elapsed:
                    _, event, command = pending_actions.pop(0)
                    t = threading.Thread(target=self._run_action, args=(event, command), daemon=True)
                    t.start()
                    self.action_threads.append(t)
                delay = scheduled - time.perf_counter()
                if delay > 0:
                    # time.sleep is high-resolution on Windows since 3.11;
                    # Event.wait there rounds to about 15 ms.
                    time.sleep(delay)
                pool.submit(submit, seq, scheduled)
                self.counts["sent"] += 1
                seq += 1
                if elapsed >= next_progress:
                    self._progress(elapsed)
                    next_progress += 5.0
        except KeyboardInterrupt:
            self._log("interrupted; waiting for in-flight requests")
        finally:
            ended_utc = utc_ms()
            pool.shutdown(wait=True)
            for t in self.action_threads:
                t.join(timeout=60)
            append_event(self.run_dir, self.run_id, "probe_end", f"{seq} requests scheduled", ended_utc)
            self.results.put(None)
            writer.join()
        if pending_actions:
            self._log(f"warning: {len(pending_actions)} action(s) never ran (run ended first)")
        self._progress(time.perf_counter() - t0)
        return {
            "started_utc_ms": started_utc,
            "ended_utc_ms": ended_utc,
            "requests": seq,
            "counts": {k: v for k, v in self.counts.items() if k != "sent"},
            "send_lag_ms": {
                "p50": _percentile(self.lags_ms, 50),
                "p99": _percentile(self.lags_ms, 99),
                "max": max(self.lags_ms, default=None),
            },
            "actions_not_run": [list(a) for a in pending_actions],
            "switches": list(self._switches),
        }


def _parse_meta(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise argparse.ArgumentTypeError(f"--meta needs key=value, got {pair!r}")
        out[key] = value
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Open-loop failover prober (ARCHITECTURE.md 8.3).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python tests/prober.py http://localhost:8080/ --run-id local-r01-app-a --duration 60",
    )
    p.add_argument("url", nargs="?",
                   help="target, e.g. http://localhost:8080/ or http://<alb-dns>/. "
                        "Mutually exclusive with --urls.")
    p.add_argument("--urls",
                   help="comma-separated primary,secondary base URLs for client-side "
                        "failover (step 11, E6a/E6b). After --switch-after consecutive "
                        "errors on the active URL, the prober switches to the other and "
                        "logs a switch_target event. Mutually exclusive with the positional URL.")
    p.add_argument("--switch-after", type=int, default=3,
                   help="consecutive errors before switching the active URL (default 3). "
                        "Ignored unless --urls is given.")
    p.add_argument("--run-id", required=True, help="<experiment>-r<NN>-<target>, e.g. e1-r01-az-a")
    p.add_argument("--rate", type=float, default=20.0, help="requests per second (default 20)")
    p.add_argument("--duration", type=float, help="seconds to run; default: until Ctrl+C")
    p.add_argument("--connect-timeout", type=float, default=2.0, help="TCP connect timeout, s (default 2)")
    p.add_argument("--total-timeout", type=float, default=5.0, help="whole-request deadline, s (default 5)")
    p.add_argument("--action", nargs=3, action="append", default=[], metavar=("AT_S", "EVENT", "COMMAND"),
                   help="at AT_S seconds into the run, run COMMAND (from the repo root) and log EVENT "
                        "to events.csv when it returns. Repeatable.")
    p.add_argument("--results-dir", type=Path, default=REPO_ROOT / "results")
    p.add_argument("--image-tag", default="", help="image tag under test, for meta.json")
    p.add_argument("--client-location", default="", help="e.g. 'DAU campus' or 'home, Gandhinagar'")
    p.add_argument("--network", choices=["wired", "wifi", "other"], default="other")
    p.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                   help="extra fields for meta.json, e.g. hc_interval=5 instance_type=t3.micro")
    p.add_argument("--quiet", action="store_true", help="no progress output")
    args = p.parse_args(argv)

    if bool(args.url) == bool(args.urls):
        p.error("pass exactly one of: positional URL, or --urls primary,secondary")

    try:
        if args.urls:
            raw = [u.strip() for u in args.urls.split(",") if u.strip()]
            if len(raw) != 2:
                raise ValueError(f"--urls needs exactly 2 comma-separated URLs, got {len(raw)}")
            targets = [(Target.parse(u), u) for u in raw]
        else:
            targets = [(Target.parse(args.url), args.url)]
        run_dir = run_dir_for(args.results_dir, args.run_id)
        actions = [(float(at), event, cmd) for at, event, cmd in args.action]
        extra = _parse_meta(args.meta)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        p.error(str(exc))
    if args.rate <= 0 or args.connect_timeout <= 0 or args.total_timeout <= 0:
        p.error("rate and timeouts must be positive")
    if args.switch_after < 1:
        p.error("--switch-after must be >= 1")
    # Raw results are never overwritten (CONTRIBUTING.md); pick a new run number.
    if (run_dir / "prober.csv").exists():
        p.error(f"{run_dir / 'prober.csv'} already exists; use a new run id")

    meta = {
        "run_id": args.run_id,
        "url": args.url if args.url else None,
        "urls": [u for _, u in targets] if args.urls else None,
        "switch_after": args.switch_after if args.urls else None,
        "rate_per_s": args.rate,
        "duration_s": args.duration,
        "connect_timeout_s": args.connect_timeout,
        "total_timeout_s": args.total_timeout,
        "new_connection_per_request": True,
        "actions": [{"at_s": at, "event": ev, "command": cmd} for at, ev, cmd in actions],
        "git_sha": _git_sha(),
        "image_tag": args.image_tag,
        "client_location": args.client_location,
        "client_network": args.network,
        "tool_versions": {
            "prober": PROBER_VERSION,
            "python": platform.python_version(),
            "os": platform.platform(),
        },
        "extra": extra,
    }
    prober = Prober(targets, args.run_id, run_dir, args.rate, args.duration,
                    args.connect_timeout, args.total_timeout, actions,
                    args.switch_after, args.quiet)
    if not args.quiet:
        where = args.url if args.url else f"[primary={targets[0][1]}, secondary={targets[1][1]}]"
        print(f"probing {where} at {args.rate}/s -> {run_dir}  (Ctrl+C to stop; "
              "is the clock NTP-synced?)", file=sys.stderr)
    meta["summary"] = prober.run()
    meta["written_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with (run_dir / "meta.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    print(json.dumps(meta["summary"]["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
