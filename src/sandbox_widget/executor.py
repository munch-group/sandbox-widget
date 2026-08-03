"""sandbox_widget.executor
=========================

The engine behind the ``%%exercise`` widget: run a cell body in a **fresh
subprocess** -- a brand-new Python interpreter, spawned fresh and discarded
after exactly one run -- not merely a fresh namespace in the current
process. Nothing a cell defines, imports, or mutates persists past that one
run, and nothing the notebook has already defined or imported is visible to
it at all: even ``import matplotlib.pyplot as plt`` inside the cell gets a
genuinely fresh module, not a ``sys.modules`` cache hit handing back the
notebook's own live object, so a mutation like
``plt.rcParams['lines.linewidth'] = 5`` inside the cell can never leak back
out.

``run_exercise`` never raises: a ``SyntaxError`` from the cell, any
exception the cell's own code raises, or the subprocess dying outright is
caught and reported via ``ExerciseResult.error``/``.traceback`` instead.
"""

from __future__ import annotations

import ast
import contextlib
import io
import multiprocessing
import sys
import traceback

__all__ = ["ExerciseResult", "run_exercise"]


class ExerciseResult:
    """The outcome of running one ``%%exercise`` cell.

    Attributes
    ----------
    stdout : str
        Everything the cell printed to stdout.
    stderr : str
        Everything the cell printed to stderr.
    outputs : list of dict
        Rich display MIME bundles produced by the cell -- a trailing bare
        expression's repr, an explicit ``display(...)`` call, or a
        matplotlib figure flushed after execution. Each entry maps MIME
        type to its data, e.g. ``{"image/png": "<base64>", "text/plain":
        "..."}``.
    error : str or None
        A short ``"ExceptionType: message"`` summary if the cell failed to
        parse or raised while running, else ``None``.
    traceback : str or None
        The full formatted traceback for ``error``, else ``None``. Carries
        the same ANSI color codes as a normal uncaught-exception traceback
        (captured via the subprocess's own ``ip.InteractiveTB``), except
        for a plain-text ``SyntaxError`` (caught before the subprocess's
        shell is even set up) or a subprocess that died outright.
    """

    __slots__ = ("stdout", "stderr", "outputs", "error", "traceback")

    def __init__(self, stdout="", stderr="", outputs=None, error=None, traceback=None):
        self.stdout = stdout
        self.stderr = stderr
        self.outputs = outputs or []
        self.error = error
        self.traceback = traceback

    @property
    def success(self):
        return self.error is None

    def __repr__(self):
        return (
            f"ExerciseResult(success={self.success!r}, error={self.error!r}, "
            f"outputs={len(self.outputs)})"
        )


def _last_line_value(tree, namespace, filename):
    """Run every statement in ``tree`` except the last in ``namespace``,
    then return the value associated with the last one -- mirroring how a
    Jupyter cell only ever shows an *output* for a bare trailing
    expression, never for a statement like an assignment (see
    ``puzzle_widget.checker``'s identical helper for the same rationale):

    - if it's a bare expression (``ast.Expr``), the expression's value;
    - otherwise (e.g. an assignment), the line still runs -- so a runtime
      error there is still caught by the caller -- but there is no
      comparable "cell output", so this returns ``None``.

    ``filename`` must be a name ``linecache`` can already resolve (see
    ``ip.compile.cache`` in ``_run_with_ipython``) -- both fragments below
    keep the *original* line numbers from ``tree`` (slicing ``tree.body``
    doesn't renumber anything), so a traceback frame from either one still
    points at the right line of the real cached source.
    """
    if not tree.body:
        return None
    *body, last = tree.body
    if body:
        exec(compile(ast.Module(body=body, type_ignores=[]), filename, "exec"), namespace)
    if isinstance(last, ast.Expr):
        return eval(compile(ast.Expression(body=last.value), filename, "eval"), namespace)
    exec(compile(ast.Module(body=[last], type_ignores=[]), filename, "exec"), namespace)
    return None


def run_exercise(source):
    """Run ``source`` in a fresh, fully isolated **subprocess** and capture
    everything it produced.

    The cell body runs in a brand-new Python interpreter -- spawned via
    ``multiprocessing`` (the ``"spawn"`` start method specifically: safe to
    call from a live, multi-threaded Jupyter kernel process, unlike
    ``fork``), one disposable process per call, never reused across cells.
    That's what makes the isolation real: an ``import`` inside the cell
    always gets a genuinely fresh module, even for something the notebook
    has already imported -- there's no ``sys.modules`` cache hit handing
    back the notebook's own live object, and no way for the cell to mutate
    shared state (e.g. matplotlib ``rcParams``) that's still visible once
    the subprocess exits.

    The subprocess sets up its own throwaway IPython shell (via
    ``IPython.testing.globalipapp``, with ``%matplotlib inline`` enabled)
    so stdout/stderr, rich ``display()`` output, and matplotlib figures are
    still captured exactly as before -- that capture machinery
    (``_run_with_ipython``) is unchanged, just running on the other side of
    a process boundary now. One consequence: a figure drawn inside
    ``%%exercise`` renders with a pristine default backend/rcParams, not
    whatever the notebook's own matplotlib session has been configured to
    at runtime -- there's no live session left to share.

    Parameters
    ----------
    source : str
        The cell body.

    Returns
    -------
    ExerciseResult
    """
    return _run_isolated(source)


