"""Scan the public repo for secrets and broker-related code. Exit 1 on violations."""
import pathlib
import re
import sys

PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub token-like string"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "AWS access key-like string"),
    (re.compile(r"""api[_-]?key\s*[=:]\s*["'][^"']{20,}["']""", re.I), "hard-coded API key"),
    (re.compile(r"ib_async|ib_insync"), "broker library reference"),
    (re.compile(r"\bplaceOrder\b"), "broker order call"),
    (re.compile(r"\breqMktData\b"), "broker market-data call"),
    (re.compile(r"\b7497\b"), "TWS port number"),
    (re.compile(r"\bU\d{7}\b"), "possible broker account id"),
]

SKIP_DIRS = {".git", "data", ".superpowers", "__pycache__", ".pytest_cache"}
SKIP_FILES = {"tools/scan_repo.py", "tests/test_repo_safety.py"}


def _iter_files(root: pathlib.Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if rel.as_posix() in SKIP_FILES:
            continue
        yield path, rel


def scan(root: pathlib.Path) -> list[str]:
    root = pathlib.Path(root)
    violations = []
    for path, rel in _iter_files(root):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for regex, why in PATTERNS:
                if regex.search(line):
                    violations.append(f"{rel.as_posix()}:{lineno}: {why}")
    return violations


if __name__ == "__main__":
    found = scan(pathlib.Path(__file__).resolve().parent.parent)
    for v in found:
        print(v)
    sys.exit(1 if found else 0)
