"""Gera os temas de PDF (Typst) a partir de ``mtg_epub/themes.py``, a fonte única da verdade.

Uso::

    python -m mtg_epub.typst_themes             # regrava typst_packages/local/mtgstory/0.2.0/themes.typ
    python -m mtg_epub.typst_themes --wrappers  # também passa ``cover:`` para os wrappers de set em stories/

Para cada tema do EPUB são gerados: fontes de título e de corpo (listas de fallback) e uma cor de
destaque lida do CSS. Também é gerado o dicionário ``nome do set -> chave do tema``.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from zipfile import ZipFile

from . import REPO_ROOT
from .themes import DEFAULT_FONTS_DIR, THEMES, THEMES_DIR, Theme, theme_for_set

THEMES_TYP = REPO_ROOT / "typst_packages" / "local" / "mtgstory" / "0.2.0" / "themes.typ"
STORIES_DIR = REPO_ROOT / "stories"
SET_NAMES_JSON = REPO_ROOT / "set-names.json"

BODY_FONTS = ("Crimson Text", "Libertinus Serif")
TITLE_FALLBACK = ("Crimson Text", "Libertinus Serif")
NEUTRAL_KEY = "neutral"
NEUTRAL_ACCENT = "#2b2b2b"

_GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_TYP_SET_NAME_RE = re.compile(r'set_name:\s*"((?:[^"\\]|\\.)*)"')


# --- fontes ---------------------------------------------------------------------------------

def _family_of(data: bytes | Path) -> str | None:
    try:
        from PIL import ImageFont
    except ImportError:  # pragma: no cover
        return None
    try:
        source = io.BytesIO(data) if isinstance(data, bytes) else str(data)
        return ImageFont.truetype(source, 20).getname()[0]
    except Exception:
        return None


def missing_theme_fonts(theme: Theme, fonts_dir: Path | None = None) -> list[str]:
    """Arquivos de fonte (soltos ou zips) do tema que não existem em ``fonts_dir``."""
    fonts_dir = fonts_dir or DEFAULT_FONTS_DIR
    names = [*theme.font_files, *(archive for _target, archive in theme.font_archives)]
    return [name for name in names if not (fonts_dir / name).exists()]


def theme_families(theme: Theme, fonts_dir: Path | None = None) -> list[str]:
    """Nomes de família reais das fontes do tema (soltas e dentro dos zips), na ordem do tema."""
    fonts_dir = fonts_dir or DEFAULT_FONTS_DIR
    families: list[str] = []

    def add(name: str | None) -> None:
        if name and name not in families:
            families.append(name)

    for font_name in theme.font_files:
        path = fonts_dir / font_name
        if path.exists():
            add(_family_of(path))
    for _target, archive_name in theme.font_archives:
        archive_path = fonts_dir / archive_name
        if not archive_path.exists():
            continue
        with ZipFile(archive_path) as archive:
            members = [m for m in archive.namelist() if m.lower().endswith((".ttf", ".otf"))]
            if members:
                add(_family_of(archive.read(members[0])))
    return families


def _css_families(value: str) -> list[str]:
    families = []
    for part in value.split(","):
        name = part.strip().strip("'\"")
        if name and name.casefold() not in _GENERIC_FAMILIES:
            families.append(name)
    return families


# --- CSS ------------------------------------------------------------------------------------

def _rules(css: str) -> list[tuple[list[str], dict[str, list[str]]]]:
    """Lista de (seletores, {propriedade: [valores na ordem]}). Declarações repetidas são mantidas."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = []
    for selectors, body in _RULE_RE.findall(css):
        props: dict[str, list[str]] = {}
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            key, _, value = declaration.partition(":")
            props.setdefault(key.strip().lower(), []).append(value.strip())
        rules.append(([s.strip() for s in selectors.split(",")], props))
    return rules


def _custom_properties(rules) -> dict[str, str]:
    result: dict[str, str] = {}
    for _selectors, props in rules:
        for key, values in props.items():
            if key.startswith("--"):
                result[key] = values[-1]
    return result


def _hex_colors(value: str, variables: dict[str, str]) -> list[str]:
    value = re.sub(r"var\((--[\w-]+)[^)]*\)", lambda m: variables.get(m.group(1), ""), value)
    colors = []
    for match in _HEX_RE.findall(value):
        color = match.lower()
        if len(color) == 4:
            color = "#" + "".join(ch * 2 for ch in color[1:])
        colors.append(color)
    return colors


def _luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_on_white(color: str) -> float:
    return 1.05 / (_luminance(color) + 0.05)


