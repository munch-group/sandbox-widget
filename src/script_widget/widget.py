"""script_widget.widget
=======================

A Jupyter widget that runs a cell body in a fresh, isolated namespace (see
``executor.py``) and shows everything it produced -- stdout, stderr, rich
display output, and any exception -- in a shaded box below the cell,
instead of the notebook's normal (unstyled) output area.

* Built on `anywidget` (same convention as ``puzzle-widget``), so it
  behaves the same across VS Code notebooks, JupyterLab, Notebook 7 and
  Colab.
* All execution/capture logic lives in ``executor.py``; this module only
  wraps the result in a synced-traitlets widget and wires up the
  ``%%exercise`` cell magic (``%%script`` is a plain alias for the same
  magic -- see ``register_exercise_magic``).

Usage
-----
    import script_widget  # registers the %%exercise cell magic (and %%script)

    %%exercise
    import matplotlib.pyplot as plt
    plt.plot([1, 2, 3])
"""

from __future__ import annotations

import anywidget
import traitlets

from .executor import run_exercise

try:  # IPython is present whenever a kernel is running, but guard anyway.
    from IPython import get_ipython
    from IPython.display import display as _ipy_display
except Exception:  # pragma: no cover
    def get_ipython():
        return None

    def _ipy_display(*a, **k):
        pass


__all__ = ["ExerciseOutputWidget", "register_exercise_magic"]


# --------------------------------------------------------------------------- #
# Frontend (ESM + CSS) -- no external dependencies, offline-safe.             #
# --------------------------------------------------------------------------- #

