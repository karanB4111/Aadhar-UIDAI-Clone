# service/

The FastAPI mock authentication service, its Dockerfile and the synthetic
dataset. Filled by PLAN step 2 (owner: Kanu).

Spec: ARCHITECTURE.md 2.1 (FR1–FR7) and 5.1.

- Endpoints: `GET /`, `GET /health`, `GET /health/deep`, `POST /api/v1/authenticate`.
- Every response includes `instance_id`, `az`, `region` and `app_version`, read
  from the environment variables `INSTANCE_ID`, `AZ`, `REGION`, `APP_VERSION`.
- `/health` must never call anything outside the process.
- Synthetic data is static JSON baked into the image; IDs start with `TEST-`.
- `SIGN_WORK` sets the CPU cost per authentication (used by calibration E0).
