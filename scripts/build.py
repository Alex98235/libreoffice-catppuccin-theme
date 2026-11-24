#!/usr/bin/env python3
"""Build LibreOffice .oxt UI-theme extensions from the Catppuccin palette.

No third-party dependencies: only the Python standard library is required.
The generated extension registers a full UI ColorScheme (window chrome +
document/editor colors) under org.openoffice.Office.UI/ColorScheme, and
registers a matching .soc palette for the color picker.

Usage:
    python3 scripts/build.py                      # 4 published flavors, all accents in each
    python3 scripts/build.py --flavor mocha       # one flavor, all accents in one .oxt
    python3 scripts/build.py --flavor mocha --accent sky   # a single-accent .oxt
    python3 scripts/build.py --all-accents        # one .oxt per flavor/accent combination
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
PALETTE_PATH = ROOT / "palette" / "catppuccin.json"
DEFAULT_OUT = ROOT / "dist"

VERSION = "1.0.0"

EXT_ID_BASE = "io.github.alex98235.libreoffice.catppuccin"
PUBLISHER_NAME = "Alexander Lindgren"
PUBLISHER_HREF = "https://github.com/Alex98235/libreoffice-catppuccin-theme"
REPO_HREF = PUBLISHER_HREF

# Published set: one .oxt per flavor, each containing every accent.
PUBLISHED_FLAVORS = ["mocha", "macchiato", "frappe", "latte"]
DEFAULT_ACCENT = "mauve"

# ---------------------------------------------------------------------------
# Node maps.
#
# EDITOR_NODES match the name->token mapping from
# catppuccin/libreoffice templates/libreoffice-xcu.tera.
# CHROME_NODES add the window/UI chrome nodes that the editor-only
# template omits: toolbars, menus, dialogs, buttons, selection colours, etc.
# ---------------------------------------------------------------------------
EDITOR_NODES = [
    ("Links", "accent", True),
    ("Spell", "red", None),
    ("Shadow", "text", True),
    ("CalcGrid", "surface2", None),
    ("CalcText", "accent", None),
    ("DocColor", "base", None),
    ("DrawGrid", "surface0", True),
    ("HTMLSGML", "blue", None),
    ("CalcValue", "blue", None),
    ("FontColor", "text", None),
    ("SQLNumber", "green", None),
    ("SQLString", "yellow", None),
    ("SmartTags", "pink", None),
    ("BASICError", "red", None),
    ("SQLComment", "blue", None),
    ("SQLKeyword", "teal", None),
    ("BASICNumber", "mauve", None),
    ("BASICString", "yellow", None),
    ("CalcFormula", "green", None),
    ("HTMLComment", "green", None),
    ("HTMLKeyword", "red", None),
    ("HTMLUnknown", "text", None),
    ("SQLOperator", "text", None),
    ("BASICComment", "blue", None),
    ("BASICKeyword", "peach", None),
    ("LinksVisited", "mauve", True),
    ("SQLParameter", "peach", None),
    ("AppBackground", "crust", None),
    ("BASICOperator", "green", None),
    ("CalcDetective", "teal", None),
    ("CalcPageBreak", "blue", None),
    ("CalcReference", "pink", None),
    ("DocBoundaries", "base", True),
    ("SQLIdentifier", "green", None),
    ("WriterTextGrid", "base", None),
    ("BASICIdentifier", "teal", None),
    ("BASICEditor", "base", None),
    ("TableBoundaries", "base", True),
    ("ObjectBoundaries", "text", True),
    ("WriterPageBreaks", "blue", None),
    ("WriterIdxShadings", "base", True),
    ("CalcDetectiveError", "red", None),
    ("WriterDirectCursor", "text", True),
    ("CalcNotesBackground", "base", None),
    ("CalcPageBreakManual", "blue", None),
    ("WriterFieldShadings", "base", True),
    ("WriterScriptIndicator", "green", None),
    ("CalcPageBreakAutomatic", "base", None),
    ("WriterHeaderFooterMark", "teal", None),
    ("CalcProtectedBackground", "base", None),
    ("WriterSectionBoundaries", "base", True),
]

CHROME_NODES = [
    ("BaseColor", "base"),
    ("FieldColor", "surface0"),
    ("WindowColor", "mantle"),
    ("FaceColor", "mantle"),
    ("MenuColor", "base"),
    ("MenuBarColor", "base"),
    ("ButtonColor", "surface0"),
    ("MenuTextColor", "text"),
    ("MenuBarTextColor", "text"),
    ("ButtonTextColor", "text"),
    ("WindowTextColor", "text"),
    ("MenuHighlightColor", "accent"),
    ("MenuBarHighlightColor", "accent"),
    ("ActiveColor", "accent"),
    ("ActiveTextColor", "base"),
    ("ActiveBorderColor", "accent"),
    ("AccentColor", "accent"),
    ("MenuHighlightTextColor", "base"),
    ("MenuBarHighlightTextColor", "base"),
    ("MenuBorderColor", "surface1"),
    ("InactiveColor", "surface0"),
    ("InactiveTextColor", "text"),
    ("InactiveBorderColor", "surface1"),
    ("DisabledColor", "surface0"),
    ("DisabledTextColor", "overlay0"),
    ("SeparatorColor", "surface1"),
    ("ShadowColor", "crust"),
]

# .soc palette: draw:name -> color token (based on libreoffice-soc.tera).
SOC_COLORS = [
    ("Background", "base"),
    ("Current Line", "accent"),
    ("Comment", "surface0"),
    ("Foreground", "rosewater"),
    ("Green", "green"),
    ("Cyan", "sky"),
    ("Purple", "mauve"),
    ("Pink", "pink"),
    ("Red", "red"),
    ("Orange", "peach"),
    ("Yellow", "yellow"),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def load_palette(path: Path = PALETTE_PATH) -> dict:
    with path.open(encoding="utf-8") as fh:
        palette = json.load(fh)
    palette.pop("version", None)
    return palette


def accent_tokens(palette: dict, flavor: str) -> list[str]:
    return [t for t, v in palette[flavor]["colors"].items() if v.get("accent")]


def hex_to_int24(hex_color: str) -> int:
    return int(hex_color.lstrip("#"), 16)


def scheme_name(palette: dict, flavor: str, accent: str) -> str:
    return f"Catppuccin {palette[flavor]['name']} - {accent.capitalize()}"


def _node_xml(name: str, value: int, visible, indent: str) -> str:
    props = f'<prop oor:name="Color" oor:op="fuse"><value>{value}</value></prop>'
    if visible is not None:
        props += (
            '<prop oor:name="IsVisible" oor:op="fuse"><value>'
            f'{"true" if visible else "false"}</value></prop>'
        )
    return f'{indent}<node oor:name="{name}">{props}</node>'


def render_theme_xcu(palette: dict, flavor: str, accent: str) -> str:
    """Render Theme_Colors.xcu for a single accent scheme."""

    return _render_theme_xcu(palette, flavor, [accent])


def _render_theme_xcu(palette: dict, flavor: str, accents: list[str]) -> str:
    """Render Theme_Colors.xcu with one or more accent schemes.

    Each accent gets its own scheme node named ``Catppuccin <Flavor> - <Accent>``
    inside ColorSchemes.  ``CurrentColorScheme`` is never emitted, so installing
    an extension does not change the user's active scheme; they pick one under
    Tools → Options → LibreOffice → Application Colors.
    """
    colors = palette[flavor]["colors"]

    def dec(token: str, accent: str) -> int:
        return hex_to_int24(colors[accent if token == "accent" else token]["hex"])

    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        '<oor:component-data xmlns:oor="http://openoffice.org/2001/registry" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'oor:name="UI" oor:package="org.openoffice.Office">',
        '  <node oor:name="ColorScheme">',
        '    <node oor:name="ColorSchemes">',
    ]

    for accent in accents:
        name = f"Catppuccin {palette[flavor]['name']} - {accent.capitalize()}"
        out.append(f'      <node oor:name="{name}" oor:op="fuse">')
        for node_name, token, visible in EDITOR_NODES:
            out.append(_node_xml(node_name, dec(token, accent), visible, "        "))
        for node_name, token in CHROME_NODES:
            out.append(_node_xml(node_name, dec(token, accent), None, "        "))
        out.append("      </node>")

    out.append("    </node>")
    out.append("  </node>")
    out.append("</oor:component-data>")
    return "\n".join(out) + "\n"


def render_soc(palette: dict, flavor: str, accent: str) -> str:
    colors = palette[flavor]["colors"]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<office:color-table xmlns:office="http://openoffice.org/2000/office" '
        'xmlns:draw="http://openoffice.org/2000/drawing">',
        "",
    ]
    for soc_name, token in SOC_COLORS:
        hexc = colors[accent if token == "accent" else token]["hex"]
        out.append(f'<draw:color draw:name="{soc_name}" draw:color="{hexc}"/>')
    out.append("")
    out.append("</office:color-table>")
    return "\n".join(out) + "\n"


def render_description(palette: dict, flavor: str, accent: str | None = None) -> str:
    ext_id = (
        f"{EXT_ID_BASE}.{flavor}" if accent is None
        else f"{EXT_ID_BASE}.{flavor}.{accent}"
    )
    display = f"Catppuccin {palette[flavor]['name']}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<description xmlns="http://openoffice.org/extensions/description/2006"
             xmlns:d="http://openoffice.org/extensions/description/2006"
             xmlns:xlink="http://www.w3.org/1999/xlink">
    <identifier value="{ext_id}" />
    <version value="{VERSION}" />
    <publisher>
        <name xlink:href="{PUBLISHER_HREF}" lang="en">{PUBLISHER_NAME}</name>
    </publisher>
    <display-name>
        <name lang="en">{display}</name>
    </display-name>
    <icon>
        <default xlink:href="assets/icon.png" />
    </icon>
    <registration>
        <simple-license accept-by="admin" default-license-id="id_license" suppress-on-update="true">
            <license-text xlink:href="license.txt" lang="en" license-id="id_license" />
        </simple-license>
    </registration>
    <extension-description>
        <src xlink:href="pkg-description.en" lang="en" />
    </extension-description>
</description>
"""