_ESM = r"""
/** HTML-escape helper -- unused for text (textContent escapes automatically)
 *  but kept for any future spot that needs to build an HTML string directly. */
function esc(s){
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

/** The 16 base ANSI colors, using the exact hex values JupyterLab itself
 *  uses for `.ansi-*-fg` (see its bundled `.jp-RenderedText pre .ansi-*-fg`
 *  rules) -- so a traceback rendered here matches a normal notebook's. */
const ANSI_16 = [
  "#3e424d", "#e75c58", "#00a250", "#ddb62b", "#208ffb", "#d160c4", "#60c6c8", "#c5c1b4",
  "#282c36", "#b22b31", "#007427", "#b27d12", "#0065ca", "#a03196", "#258f8f", "#a1a6b2",
];

function rgbToHex(r, g, b){
  return "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
}

/** Standard xterm 256-color palette lookup: 0-15 are the base ANSI colors,
 *  16-231 a 6x6x6 RGB cube, 232-255 a grayscale ramp. IPython 9's traceback
 *  formatter (pygments' Terminal256Formatter) uses this for syntax
 *  highlighting the source-code context lines, not just the 16 base colors
 *  used for structural bits (filenames, line numbers, the exception name). */
function xterm256(n){
  if (n < 16) return ANSI_16[n];
  if (n < 232){
    n -= 16;
    const levels = [0, 95, 135, 175, 215, 255];
    const r = Math.floor(n / 36), g = Math.floor((n % 36) / 6), b = n % 6;
    return rgbToHex(levels[r], levels[g], levels[b]);
  }
  const gray = 8 + (n - 232) * 10;
  return rgbToHex(gray, gray, gray);
}

/** Apply one escape sequence's `;`-separated SGR params to a running style
 *  state, consuming the extra params `38`/`48` (extended color) take. */
function applySGR(state, codes){
  for (let i = 0; i < codes.length; i++){
    const code = codes[i];
    if (code === 0){ state.fg = null; state.bg = null; state.bold = false; state.italic = false; state.underline = false; }
    else if (code === 1){ state.bold = true; }
    else if (code === 22){ state.bold = false; }
    else if (code === 3){ state.italic = true; }
    else if (code === 23){ state.italic = false; }
    else if (code === 4){ state.underline = true; }
    else if (code === 24){ state.underline = false; }
    else if (code === 39){ state.fg = null; }
    else if (code === 49){ state.bg = null; }
    else if (code >= 30 && code <= 37){ state.fg = ANSI_16[code - 30]; }
    else if (code >= 90 && code <= 97){ state.fg = ANSI_16[8 + code - 90]; }
    else if (code >= 40 && code <= 47){ state.bg = ANSI_16[code - 40]; }
    else if (code >= 100 && code <= 107){ state.bg = ANSI_16[8 + code - 100]; }
    else if (code === 38 || code === 48){
      const mode = codes[i + 1];
      let color = null;
      if (mode === 5){ color = xterm256(codes[i + 2]); i += 2; }
      else if (mode === 2){ color = rgbToHex(codes[i + 2], codes[i + 3], codes[i + 4]); i += 4; }
      if (code === 38) state.fg = color; else state.bg = color;
    }
  }
}

/** Turn ANSI SGR-colored text (e.g. an IPython-formatted traceback) into a
 *  DOM fragment of plain text and colored `<span>`s. Text with no escape
 *  codes at all comes back as a single unstyled text node. */
function ansiToHtml(text){
  const frag = document.createDocumentFragment();
  const state = { fg: null, bg: null, bold: false, italic: false, underline: false };
  const re = /\x1b\[([0-9;]*)m/g;
  let lastIndex = 0, match;

  function flush(chunk){
    if (!chunk) return;
    if (state.fg || state.bg || state.bold || state.italic || state.underline){
      const span = document.createElement("span");
      if (state.fg) span.style.color = state.fg;
      if (state.bg) span.style.backgroundColor = state.bg;
      if (state.bold) span.style.fontWeight = "bold";
      if (state.italic) span.style.fontStyle = "italic";
      if (state.underline) span.style.textDecoration = "underline";
      span.textContent = chunk;
      frag.appendChild(span);
    } else {
      frag.appendChild(document.createTextNode(chunk));
    }
  }

  while ((match = re.exec(text)) !== null){
    flush(text.slice(lastIndex, match.index));
    lastIndex = re.lastIndex;
    const codes = match[1].length ? match[1].split(";").map(Number) : [0];
    applySGR(state, codes);
  }
  flush(text.slice(lastIndex));
  return frag;
}

/** MIME types in the order we prefer to render them, richest first --
 *  same preference order Jupyter itself uses for a display mimebundle. */
const MIME_PRIORITY = ["image/png", "image/jpeg", "image/svg+xml", "text/html", "text/plain"];

function pickMime(data){
  for (const mime of MIME_PRIORITY){
    if (mime in data) return mime;
  }
  const keys = Object.keys(data);
  return keys.length ? keys[0] : null;
}

/** Build a DOM node for one captured rich-display MIME bundle, picking the
 *  richest available representation. Returns null for an empty bundle. */
function renderOutput(data){
  const mime = pickMime(data);
  if (mime == null) return null;
  const value = data[mime];

  if (mime === "image/png" || mime === "image/jpeg"){
    const img = document.createElement("img");
    img.className = "sw-image";
    img.src = "data:" + mime + ";base64," + value;
    return img;
  }
  if (mime === "image/svg+xml"){
    const wrap = document.createElement("div");
    wrap.className = "sw-svg";
    wrap.innerHTML = value;
    return wrap;
  }
  if (mime === "text/html"){
    const wrap = document.createElement("div");
    wrap.className = "sw-html";
    wrap.innerHTML = value;
    return wrap;
  }
  const pre = document.createElement("pre");
  pre.className = "sw-text";
  pre.textContent = Array.isArray(value) ? value.join("") : String(value);
  return pre;
}

/**
 * anywidget render entry point. An %%exercise result is fully determined at
 * widget-construction time and never changes afterward (unlike PuzzleWidget,
 * there's no interactive re-checking), so this draws once from the model's
 * initial state -- no change listeners needed.
 */
function render({ model, el }){
  // Both classic ipywidgets and JupyterLab wrap a widget's view in one or
  // more shrink-to-fit containers by default, so the box only ends up as
  // wide as its own content instead of the output area (which lines up
  // with the input cell above it). Force every ancestor in that wrapper
  // chain to fill its parent -- inline styles win regardless of exactly
  // what those wrapper elements are called in a given frontend.
  let ancestor = el;
  for (let i = 0; i < 4 && ancestor; i++){
    ancestor.style.width = "100%";
    ancestor.style.boxSizing = "border-box";
    ancestor = ancestor.parentElement;
  }

  const root = document.createElement("div");
  root.className = "sw-root";

  const header = document.createElement("div");
  header.className = "sw-header";
  header.textContent = "Terminal output:";
  root.appendChild(header);

  // Everything the cell produced lives in one continuous white panel --
  // nesting it inside the gray .sw-root "mat" this way (rather than laying
  // stdout/stderr/outputs/traceback directly on the gray background) means
  // there's no gray gap visible between them.
  const body = document.createElement("div");
  body.className = "sw-body";
  root.appendChild(body);

  let outputPre = null;
  const output = [model.get("stdout"), model.get("stderr")].filter(Boolean).join("\n");
  if (output){
    const wrap = document.createElement("div");
    wrap.className = "sw-output-wrap";
    outputPre = document.createElement("pre");
    outputPre.className = "sw-output";
    outputPre.appendChild(ansiToHtml(output));
    wrap.appendChild(outputPre);
    body.appendChild(wrap);
  }

  (model.get("outputs") || []).forEach((data) => {
    const node = renderOutput(data);
    if (node) body.appendChild(node);
  });

  const tb = model.get("traceback");
  if (tb){
    const pre = document.createElement("pre");
    pre.className = "sw-traceback";
    pre.appendChild(ansiToHtml(tb));
    body.appendChild(pre);
  }

  el.appendChild(root);

  // A native scrollbar's own "there's more" affordance turns out to be
  // unreliable across notebook frontends (some force an auto-hiding overlay
  // scrollbar no CSS override changes), so signal truncation ourselves: once
  // the box is actually laid out (double rAF, since a widget's element isn't
  // always attached to the visible document yet at the point render() runs),
  // check whether it really overflows and, if so, add a "scroll to see
  // more" badge that tracks scroll position -- hidden once the user has
  // actually scrolled down to the last line, so it never claims there's more
  // when there isn't.
  if (outputPre){
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (outputPre.scrollHeight > outputPre.clientHeight + 1){
        const badge = document.createElement("div");
        badge.className = "sw-more";
        badge.textContent = "scroll to see more";
        outputPre.parentElement.appendChild(badge);

        const updateBadge = () => {
          const atBottom = outputPre.scrollTop + outputPre.clientHeight >= outputPre.scrollHeight - 1;
          badge.style.display = atBottom ? "none" : "";
        };
        outputPre.addEventListener("scroll", updateBadge);
        updateBadge();
      }
    }));
  }
}

export default { render };
"""

