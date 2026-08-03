
# sandbox-widget

A Jupyter cell magic that runs a cell in a fresh, isolated namespace and
shows everything it produced -- stdout, stderr, rich display output, any
exception -- in a shaded box below the cell, built on
[anywidget](https://anywidget.dev).

```python
import sandbox_widget  # registers the %%exercise cell magic
```

```
%%exercise
import matplotlib.pyplot as plt
plt.plot([1, 2, 3])
```

Nothing the cell defines or imports persists past that one run, and nothing
the notebook has already defined is visible to it -- except through the
cell's own `import`/`from ... import` statements. Because Python caches
loaded modules in `sys.modules`, such an import is essentially free and
hands back the exact same live object the notebook already has (the same
`plt`, with the same open figures; the same model, with the same weights) --
nothing is reloaded or reinitialized, and no kernel restart happens.

## Installation

```bash
# pixi
pixi workspace channel add munch-group
pixi add sandbox-widget

# conda
conda install -c munch-group sandbox-widget

# pip
pip install sandbox-widget
```

## Writing a `%%exercise` cell

- Anything the cell needs -- a library, a model, a helper function -- must
  be imported by the cell itself. Plain notebook variables with no import
  path (e.g. a dataframe built inline two cells up) aren't visible.
- A trailing bare expression is displayed, exactly like a normal cell
  (`a + b`, or a variable's name on its own); an assignment as the last line
  still runs, but produces no comparable output.

## Documentation

Full docs live at
[munch-group.org/script-widget](https://munch-group.org/script-widget).

## Development

This repo is managed with [pixi](https://pixi.sh):

```bash
pixi run install-dev   # editable install into the pixi environment
pixi run test          # run the pytest suite
pixi run docs          # execute the documentation notebooks
pixi run api           # build the quartodoc API reference
```

## License

MIT