def render_pkg_description(palette: dict, flavor: str, accent: str | None = None) -> str:
    name = palette[flavor]["name"]
    scope = "all accent colors" if accent is None else f"{accent} accent"
    return (
        f"Catppuccin {name} ({scope}). An UNOFFICIAL LibreOffice UI theme built "
        "from the Catppuccin palette (https://catppuccin.com).\n\n"
        "Themes menus, toolbars, buttons, dialogs and document/editor colors.\n\n"
        "Not affiliated with or endorsed by the Catppuccin project or the "
        "catppuccin/libreoffice maintainers. Palette: MIT, (c) Catppuccin "
        "contributors. See the project README for details.\n"
    )


MANIFEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="http://openoffice.org/2001/manifest">
  <!-- Theme ColorScheme data -->
  <manifest:file-entry manifest:full-path="Theme_Colors.xcu" manifest:media-type="application/vnd.sun.star.configuration-data"/>
  <!-- Palette path registration -->
  <manifest:file-entry manifest:full-path="Paths.xcu" manifest:media-type="application/vnd.sun.star.configuration-data"/>
</manifest:manifest>
"""

PATHS_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:component-data xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" oor:name="Paths" oor:package="org.openoffice.Office">
  <node oor:name="Paths">
    <node oor:name="Palette">
      <node oor:name="InternalPaths">
        <!-- %origin% is the root of this extension -->
        <node oor:name="%origin%/palettes" oor:op="fuse"/>
      </node>
    </node>
  </node>
</oor:component-data>
"""