_CSS = r"""
/* Styles for the DOM built in _ESM's render(): a plain gray "mat" (.sw-root,
   bordered on all four edges, no success/failure color change), a small
   "Terminal output:" label (.sw-header) sitting directly on that gray
   background, then one continuous white panel (.sw-body) holding
   everything the cell produced -- combined stdout+stderr (.sw-output), any
   rendered outputs (.sw-image/.sw-svg/.sw-html/.sw-text), and
   .sw-traceback -- stacked with plain margin so no gray ever shows between
   them. margin-top on .sw-root separates the box from the code cell above
   it. */
.sw-root { width: 100%; box-sizing: border-box; margin-top: 8px;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: #f3f4f6; border-radius: 6px; padding: 8px;
  border: 1px solid #9ca3af; }
.sw-header { font-size: 11.5px; font-weight: 600; letter-spacing: .02em;
  color: #6b7280; text-transform: uppercase; margin: 2px 4px 6px; }
.sw-body { background: #ffffff; border-radius: 4px; padding: 10px 14px; }
.sw-body > * + * { margin-top: 8px; }
.sw-output, .sw-text, .sw-traceback {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, "Cascadia Code", Menlo, monospace;
  font-size: 12.5px; line-height: 18px; white-space: pre-wrap;
  word-break: break-word; color: #24292f; }
.sw-output { max-height: 540px; overflow-y: auto; }
.sw-image { max-width: 100%; border-radius: 4px; }
.sw-html, .sw-svg { border-radius: 4px; overflow-x: auto; }
/* A custom "scroll to see more" badge -- not a native-scrollbar restyle,
   which some notebook frontends override with their own auto-hiding
   scrollbar regardless of CSS -- so truncated output still visibly signals
   there's more beneath the fold. Positioned over (not inside) the
   scrollable .sw-output, so it can't itself scroll out of view; hidden via
   inline style once a scroll listener (in _ESM) detects the user has
   actually reached the bottom. */
.sw-output-wrap { position: relative; }
.sw-more {
  position: absolute; right: 6px; bottom: 6px;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 10px; font-weight: 700; letter-spacing: .02em;
  color: #ffffff; background: rgba(107, 114, 128, 0.85);
  padding: 2px 8px; border-radius: 999px; white-space: nowrap;
  pointer-events: none; }
"""