def _saturation(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    high, low = max(channels), min(channels)
    return 0.0 if high == 0 else (high - low) / high


def _selector_matches(selectors: list[str], wanted: str) -> bool:
    return any(s.replace(" ", "") == wanted for s in selectors)


def accent_from_css(css: str) -> str:
    """Cor de destaque do tema, legível sobre papel branco.

    Candidatos, em ordem: ``color`` de h1/h2, cor da capitular (``h1 + p::first-letter``), cor do
    ornamento (``hr::before``), cores de borda de h1/h2 e custom properties. Prefere o primeiro
    candidato legível e com cor (saturação); senão o primeiro legível; senão o primeiro candidato escurecido; senão preto.
    """
    rules = _rules(css)
    variables = _custom_properties(rules)
    candidates: list[str] = []

    def collect(predicate, only_props: tuple[str, ...] | None = None) -> None:
        for selectors, props in rules:
            if not predicate(selectors):
                continue
            for key, values in props.items():
                if only_props is not None and key not in only_props:
                    continue
                if key.startswith("border") or key == "color":
                    for value in values:
                        candidates.extend(_hex_colors(value, variables))

    is_heading = lambda sel: any(s.split(",")[0] in {"h1", "h2", "h3"} for s in sel) and not any("::" in s for s in sel)
    collect(is_heading, ("color",))
    collect(lambda sel: any("first-letter" in s for s in sel), ("color",))
    collect(lambda sel: any(s.startswith("hr") and "::before" in s for s in sel), ("color",))
    collect(is_heading)
    candidates.extend(_hex_colors(" ".join(variables.values()), {}))

    readable = [c for c in candidates if _contrast_on_white(c) >= 3.0]
    colorful = [c for c in readable if _saturation(c) >= 0.25]
    if colorful or readable:
        return (colorful or readable)[0]
    return _darkened(candidates[0]) if candidates else "#000000"


def _darkened(color: str) -> str:
    """Escurece a cor (mistura com preto) até ficar legível sobre papel branco."""
    channels = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    for factor in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4):
        darker = "#" + "".join(f"{int(c * factor):02x}" for c in channels)
        if _contrast_on_white(darker) >= 3.0:
            return darker
    return "#000000"


def title_families_from_css(css: str) -> list[str]:
    """``font-family`` do primeiro h1/h2 do tema (sem famílias genéricas)."""
    for selectors, props in _rules(css):
        if any(s.split(",")[0] in {"h1", "h2"} for s in selectors) and not any("::" in s for s in selectors):
            if "font-family" in props:
                return _css_families(props["font-family"][-1])
    return []


# --- geração --------------------------------------------------------------------------------

def theme_spec(theme: Theme, fonts_dir: Path | None = None) -> dict:
    css = (THEMES_DIR / theme.css_file).read_text(encoding="utf-8")
    discovered = theme_families(theme, fonts_dir)
    title: list[str] = [f for f in title_families_from_css(css) if f in discovered]
    for family in discovered:
        if family not in title:
            title.append(family)
    for family in TITLE_FALLBACK:
        if family not in title:
            title.append(family)
    return {"title_fonts": title, "body_fonts": list(BODY_FONTS), "accent": accent_from_css(css)}


def known_set_names(stories_dir: Path | None = None) -> list[str]:
    """Nomes de set conhecidos: set-names.json, ``set_name`` dos .typ do acervo e "Chronological"."""
    names: list[str] = []

    def add(name: str) -> None:
        name = name.strip()
        if name and name not in names:
            names.append(name)

    if SET_NAMES_JSON.exists():
        for value in json.loads(SET_NAMES_JSON.read_text(encoding="utf-8")).values():
            add(str(value))
    stories_dir = stories_dir or STORIES_DIR
    for path in sorted(stories_dir.glob("[0-9]*/*.typ")):
        if ".tmp" in path.name:
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            continue
        match = _TYP_SET_NAME_RE.search(head)
        if match:
            add(match.group(1).replace('\\"', '"').replace("\\\\", "\\"))
    add("Chronological")
    return names


def set_theme_map(names: list[str]) -> dict[str, str]:
    """nome do set -> chave do tema (só os que têm tema; os demais caem no neutro)."""
    keys_by_id = {id(theme): key for key, theme in THEMES.items()}
    mapping: dict[str, str] = {}
    for name in names:
        theme = theme_for_set(name)
        if theme is not None:
            mapping[name] = keys_by_id[id(theme)]
    return mapping


def _typ_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _typ_fonts(fonts: list[str]) -> str:
    return "(" + ", ".join(_typ_string(f) for f in fonts) + ",)"


def _typ_theme(spec: dict) -> str:
    return (
        f"(title-font: {_typ_fonts(spec['title_fonts'])}, body-font: {_typ_fonts(spec['body_fonts'])}, "
        f"accent: rgb({_typ_string(spec['accent'])}))"
    )


