"""Pin the GitHub Actions workflows as text (the project has no YAML dependency)."""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
GATES = [
    "uv run pytest -q",
    "uv run ruff check src tests",
    "uv run ruff format --check src tests",
    "uv run mypy",
]


def test_ci_workflow_runs_the_four_gates_on_both_platforms() -> None:
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert all(gate in text for gate in GATES)
    assert "ubuntu-latest" in text
    assert "windows-latest" in text
    assert 'python-version: "3.12"' in text
    assert "pull_request" in text


def test_tag_workflow_builds_and_uploads_the_exe() -> None:
    text = (WORKFLOWS / "build-exe.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in text or 'tags:\n      - "v*"' in text
    assert "pyinstaller packaging/wardogs-flight-eng.spec" in text
    assert "dist/wardogs-flight-eng.exe" in text
    assert "SHA256SUMS" in text
    assert "upload-artifact" in text
