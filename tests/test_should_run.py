import datetime as dt
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from should_run import should_run  # noqa: E402


def et(y, m, d, h, mi):
    return dt.datetime(y, m, d, h, mi)


def test_trading_day_after_close_runs():
    assert should_run(et(2026, 11, 16, 17, 35), "schedule") is True


def test_before_close_plus_buffer_does_not_run():
    assert should_run(et(2026, 11, 16, 16, 10), "schedule") is False
    assert should_run(et(2026, 11, 16, 12, 0), "schedule") is False
    assert should_run(et(2026, 11, 16, 16, 20), "schedule") is True


def test_weekend_does_not_run():
    assert should_run(et(2026, 11, 14, 18, 0), "schedule") is False
    assert should_run(et(2026, 11, 15, 18, 0), "schedule") is False


def test_holiday_does_not_run():
    assert should_run(et(2026, 11, 26, 18, 0), "schedule") is False


def test_early_close_day():
    assert should_run(et(2026, 11, 27, 13, 30), "schedule") is True
    assert should_run(et(2026, 11, 27, 13, 10), "schedule") is False


def test_workflow_dispatch_always_runs():
    assert should_run(et(2026, 11, 14, 3, 0), "workflow_dispatch") is True
    assert should_run(et(2026, 11, 26, 9, 0), "workflow_dispatch") is True


def test_cli_prints_output_line():
    r = subprocess.run([sys.executable, "tools/should_run.py", "workflow_dispatch"], capture_output=True, text=True,
                       cwd=pathlib.Path(__file__).resolve().parent.parent)
    assert r.returncode == 0
    assert r.stdout.strip() == "run=true"
