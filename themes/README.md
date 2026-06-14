# Themes

A theme is one folder with a single `global.css`. The CSS file is concatenated into every rendered wallpaper, so anything declared at the root scope applies to all widgets.

Included themes: `dark`, `forest`, `hacker`, `lavender`, `midnight`, `minimal`, `mono`, `neon`, `nord`, `ocean`, `paper`, `rose`, `slate`, `solarized`, `sunset`, `terminal-light`, and `warm`.

Required tokens (used by widgets and presets):

| Variable | Purpose |
|---|---|
| `--bg` | Page background |
| `--fg`, `--fg-dim`, `--fg-bright` | Text colors |
| `--accent`, `--accent2` | Highlight colors |
| `--surface` | Widget panel background |
| `--border` | Widget panel border |
| `--font` | Body font stack |
| `--font-size-sm` / `-md` / `-lg` / `-xl` | Type scale |

Plus a `body { ... }` rule and a `.widget { ... }` rule for the shared widget chrome. See `minimal/global.css` for a clean example.

## Optional widget hooks

Some presets ship a sensible default look that uses the tokens above, and offer optional CSS hooks a theme can override for a more distinctive style. If a theme doesn't define them, the preset's baseline is used — themes always work out of the box.

### `photo_library`

Override `.photo-frame` to restyle the photo's frame. The widget always sets `aspect-ratio` inline to match the image's natural dimensions, so don't override that.

| Selector | What it is |
|---|---|
| `.photo-frame` | The frame around the image |
| `.photo-frame img` | The image itself (filters etc.) |
| `.photo-caption` | Caption text under the photo (only shown when `show_caption` is true) |
| `.photo-empty` | Fallback shown when no image is available |

See `minimal/global.css` (polaroid look), `hacker/global.css` (CRT terminal look), and the other included themes for examples.
