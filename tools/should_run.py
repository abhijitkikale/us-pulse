"""Guard for the nightly workflow: build only when the US market has closed today.
CLI: python tools/should_run.py <event_name>  ->  prints `run=true` or `run=false` (append to $GITHUB_OUTPUT)."""
import datetime as dt
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import us_calendar  # noqa: E402

BUFFER_MIN = 20


def should_run(now_et: dt.datetime, event: str) -> bool:
    """now_et: New York wall-clock time (naive or aware). A manual dispatch always runs."""
    if event == "workflow_dispatch":
        return True
    close = us_calendar.close_minute(now_et.date())
    if close is None:
        return False
    return now_et.hour * 60 + now_et.minute >= close + BUFFER_MIN


def main(argv):
    from zoneinfo import ZoneInfo
    event = argv[1] if len(argv) > 1 else "schedule"
    now = dt.datetime.now(ZoneInfo(us_calendar.TZ))
    print("run=" + ("true" if should_run(now, event) else "false"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
