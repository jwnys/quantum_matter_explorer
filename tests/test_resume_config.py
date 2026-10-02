"""The config a --resume continuation starts from.

A fresh run writes config/effective_config.yaml into its run folder, while runs made
by older versions of this tool carry config/generated_config.yaml. Resume must accept both, and
must prefer the effective config, which records what actually ran (including any
command-line overrides).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import find_parent_config


def _run_dir(tmp: str, config_names: list[str]) -> Path:
    run = Path(tmp) / "run_x"
    (run / "config").mkdir(parents=True)
    for name in config_names:
        (run / "config" / name).write_text("llm:\n  provider: vllm\n")
    return run


def test_effective_config_is_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        run = _run_dir(tmp, ["effective_config.yaml"])
        found = find_parent_config(run)
        assert found is not None and found.name == "effective_config.yaml"


def test_legacy_generated_config_is_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        run = _run_dir(tmp, ["generated_config.yaml"])
        found = find_parent_config(run)
        assert found is not None and found.name == "generated_config.yaml"


def test_effective_config_is_preferred_over_legacy():
    with tempfile.TemporaryDirectory() as tmp:
        run = _run_dir(tmp, ["effective_config.yaml", "generated_config.yaml"])
        found = find_parent_config(run)
        assert found is not None and found.name == "effective_config.yaml"


def test_missing_config_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        run = _run_dir(tmp, [])
        assert find_parent_config(run) is None


if __name__ == "__main__":
    test_effective_config_is_accepted()
    test_legacy_generated_config_is_accepted()
    test_effective_config_is_preferred_over_legacy()
    test_missing_config_returns_none()
    print("all resume-config checks passed")
