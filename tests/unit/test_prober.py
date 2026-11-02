import csv
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import event
import prober


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/slow":
            time.sleep(1.5)
        status = 503 if self.path == "/down" else 404 if self.path == "/missing" else 200
        body = b'{"ok": true}'
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Instance-Id", "i-test-a")
        self.send_header("X-AZ", "ap-south-1a")
        self.send_header("X-Region", "ap-south-1")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def probe(url, connect_timeout=2.0, total_timeout=5.0):
    return prober.probe_once(prober.Target.parse(url), 0, connect_timeout, total_timeout)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_success_reads_identity_headers(server):
    res = probe(server + "/")
    assert res.status == 200 and res.error_class == ""
    assert res.headers["x-instance-id"] == "i-test-a"
    assert res.headers["x-az"] == "ap-south-1a"
    assert res.resolved_ip == "127.0.0.1"
    assert res.t_recv_utc_ms >= res.t_send_utc_ms


@pytest.mark.parametrize("path, cls", [("/down", "http_5xx"), ("/missing", "http_other")])
def test_http_errors_are_classified(server, path, cls):
    res = probe(server + path)
    assert res.error_class == cls
    # The identity still arrives on errors, so the analysis can tell which target failed.
    assert res.headers["x-az"] == "ap-south-1a"


def test_refused_connection_is_conn_error():
    # Windows retries a refused connect for about 2 s before failing it, so give
    # it longer than the default 2 s connect timeout here.
    res = probe(f"http://127.0.0.1:{free_port()}/", connect_timeout=4.0)
    assert res.error_class == "conn_error" and res.status is None
    assert res.error_detail.startswith("connect:")


def test_dns_failure_is_conn_error():
    res = probe("http://no-such-host.invalid/")
    assert res.error_class == "conn_error" and res.error_detail.startswith("dns:")


def test_slow_response_hits_total_timeout(server):
    res = probe(server + "/slow", total_timeout=0.5)
    assert res.error_class == "timeout"
    assert 400 < res.latency_ms < 1200


def test_unanswered_connect_is_timeout():
    # A listening socket with a full backlog never completes the handshake
    # on most systems; fall back to a non-routable address if it does.
    res = probe("http://10.255.255.1:81/", connect_timeout=0.3, total_timeout=1.0)
    assert res.error_class in ("timeout", "conn_error")
    assert res.latency_ms < 1500


def test_request_closes_connection():
    req = prober.Target.parse("http://example.test:8080/health").request_bytes().decode()
    assert req.startswith("GET /health HTTP/1.1\r\n")
    assert "Host: example.test:8080\r\n" in req
    assert "Connection: close\r\n" in req


@pytest.mark.parametrize("run_id", ["e1-r01-az-a", "e6b-r05-mumbai", "local-r01-app-a"])
def test_run_dir_layout(tmp_path, run_id):
    assert prober.run_dir_for(tmp_path, run_id) == tmp_path / run_id.split("-r")[0] / run_id


@pytest.mark.parametrize("run_id", ["e1", "e1-1-az-a", "E1-r01-az-a", "e1-r1-az-a", "../e1-r01-x"])
def test_bad_run_ids_are_rejected(tmp_path, run_id):
    with pytest.raises(ValueError):
        prober.run_dir_for(tmp_path, run_id)


def test_open_loop_run_writes_all_three_files(server, tmp_path):
    rc = prober.main([
        server + "/", "--run-id", "t1-r01-unit", "--rate", "20", "--duration", "1.5",
        "--results-dir", str(tmp_path), "--quiet", "--network", "wired",
        "--action", "0.5", "inject_start", "python -c pass",
        "--meta", "hc_interval=5",
    ])
    assert rc == 0
    run_dir = tmp_path / "t1" / "t1-r01-unit"

    rows = read_csv(run_dir / "prober.csv")
    assert list(rows[0]) == prober.PROBER_COLUMNS
    assert len(rows) == 30  # 20/s for 1.5 s
    assert sorted(int(r["seq"]) for r in rows) == list(range(30))
    assert all(r["status"] == "200" and r["az"] == "ap-south-1a" for r in rows)
    sends = sorted(int(r["t_send_utc_ms"]) for r in rows)
    assert 1300 < sends[-1] - sends[0] < 1700  # sent on schedule, not back to back

    events = read_csv(run_dir / "events.csv")
    assert [e["event"] for e in events] == ["probe_start", "inject_start", "probe_end"]
    assert "exit 0" in events[1]["detail"]

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["rate_per_s"] == 20 and meta["client_network"] == "wired"
    assert meta["extra"] == {"hc_interval": "5"}
    assert meta["summary"]["counts"]["ok"] == 30


def test_open_loop_keeps_sending_while_requests_hang(server, tmp_path):
    # Every request takes 1.5 s; a closed loop would manage about 1 in 1 s.
    prober.main([server + "/slow", "--run-id", "t2-r01-unit", "--rate", "20", "--duration", "1",
                 "--results-dir", str(tmp_path), "--quiet"])
    rows = read_csv(tmp_path / "t2" / "t2-r01-unit" / "prober.csv")
    assert len(rows) == 20


def test_refuses_to_overwrite_raw_results(server, tmp_path):
    args = [server + "/", "--run-id", "t3-r01-unit", "--duration", "0.1",
            "--results-dir", str(tmp_path), "--quiet"]
    prober.main(args)
    with pytest.raises(SystemExit):
        prober.main(args)


def test_event_cli_appends(tmp_path):
    event.main(["t4-r01-unit", "inject_start", "--detail", "stopped app-a", "--results-dir", str(tmp_path)])
    event.main(["t4-r01-unit", "restore", "--results-dir", str(tmp_path)])
    rows = read_csv(tmp_path / "t4" / "t4-r01-unit" / "events.csv")
    assert [r["event"] for r in rows] == ["inject_start", "restore"]
    assert rows[0]["detail"] == "stopped app-a"
    assert int(rows[1]["t_utc_ms"]) >= int(rows[0]["t_utc_ms"])
