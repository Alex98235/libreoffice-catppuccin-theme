# Contributing

Thanks for taking an interest! This project is small, but clear guidelines help
everyone.

## Quick start

```bash
git clone git@github.com:Alex98235/libreoffice-catppuccin-theme.git
cd libreoffice-catppuccin-theme
python3 scripts/build.py          # produces dist/catppuccin-{flavor}.oxt
```

## Project structure

```text
palette/catppuccin.json       - vendored Catppuccin palette
scripts/build.py              - the whole build: reads the palette, renders XML, zips .oxt files
dist/                         - generated .oxt files (gitignored, only in GitHub Releases)
```

## How colour mapping works

`build.py` defines two node lists that map LibreOffice UI elements to Catppuccin
colour tokens:

- **`EDITOR_NODES`**: 51 document/editor colour groups (grid lines, syntax
  highlighting, page boundaries, …). This mapping is kept consistent with the
  official `catppuccin/libreoffice` port.
- **`CHROME_NODES`**: 22 window-chrome groups (toolbars, menus, buttons,
  selection colours, …). These are the extra nodes that make this a **full UI
  theme** rather than just a document-colour scheme.

A colour token like `"base"`, `"surface0"` or `"accent"` is resolved against the
current flavour's palette entry at build time. Because tokens are semantic, the
same mapping works correctly for light (`latte`) and dark flavours.

### Adding or modifying a colour node

1. Decide which category it belongs to (chrome or editor).
2. Open `scripts/build.py` and add a new tuple to `EDITOR_NODES` or
   `CHROME_NODES`.
   - Editor nodes take a third field for `IsVisible` (boolean or `None` for
     no override).
   - Chrome nodes use the two-field form `(name, token)`.
3. Run `python3 scripts/build.py` and rebuild the `.oxt`.
4. Install the rebuilt extension to verify visually.

### Updating the palette

Replace `palette/catppuccin.json` with the latest release from
[catppuccin/palette](https://github.com/catppuccin/palette). The build script
parses the same structure every version of the palette has used, so no code
changes should be needed.

## Submitting changes

1. Create a feature branch from `main`.
2. Make your changes, then run `python3 scripts/build.py` to check everything
   still builds.
3. Commit following [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
4. Open a pull request to `main`.
5. Use **squash** or **rebase** when merging.

## Editor config

An `.editorconfig` file is checked in; please ensure your editor respects it
(LF line endings, UTF-8, consistent indentation).
