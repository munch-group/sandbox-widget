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


def test_exercise_sandbox_and_python_cell_magics_are_distinct_functions():
    # %%exercise/%%sandbox/%%python no longer share one handler -- each
    # combines a different (trailing-expression display, rendering) pair
    # (see register_exercise_magic's docstring), so each needs its own
    # function now.
    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    cell = shell.magics_manager.magics["cell"]
    assert cell["exercise"] is not cell["sandbox"]
    assert cell["exercise"] is not cell["python"]
    assert cell["sandbox"] is not cell["python"]


def test_register_exercise_magic_registers_the_line_magics():
    shell = _FakeShell()
    assert register_exercise_magic(ipython=shell) is True
    assert "sandbox" in shell.magics_manager.magics["line"]
    assert "python" in shell.magics_manager.magics["line"]


def test_sandbox_and_python_line_magics_are_distinct_functions():
    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    assert shell.magics_manager.magics["line"]["sandbox"] is not shell.magics_manager.magics["line"]["python"]


def test_line_magic_handler_is_distinct_from_cell_magic_handler():
    # Guards against accidentally registering a cell handler (line, cell) as
    # a line magic too -- IPython calls a line magic with a single
    # positional argument, so that mistake would blow up at call time.
    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    assert shell.magics_manager.magics["line"]["sandbox"] is not shell.magics_manager.magics["cell"]["exercise"]
    assert shell.magics_manager.magics["line"]["sandbox"].__name__ == "sandbox_file"
    assert shell.magics_manager.magics["line"]["python"].__name__ == "python_file"


def _fake_run_exercise(result, calls=None):
    """A ``run_exercise`` stand-in that records the ``display_last_expr`` it
    was called with (defaulting to the real function's own default, so a
    test that doesn't care can omit the kwarg entirely) and returns a fixed
    result.
    """

    def fake(source, display_last_expr=True):
        if calls is not None:
            calls.append((source, display_last_expr))
        return result

    return fake


def test_exercise_cell_magic_displays_boxed_with_trailing_expr_display_on(monkeypatch):
    calls = []
    monkeypatch.setattr(widget_module, "run_exercise", _fake_run_exercise(ExerciseResult(stdout="hi\n"), calls))
    displayed = []
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: displayed.append(w))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    shell.magics_manager.magics["cell"]["exercise"]("", "print('hi')")

    assert calls == [("print('hi')", True)]
    assert len(displayed) == 1
    assert isinstance(displayed[0], ExerciseOutputWidget)
    assert displayed[0].stdout == "hi\n"


def test_python_cell_magic_suppresses_trailing_expr_display_but_still_boxes_output(monkeypatch):
    calls = []
    monkeypatch.setattr(widget_module, "run_exercise", _fake_run_exercise(ExerciseResult(stdout="hi\n"), calls))
    displayed = []
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: displayed.append(w))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    shell.magics_manager.magics["cell"]["python"]("", "x")

    assert calls == [("x", False)]
    assert len(displayed) == 1
    assert isinstance(displayed[0], ExerciseOutputWidget)


def test_sandbox_cell_magic_renders_plainly_without_a_widget_box(monkeypatch, capsys):
    result = ExerciseResult(
        stdout="out\n", stderr="err\n",
        outputs=[{"text/plain": "1"}],
        error="ValueError: boom", traceback="the traceback\n",
    )
    calls = []
    monkeypatch.setattr(widget_module, "run_exercise", _fake_run_exercise(result, calls))
    published = []
    monkeypatch.setattr(widget_module, "publish_display_data", lambda data, **k: published.append(data))
    displayed = []
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: displayed.append(w))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    shell.magics_manager.magics["cell"]["sandbox"]("", "irrelevant")

    # sandbox keeps %%exercise's notebook-style trailing-expression display...
    assert calls == [("irrelevant", True)]
    # ...but renders like a plain, unstyled cell instead of the widget box:
    # real stdout/stderr streams, published rich outputs, a raw traceback on
    # stderr, and no ExerciseOutputWidget at all.
    captured = capsys.readouterr()
    assert captured.out == "out\n"
    assert captured.err == "err\nthe traceback\n"
    assert published == [{"text/plain": "1"}]
    assert displayed == []


def test_line_magic_reads_a_file_and_forwards_its_contents_to_run_exercise(tmp_path, monkeypatch, capsys):
    script = tmp_path / "script.py"
    script.write_text("x = 1 + 1\n")

    calls = []
    monkeypatch.setattr(widget_module, "run_exercise", _fake_run_exercise(ExerciseResult(stdout="2\n"), calls))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    shell.magics_manager.magics["line"]["sandbox"](str(script))

    assert calls == [("x = 1 + 1\n", True)]
    assert capsys.readouterr().out == "2\n"


def test_python_line_magic_reads_a_file_with_trailing_expr_suppressed_and_boxed_display(tmp_path, monkeypatch):
    script = tmp_path / "script.py"
    script.write_text("x\n")

    calls = []
    monkeypatch.setattr(widget_module, "run_exercise", _fake_run_exercise(ExerciseResult(), calls))
    displayed = []
    monkeypatch.setattr(widget_module, "_ipy_display", lambda w: displayed.append(w))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    shell.magics_manager.magics["line"]["python"](str(script))

    assert calls == [("x\n", False)]
    assert len(displayed) == 1
    assert isinstance(displayed[0], ExerciseOutputWidget)


def test_line_magic_reads_quoted_filenames_with_spaces(tmp_path, monkeypatch):
    # Regression guard for arg_split's posix= argument: with posix=False the
    # surrounding quote characters stay embedded in the parsed token, so a
    # quoted path containing a space would fail to resolve.
    script = tmp_path / "my script.py"
    script.write_text("1 + 1\n")

    calls = []
    monkeypatch.setattr(widget_module, "run_exercise", _fake_run_exercise(ExerciseResult(), calls))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    shell.magics_manager.magics["line"]["sandbox"](f'"{script}"')

    assert calls == [("1 + 1\n", True)]


def test_line_magic_raises_usage_error_on_empty_filename(monkeypatch):
    monkeypatch.setattr(widget_module, "run_exercise", lambda *a, **k: pytest.fail("run_exercise should not run"))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    with pytest.raises(UsageError):
        shell.magics_manager.magics["line"]["sandbox"]("   ")


def test_line_magic_raises_usage_error_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(widget_module, "run_exercise", lambda *a, **k: pytest.fail("run_exercise should not run"))

    missing = tmp_path / "does_not_exist.py"
    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    with pytest.raises(UsageError) as exc_info:
        shell.magics_manager.magics["line"]["sandbox"](str(missing))
    assert str(missing) in str(exc_info.value)


def test_line_magic_raises_usage_error_on_directory_path(tmp_path, monkeypatch):
    monkeypatch.setattr(widget_module, "run_exercise", lambda *a, **k: pytest.fail("run_exercise should not run"))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    with pytest.raises(UsageError):
        shell.magics_manager.magics["line"]["sandbox"](str(tmp_path))


def test_python_line_magic_also_raises_usage_error_on_missing_file(tmp_path, monkeypatch):
    # %python shares _read_source_file with %sandbox -- one direct check
    # that the error path is wired up on this name too.
    monkeypatch.setattr(widget_module, "run_exercise", lambda *a, **k: pytest.fail("run_exercise should not run"))

    shell = _FakeShell()
    register_exercise_magic(ipython=shell)
    with pytest.raises(UsageError):
        shell.magics_manager.magics["line"]["python"](str(tmp_path / "does_not_exist.py"))