def render_themes_typ(fonts_dir: Path | None = None, stories_dir: Path | None = None,
                      missing: list[str] | None = None) -> str:
    """``missing`` (opcional) recebe "tema: arquivo" para cada fonte ausente (o resultado muda sem ela)."""
    if missing is not None:
        for key, theme in THEMES.items():
            missing.extend(f"{key}: {name}" for name in missing_theme_fonts(theme, fonts_dir))
    specs = {key: theme_spec(theme, fonts_dir) for key, theme in THEMES.items()}
    specs[NEUTRAL_KEY] = {
        "title_fonts": list(TITLE_FALLBACK),
        "body_fonts": list(BODY_FONTS),
        "accent": NEUTRAL_ACCENT,
    }
    mapping = set_theme_map(known_set_names(stories_dir))
    lines = [
        "// ARQUIVO GERADO por `python -m mtg_epub.typst_themes` a partir de mtg_epub/themes.py.",
        "// Não edite à mão: rode o gerador de novo.",
        "",
        "#let themes = (",
    ]
    lines += [f"  {_typ_string(key)}: {_typ_theme(spec)}," for key, spec in specs.items()]
    lines += [")", "", "#let set-themes = ("]
    lines += [f"  {_typ_string(name)}: {_typ_string(key)}," for name, key in sorted(mapping.items())]
    lines += [
        ")",
        "",
        "// Tema pelo nome do set; sets desconhecidos caem no neutro.",
        f'#let theme-for(set-name) = themes.at(set-themes.at(set-name, default: "{NEUTRAL_KEY}"), default: themes.at("{NEUTRAL_KEY}"))',
        "",
    ]
    return "\n".join(lines)


def _write_if_changed(path: Path, data: bytes) -> bool:
    """Grava só se o conteúdo mudou (preserva o mtime e não invalida caches). Devolve se gravou."""
    try:
        if path.read_bytes() == data:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def write_themes_typ(path: Path = THEMES_TYP, missing: list[str] | None = None) -> Path:
    _write_if_changed(path, render_themes_typ(missing=missing).encode("utf-8"))
    return path


# --- wrappers de set (capa) -----------------------------------------------------------------

_INCLUDE_RE = re.compile(r'^#include\s+"((?:[^"\\]|\\.)*)"', re.M)
_INCLUDE_LINE_RE = re.compile(r'^(#include ")([^\r\n]*)(")[ \t]*(?=\r|\n|$)', re.M)
_CONF_CALL_RE = re.compile(
    r'#show: doc => conf\((?P<name>"(?:[^"\\]|\\.)*")(?:, cover: image\("(?:[^"\\]|\\.)*"\))?, doc\)'
)


def repair_include_quotes(text: str, base_dir: Path | None = None) -> str:
    """Corrige caminhos de ``#include`` quebrados em wrappers antigos.

    - aspas soltas no meio do caminho (``"./004 - Dragon"s Maze/..."``): o nome real da pasta usa
      apóstrofo;
    - com ``base_dir``, caminhos com ``:`` cujo arquivo real usa ``-`` (nomes de arquivo no disco).
    """

    def fix(match: re.Match) -> str:
        path = match.group(2).replace('"', "'")
        if base_dir is not None and not (base_dir / path).exists():
            alternative = path.replace(":", "-")
            if (base_dir / alternative).exists():
                path = alternative
        return match.group(1) + path + match.group(3)

    return _INCLUDE_LINE_RE.sub(fix, text)


def cover_for_wrapper(wrapper: Path) -> Path | None:
    """Mesma regra de ``metadata.extract_metadata``: 1ª imagem do primeiro conto incluído."""
    from .metadata import _cover_candidates

    match = _INCLUDE_RE.search(repair_include_quotes(wrapper.read_bytes().decode("utf-8"), wrapper.parent))
    if not match:
        return None
    first_story = (wrapper.parent / match.group(1).replace('\\"', '"')).resolve()
    candidates = _cover_candidates(first_story)
    return candidates[0] if candidates else None


