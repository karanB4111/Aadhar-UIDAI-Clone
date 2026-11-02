# Mock authentication service (ARCHITECTURE.md 5.1.1).
# Build for the t3.micro (x86_64), even on an Apple Silicon laptop:
#   docker buildx build --platform linux/amd64 -t aadhaar-mock:$(git rev-parse --short HEAD) .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEB_CONCURRENCY=2 \
    SIGN_WORK=1000

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data

RUN useradd --system --uid 10001 --no-create-home app
USER app

EXPOSE 8000

# For local docker compose (step 3). On AWS the ALB health check is what counts.
HEALTHCHECK --interval=10s --timeout=2s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# Exec form so uvicorn is PID 1 and gets SIGTERM from `docker stop`.
# Keep-alive (65 s) must outlast the ALB idle timeout (60 s), or the ALB can
# reuse a connection uvicorn has just closed and return a 502.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "65"]
