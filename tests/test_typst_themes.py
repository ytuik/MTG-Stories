"""Temas de PDF (Typst) gerados a partir de mtg_epub/themes.py e compilação dos pacotes do repositório."""
from __future__ import annotations

import os
import re

import pytest
import typst

from mtg_epub import REPO_ROOT, typst_themes
from mtg_epub.themes import THEMES, theme_for_set
from mtg_epub.typst_themes import (
    NEUTRAL_KEY,
    THEMES_TYP,
    accent_from_css,
    cover_for_wrapper,
    known_set_names,
    render_themes_typ,
    set_theme_map,
    theme_spec,
)

PACKAGES = REPO_ROOT / "typst_packages"
FONTS = REPO_ROOT / "fonts"
STORY = REPO_ROOT / "stories" / "057 - Bloomburrow" / "002_Episode 2- An Expected Party.typ"
SET_WRAPPER = REPO_ROOT / "stories" / "057_Bloomburrow.typ"
GUIDE = REPO_ROOT / "planeswalkers_guides" / "001 - Planeswalker's Guide to Ulgrotha" / "001 - Planeswalker's Guide to Ulgrotha.typ"

needs_fonts = pytest.mark.skipif(not FONTS.is_dir(), reason="fonts/ ausente (checkout parcial)")

needs_packages = pytest.mark.skipif(
    not (PACKAGES / "local" / "mtgstory" / "0.2.0" / "mtgstory.typ").exists()
    or not THEMES_TYP.exists(),
    reason="pacotes Typst do repositório (ou themes.typ) ausentes",
)


def compile_typ(source, root=REPO_ROOT, **kwargs):
    return typst.compile(
        str(source),
        root=str(root),
        package_path=str(PACKAGES),
        package_cache_path=str(PACKAGES / "cache"),
        font_paths=[str(FONTS)] if FONTS.exists() else [],
        **kwargs,
    )


def test_set_mapping_matches_theme_for_set():
    names = known_set_names()
    mapping = set_theme_map(names)
    assert "Chronological" in names and "Bloomburrow" in names
    for name in names:
        theme = theme_for_set(name)
        if theme is None:
            assert name not in mapping
        else:
            assert THEMES[mapping[name]] is theme
    assert mapping["Bloomburrow"] == "fables"
    assert mapping["Chronological"] == "anthology"


def test_generated_typ_contains_all_themes_and_a_neutral_one():
    content = render_themes_typ()
    for key in [*THEMES, NEUTRAL_KEY]:
        assert f'"{key}": (title-font:' in content
    assert '"Bloomburrow": "fables"' in content
    assert "#let theme-for(set-name)" in content


@needs_fonts
def test_theme_specs_use_real_family_names_and_fallbacks():
    gothic = theme_spec(THEMES["gothic"], FONTS)
    assert gothic["title_fonts"][0] == "Old English Text MT"
    assert gothic["title_fonts"][-2:] == ["Crimson Text", "Libertinus Serif"]
    assert gothic["accent"] == "#8a0303"
    assert theme_spec(THEMES["mythos"], FONTS)["title_fonts"][0] == "Cinzel"
    for theme in THEMES.values():
        spec = theme_spec(theme, FONTS)
        assert spec["body_fonts"][0] == "Crimson Text"
        assert re.fullmatch(r"#[0-9a-f]{6}", spec["accent"])


def test_accent_prefers_readable_colors_over_white_paper():
    # Título claro (invisível no papel) cai para a cor da capitular/ornamento.
    css = "h1, h2 { color: #e6e6e6; } h1 + p::first-letter { color: #ff3333; }"
    assert accent_from_css(css) == "#ff3333"
    assert accent_from_css("h1 { color: #111; }") == "#111111"
    assert accent_from_css("p { margin: 0 }") == "#000000"
    assert accent_from_css("h1 { color: #fff; }") != "#ffffff"


def test_cover_rule_uses_first_image_of_first_story():
    if not SET_WRAPPER.exists():
        pytest.skip("wrapper de Bloomburrow ausente")
    cover = cover_for_wrapper(SET_WRAPPER)
    if cover is None:
        pytest.skip("imagens de Bloomburrow ausentes")
    assert cover.parent.name == "001_Episode 1- Calamity Comes to Valley"
    assert cover.suffix.lower() in {".jpg", ".png", ".jpeg", ".webp"}


@needs_packages
def test_generated_themes_compile_and_fall_back_to_neutral(tmp_path):
    mapping = set_theme_map(known_set_names())
    checks = "\n".join(
        f'#assert(theme-for({typst_themes._typ_string(name)}) == themes.at("{key}"))'
        for name, key in sorted(mapping.items())
    )
    doc = tmp_path / "themes_check.typ"
    doc.write_text(
        '#import "@local/mtgstory:0.2.0": theme-for, themes\n'
        '#let a = theme-for("Bloomburrow")\n'
        '#let b = theme-for("Duskmourn: House of Horror")\n'
        '#let unknown = theme-for("Totally Unknown Set")\n'
        '#assert(unknown == themes.at("neutral"))\n'
        "#assert(a != b)\n"
        f"{checks}\n"
        "#text(font: a.title-font, fill: a.accent)[Fables] #text(font: b.title-font, fill: b.accent)[Analog]"
        " #text(font: unknown.title-font, fill: unknown.accent)[Neutral]\n",
        encoding="utf-8",
    )
    assert compile_typ(doc, root=tmp_path, format="pdf").startswith(b"%PDF")


