"""Tests for the %%exercise execution engine (executor.run_exercise).

Every call now spawns a real subprocess (see executor.py's module
docstring), so these are no longer split into a "no shell"/"with a live
shell" pair the way they were before that redesign -- there's only one
path, and every test here pays real subprocess-spawn latency.
"""
import re

from sandbox_widget.executor import run_exercise


def _strip_ansi(text):
    # Traceback text is colored (real ANSI SGR codes -- see
    # test_traceback_carries_ansi_color_codes), which splits a literal
    # substring like "1 / 0" across escape-code boundaries token by token;
    # strip codes first when a test wants to assert on the plain text.
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_trailing_expression_is_captured_as_a_text_output():
    result = run_exercise("a = 10\nb = 5\na + b")
    assert result.success is True
    assert result.outputs == [{"text/plain": "15"}]


def test_stdout_is_captured():
    result = run_exercise("print('hi')")
    assert result.success is True
    assert result.stdout == "hi\n"


def test_assignment_is_not_a_result():
    # No comparable "cell output" for an assignment, exactly like a real
    # notebook cell -- see puzzle_widget.checker's identical convention.
    result = run_exercise("x = 1\nx += 1")
    assert result.success is True
    assert result.outputs == []


def test_empty_cell_succeeds_with_no_output():
    result = run_exercise("")
    assert result.success is True
    assert result.stdout == result.stderr == ""
    assert result.outputs == []


def test_exception_is_caught_and_reported():
    result = run_exercise("1 / 0")
    assert result.success is False
    assert result.error == "ZeroDivisionError: division by zero"
    assert "ZeroDivisionError" in result.traceback


def test_traceback_carries_ansi_color_codes():
    # globalipapp's TerminalInteractiveShell defaults to "nocolor" (sensible
    # for a real terminal, wrong for a Jupyter kernel, whose frontend always
    # renders ANSI regardless of ttys) -- _make_headless_shell forces
    # "neutral" instead so a %%exercise traceback is colored like a real
    # kernel's, not silently plain text.
    result = run_exercise("1 / 0")
    assert "\x1b[" in result.traceback


def test_matplotlib_setup_does_not_leak_to_real_stdout(capfd):
    # %matplotlib inline unconditionally prints "No event loop hook
    # running." under the hood (inline figures need no real GUI event
    # loop) -- since the subprocess inherits, rather than pipes, its
    # stdout, an unredirected leak here would land on the *real* kernel's
    # stdout, bypassing capture_output and showing up outside (not inside)
    # the widget's own output box, or worse, disrupting the widget's own
    # display on that same cell run.
    run_exercise("1 + 1")
    captured = capfd.readouterr()
    assert "No event loop hook running" not in captured.out


def test_traceback_shows_the_cells_own_source_line():
    # The cell is compiled under a synthetic filename, but it's registered
    # with linecache via ip.compile.cache (same trick a real notebook cell
    # uses for itself) precisely so the traceback can show -- and syntax
    # -highlight -- the actual failing line, not just a bare "File ..., line
    # N" with nothing beneath it.
    result = run_exercise("1 / 0")
    assert "1 / 0" in _strip_ansi(result.traceback)


def test_traceback_does_not_leak_internal_executor_frames():
    # A student running this same code as a plain script would never see
    # sandbox_widget's own exec/eval plumbing (_last_line_value,
    # _run_with_ipython) -- only their own code, and anything it calls into.
    result = run_exercise("def f():\n    1 / 0\n\nf()\n")
    assert result.success is False
    assert "_last_line_value" not in result.traceback
    assert "_run_with_ipython" not in result.traceback
    assert "executor.py" not in result.traceback
    plain = _strip_ansi(result.traceback)
    assert "1 / 0" in plain
    assert "f()" in plain


def test_syntax_error_is_caught_and_reported():
    result = run_exercise("if x:")
    assert result.success is False
    assert "SyntaxError" in result.error


def test_each_run_gets_a_fresh_namespace():
    # Nothing a cell defines persists to the next run -- each call is a
    # brand-new subprocess with its own interpreter, not just a fresh dict
    # in the same process.
    run_exercise("leaked = 123")
    result = run_exercise("leaked")
    assert result.success is False
    assert "NameError" in result.error


def test_rcparam_mutation_inside_the_cell_does_not_leak_to_the_notebook_process():
    # The cell runs in its own subprocess with its own sys.modules, so
    # importing an already-loaded library (matplotlib, here) gets a
    # genuinely fresh module in a different process, not a sys.modules
    # cache hit handing back this process's own live object -- mutating
    # its global state inside the cell can't be visible out here.
    import matplotlib.pyplot as plt

    original = plt.rcParams["lines.linewidth"]
    result = run_exercise(
        "import matplotlib.pyplot as plt\n"
        "plt.rcParams['lines.linewidth'] = 99\n"
    )
    assert result.success is True
    assert plt.rcParams["lines.linewidth"] == original


def test_trailing_expression_is_displayed_via_ipython():
    result = run_exercise("a = 10\na")
    assert result.success is True
    assert result.outputs == [{"text/plain": "10"}]


def test_explicit_display_call_is_captured():
    result = run_exercise(
        "from IPython.display import display\n"
        "display({'text/plain': 'explicit'}, raw=True)\n"
    )
    assert {"text/plain": "explicit"} in result.outputs


def test_matplotlib_figure_is_flushed_after_the_cell():
    # No plt.show() needed -- post_execute's flush_figures hook (registered
    # by %matplotlib inline, which the subprocess enables for itself) picks
    # up any still-open figure after the cell finishes, exactly like it
    # would after a normal cell.
    source = "import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\n"
    result = run_exercise(source)
    assert result.success is True
    assert any("image/png" in o for o in result.outputs)


def test_figure_is_flushed_even_if_the_cell_raises_after_drawing():
    source = "import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\nraise ValueError('boom')\n"
    result = run_exercise(source)
    assert result.success is False
    assert "ValueError" in result.error
    assert any("image/png" in o for o in result.outputs)
