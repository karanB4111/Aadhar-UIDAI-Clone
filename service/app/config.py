"""Settings read from the environment (ARCHITECTURE.md 5.1.1).

On EC2, user data reads the instance ID, AZ and region from IMDS on the host and
passes them in. The container itself never calls IMDS (6.3).
"""

import os
import socket
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "data" / "residents.json"

# Record that /health/deep authenticates. Keep in sync with scripts/generate_dataset.py.
CANARY_UID = "TEST-0000-0000-0001"
CANARY_OTP = "000001"


@dataclass(frozen=True)
class Settings:
    instance_id: str
    az: str
    region: str
    app_version: str
    sign_work: int
    signing_key: bytes
    dataset_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        sign_work = int(os.environ.get("SIGN_WORK", "1000"))
        if sign_work < 1:
            raise ValueError("SIGN_WORK must be at least 1")
        return cls(
            # Locally the hostname is the container ID, which is enough to tell
            # two containers apart.
            instance_id=os.environ.get("INSTANCE_ID", socket.gethostname()),
            az=os.environ.get("AZ", "local"),
            region=os.environ.get("REGION", "local"),
            app_version=os.environ.get("APP_VERSION", "dev"),
            sign_work=sign_work,
            # Demo signature only (ARCHITECTURE.md 2.4), so a default key is fine.
            signing_key=os.environ.get("SIGNING_KEY", "demo-key-not-a-secret").encode(),
            dataset_path=Path(os.environ.get("DATASET_PATH", DEFAULT_DATASET)),
        )

    def identity(self) -> dict:
        """The FR2 fields that go on every response."""
        return {
            "instance_id": self.instance_id,
            "az": self.az,
            "region": self.region,
            "app_version": self.app_version,
        }
