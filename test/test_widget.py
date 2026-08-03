"""Headless tests for ``ExerciseOutputWidget`` and the ``%%exercise`` magic."""
import types

from sandbox_widget import ExerciseOutputWidget
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
    time: `magics_manager.magics["cell"]` (a plain dict) and
    `register_magic_function`. A real `InteractiveShell` is only needed to
    actually *run* a cell (see test_executor.py's `ip` fixture) -- not to
    verify this wiring, so a fake keeps this test isolated and deterministic.
    """

    def __init__(self, cell_magics):
        self.magics_manager = types.SimpleNamespace(magics={"cell": dict(cell_magics)})

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