def update_set_wrappers(stories_dir: Path | None = None, only: Path | None = None) -> list[Path]:
    """Atualiza os wrappers da raiz de stories/: ``cover: image("...")`` e aspas soltas nos ``#include``."""
    stories_dir = stories_dir or STORIES_DIR
    changed: list[Path] = []
    for wrapper in sorted(stories_dir.glob("[0-9]*_*.typ")):
        if only is not None and wrapper != only:
            continue
        # Bytes, sem normalizar quebras de linha: os wrappers têm finais de linha próprios.
        original = wrapper.read_bytes().decode("utf-8")
        text = repair_include_quotes(original, wrapper.parent)
        match = _CONF_CALL_RE.search(text)
        if not match or "@local/mtgset" not in text:
            continue
        cover = cover_for_wrapper(wrapper)
        if cover is None:
            new_line = f"#show: doc => conf({match.group('name')}, doc)"
        else:
            rel = cover.relative_to(wrapper.parent.resolve()).as_posix()
            new_line = f'#show: doc => conf({match.group("name")}, cover: image({_typ_string(rel)}), doc)'
        new_text = text[: match.start()] + new_line + text[match.end() :]
        if _write_if_changed(wrapper, new_text.encode("utf-8")):
            changed.append(wrapper)
    return changed


_SET_NUMBER_RE = re.compile(r"^(\d+)")


def _numeric_key(path: Path) -> tuple[int, str]:
    match = _SET_NUMBER_RE.match(path.name)
    return (int(match.group(1)) if match else 10**9, path.name.casefold())


def _wrapper_set_name(folder: Path) -> str:
    """Nome do set: ``set_name`` do primeiro conto da pasta; senão o nome da pasta sem o número."""
    for path in sorted(folder.glob("*.typ"), key=_numeric_key):
        try:
            match = _TYP_SET_NAME_RE.search(path.read_text(encoding="utf-8", errors="replace")[:1500])
        except OSError:
            continue
        if match:
            return match.group(1).replace('\\"', '"').replace("\\\\", "\\")
    return folder.name.split(" - ", 1)[-1].strip()


def sync_set_wrapper(folder: Path, stories_dir: Path | None = None) -> Path | None:
    """Regenera os ``#include`` do wrapper ``stories/NNN_*.typ`` a partir dos .typ da pasta do set.

    Mantém o cabeçalho (import e ``conf(...)`` com ``cover:``), o estilo de caminho (``./`` ou não)
    e os finais de linha do wrapper existente. Sem wrapper, cria um no formato dos demais e define
    o ``cover`` pela mesma regra de ``update_set_wrappers``. Devolve o wrapper se gravou, senão None.
    """
    folder = Path(folder)
    stories_dir = Path(stories_dir) if stories_dir is not None else folder.parent
    number = _SET_NUMBER_RE.match(folder.name)
    if number is None or not folder.is_dir():
        return None
    stories = sorted(
        (p for p in folder.glob("*.typ") if p.is_file() and ".tmp" not in p.name), key=_numeric_key
    )
    if not stories:
        return None
    wrappers = sorted(p for p in stories_dir.glob(f"{number.group(1)}_*.typ") if p.is_file())
    created = not wrappers
    if wrappers:
        wrapper = wrappers[0]
        original = wrapper.read_bytes().decode("utf-8")
        eol = "\r\n" if "\r\n" in original else "\n"
        text = original.replace("\r\n", "\n")
        includes = list(_INCLUDE_LINE_RE.finditer(text))
        head = text[: includes[0].start()] if includes else text.rstrip("\n") + "\n\n"
        dotted = bool(includes) and includes[0].group(2).startswith("./")
        if "@local/mtgset" not in head:
            return None
    else:
        set_name = _wrapper_set_name(folder)
        slug = re.sub(r'[<>:"/\|?*]', "-", set_name).strip() or folder.name
        wrapper = stories_dir / f"{number.group(1)}_{slug}.typ"
        eol, dotted = "\n", True
        head = f'#import "@local/mtgset:0.1.0": conf\n#show: doc => conf({_typ_string(set_name)}, doc)\n\n'
    prefix = "./" if dotted else ""
    body = "\n".join(f'#include "{prefix}{folder.name}/{p.name}"' for p in stories)
    wrote = _write_if_changed(wrapper, (head + body + "\n").replace("\n", eol).encode("utf-8"))
    if created:  # wrapper novo: cover pela mesma regra dos demais (o existente mantém o cabeçalho)
        update_set_wrappers(wrapper.parent, only=wrapper)
    return wrapper if wrote else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wrappers", action="store_true", help="também atualiza `cover:` nos wrappers de set")
    parser.add_argument("--strict", action="store_true", help="exit 1 se alguma fonte dos temas não for encontrada")
    args = parser.parse_args(argv)
    missing: list[str] = []
    print(f"themes.typ: {write_themes_typ(missing=missing)}")
    for entry in missing:
        print(f"aviso: fonte não encontrada em fonts/ ({entry}); themes.typ gerado sem ela", file=sys.stderr)
    if args.wrappers:
        changed = update_set_wrappers()
        print(f"wrappers atualizados: {len(changed)}")
    return 1 if args.strict and missing else 0


if __name__ == "__main__":
    sys.exit(main())
