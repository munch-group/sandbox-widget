"""Headless tests for ``ExerciseOutputWidget`` and the ``%%exercise`` magic."""
import types

import pytest
from IPython.core.error import UsageError

from sandbox_widget import ExerciseOutputWidget
from sandbox_widget import widget as widget_module
from sandbox_widget.executor import ExerciseResult
from sandbox_widget.widget import register_exercise_magic


def test_widget_copies_a_successful_result():
    result = ExerciseResult(stdout="hi\n", outputs=[{"text/plain": "1"}])
    w = ExerciseOutputWidget(result)
    assert w.stdout == "hi\n"
    assert w.outputs == [{"text/plain": "1"}]
    assert w.success is True
    assert w.error == ""
    assert w.traceback == ""


def test_widget_copies_a_failed_result():
    result = ExerciseResult(error="ValueError: boom", traceback="Traceback...\nValueError: boom\n")
    w = ExerciseOutputWidget(result)
    assert w.success is False
    assert w.error == "ValueError: boom"
    assert "boom" in w.traceback


def test_register_exercise_magic_without_a_live_shell_returns_false(monkeypatch):
    # `register_exercise_magic` falls back to the global `get_ipython()` when
    # `ipython` isn't given, same as puzzle_widget's `register_puzzle_magic`.
    # Patch that lookup directly rather than relying on ambient global state
    # (nothing in this process registers a live IPython singleton anymore --
    # run_exercise's own throwaway shell now lives in a subprocess -- but
    # asserting on a real function result shouldn't depend on that happening
    # to stay true either).
    from sandbox_widget import widget as widget_module

    monkeypatch.setattr(widget_module, "get_ipython", lambda: None)
    assert register_exercise_magic(ipython=None) is False


class _FakeShell:
    """The minimal surface `register_exercise_magic` touches at registration
    time: `magics_manager.magics["cell"]`/`["line"]` (plain dicts) and
    `register_magic_function`. A real `InteractiveShell` is only needed to
    actually *run* a cell (see test_executor.py's `ip` fixture) -- not to
    verify this wiring, so a fake keeps this test isolated and deterministic.
    """

    def __init__(self, cell_magics=None, line_magics=None):
        self.magics_manager = types.SimpleNamespace(
            magics={"cell": dict(cell_magics or {}), "line": dict(line_magics or {})}
        )

    def register_magic_function(self, func, magic_kind, magic_name):
        self.magics_manager.magics[magic_kind][magic_name] = func


def test_register_exercise_magic_registers_the_cell_magic():
    shell = _FakeShell(cell_magics={})
    assert register_exercise_magic(ipython=shell) is True
    assert shell.magics_manager.magics["cell"]["exercise"].__name__ == "exercise"


def test_sandbox_is_a_plain_alias_for_exercise():
    # %%sandbox isn't a separate implementation -- it's the exact same
    # handler function registered under a second name (named %%sandbox,
    # not %%script, specifically so it doesn't clash with IPython's own
    # built-in %%script cell magic).
    shell = _FakeShell(cell_magics={})
    register_exercise_magic(ipython=shell)
    assert shell.magics_manager.magics["cell"]["sandbox"] is shell.magics_manager.magics["cell"]["exercise"]


def test_python_cell_magic_is_a_plain_alias_for_exercise():
    # Unlike %%sandbox (chosen to *avoid* clashing with IPython's built-in
    # %%script), %%python is a deliberate *override* of IPython's built-in
    # %%script-shortcut magic of the same name -- but it's still just the
    # same handler under a third name, same as %%sandbox.
    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    assert shell.magics_manager.magics["cell"]["python"] is shell.magics_manager.magics["cell"]["exercise"]


def test_register_exercise_magic_registers_the_line_magics():
    shell = _FakeShell()
    assert register_exercise_magic(ipython=shell) is True
    assert "sandbox" in shell.magics_manager.magics["line"]
    assert "python" in shell.magics_manager.magics["line"]


def test_python_line_magic_is_a_plain_alias_for_sandbox_line():
    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    assert shell.magics_manager.magics["line"]["python"] is shell.magics_manager.magics["line"]["sandbox"]


def test_line_magic_handler_is_distinct_from_cell_magic_handler():
    # Guards against accidentally registering the cell handler exercise(line,
    # cell) as a line magic too -- IPython calls a line magic with a single
    # positional argument, so that mistake would blow up at call time.
    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    assert shell.magics_manager.magics["line"]["sandbox"] is not shell.magics_manager.magics["cell"]["exercise"]
    assert shell.magics_manager.magics["line"]["sandbox"].__name__ == "exercise_file"


def test_line_magic_reads_a_file_and_forwards_its_contents_to_run_exercise(tmp_path, monkeypatch):
    script = tmp_path / "script.py"
    script.write_text("x = 1 + 1\n")

    calls = []
    fake_result = ExerciseResult(stdout="2\n")
    monkeypatch.setattr(widget_module, "run_exercise", lambda source: calls.append(source) or fake_result)
    displayed = []
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: displayed.append(w))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    shell.magics_manager.magics["line"]["sandbox"](str(script))

    assert calls == ["x = 1 + 1\n"]
    assert len(displayed) == 1
    assert isinstance(displayed[0], ExerciseOutputWidget)
    assert displayed[0].stdout == "2\n"


def test_line_magic_reads_quoted_filenames_with_spaces(tmp_path, monkeypatch):
    # Regression guard for arg_split's posix= argument: with posix=False the
    # surrounding quote characters stay embedded in the parsed token, so a
    # quoted path containing a space would fail to resolve.
    script = tmp_path / "my script.py"
    script.write_text("1 + 1\n")

    calls = []
    monkeypatch.setattr(widget_module, "run_exercise", lambda source: calls.append(source) or ExerciseResult())
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: None)

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    shell.magics_manager.magics["line"]["sandbox"](f'"{script}"')

    assert calls == ["1 + 1\n"]


def test_line_magic_raises_usage_error_on_empty_filename(monkeypatch):
    monkeypatch.setattr(widget_module, "run_exercise", lambda source: pytest.fail("run_exercise should not run"))
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: pytest.fail("_ipy_display should not run"))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    with pytest.raises(UsageError):
        shell.magics_manager.magics["line"]["sandbox"]("   ")


def test_line_magic_raises_usage_error_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(widget_module, "run_exercise", lambda source: pytest.fail("run_exercise should not run"))
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: pytest.fail("_ipy_display should not run"))

    missing = tmp_path / "does_not_exist.py"
    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    with pytest.raises(UsageError) as exc_info:
        shell.magics_manager.magics["line"]["sandbox"](str(missing))
    assert str(missing) in str(exc_info.value)


def test_line_magic_raises_usage_error_on_directory_path(tmp_path, monkeypatch):
    monkeypatch.setattr(widget_module, "run_exercise", lambda source: pytest.fail("run_exercise should not run"))
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: pytest.fail("_ipy_display should not run"))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    with pytest.raises(UsageError):
        shell.magics_manager.magics["line"]["sandbox"](str(tmp_path))
