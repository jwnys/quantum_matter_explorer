"""The run_python timeout must kill the whole process group, not just the leader.

On timeout the tool SIGTERMs the group and then must SIGKILL it even when the
group leader exits promptly: a descendant that ignores SIGTERM would otherwise
survive while the tool reports the group killed. These tests pin that contract,
plus the ordinary OK/ERROR/TIMEOUT paths. Everything runs against a temp run
dir with plain python3, no GPU or Julia.
"""
import importlib
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _impl(run_dir: Path):
    """Reload the module so it picks up QME_RUN_DIR for this test."""
    os.environ["QME_RUN_DIR"] = str(run_dir)
    import qme.tools.python_exec as pe
    importlib.reload(pe)
    return pe.run_python_impl


def test_ok_path():
    with tempfile.TemporaryDirectory() as tmp:
        run = _impl(Path(tmp))
        out = run("print('hello')", timeout_s=30)
        assert out.startswith("status=OK") and "hello" in out


def test_error_path():
    with tempfile.TemporaryDirectory() as tmp:
        run = _impl(Path(tmp))
        out = run("raise ValueError('boom')", timeout_s=30)
        assert out.startswith("status=ERROR") and "ValueError" in out


def test_plain_timeout():
    with tempfile.TemporaryDirectory() as tmp:
        run = _impl(Path(tmp))
        out = run("import time; time.sleep(60)", timeout_s=2)
        assert out.startswith("status=TIMEOUT")


def test_timeout_kills_sigterm_ignoring_descendant():
    # The leader hangs (forcing the timeout); its child ignores SIGTERM and would
    # write a marker file 3 s later. If the group kill is complete, the marker
    # never appears even though the leader died on the initial SIGTERM.
    code = """
import subprocess, sys, time
child = '''
import signal, time, pathlib
signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(3)
pathlib.Path("marker.txt").write_text("survived")
'''
subprocess.Popen([sys.executable, "-c", child])
time.sleep(60)
"""
    with tempfile.TemporaryDirectory() as tmp:
        run = _impl(Path(tmp))
        out = run(code, timeout_s=2)
        assert out.startswith("status=TIMEOUT")
        time.sleep(4)
        assert not (Path(tmp) / "marker.txt").exists(), \
            "a SIGTERM-ignoring descendant survived the group kill"


if __name__ == "__main__":
    test_ok_path()
    test_error_path()
    test_plain_timeout()
    test_timeout_kills_sigterm_ignoring_descendant()
    print("run_python process-group contract checks passed")
