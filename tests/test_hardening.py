"""Testes de robustez do pipeline EPUB: cache, validação, epubcheck, regex Typst e metadados."""
import json
from pathlib import Path

import pytest
import typst

from mtg_epub import cli, metadata as metadata_module, pipeline as pipeline_module, typst_html
from mtg_epub.metadata import extract_metadata
from mtg_epub.models import StoryMetadata
from mtg_epub.pipeline import EpubPipeline, collect_typst_files


def _story(tmp_path: Path, title: str = "Story") -> tuple[Path, StoryMetadata]:
    typ = tmp_path / "001_story.typ"
    typ.write_text("Hello world", encoding="utf-8")
    meta = StoryMetadata(
        title=title, set_name="Unknown Set", author="Someone", date="2024-01-01",
        series="Series", series_index=1, source_file=typ,
    )
    return typ, meta


@pytest.fixture
def fake_build(monkeypatch):
    """Substitui build_epub (que exige Typst) por um que só grava um arquivo."""
    calls = []

    def _build(metadata, chapters, root, output_path, css_content, fonts=None, **_):
        calls.append(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"epub")
        return []

    monkeypatch.setattr(pipeline_module, "build_epub", _build)
    return calls


# --- cache / fingerprint ---------------------------------------------------

def test_cache_skips_then_regenerates_when_inputs_change(tmp_path, monkeypatch, fake_build):
    typ, meta = _story(tmp_path)
    output = tmp_path / "out" / "a.epub"
    pipe = EpubPipeline(tmp_path / "out", fonts_dir=None, validate=False)

    assert pipe.convert([typ], output, meta, chapter_titles=["T"]).status == "generated"
    assert pipe.convert([typ], output, meta, chapter_titles=["T"]).status == "skipped"

    # metadado
    changed = StoryMetadata(**{**meta.__dict__, "title": "Other title"})
    assert pipe.convert([typ], output, changed, chapter_titles=["T"]).status == "generated"
    assert pipe.convert([typ], output, changed, chapter_titles=["T"]).status == "skipped"

    # CSS
    monkeypatch.setattr(pipeline_module, "EPUB_CSS", pipeline_module.EPUB_CSS + "\nbody{color:red}")
    assert pipe.convert([typ], output, changed, chapter_titles=["T"]).status == "generated"
    assert pipe.convert([typ], output, changed, chapter_titles=["T"]).status == "skipped"

    # versão do pipeline
    monkeypatch.setattr(pipeline_module, "PIPELINE_VERSION", "999.0.0")
    assert pipe.convert([typ], output, changed, chapter_titles=["T"]).status == "generated"

    # persistência atômica: sem .tmp sobrando e JSON válido
    cache_file = tmp_path / "out" / ".epub-cache.json"
    assert json.loads(cache_file.read_text(encoding="utf-8"))
    assert not list((tmp_path / "out").glob("*.tmp"))


def test_theme_failure_becomes_error_result(tmp_path, monkeypatch, fake_build):
    typ, meta = _story(tmp_path)

    def boom(_name):
        raise RuntimeError("tema quebrado")

    monkeypatch.setattr(pipeline_module, "theme_for_set", boom)
    result = EpubPipeline(tmp_path / "out", fonts_dir=None).convert([typ], tmp_path / "out" / "a.epub", meta)

    assert result.success is False
    assert result.status == "failed"
    assert "tema quebrado" in result.error
    assert fake_build == []


# --- validação / epubcheck -------------------------------------------------

def test_no_validate_does_not_call_validate_or_epubcheck(tmp_path, monkeypatch, fake_build):
    typ, _ = _story(tmp_path)
    called = []
    monkeypatch.setattr(pipeline_module, "validate_epub", lambda path: called.append("validate") or [])
    monkeypatch.setattr(pipeline_module, "run_epubcheck", lambda *a, **k: called.append("epubcheck") or [])

    out = tmp_path / "out"
    code = cli.main(["--file", str(typ), "--output-dir", str(out), "--no-validate",
                     "--epubcheck", str(tmp_path / "missing.jar"), "--jobs", "1"])

    assert code == 0
    assert called == []
    assert fake_build  # converteu


def test_validation_runs_once_in_pipeline(tmp_path, monkeypatch, fake_build):
    typ, _ = _story(tmp_path)
    called = []
    monkeypatch.setattr(pipeline_module, "validate_epub", lambda path: called.append(path) or [])
    monkeypatch.setattr(cli, "validate_epub", lambda path: called.append(path) or [])

    cli.main(["--file", str(typ), "--output-dir", str(tmp_path / "out"), "--jobs", "1"])

    assert len(called) == 1


def test_missing_epubcheck_aborts_before_converting(tmp_path, fake_build, capsys):
    typ, _ = _story(tmp_path)

    code = cli.main(["--file", str(typ), "--output-dir", str(tmp_path / "out"),
                     "--epubcheck", str(tmp_path / "nope.jar")])

    assert code == 2
    assert fake_build == []
    assert "EpubCheck não encontrado" in capsys.readouterr().err


