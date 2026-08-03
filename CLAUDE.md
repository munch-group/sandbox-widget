# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

Project context for `sandbox-widget` -- a Jupyter cell magic that runs a
cell in a fresh, fully isolated subprocess, built on
[anywidget](https://anywidget.dev). The GitHub repo and local folder are
still named `script-widget` -- see the note below.

## What this is

Tag a cell `%%exercise` and its body runs in a brand-new Python interpreter
process, spawned fresh and discarded after exactly one run -- nothing the
cell defines, imports, or mutates persists past that one run, and nothing
the notebook has already defined or imported is visible to it at all, not
even via a `sys.modules` cache hit: `import matplotlib.pyplot as plt`
inside the cell gets a genuinely fresh module, not the notebook's own live
object, so a mutation like `plt.rcParams['lines.linewidth'] = 5` inside the
cell can never leak back out. Everything the cell produced -- stdout,
stderr, rich display output, any exception -- is shown in a shaded
`ExerciseOutputWidget` box below the cell instead of the notebook's normal
(unstyled) output area.

The repo was scaffolded from the `munch-group` Python-library template
(pixi environment, quartodoc docs, conda/PyPI release automation) -- the
same template `puzzle-widget`/`steps-widget`/`turtle-widget` use. Like
`puzzle-widget`, there is no separate console-script entry point (no CLI
use case) -- the whole package is the widget + magic, and the exec/capture
logic is split out into its own `executor.py` for the same reason
`puzzle-widget` splits out `checker.py`: it's independently useful and
(mostly) unit-testable without a live IPython shell.

Note: the identifiers now diverge **three** ways, each deliberate:

- The **magic name** is `%%exercise` (canonical), with a `%%sandbox` alias
  -- not `%%script`, specifically to avoid clashing with IPython's own
  built-in `%%script` cell magic (see "Package layout" below).
- The **importable module / PyPI-conda package name** is
  `sandbox_widget`/`sandbox-widget` (renamed from `script_widget`/
  `script-widget`).
- The **GitHub repo and local folder** are still named `script-widget` --
  that rename was explicitly out of scope when the package/module was
  renamed to `sandbox-widget`/`sandbox_widget`: it would touch the repo's
  identity (folder location, GitHub URLs, git history) rather than just
  the installable package, a bigger and more disruptive change than
  renaming the package alone. Links to `github.com/munch-group/
  script-widget` and the docs site `munch-group.org/script-widget` are
  correct as they stand -- don't "fix" them to say `sandbox-widget` unless
  the repo itself gets renamed too.

## Package layout

The package is `sandbox_widget` under `src/`:

- `src/sandbox_widget/executor.py` -- the engine. `run_exercise(source)`
  spawns a subprocess (`multiprocessing.get_context("spawn")`, one
  disposable process per call, never reused -- see "Architecture" below
  for why not `fork`) and hands it off to `_child_main`, which runs
  entirely *inside* that subprocess: `ast.parse`s the cell body, execs
  every statement but the last in a fresh, empty namespace, then handles
  the last statement like a real notebook cell (a bare expression's value
  gets displayed, an assignment still runs but produces no output), via
  `_run_with_ipython` against a throwaway IPython shell the subprocess
  builds for itself (`_make_headless_shell`, same `IPython.testing.
  globalipapp` mechanism the test suite uses for headless testing).
  Capture goes through `IPython.utils.capture.capture_output` (stdout,
  stderr, and rich display output all at once) and `ip.events.trigger(
  "post_execute")` is called after running so the subprocess's own
  `%matplotlib inline` flush hook fires exactly as it would after a normal
  cell. The result -- an `ExerciseResult(stdout, stderr, outputs, error,
  traceback)` -- is sent back to the parent process over a
  `multiprocessing.Pipe`; `run_exercise` never raises, whether the cell hit
  a `SyntaxError`, a runtime exception (reported via `.error`/`.traceback`,
  with `.traceback` from `ip.InteractiveTB.structured_traceback()`/
  `.stb2text()` -- see "Colored tracebacks" under Architecture), or the
  subprocess dying outright (reported as a generic `.error` with the
  child's exit code).
- `src/sandbox_widget/widget.py` -- `ExerciseOutputWidget` (the
  `anywidget.AnyWidget`) + the embedded `_ESM`/`_CSS` frontend strings +
  `register_exercise_magic()`, which registers both `%%exercise` (the
  canonical name) and `%%sandbox` (a plain alias -- same handler function
  registered under a second `magic_name`, not a separate implementation).
  It's `%%sandbox`, not `%%script`, specifically to avoid clashing with
  IPython's own built-in `%%script` cell magic (which shells out to an
  external interpreter, e.g. `%%script bash`) -- an earlier version
  registered the alias as `%%script` and silently shadowed the built-in for
  the rest of the kernel session, and a cell using `%%script` before
  `sandbox_widget` had been imported hit the *built-in's* own confusing
  failure (missing interpreter argument) rather than a clear "magic not
  found" error. The widget's traits are copied from an
  `ExerciseResult` once at construction and never change afterward (unlike
  `puzzle_widget.PuzzleWidget`, there's no interactive re-checking), so the
  frontend's `render()` draws once from the model's initial state with no
  change listeners. The embedded CSS's class prefix (`sw-*`) predates the
  package rename -- it stood for "script widget" back when the package was
  `script_widget` -- but reads just as naturally as "sandbox widget" now,
  so it wasn't changed; it's an internal styling namespace, not
  user-facing, so there's no user-visible reason to touch it. The box
  itself is always a plain gray (no color/header change on success vs.
  failure); stdout and stderr are merged into one white `.sw-output` block
  rather than two separately colored ones.
- `src/sandbox_widget/__init__.py` -- re-exports `ExerciseResult`/
  `run_exercise`/`ExerciseOutputWidget`/`register_exercise_magic` from
  `executor.py`/`widget.py`. Importing `sandbox_widget` therefore both
  exposes the public API and registers the cell magic as a side effect.
- `test/` -- headless pytest suite: `test_executor.py` (the engine -- every
  test spawns a real subprocess now, so there's no more no-shell/with-shell
  split; each `run_exercise` call pays real process-startup latency, which
  is why the suite got noticeably slower after the subprocess-isolation
  redesign), `test_widget.py` (`ExerciseOutputWidget` + the magic --
  registration wiring is tested against a hand-rolled fake shell, not a
  real one, to stay deterministic and isolated from other tests' IPython
  singleton state), `test_frontend.py` (`node --check` on the extracted
  `_ESM`, skipped if `node` isn't on `PATH`).
- `docs/` -- Quarto + quartodoc site (`docs/pages/*.ipynb` prose,
  `docs/api/*.qmd` API ref -- the checked-in `.qmd` files are placeholders;
  run `pixi run api` to regenerate them from the live docstrings).
- `pyproject.toml` -- packaging metadata **and** the pixi workspace (deps +
  task runner).
- `conda-build/`, `.github/workflows/` -- conda/PyPI release on tag push.
- `scripts/` -- version-bump / docs-build / release helpers invoked by pixi
  tasks.

## Architecture

### Why a subprocess, not just a fresh namespace

An earlier design ran the cell in a fresh, empty *namespace* but in the
**same process** as the notebook kernel. That gave reproducibility (a cell
can't read some already-defined notebook variable it didn't import) but
not real isolation: Python caches loaded modules in `sys.modules`
process-wide, so `import matplotlib.pyplot as plt` inside the cell was a
cache hit handing back the exact same live module object the notebook
already had -- meaning `plt.rcParams['lines.linewidth'] = 5` inside
`%%exercise` silently mutated the notebook's own matplotlib state too. That
was a real, reported problem (a cell described as "isolated" wasn't, for
anything reachable through an already-imported module), and there's no way
to fix it while staying in-process: `sys.modules` is inherently one cache
per interpreter, not per namespace, and even `importlib.reload()` replaces
a module *in place* (same object identity, still visible everywhere).
Genuinely fresh imports require a genuinely fresh interpreter -- hence
`run_exercise` now spawns a real subprocess per cell (see "Package layout"
above) instead of merely `exec`-ing into an empty dict.

Two rejected alternatives, and why: bypassing `sys.modules` for the cell's
own imports without a new process was considered and dropped -- libraries
like numpy/matplotlib/pandas/torch keep process-wide global C-level state
and often aren't safe to load a second time in the same interpreter (real
risk of crashes or silent misbehavior for exactly the libraries most likely
to appear in an exercise cell). Forking the live kernel process (`os.fork()`
or `multiprocessing`'s default `fork` start method on Linux) was also
dropped: forking a process with live background threads (which a running
Jupyter kernel always has -- zmq's io threads, heartbeat, etc.) is a
well-documented hazard that can leave the child in a half-broken state or
destabilize the parent kernel. `run_exercise` explicitly uses
`multiprocessing.get_context("spawn")` -- always a brand-new interpreter
booted from scratch, never a copy-on-write fork of the live kernel -- which
is slower per cell (a fresh interpreter, plus re-importing whatever the
cell needs, from under a second to a couple of seconds for heavy libraries)
but is the only one of the three options that's actually safe.

The tradeoff that *is* still real and intentional, same as before: a plain
notebook variable with no import path (a dataframe built inline, a model
trained ad hoc and only ever bound to a local name) is **not** visible to
`%%exercise`, full stop -- there is no fallback, and now not even an
already-imported *module* is shared, since the subprocess has its own
`sys.modules` from the moment it boots.

### The matplotlib-figure-flush trick

`capture_output`'s display-publisher swap captures explicit `display(...)`
calls and the trailing expression's auto-display, but **not** a bare
`plt.plot(...)` with no `.show()`/`display()` call -- that auto-flush
normally happens via a `post_execute` hook the inline backend registers on
the shell, which never fires for a bare `exec()` call outside `ip.
run_cell`. `_run_with_ipython` calls `ip.events.trigger("post_execute")`
itself, still inside the `capture_output` block, right after running the
cell -- this fires whatever hook `_make_headless_shell`'s own
`%matplotlib inline` call just registered *in the subprocess*, not
anything belonging to the notebook's own matplotlib session (there isn't
one shared with the subprocess to reuse). It's called in a `finally`, so a
figure drawn before an exception still gets flushed and shown, exactly
like a real cell -- but note the figure renders with a pristine default
backend/rcParams, not whatever runtime configuration the notebook's own
matplotlib session happens to be carrying.

### Colored tracebacks that show the cell's own source

A `%%exercise` traceback is meant to look exactly like what a student would
see running the same code as a plain script or in a real notebook cell --
not a plain `traceback.format_exc()` dump, and not cluttered with
`sandbox_widget`'s own internal frames. Three things make that true:

- **`_make_headless_shell` forces `shell.colors = "neutral"`.** Without
  this, there are no ANSI codes to highlight in the first place --
  `IPython.testing.globalipapp`'s shell is a `TerminalInteractiveShell`,
  which (reasonably, for a *real* terminal) auto-detects "nocolor" when
  there's no tty, exactly the case in a subprocess with no real terminal
  attached. A real Jupyter kernel's shell (`ZMQInteractiveShell`) doesn't do
  that detection -- it defaults to "neutral" (color on) unconditionally,
  since its frontend always renders ANSI regardless of ttys -- so this line
  is what makes the subprocess's shell match a real kernel's default
  instead of silently downgrading to plain text.
  `test_traceback_carries_ansi_color_codes` catches a regression here.
- **The cell's source is registered with `linecache` before it's compiled.**
  `_run_with_ipython` calls `ip.compile.cache(source)` -- the exact
  mechanism a real notebook cell uses on itself -- to get a filename (like
  `<ipython-input-0-...>`) that's already wired into `linecache`, and
  compiles the cell under *that* filename instead of a bare synthetic one
  like `"<exercise>"`. Skip this and a traceback frame has no source
  `structured_traceback` can look up: it renders as a bare `File
  "<exercise>", line N` with no code shown beneath it at all -- not merely
  uncolored, genuinely blank, since there's nothing there to highlight.
- **`tb_offset=2` strips `sandbox_widget`'s own frames.** The call chain
  between "where the `try` lives" and "the cell's own code" is exactly two
  functions deep (`_run_with_ipython` -> `_last_line_value`, both frames
  showing up in `sys.exc_info()`'s traceback if left alone) --
  `ip.InteractiveTB.structured_traceback(*sys.exc_info(), tb_offset=2)`
  drops exactly those two, same idea as `InteractiveShell` itself passing
  `tb_offset=1` to drop its own one wrapper frame (`init_traceback_handlers`'s
  comment: "we always want to remove the topmost item in the traceback,
  which is our own internal code"). Get this number wrong and either an
  executor.py frame leaks into what the student sees, or (overshoot) the
  outermost frame of their *own* code gets silently eaten too --
  `test_traceback_does_not_leak_internal_executor_frames` pins both ends
  down (asserts neither `_last_line_value` nor `executor.py` appear, and
  that the cell's own lines still do).

With all three in place, `ip.InteractiveTB.structured_traceback(...)` +
`.stb2text(...)` -- exactly the call `InteractiveShell` itself makes before
printing an exception, run against the subprocess's own throwaway shell
(`_make_headless_shell`) -- returns text with real ANSI SGR escape codes
(IPython 9's traceback formatter is pygments-based, so source-context lines
carry full syntax highlighting via 256-color codes, not just the 16 basic
ones used for the exception header/filename/line number). The frontend has
no ANSI-rendering library to lean on (`_ESM` is dependency-free by design),
so `widget.py`'s `_ESM` embeds a small SGR-code interpreter
(`ansiToHtml`/`applySGR`/`xterm256`) that turns those escape codes into
colored `<span>`s, using the exact hex values JupyterLab itself uses for
`.ansi-*-fg` so the result matches a real notebook's palette. Text with no
escape codes at all (a plain-text `SyntaxError`, caught in `_child_main`
before the subprocess's shell -- and hence its `ip.compile.cache` -- is
even built) round-trips through the same function as a single unstyled
text node.

## Gotchas

- **Every `%%exercise` run costs a real process spawn now.** Since the
  subprocess-isolation redesign, `run_exercise` always pays interpreter
  startup + re-importing whatever the cell needs (and IPython itself,
  inside `_make_headless_shell`) -- noticeably slower than the old
  in-process `exec`, and the whole reason `pixi run test` got much slower
  too (every `test_executor.py` test spawns one). This is the accepted
  cost of genuine isolation, not a bug to "optimize away" by reintroducing
  a shared/reused process.
- **`multiprocessing.get_context("spawn")` is deliberate -- don't switch to
  the default context or to `fork`.** The default start method is `fork`
  on Linux; forking a live, multi-threaded Jupyter kernel process is a
  known way to corrupt or hang it (see "Why a subprocess" under
  Architecture). Always go through the explicit `spawn` context.
- **A matplotlib figure drawn inside `%%exercise` uses a pristine
  backend/rcParams, not the notebook's own.** The subprocess calls
  `%matplotlib inline` on its own throwaway shell; it has no access to
  whatever the notebook's actual matplotlib session has been configured to
  at runtime (custom rcParams set earlier in the notebook, a non-default
  backend, etc.) -- only whatever `matplotlibrc`-style config loads fresh
  from disk.
- **A subprocess that dies outright is still reported, not left hanging.**
  `_run_isolated` treats `EOFError` from `parent_conn.recv()` (the child
  closed its pipe end without sending anything -- crashed, killed, etc.)
  as a normal failure mode: it returns an `ExerciseResult` with a generic
  `.error` naming the child's exit code, same contract as a caught
  exception (`run_exercise` still never raises).
- **`multiprocessing.Process` inherits the subprocess's stdout/stderr fds
  -- it doesn't pipe them.** Anything printed *outside* the
  `capture_output()` block in `_run_with_ipython` goes straight to the
  real kernel's stdout, bypassing `ExerciseResult` entirely: it won't show
  up in the widget's own output box, and (worse, since it's an
  unpredictable race against the kernel's iopub message flushing) it can
  show up oddly delayed, attached to whatever cell happens to be executing
  when it's finally flushed -- not necessarily the `%%exercise` cell that
  produced it. `_make_headless_shell`'s own `%matplotlib inline` setup call
  hits this: it unconditionally prints "No event loop hook running." (inline
  figures need no real GUI event loop, but `enable_gui` prints that
  regardless), so it's wrapped in its own `contextlib.redirect_stdout`
  right there, rather than relying on the later `capture_output()` block to
  catch it. `test_matplotlib_setup_does_not_leak_to_real_stdout` (using
  pytest's `capfd`, which -- unlike `capsys` -- catches file-descriptor
  -level writes from a real subprocess) guards this.
- **No IPython input transforms inside the cell body.** `%%exercise` parses
  with plain `ast.parse`/`exec`, not `ip.run_cell`, so line magics
  (`%time`), shell escapes (`!ls`), and `?`-help don't work inside the cell
  -- plain Python only.
- **`IPython.testing.globalipapp`'s shell restricts rich display to
  `text/plain` by default.** `TerminalInteractiveShell` (reasonably, for a
  real terminal) sets `display_formatter.active_types = ["text/plain"]`,
  which silently drops `image/png` etc. even though the matplotlib-inline
  formatter is registered and would produce real PNG bytes if called
  directly. `_make_headless_shell` explicitly widens `active_types` back
  to `format_types` for exactly this reason -- forget this (e.g. if this
  function gets refactored) and figure capture silently degrades to a
  `text/plain` repr of the `Figure` object, not a missing output.
- **The package/magic name mismatch is intentional, not a leftover.** The
  package is `sandbox_widget`; the magic is `%%exercise` (with a
  `%%sandbox` alias). Don't "fix" this by renaming the package to match
  the magic name -- see the note in "What this is" above.
- **The repo/folder name (`script-widget`) no longer matches the package
  name (`sandbox-widget`), and that's also intentional.** The package was
  renamed from `script_widget`/`script-widget` to `sandbox_widget`/
  `sandbox-widget`, but the GitHub repo and local folder were deliberately
  left as `script-widget` -- see the note in "What this is" above. Don't
  "fix" GitHub/docs-site URLs to say `sandbox-widget` without actually
  renaming the repo first; as of this rename they still correctly point at
  `github.com/munch-group/script-widget` and
  `munch-group.org/script-widget`.

## Environment & commands

Pixi-managed (config in `pyproject.toml` under `[tool.pixi.*]`; channels
`conda-forge` + `munch-group`; platforms `osx-arm64`, `linux-64`). Python
`>=3.9,<3.14`. Key deps: `anywidget` (0.11.x), `traitlets`, `ipython`,
`nodejs` (for the `node --check` frontend test), `matplotlib-base`
(dev/test only, for the figure-capture tests), `quarto`/`quartodoc`,
`pytest`.

- Dev install: `pixi run install-dev` (`pip install --no-build-isolation
  --force-reinstall --no-deps .` -- a real, **non-editable** install, despite
  the task name; re-run it after every `src/` edit or `import sandbox_widget`
  picks up the stale previously-installed copy, not your change).
- Run tests: `pixi run test` (== `pytest test/`).
- Run a single test: `pixi run pytest test/test_executor.py::test_exception_is_caught_and_reported`
  (or plain `pytest ...` -- `test/conftest.py` puts `src/` on `sys.path`, so
  this works even without `install-dev`).
- Try the widget: open a notebook, `import sandbox_widget`, then
  ```
  %%exercise
  import matplotlib.pyplot as plt
  plt.plot([1, 2, 3])
  ```
- JS syntax check after editing the embedded frontend string:
  ```bash
  python -c "from sandbox_widget import widget as m; open('/tmp/e.mjs','w').write(m._ESM)"
  node --check /tmp/e.mjs
  ```
  (also `test_frontend.py::test_esm_is_syntactically_valid_js`, run
  automatically by `pixi run test` whenever `node` is on `PATH`).
- Build docs: `pixi run api` (quartodoc API pages), then `pixi run docs`
  (execute the doc notebooks in place).
- Release: `pixi run bump` / `release` / `version` drive
  `scripts/bump_version.py` + a tag push, which triggers the conda/PyPI
  workflows.
- Code review: `/review <target-file>` fans out specialist subagents
  (Python, frontend, API consistency, UI heuristics, theming) into a
  prioritized report under `.claude/review-reports/`; `/review-apply`
  applies that report's findings in small, test-gated, one-commit-per-batch
  steps. See `review-kit/README.md` for the full workflow.

## Distribution

Both `.github/workflows/conda-release.yml` and `pypi-release.yml` trigger on
version tag pushes (`vX.Y[.Z][.rcN]`), building on `macOS-latest` and
`ubuntu-latest` (no `win-64` in this workspace's platform list) and pure
Python wheel to PyPI, mirroring `puzzle-widget`'s setup.

## Testing approach

- `executor.run_exercise` tests all go through the same real-subprocess
  path now (no more no-shell/with-shell split) -- `test_executor.py`
  exercises stdout/stderr capture, the trailing-expression/`display()`
  paths, matplotlib figure flush (including flush-on-exception), and the
  isolation guarantee itself (mutating a freshly-imported matplotlib's
  `rcParams` inside the cell must not affect the test process's own
  already-imported copy). Each test pays real process-spawn latency --
  this is why the suite is seconds, not milliseconds, and that's expected.
- `ExerciseOutputWidget` is tested by constructing it directly from an
  `ExerciseResult` -- no magic/subprocess involved.
- `register_exercise_magic`'s registration wiring is tested against a
  hand-rolled fake shell rather than a real `InteractiveShell`, to stay
  deterministic and avoid spawning anything.
- The actual shaded-box rendering isn't (and can't be, headlessly)
  exercised by the pytest suite -- `test_frontend.py` only checks the
  extracted `_ESM` parses as valid JS. Manually verify the rendered output
  against a live notebook after editing `_ESM`/`_CSS`.
