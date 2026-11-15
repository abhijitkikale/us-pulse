import pathlib

import pytest

import scan_repo

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _scan_text(tmp_path, text):
    (tmp_path / "sample.py").write_text(text, encoding="utf-8")
    return scan_repo.scan(tmp_path)


def test_scan_clean_repo_has_no_violations():
    assert scan_repo.scan(ROOT) == []


@pytest.mark.parametrize(
    "text",
    [
        "x = 'ghp_" + "a1B2c3D4e5" * 3 + "a1B2c3'",
        "k = 'AKIA" + "ABCDEFGHIJKLMNOP'",
        'api_key = "' + "abcdefghij0123456789" + '"',
    ],
)
def test_scan_flags_token_like_string(tmp_path, text):
    assert len(_scan_text(tmp_path, text)) >= 1


@pytest.mark.parametrize(
    "text",
    [
        "import ib_async",
        "ib.placeOrder(c, o)",
        "ib.reqMktData(c)",
        "port = 7497",
        "acct = 'U1234567'",
    ],
)
def test_scan_flags_broker_code(tmp_path, text):
    assert len(_scan_text(tmp_path, text)) >= 1


def test_scan_ignores_word_fragments(tmp_path):
    assert _scan_text(tmp_path, "n = 17497\nid = 'XU12345678'\n") == []


def test_gitignore_blocks_data_and_secrets():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in ["data/*.pkl", "data/raw/", ".env", "*.token", "__pycache__/"]:
        assert entry in lines


def test_no_personal_identifiers_in_tracked_files():
    import subprocess
    needles = ["Kik" + "ale", "gmail" + ".com"]
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    hits = []
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        data = p.read_bytes()
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="ignore")
        hits += [(f, n) for n in needles if n in text]
    assert hits == []