@needs_packages
@pytest.mark.skipif(not STORY.exists(), reason="conto de exemplo ausente")
def test_real_story_compiles_to_pdf_and_html():
    assert compile_typ(STORY, format="pdf").startswith(b"%PDF")
    html = compile_typ(STORY, format="html").decode("utf-8")
    # Estrutura do HTML (EPUB) inalterada: título, autor, set/data, parágrafos e figuras.
    assert html.count("<h3>") == 1
    assert "<h3>Episode 2: An Expected Party</h3>" in html
    assert "From set <em>Bloomburrow</em>" in html
    assert html.count("<img") >= 1 and html.count("<figure") >= 1
    assert html.count("<p>") > 50
    assert "<hr" not in html


@needs_packages
@pytest.mark.skipif(not SET_WRAPPER.exists() or not STORY.exists(), reason="wrapper de set ausente")
def test_set_book_compiles_with_outline():
    pdf = compile_typ(SET_WRAPPER, format="pdf")
    assert pdf.startswith(b"%PDF")
    assert b"/Type/Outlines" in pdf
    # Título do documento é o do set, não o do último conto incluído.
    assert b"/Title(Bloomburrow)/Author(Wizards of the Coast)" in pdf


@needs_packages
@pytest.mark.skipif(not GUIDE.exists(), reason="guia de exemplo ausente")
def test_guide_compiles_to_pdf():
    assert compile_typ(GUIDE, format="pdf").startswith(b"%PDF")


# --- fontes ausentes, escrita idempotente e wrapper de set ---------------------------------

def test_missing_fonts_are_reported_and_strict_fails(tmp_path, monkeypatch, capsys):
    out = tmp_path / "themes.typ"
    monkeypatch.setattr(typst_themes, "THEMES_TYP", out)
    monkeypatch.setattr(typst_themes, "DEFAULT_FONTS_DIR", tmp_path / "sem-fontes")
    missing: list[str] = []
    typst_themes.write_themes_typ(out, missing=missing)
    assert any(entry.startswith("gothic: ") for entry in missing)

    monkeypatch.setattr(typst_themes, "write_themes_typ",
                        lambda path=out, missing=None: typst_themes.render_themes_typ(missing=missing) and out)
    assert typst_themes.main(["--strict"]) == 1
    assert "fonte não encontrada" in capsys.readouterr().err
    assert typst_themes.main([]) == 0


def test_write_themes_typ_only_writes_when_content_changes(tmp_path):
    out = tmp_path / "themes.typ"
    typst_themes.write_themes_typ(out)
    os.utime(out, (1_000, 1_000))
    typst_themes.write_themes_typ(out)
    assert out.stat().st_mtime == 1_000
    out.write_text("velho", encoding="utf-8")
    os.utime(out, (1_000, 1_000))
    typst_themes.write_themes_typ(out)
    assert out.stat().st_mtime != 1_000


def _set(tmp_path, names, number="057", title="Bloomburrow"):
    stories = tmp_path / "stories"
    folder = stories / f"{number} - {title}"
    folder.mkdir(parents=True)
    for name in names:
        (folder / name).write_text(f'#let x = (\n    set_name: "{title}",\n)\n', encoding="utf-8")
    return stories, folder


def test_sync_set_wrapper_adds_new_story_in_numeric_order_and_keeps_header(tmp_path):
    stories, folder = _set(tmp_path, ["001_A.typ", "002_B.typ", "010_C.typ", "003_B.tmp.typ"])
    wrapper = stories / "057_Bloomburrow.typ"
    head = '#import "@local/mtgset:0.1.0": conf\r\n#show: doc => conf("Bloomburrow", cover: image("057 - Bloomburrow/001_A/01.jpg"), doc)\r\n\r\n'
    wrapper.write_bytes((head + '#include "./057 - Bloomburrow/001_A.typ"\r\n').encode())
    assert typst_themes.sync_set_wrapper(folder, stories) == wrapper
    text = wrapper.read_bytes().decode()
    assert text.startswith(head)
    assert text.endswith(
        '#include "./057 - Bloomburrow/001_A.typ"\r\n#include "./057 - Bloomburrow/002_B.typ"\r\n'
        '#include "./057 - Bloomburrow/010_C.typ"\r\n'
    )
    assert "\n" not in text.replace("\r\n", "")
    assert typst_themes.sync_set_wrapper(folder, stories) is None  # idempotente


def test_sync_set_wrapper_keeps_include_style_without_dot_slash(tmp_path):
    stories, folder = _set(tmp_path, ["001_A.typ", "002_B.typ"])
    wrapper = stories / "057_Bloomburrow.typ"
    wrapper.write_text('#import "@local/mtgset:0.1.0": conf\n#show: doc => conf("Bloomburrow", doc)\n\n#include "057 - Bloomburrow/001_A.typ"\n', encoding="utf-8")
    typst_themes.sync_set_wrapper(folder, stories)
    assert '#include "057 - Bloomburrow/002_B.typ"' in wrapper.read_text(encoding="utf-8")


def test_sync_set_wrapper_creates_missing_wrapper_with_cover(tmp_path):
    stories, folder = _set(tmp_path, ["001_A.typ", "002_B.typ"])
    (folder / "001_A").mkdir()
    (folder / "001_A" / "01.jpg").write_bytes(b"jpg")
    wrapper = typst_themes.sync_set_wrapper(folder, stories)
    assert wrapper == stories / "057_Bloomburrow.typ"
    lines = wrapper.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '#import "@local/mtgset:0.1.0": conf'
    assert lines[1] == '#show: doc => conf("Bloomburrow", cover: image("057 - Bloomburrow/001_A/01.jpg"), doc)'
    assert lines[3:] == ['#include "./057 - Bloomburrow/001_A.typ"', '#include "./057 - Bloomburrow/002_B.typ"']