def write_png(path: Path, rgb: tuple[int, int, int], size: int = 96) -> None:
    """Write a solid-colour square PNG using only the standard library."""
    r, g, b = rgb
    raw = bytearray()
    row = bytes((r, g, b)) * size
    for _ in range(size):
        raw.append(0)  # filter type 0
        raw.extend(row)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _validate_xml(label: str, text: str) -> None:
    try:
        ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:  # pragma: no cover - defensive
        raise SystemExit(f"[build] {label} is not well-formed XML: {exc}") from exc


def build_one(palette: dict, flavor: str, accent: str, out_dir: Path) -> Path:
    if flavor not in palette:
        raise SystemExit(f"[build] unknown flavor '{flavor}' (have: {', '.join(palette)})")
    if accent not in palette[flavor]["colors"]:
        raise SystemExit(f"[build] unknown accent '{accent}' for flavor '{flavor}'")

    theme_xcu = render_theme_xcu(palette, flavor, accent)
    soc = render_soc(palette, flavor, accent)
    desc = render_description(palette, flavor, accent)
    pkg_desc = render_pkg_description(palette, flavor, accent)

    # Fail fast on malformed XML before packaging.
    _validate_xml("Theme_Colors.xcu", theme_xcu)
    _validate_xml("Paths.xcu", PATHS_XCU)
    _validate_xml("manifest.xml", MANIFEST_XML)
    _validate_xml("description.xml", desc)
    _validate_xml("palette .soc", soc)

    out_dir.mkdir(parents=True, exist_ok=True)
    oxt_name = f"catppuccin-{flavor}-{accent}.oxt"
    oxt_path = out_dir / oxt_name

    staging = Path(tempfile.mkdtemp(prefix="lo-theme-"))
    try:
        (staging / "META-INF").mkdir()
        (staging / "palettes").mkdir()
        (staging / "assets").mkdir()

        (staging / "description.xml").write_text(desc, encoding="utf-8")
        (staging / "Theme_Colors.xcu").write_text(theme_xcu, encoding="utf-8")
        (staging / "Paths.xcu").write_text(PATHS_XCU, encoding="utf-8")
        (staging / "license.txt").write_text((ROOT / "LICENSE").read_text("utf-8"), encoding="utf-8")
        (staging / "pkg-description.en").write_text(pkg_desc, encoding="utf-8")
        (staging / "META-INF" / "manifest.xml").write_text(MANIFEST_XML, encoding="utf-8")
        (staging / "palettes" / f"catppuccin-{flavor}-{accent}.soc").write_text(
            soc, encoding="utf-8"
        )
        accent_hex = palette[flavor]["colors"][accent]["hex"].lstrip("#")
        write_png(staging / "assets" / "icon.png",
                  struct.unpack("BBB", bytes.fromhex(accent_hex)))

        with zipfile.ZipFile(oxt_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(staging).as_posix())
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return oxt_path