def _run_isolated(source):
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe()
    process = ctx.Process(target=_child_main, args=(source, child_conn))
    process.start()
    child_conn.close()
    try:
        result = parent_conn.recv()
    except EOFError:
        # The child died (crashed, was killed) before sending anything.
        result = None
    process.join()

    if result is None:
        return ExerciseResult(
            error=f"Exercise process exited unexpectedly (exit code {process.exitcode}).",
        )
    return result


def _child_main(source, conn):
    """Entry point run inside the spawned subprocess: parse, execute, and
    capture ``source``, then send the resulting ``ExerciseResult`` back
    through ``conn`` before this disposable interpreter exits.
    """
    try:
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as e:
            result = ExerciseResult(error=f"SyntaxError: {e.msg}", traceback=traceback.format_exc())
        else:
            ip = _make_headless_shell()
            result = _run_with_ipython(tree, {}, ip, source)
    except BaseException as e:  # pragma: no cover - defensive fallback
        result = ExerciseResult(error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc())
    conn.send(result)
    conn.close()


def _make_headless_shell():
    """A throwaway IPython shell for the subprocess to execute against --
    same mechanism ``IPython.testing.globalipapp`` uses for headless
    testing (no real terminal needed), just re-created fresh in a
    brand-new process instead of a test process.
    """
    from IPython.testing.globalipapp import get_ipython

    shell = get_ipython()
    # globalipapp hands back a TerminalInteractiveShell, which (reasonably,
    # for a real terminal) auto-detects "nocolor" when there's no tty --
    # exactly the case here. A real Jupyter kernel's shell defaults to
    # "neutral" (color on) instead, since its frontend always renders ANSI
    # colors regardless of ttys; force the same default here, or
    # ip.InteractiveTB.structured_traceback() silently returns plain,
    # uncolored text.
    shell.colors = "neutral"
    try:
        # `%matplotlib inline` unconditionally calls `enable_gui(None)`
        # under the hood (inline figures need no real GUI event loop), which
        # unconditionally prints "No event loop hook running." -- benign,
        # but `multiprocessing.Process` doesn't redirect this subprocess's
        # stdout to a pipe, so an un-redirected print here goes straight to
        # the *real* kernel's stdout, bypassing capture_output entirely and
        # leaking out next to (not inside) the widget's own output box.
        with contextlib.redirect_stdout(io.StringIO()):
            shell.run_line_magic("matplotlib", "inline")
    except Exception:
        # matplotlib isn't a sandbox_widget runtime dependency (dev/test
        # only) -- fine if it's simply not installed here.
        pass
    # globalipapp's TerminalInteractiveShell restricts rich display to
    # text/plain by default (sensible for a real terminal, not a Jupyter
    # kernel) -- widen it so this shell behaves like a real kernel.
    shell.display_formatter.active_types = shell.display_formatter.format_types
    return shell


def _run_with_ipython(tree, namespace, ip, source):
    from IPython.display import display as ipy_display
    from IPython.utils.capture import capture_output

    # Register the cell's real source with linecache under a name IPython's
    # own compiler cache hands out (exactly what a real notebook cell does
    # for itself) -- without this, frames compiled under a synthetic
    # filename like "<exercise>" have no source line ``structured_traceback``
    # can look up, so the traceback shows bare "File <exercise>:N" with no
    # code and nothing to syntax-highlight.
    filename = ip.compile.cache(source)

    error = tb = None
    with capture_output() as cap:
        try:
            value = _last_line_value(tree, namespace, filename)
            if value is not None:
                ipy_display(value)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            # tb_offset=2 drops exactly this function's own frame and
            # _last_line_value's -- the two frames of "our" plumbing between
            # here and the cell's own code -- so what's left matches what
            # running the same code as a plain script would show: only the
            # cell's frames (and anything deeper they call into), nothing
            # from sandbox_widget itself.
            stb = ip.InteractiveTB.structured_traceback(*sys.exc_info(), tb_offset=2)
            tb = ip.InteractiveTB.stb2text(stb)
        finally:
            # Flush any matplotlib figures the cell drew, exactly like a
            # normal cell would -- runs even if the cell raised, so a
            # figure drawn before the error still shows up.
            ip.events.trigger("post_execute")

    return ExerciseResult(
        stdout=cap.stdout, stderr=cap.stderr,
        outputs=[o.data for o in cap.outputs],
        error=error, traceback=tb,
    )
