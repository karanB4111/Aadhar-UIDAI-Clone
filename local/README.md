# local/

Docker compose and nginx for rehearsing failover on a laptop before touching
AWS. Filled by PLAN step 3 (owner: Khushi).

Two copies of the `service/` image, with different `INSTANCE_ID` and `AZ`
values, behind nginx standing in for the ALB. Stopping one container should
move all traffic to the other. nginx is only a stand-in; the measurements that
go in the report (steps 7, 11) are taken against the real ALB on AWS, where
the health-check timing is governed by the target group (ARCHITECTURE.md 5.2),
not by `max_fails` / `fail_timeout` here.

## What is in this folder

| File | Purpose |
|---|---|
| `docker-compose.yml` | `app-a`, `app-b` and `lb` (nginx) on one bridge network |
| `nginx.conf` | upstream block for both apps; stand-in for the ALB |

## Prerequisites

1. Docker Desktop (or Docker Engine) running. `docker compose version` should work.
2. The image built locally. From the repo root:

   ```bash
   cd service
   TAG=$(git rev-parse --short HEAD)
   docker buildx build --platform linux/amd64 --load -t aadhaar-mock:$TAG .
   ```

   On Windows PowerShell use `$TAG = git rev-parse --short HEAD` and
   `-t "aadhaar-mock:$TAG"`.

## Run the stack

From this folder:

```bash
TAG=$(git rev-parse --short HEAD) docker compose up -d
```

PowerShell:

```powershell
$env:TAG = (git rev-parse --short HEAD); docker compose up -d
```

Compose waits for both app containers to pass their own HEALTHCHECK
(`service/Dockerfile`) before it starts nginx, so the first probe below
shouldn't race the boot.

Check it is up:

```bash
curl -s localhost:8080/ | python -m json.tool
curl -s localhost:8080/health
curl -s -X POST localhost:8080/api/v1/authenticate \
    -H 'content-type: application/json' \
    -d '{"uid":"TEST-0000-0000-0001","otp":"000001"}'
```

Hit the service a few times and watch the `X-AZ` header switch:

```bash
for i in 1 2 3 4 5 6; do
    curl -sD- -o /dev/null localhost:8080/health | grep -i 'x-az'
done
```

You should see `ap-south-1a` and `ap-south-1b` alternating (nginx uses
round-robin by default).

## Rehearse the failover

In one terminal, keep hitting the LB:

```bash
# POSIX
while true; do
    curl -sD- -o /dev/null localhost:8080/health | grep -i 'x-az'
    sleep 0.2
done
```

```powershell
# PowerShell
while ($true) {
    (Invoke-WebRequest -UseBasicParsing http://localhost:8080/health).Headers['X-AZ']
    Start-Sleep -Milliseconds 200
}
```

In another terminal, stop one of the apps:

```bash
docker compose stop app-a
```

Expected: within a few requests the stream becomes `ap-south-1b` only.
`restart: "no"` (see `docker-compose.yml`) keeps `app-a` down, which matches
E1 ("process stopped" in ARCHITECTURE.md 8.4).

Bring it back:

```bash
docker compose start app-a
```

Within one `fail_timeout` window (5 s, see `nginx.conf`) nginx probes `app-a`
again and the stream resumes mixing both AZs.

The prober from `tests/` (step 4) runs against this same `localhost:8080`
endpoint to produce the CSV that the analysis scripts (step 5) chart.

## Shut it down

```bash
docker compose down
```

## Notes and gotchas

- The exposed port is **8080** on the host (so port 80 stays free), proxied
  to **80** inside nginx, which forwards to **8000** on each app (uvicorn).
- nginx's `max_fails=1 fail_timeout=5s` is **not** the ALB's `interval=5s,
  unhealthy=2`. It is close enough for a rehearsal but the step 7 report
  numbers come from the AWS ALB.
- Set `TAG` to the SHA of the image you built, or leave it unset and compose
  will try `aadhaar-mock:dev`. If you see `pull access denied`, you did not
  build the image (see "Prerequisites").
- The image is built for `linux/amd64` on purpose (CONTRIBUTING.md). On an
  Apple Silicon laptop Docker Desktop will run it under emulation, which is
  slower but correct; a native arm64 build would not match AWS.
