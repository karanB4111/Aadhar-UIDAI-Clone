"""Mock Aadhaar-style authentication service (ARCHITECTURE.md 2.1, 5.1).

Endpoints:
    GET  /                      service identity (FR5)
    GET  /health                shallow check for the ALB (FR3)
    GET  /health/deep           canary authentication for Route 53 (FR4)
    POST /api/v1/authenticate   signed Y/N decision (FR1)

Every response, including errors, carries the instance identity in
X-Instance-Id / X-AZ / X-Region / X-App-Version headers. JSON bodies from our
own endpoints carry the same fields (FR2).
"""

from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from . import auth
from .config import CANARY_OTP, CANARY_UID, Settings

settings = Settings.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load before serving, so /health only ever answers once the data is in (5.1.1).
    # A bad dataset stops the worker from starting at all.
    app.state.records = auth.load_dataset(settings.dataset_path)
    yield


app = FastAPI(
    title="Aadhaar HA/DR demo: mock authentication service",
    description="Synthetic data only. Not affiliated with UIDAI.",
    version=settings.app_version,
    lifespan=lifespan,
)


class IdentityHeaders:
    """Pure ASGI middleware: add identity headers to every HTTP response."""

    def __init__(self, app):
        self.app = app
        self.headers = [
            (b"x-instance-id", settings.instance_id.encode()),
            (b"x-az", settings.az.encode()),
            (b"x-region", settings.region.encode()),
            (b"x-app-version", settings.app_version.encode()),
        ]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_identity(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + self.headers
            await send(message)

        await self.app(scope, receive, send_with_identity)


app.add_middleware(IdentityHeaders)


class Demographics(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    dob: date | None = None
    gender: Literal["M", "F", "T"] | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.name is None and self.dob is None and self.gender is None:
            raise ValueError("demo needs at least one of name, dob, gender")
        return self


class AuthRequest(BaseModel):
    # Only the synthetic format is accepted, so a real Aadhaar number is rejected (FR6).
    uid: str = Field(pattern=r"^TEST-\d{4}-\d{4}-\d{4}$", examples=["TEST-0000-0000-0001"])
    otp: str | None = Field(default=None, pattern=r"^\d{6}$", examples=["000001"])
    demo: Demographics | None = None

    @model_validator(mode="after")
    def exactly_one_factor(self):
        if (self.otp is None) == (self.demo is None):
            raise ValueError("send exactly one factor: otp or demo")
        return self


@app.get("/")
async def root():
    return {
        "service": "aadhaar-mock-auth",
        "synthetic_data_only": True,
        **settings.identity(),
    }


@app.get("/health")
async def health(request: Request):
    # Shallow: in-process only, never calls anything outside (FR3).
    if not getattr(request.app.state, "records", None):
        return JSONResponse({"status": "unavailable", **settings.identity()}, status_code=503)
    return {"status": "ok", **settings.identity()}


@app.get("/health/deep")
def health_deep(request: Request):
    # Canary: one real authentication end to end, then check the signature (FR4).
    try:
        result = auth.authenticate(
            request.app.state.records, CANARY_UID, CANARY_OTP, None,
            settings.signing_key, settings.sign_work,
        )
        ok = result["auth"] == "Y" and auth.verify(result, settings.signing_key)
    except Exception as exc:  # any failure means the region should not get traffic
        return JSONResponse(
            {"status": "unavailable", "error": type(exc).__name__, **settings.identity()},
            status_code=503,
        )
    if not ok:
        return JSONResponse(
            {"status": "unavailable", "error": "canary_failed", **settings.identity()},
            status_code=503,
        )
    return {"status": "ok", "txn_id": result["txn_id"], **settings.identity()}


# A plain `def` runs in the threadpool, so CPU-heavy signing does not block the
# event loop and /health keeps answering under load (avoids false ALB removals, 5.2).
@app.post("/api/v1/authenticate")
def authenticate(body: AuthRequest, request: Request):
    demo = None
    if body.demo is not None:
        demo = body.demo.model_dump()
        if demo["dob"] is not None:
            demo["dob"] = demo["dob"].isoformat()
    result = auth.authenticate(
        request.app.state.records, body.uid, body.otp, demo,
        settings.signing_key, settings.sign_work,
    )
    return {**result, **settings.identity()}
