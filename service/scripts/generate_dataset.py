"""Generate the synthetic resident dataset baked into the image (FR6).

Every record is made up. IDs use the TEST-NNNN-NNNN-NNNN format so they can
never be mistaken for real Aadhaar numbers. The seed is fixed, so running this
again gives the same file.

    python scripts/generate_dataset.py            # writes data/residents.json
    python scripts/generate_dataset.py -n 5000    # a bigger dataset
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 17  # group number

FIRST_NAMES = [
    "Aarav", "Aditi", "Arjun", "Diya", "Ishaan", "Kavya", "Meera", "Nikhil",
    "Pooja", "Rahul", "Riya", "Rohan", "Sanya", "Tanvi", "Vihaan", "Zara",
]
LAST_NAMES = [
    "Bhatt", "Desai", "Iyer", "Joshi", "Kapoor", "Mehta", "Nair", "Patel",
    "Rao", "Reddy", "Shah", "Sharma", "Singh", "Verma",
]
GENDERS = ["M", "F", "T"]

# Fixed record used by /health/deep. Keep in sync with app/config.py.
CANARY = {
    "uid": "TEST-0000-0000-0001",
    "name": "Canary Record",
    "dob": "2000-01-01",
    "gender": "T",
    "otp": "000001",
}


def make_record(rng: random.Random, n: int) -> dict:
    digits = f"{n:012d}"
    dob = date(1950, 1, 1) + timedelta(days=rng.randrange(365 * 55))
    return {
        "uid": f"TEST-{digits[0:4]}-{digits[4:8]}-{digits[8:12]}",
        "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        "dob": dob.isoformat(),
        "gender": rng.choice(GENDERS),
        "otp": f"{rng.randrange(1_000_000):06d}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--count", type=int, default=1000, help="records besides the canary")
    parser.add_argument(
        "-o", "--out", type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "residents.json",
    )
    args = parser.parse_args()

    rng = random.Random(SEED)
    # Start at 1000 so generated IDs never collide with the canary.
    records = [CANARY] + [make_record(rng, 1000 + i) for i in range(args.count)]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        json.dump({"synthetic": True, "records": records}, f, indent=1)
        f.write("\n")
    print(f"wrote {len(records)} records to {args.out}")


if __name__ == "__main__":
    main()
