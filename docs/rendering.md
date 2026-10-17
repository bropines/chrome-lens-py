# Overlay rendering

[Back to the README](../README.md)

With `--translate-out` (`-to`) `lens_scan` saves a copy of the image with the translation painted over the original text. From Python this is `output_overlay_path` in [`process_image`](api.md#process_image).

```bash
lens_scan manga.png -t ru -to out.png                      # Chromium style, the default
lens_scan manga.png -t ru -to out.png --vertical-text horizontal
lens_scan page.png  -t ru -to out.png --overlay-mode legacy
```

## Contents

- [How it works](#how-it-works)
- [Vertical text](#vertical-text)
- [Making the result readable](#making-the-result-readable)
- [Manga mode](#manga-mode)
- [Right-to-left scripts and fonts](#right-to-left-scripts-and-fonts)
- [Settings reference](#settings-reference)

## How it works

The default `chromium` mode follows Chrome's own Lens overlay. It erases the source text with the background patch the server sends, then draws the translation in the original colours, angle and line box. The font size is fitted to each line. Right-to-left scripts, vertical CJK and per-character font fallback are handled.

`--overlay-mode legacy` is the old white-box overlay. It is deprecated: using it with an overlay output raises a `DeprecationWarning`.

An overlay is written only when the image has translated text, so `-t` is required.

## Vertical text

`--vertical-text` decides what happens to top-to-bottom CJK source text.

| Value | Behaviour |
| :--- | :--- |
| `auto` (default) | Stays vertical only when translating into a CJK language. |
| `keep` | Always vertical, exactly like Chromium. |
| `horizontal` | Reflows the paragraph into horizontal wrapped lines. |

## Making the result readable

Chromium repaints each line into the box the original occupied. That is right for a street sign and wrong for a manga bubble, where the translation is much longer than the Japanese it replaces. These options close the gap.

| Flag | API parameter | What it does |
| :--- | :--- | :--- |
| `--erase-mode patch\|hull` | `erase_mode` | `patch` uses the server's inpainted background, like Chromium. `hull` wraps the text area in a convex hull and fills it with the surrounding colour. Cleaner, but only where that colour is flat, for example inside a speech bubble. |
| `--hull-padding N` | `hull_padding` | How far the hull reaches past the text, in line heights (default `0.45`). |
| `--outline N` | `outline_scale` | Multiplier on the outline drawn behind the translated text; `0` removes it. A real stroke, so it stays clean up to `8`. |
| `--min-text-size PX` | `min_readable_px` | Floor on the rendered text size. Lens fits text to the original line box, so fine print on a large page can come back a few pixels tall. Enlarging the text does not enlarge the erased area, which is measured from the text as drawn. Lines may overlap, which is why it is off by default. |
| `--text-align auto\|left\|center\|right` | `text_align` | `auto` follows the source line. |
| `--font PATH` | `font_path` | A `.ttf` font. Text is set in it wherever it has the glyphs; other scripts get the best installed font. |

```bash
lens_scan page.png -t en -to out.png --erase-mode hull --outline 3 --min-text-size 18
```

## Manga mode

`--manga` is a preset for pages of vertical Japanese. It sets:

- `vertical_text` to `horizontal`: always reflow;
- `erase_mode` to `hull`;
- a minimum text size of at least 14 px;
- a layout wider than the detected box, by `--manga-growth` (default `1.45`).

```bash
lens_scan page.png ja -t en -to out.png --manga
lens_scan page.png ja -t en -to out.png --manga --manga-growth 1.8
```

The preset overrides `--vertical-text` and `--erase-mode`. A larger `--min-text-size` still wins over the 14 px floor.

## Right-to-left scripts and fonts

Pillow's published wheels are built without libraqm, so they cannot shape Arabic, Hebrew, Persian and the like. Two extras fill the gap:

```bash
pip install "chrome-lens-py[rtl]"      # python-bidi + arabic-reshaper
pip install "chrome-lens-py[fonts]"    # fontTools, for per-character font fallback
```

Without `fonts` the renderer still works, but a font that lacks glyphs for the target script draws empty boxes. Without `rtl`, right-to-left text is drawn unshaped and a warning is logged.

## Settings reference

All of these are settings: they can live in the config file or in `LENS_*` variables too, see [Configuration](cli.md#configuration). The server accepts the API parameter names, see [daemon.md](daemon.md#http-api).

| Flag | API parameter | Config key | Default |
| :--- | :--- | :--- | :--- |
| `--overlay-mode` | `overlay_mode` | `overlay_mode` | `chromium` |
| `--vertical-text` | `vertical_text` | `vertical_text` | `auto` |
| `--erase-mode` | `erase_mode` | `erase_mode` | `patch` |
| `--hull-padding` | `hull_padding` | `hull_padding` | `0.45` |
| `--outline` | `outline_scale` | `outline_scale` | `1.0` |
| `--min-text-size` | `min_readable_px` | `min_readable_px` | `0` |
| `--text-align` | `text_align` | `text_align` | `auto` |
| `--manga` | `manga_mode` | `manga_mode` | off |
| `--manga-growth` | `manga_box_growth` | `manga_box_growth` | `1.45` |
| `--font` | `font_path` | `font_path` | system font |
| `--font-size` | `font_size` (constructor) | `font_size` | `20`, `legacy` mode only |