# --------------------------------------------------------------------------- #
# The widget                                                                  #
# --------------------------------------------------------------------------- #

class ExerciseOutputWidget(anywidget.AnyWidget):
    """Everything a ``%%exercise`` cell produced, rendered in a shaded box.

    Parameters
    ----------
    result : script_widget.executor.ExerciseResult
        The outcome of ``run_exercise``. All traits below are copied from
        it once at construction time and never change afterward.

    Attributes
    ----------
    stdout, stderr : str
        Captured output streams.
    outputs : list of dict
        Captured rich display MIME bundles (see ``ExerciseResult.outputs``).
    success : bool
        Whether the cell ran without raising.
    error : str
        Short exception summary, or ``""`` if none.
    traceback : str
        Full formatted traceback, or ``""`` if none.
    """

    _esm = _ESM
    _css = _CSS

    stdout = traitlets.Unicode("").tag(sync=True)
    stderr = traitlets.Unicode("").tag(sync=True)
    outputs = traitlets.List(traitlets.Dict()).tag(sync=True)
    success = traitlets.Bool(True).tag(sync=True)
    error = traitlets.Unicode("").tag(sync=True)
    traceback = traitlets.Unicode("").tag(sync=True)

    def __init__(self, result):
        # Pass the trait values as constructor kwargs rather than assigning
        # them one at a time after the fact: `Widget.__init__` sets kwarg
        # traits *before* calling `self.open()`, so the single comm_open
        # message already carries the full, correct state. Setting them
        # afterward instead (the previous approach) opens the comm with the
        # traits' default (empty) values first, then sends a separate
        # `comm.send()` update message per trait -- a race the frontend can
        # lose on a cold widget-manager/first-render (exactly when a
        # brand-new anywidget ESM module is still being evaluated), drawing
        # the box from the initial empty state before the stdout/stderr/etc.
        # update messages are processed. This is what made the very first
        # `%%exercise`/`%%script` cell in a kernel session show up with no
        # stdout, self-correcting on the very next run once the frontend was
        # warmed up.
        super().__init__(
            stdout=result.stdout,
            stderr=result.stderr,
            outputs=result.outputs,
            success=result.success,
            error=result.error or "",
            traceback=result.traceback or "",
        )
        # Every ipywidgets-compliant frontend (JupyterLab, classic Notebook,
        # VS Code, Colab, ...) honors `layout.width` natively on the view
        # element -- more portable than anything _ESM's render() can do by
        # poking at ancestor DOM nodes, since some frontends (e.g. VS Code's
        # notebook renderer) sandbox the widget in a way our own JS can't
        # reach out of.
        self.layout.width = "100%"


def register_exercise_magic(ipython=None):
    r"""Register the `%%exercise` cell magic (and its `%%script` alias).

    In IPython/Jupyter, `%%exercise` runs the cell body in a fresh
    subprocess (see ``executor.run_exercise``) and displays everything it
    produced -- stdout, stderr, rich output, any exception -- in a shaded
    ``ExerciseOutputWidget`` below the cell::

        %%exercise
        import matplotlib.pyplot as plt
        plt.plot([1, 2, 3])

    `%%script` runs the exact same handler under a second name -- both are
    registered from the same function, so there's no separate
    implementation to keep in sync.

    Nothing the cell defines, imports, or mutates persists past that one
    run, and nothing the notebook has already defined or imported is
    visible to it at all -- not even via a ``sys.modules`` cache hit, since
    the cell runs in its own interpreter process.

    Called automatically on import; returns True when a live shell is
    found, False otherwise (e.g. plain Python).
    """
    ip = ipython or get_ipython()
    if ip is None:
        return False

    def exercise(line, cell):
        result = run_exercise(cell or "")
        _ipy_display(ExerciseOutputWidget(result))

    ip.register_magic_function(exercise, magic_kind="cell", magic_name="exercise")
    ip.register_magic_function(exercise, magic_kind="cell", magic_name="script")
    return True


try:
    register_exercise_magic()
except Exception:
    pass
