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