def test_missing_java_aborts_before_converting(tmp_path, monkeypatch, fake_build, capsys):
    typ, _ = _story(tmp_path)
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"")
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    code = cli.main(["--file", str(typ), "--output-dir", str(tmp_path / "out"), "--epubcheck", str(jar)])

    assert code == 2
    assert fake_build == []
    assert "Java" in capsys.readouterr().err


def test_defaults_are_relative_to_repo_root():
    args = cli.build_parser().parse_args(["--file", "x.typ", "--epubcheck"])
    assert args.epubcheck == cli.REPO_ROOT / "tools" / "epubcheck-5.4.0" / "epubcheck.jar"
    assert args.stories_dir == cli.REPO_ROOT / "stories"
    assert args.fonts_dir == cli.REPO_ROOT / "fonts"


# --- Typst: regex com parênteses aninhados e temporários ------------------

def test_strip_broken_images_handles_nested_parentheses():
    src = (
        'Before\n#figure(image("a(b).png", width: calc.min(1, 2)), caption: [Cap (x) [y]])\nMiddle\n'
        '#image("c(d).png", width: calc.min(1, 2))\nAfter'
    )
    out = typst_html._strip_broken_images(src)

    assert "image(" not in out
    assert "#emph[Cap (x) [y]]" in out
    assert "Before" in out and "Middle" in out and out.rstrip().endswith("After")
    assert ".png" not in out and "calc.min" not in out


def test_strip_broken_images_keeps_figures_without_image():
    src = '#figure(table([a (b)]), caption: [Tabela])\ntexto'
    assert typst_html._strip_broken_images(src) == src


def test_compile_failure_cleans_temp_file(tmp_path, monkeypatch):
    typ = tmp_path / "001_a.typ"
    typ.write_text("hi", encoding="utf-8")

    def fail(*args, **kwargs):
        raise ValueError("falha")

    monkeypatch.setattr(typst_html.typst, "compile", fail)
    with pytest.raises(ValueError):
        typst_html.compile_chapter_html(typ, tmp_path)

    assert list(tmp_path.glob("*.tmp.typ")) == []


def test_image_fallback_records_original_error(tmp_path, monkeypatch):
    typ = tmp_path / "001_a.typ"
    typ.write_text('#image("x.png")\nTexto', encoding="utf-8")
    attempts = []

    def fake_compile(path, **kwargs):
        attempts.append(path)
        if len(attempts) == 1:
            raise typst.TypstError("cannot find file x.png")
        return "<html><body><p>Texto</p></body></html>"

    monkeypatch.setattr(typst_html.typst, "compile", fake_compile)
    chapter = typst_html.compile_chapter_html(typ, tmp_path)

    assert len(attempts) == 2
    assert len(chapter.warnings) == 1
    assert "cannot find file x.png" in chapter.warnings[0]
    assert list(tmp_path.glob("*.tmp.typ")) == []


def test_collect_typst_files_ignores_temp_files(tmp_path):
    (tmp_path / "001_a.typ").write_text("a", encoding="utf-8")
    (tmp_path / "001_a.typ.12345678.tmp.typ").write_text("a", encoding="utf-8")
    assert [p.name for p in collect_typst_files(tmp_path)] == ["001_a.typ"]


# --- metadata --------------------------------------------------------------

def test_metadata_unescapes_quotes_in_strings(tmp_path):
    typ = tmp_path / "001_a.typ"
    typ.write_text(
        '#show: doc => conf(\n  "Say \\"Hi\\" (now)",\n  set_name: "Set \\"X\\"",\n  author: "A \\\\ B",\n  doc\n)\n',
        encoding="utf-8",
    )
    meta = extract_metadata(typ)

    assert meta.title == 'Say "Hi" (now)'
    assert meta.set_name == 'Set "X"'
    assert meta.author == "A \\ B"


def test_invalid_series_index_falls_back_with_warning(tmp_path):
    typ = tmp_path / "001_a.typ"
    typ.write_text("texto", encoding="utf-8")
    with pytest.warns(RuntimeWarning, match="series_index"):
        meta = extract_metadata(typ, {"series_index": "abc"})
    assert meta.series_index == 1


def test_corrupt_set_names_warns_and_is_not_overwritten(tmp_path, monkeypatch):
    bad = tmp_path / "set-names.json"
    bad.write_text("{corrompido", encoding="utf-8")
    monkeypatch.setattr(metadata_module, "SET_NAMES_FILE", bad)
    monkeypatch.setattr(metadata_module, "_set_names_cache", None)

    with pytest.warns(RuntimeWarning, match="corrompido"):
        names = metadata_module._load_set_names()

    assert isinstance(names, dict)
    assert bad.read_text(encoding="utf-8") == "{corrompido"


def test_missing_fonts_dir_warns(tmp_path):
    from mtg_epub.themes import THEMES, prepare_theme_fonts
    with pytest.warns(RuntimeWarning, match="fontes"):
        assert prepare_theme_fonts(THEMES["gothic"], tmp_path / "nao-existe", tmp_path) == []