def build_one_flavor(palette: dict, flavor: str, out_dir: Path) -> Path:
    """Build one ``.oxt`` holding every accent scheme for *flavor*.

    The extension registers ``Catppuccin <Flavor> - <Accent>`` for each accent
    token, so the user installs once and picks their accent in
    Tools -> Options -> LibreOffice -> Application Colors.
    """
    if flavor not in palette:
        raise SystemExit(f"[build] unknown flavor '{flavor}' (have: {', '.join(palette)})")

    accents = accent_tokens(palette, flavor)
    theme_xcu = _render_theme_xcu(palette, flavor, accents)
    socs = {accent: render_soc(palette, flavor, accent) for accent in accents}
    desc = render_description(palette, flavor, None)
    pkg_desc = render_pkg_description(palette, flavor, None)

    _validate_xml("Theme_Colors.xcu", theme_xcu)
    _validate_xml("Paths.xcu", PATHS_XCU)
    _validate_xml("manifest.xml", MANIFEST_XML)
    _validate_xml("description.xml", desc)
    for accent, soc in socs.items():
        _validate_xml(f"palette .soc ({accent})", soc)

    out_dir.mkdir(parents=True, exist_ok=True)
    oxt_path = out_dir / f"catppuccin-{flavor}.oxt"

    staging = Path(tempfile.mkdtemp(prefix="lo-theme-"))
    try:
        (staging / "META-INF").mkdir()
        (staging / "palettes").mkdir()
        (staging / "assets").mkdir()

        (staging / "description.xml").write_text(desc, encoding="utf-8")
        (staging / "Theme_Colors.xcu").write_text(theme_xcu, encoding="utf-8")
        (staging / "Paths.xcu").write_text(PATHS_XCU, encoding="utf-8")
        (staging / "license.txt").write_text((ROOT / "LICENSE").read_text("utf-8"), encoding="utf-8")
        (staging / "pkg-description.en").write_text(pkg_desc, encoding="utf-8")
        (staging / "META-INF" / "manifest.xml").write_text(MANIFEST_XML, encoding="utf-8")
        for accent, soc in socs.items():
            (staging / "palettes" / f"catppuccin-{flavor}-{accent}.soc").write_text(
                soc, encoding="utf-8"
            )

        icon_accent = DEFAULT_ACCENT if DEFAULT_ACCENT in palette[flavor]["colors"] else accents[0]
        accent_hex = palette[flavor]["colors"][icon_accent]["hex"].lstrip("#")
        write_png(staging / "assets" / "icon.png",
                  struct.unpack("BBB", bytes.fromhex(accent_hex)))

        with zipfile.ZipFile(oxt_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(staging).as_posix())
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return oxt_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flavor", help="flavor to build (default: all published flavors)")
    parser.add_argument("--accent", default=None,
                        help="single accent token; when omitted each flavor is "
                             "built as one combined .oxt containing all accents")
    parser.add_argument("--all-accents", action="store_true",
                        help="build one .oxt per flavor/accent combination (many files)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"output directory (default: {DEFAULT_OUT})")
    args = parser.parse_args(argv)

    palette = load_palette()
    built: list[Path] = []

    if args.flavor and args.flavor not in palette:
        parser.error(f"unknown flavor '{args.flavor}' (choose from: {', '.join(palette)})")

    if args.all_accents:
        for flavor in palette:
            for accent in accent_tokens(palette, flavor):
                built.append(build_one(palette, flavor, accent, args.out))
    elif args.flavor:
        if args.accent:
            built.append(build_one(palette, args.flavor, args.accent, args.out))
        else:
            built.append(build_one_flavor(palette, args.flavor, args.out))
    elif args.accent:
        for flavor in PUBLISHED_FLAVORS:
            built.append(build_one(palette, flavor, args.accent, args.out))
    else:
        for flavor in PUBLISHED_FLAVORS:
            built.append(build_one_flavor(palette, flavor, args.out))

    print(f"[build] Catppuccin LibreOffice themes v{VERSION} -> {args.out}")
    for path in built:
        print(f"[build]   {path.name}  ({path.stat().st_size} bytes)")
    print(f"[build] done: {len(built)} extension(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
