"""Log a failure injection or restore to a run's events.csv (ARCHITECTURE.md 8.3).

Use this when you inject by hand (AWS CLI, SSM, console) instead of with the
prober's --action. With a command after `--`, it runs the command first and
takes the timestamp when the command returns:

    python tests/event.py e2-r01-az-a inject_start -- aws ec2 stop-instances --instance-ids i-0abc
    python tests/event.py e2-r01-az-a restore --detail "started i-0abc from the console"
"""

import argparse
import subprocess
import sys
from pathlib import Path

from prober import REPO_ROOT, append_event, run_dir_for


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Everything after `--` is the command, so its own flags are not parsed here.
    command = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                usage="%(prog)s run_id event [--detail TEXT] [-- command ...]")
    p.add_argument("run_id", help="same run id the prober is using, e.g. e1-r01-az-a")
    p.add_argument("event", help="inject_start, inject_end, restore, ...")
    p.add_argument("--detail", default="", help="free text stored with the event")
    p.add_argument("--results-dir", type=Path, default=REPO_ROOT / "results")
    args = p.parse_args(argv)

    try:
        run_dir = run_dir_for(args.results_dir, args.run_id)
    except ValueError as exc:
        p.error(str(exc))
    detail = args.detail
    code = 0
    if command:
        code = subprocess.run(command).returncode
        detail = " ".join(filter(None, [detail, f"{' '.join(command)} (exit {code})"]))
    t = append_event(run_dir, args.run_id, args.event, detail)
    print(f"{t} {args.event} {detail}")
    return code


if __name__ == "__main__":
    sys.exit(main())
