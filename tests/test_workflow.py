import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".github" / "workflows" / "refresh.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(TEXT)
TRIGGERS = WF.get("on", WF.get(True))          # PyYAML reads the bare key `on` as boolean True
BUILD = WF["jobs"]["build"]
DEPLOY = WF["jobs"]["deploy"]


def _steps():
    return BUILD["steps"]


def _index(needle):
    for i, s in enumerate(_steps()):
        if needle in s.get("run", ""):
            return i
    raise AssertionError(f"no step runs {needle}")


def test_top_level_permissions_empty():
    assert WF["permissions"] == {}


def test_only_schedule_and_dispatch_triggers():
    assert set(TRIGGERS) == {"schedule", "workflow_dispatch"}
    assert all("cron" in c for c in TRIGGERS["schedule"])
    crons = {c["cron"] for c in TRIGGERS["schedule"]}
    assert "35 21 * * 1-5" in crons and "35 22 * * 1-5" in crons


def test_actions_pinned_to_sha():
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", TEXT, re.M)
    assert uses
    for u in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u), u


def test_no_secrets_referenced():
    assert "secrets." not in TEXT


def test_commit_step_only_adds_allowed_files():
    allowed = {"data/sectors.csv", "data/membership.csv", "data/last_count.txt"}
    runs = [s["run"] for s in _steps() if "git add" in s.get("run", "")]
    assert len(runs) == 1
    found = set(re.findall(r"data/[\w.]+", runs[0]))
    assert found == allowed
    assert "git add -A" not in TEXT and "git add ." not in TEXT


def test_scan_runs_before_build():
    assert _index("tools/scan_repo.py") < _index("pipeline/run.py")
    assert _index("pytest") < _index("pipeline/run.py")


def test_job_permissions_and_concurrency():
    assert BUILD["permissions"] == {"contents": "write"}
    assert DEPLOY["permissions"] == {"pages": "write", "id-token": "write"}
    assert DEPLOY["needs"] == "build"
    assert DEPLOY["environment"]["name"] == "github-pages"
    assert WF["concurrency"] == {"group": "refresh", "cancel-in-progress": False}
    assert BUILD["timeout-minutes"] == 90


def test_all_later_steps_gated_by_guard_and_no_continue_on_error():
    steps = _steps()
    guard = next(i for i, s in enumerate(steps) if "should_run.py" in s.get("run", ""))
    for s in steps[guard + 1:]:
        assert "steps.guard.outputs.run" in s.get("if", ""), s
    assert "continue-on-error" not in TEXT
    assert "needs.build.outputs.run" in DEPLOY["if"]


def test_requirements_pinned():
    lines = [l.strip() for l in (ROOT / "requirements.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    assert all("==" in l for l in lines), lines
    assert any(l.startswith("plotly==") for l in lines)
    assert "yfinance==1.2.0" in lines
