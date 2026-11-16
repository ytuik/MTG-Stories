import json
import os

import pytest

from mtg_epub import pdf, status


class FakeEpubs:
    """Substitui o cálculo de fingerprint de EPUB (depende de temas, fontes etc.)."""
    states: dict = {}

    def __init__(self, epubs_dir, manifest_path):
        pass

    def classify(self, source):
        return self.states.get(source.name, status.OK)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "typst_packages").mkdir(parents=True)
    (root / "fonts").mkdir()
    (root / "data").mkdir()
    monkeypatch.setattr(pdf, "REPO_ROOT", root)
    monkeypatch.setattr(status, "EpubChecker", FakeEpubs)
    FakeEpubs.states = {}
    return root


def typ(root, rel, text="body"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def write_pdf(source, *, cache=True):
    out = pdf.output_path(source)
    out.write_bytes(b"%PDF")
    if cache:
        c = pdf.Cache(pdf.REPO_ROOT / pdf.CACHE_NAME)
        c.update(out, pdf.fingerprint(source, with_images=True, pdfa=False, static=pdf.static_signature()))
    return out


def classify(source):
    return status.classify_pdf(source, pdf.Cache(pdf.REPO_ROOT / pdf.CACHE_NAME), pdf.static_signature())


def test_pdf_missing_ok_stale_by_cache(repo):
    src = typ(repo, "stories/001 - A/001_X.typ")
    assert classify(src) == status.MISSING
    write_pdf(src)
    assert classify(src) == status.OK
    src.write_text("changed", encoding="utf-8")
    assert classify(src) == status.STALE


def test_pdf_stale_when_included_file_changes(repo):
    src = typ(repo, "stories/001 - A/001_X.typ", '#include "inc.typ"')
    inc = typ(repo, "stories/001 - A/inc.typ", "one")
    write_pdf(src)
    inc.write_text("two", encoding="utf-8")
    assert classify(src) == status.STALE


def test_pdf_without_cache_entry_falls_back_to_mtime(repo):
    src = typ(repo, "stories/001 - A/001_X.typ")
    out = write_pdf(src, cache=False)
    os.utime(src, (1_000, 1_000))
    os.utime(out, (2_000, 2_000))
    assert classify(src) == status.OK
    os.utime(src, (3_000, 3_000))
    assert classify(src) == status.STALE


def test_failed_manifest_items(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"scraped_items": {
        "a": {"id": "a", "status": "scraped"},
        "b": {"id": "b", "status": "failed", "error": "boom", "title": "B"},
        "c": {"id": "c", "status": "skipped"},
    }}), encoding="utf-8")
    assert [f["id"] for f in status.failed_manifest_items(path)] == ["b"]
    assert status.failed_manifest_items(tmp_path / "nope.json") == []
    path.write_text("{not json", encoding="utf-8")
    assert status.failed_manifest_items(path) == []


def test_missing_timeline_grouped_by_era_and_set(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"stories": [], "missing_from_archive": [
        {"title": "T1", "url": "u1", "era": "E1", "date": "d", "set_name": "S"},
        {"title": "T2", "url": "u2", "era": "E1", "date": "d", "set_name": None},
        {"title": "T3", "url": "u3", "era": "E2", "date": "d", "set_name": "S"},
    ]}), encoding="utf-8")
    grouped = status.missing_timeline(path)
    assert list(grouped) == ["E1", "E2"]
    assert list(grouped["E1"]) == ["S", "Sem set"]
    assert grouped["E2"]["S"][0]["title"] == "T3"


def test_collect_reports_per_set_and_strict_exit(repo, capsys):
    a = typ(repo, "stories/001 - A/001_A.typ")
    b = typ(repo, "stories/001 - A/002_B.typ")
    typ(repo, "stories/001 - A/003_C.typ")
    typ(repo, "stories/chronological/01 - Era.typ")
    typ(repo, "stories/001 - A/003_C.tmp.typ")
    typ(repo, "planeswalkers_guides/001 - G/001 - G.typ")
    write_pdf(a)
    write_pdf(b)
    b.write_text("changed", encoding="utf-8")
    FakeEpubs.states = {"001_A.typ": status.MISSING, "002_B.typ": status.STALE}
    (repo / "scraped_manifest.json").write_text(
        json.dumps({"scraped_items": {"x": {"status": "failed", "error": "e"}}}), encoding="utf-8")

    report = status.collect()
    entry = report["sets"]["001 - A"]
    assert entry["total"] == 3
    assert entry["no_pdf"] == ["stories/001 - A/003_C.typ"]
    assert entry["stale_pdf"] == ["stories/001 - A/002_B.typ"]
    assert entry["no_epub"] == ["stories/001 - A/001_A.typ"]
    assert entry["stale_epub"] == ["stories/001 - A/002_B.typ"]
    guide = report["sets"]["[guide] 001 - G"]
    assert guide["no_pdf"] == ["planeswalkers_guides/001 - G/001 - G.typ"] and guide["no_epub"] == []
    assert [f["id"] for f in report["failed"]] == ["x"]
    assert report["sets"]["[cronológico] stories/chronological"]["no_pdf"] == ["stories/chronological/01 - Era.typ"]

    assert status.main([]) == 0
    assert status.main(["--strict"]) == 1
    assert "001 - A" in capsys.readouterr().out
    pending = status.sets_needing_rebuild(report)
    assert pending["001 - A"]["pdf"] and pending["[guide] 001 - G"]["kind"] == "guide"


def test_strict_passes_when_clean(repo):
    a = typ(repo, "stories/001 - A/001_A.typ")
    write_pdf(a)
    assert status.main(["--strict"]) == 0


def test_json_output(repo):
    a = typ(repo, "stories/001 - A/001_A.typ")
    write_pdf(a)
    assert status.main(["--json"]) == 0
    data = json.loads((repo / "status.json").read_text(encoding="utf-8"))
    assert data["sets"]["001 - A"]["total"] == 1


MANUAL = ("# Título\n\nIntro manual.\n\n---\n\n## 2. Obras pagas\n\n| a | b |\n| - | - |\n"
          "| livro | pago |\n\n## 3. Como rodar\n\ntexto manual final\n")


def md_repo(repo, newline="\n"):
    (repo / "data" / "chronology.json").write_text(json.dumps({"missing_from_archive": [
        {"title": "T1", "url": "u1", "era": "E1", "date": "d", "set_name": "S"}]}), encoding="utf-8")
    md = repo / "MISSING_STORIES.md"
    md.write_bytes(MANUAL.replace("\n", newline).encode("utf-8"))
    return md


def test_write_md_preserves_manual_text_and_is_idempotent(repo):
    md = md_repo(repo)
    assert status.main(["--write-md"]) == 0
    first = md.read_bytes()
    text = first.decode("utf-8")
    assert status.MD_START in text and status.MD_END in text and "[T1](u1)" in text
    for fragment in ("| livro | pago |", "texto manual final", "## 2. Obras pagas", "Intro manual."):
        assert fragment in text
    assert text.index("Intro manual.") < text.index(status.MD_START) < text.index("## 2. Obras pagas")

    assert status.main(["--write-md"]) == 0
    assert md.read_bytes() == first


def test_write_md_replaces_only_marked_block_and_keeps_crlf(repo):
    md = md_repo(repo, newline="\r\n")
    status.main(["--write-md"])
    first = md.read_bytes()
    assert b"\r\n" in first and b"\n" not in first.replace(b"\r\n", b"")
    (repo / "data" / "chronology.json").write_text(json.dumps({"missing_from_archive": []}), encoding="utf-8")
    status.main(["--write-md"])
    second = md.read_bytes().decode("utf-8")
    assert "[T1](u1)" not in second and "Total: **0**" in second
    assert second.count(status.MD_START) == 1
    assert "texto manual final" in second and "Intro manual." in second


def test_pdfa_pdf_is_ok_and_rebuild_repeats_pdfa(repo):
    src = typ(repo, "stories/001 - A/001_X.typ")
    out = pdf.output_path(src)
    out.write_bytes(b"%PDF")
    cache = pdf.Cache(repo / pdf.CACHE_NAME)
    fp = pdf.fingerprint(src, with_images=True, pdfa=True, static=pdf.static_signature())
    cache.update(out, fp, {"with_images": True, "pdfa": True})
    assert classify(src) == status.OK
    report = status.collect()
    assert report["sets"]["001 - A"]["pdfa"] == ["stories/001 - A/001_X.typ"]
    src.write_text("changed", encoding="utf-8")
    pending = status.sets_needing_rebuild(status.collect())
    assert pending["001 - A"]["pdfa"] == ["stories/001 - A/001_X.typ"]


def test_pdf_by_mtime_is_stale_when_template_is_newer(repo):
    src = typ(repo, "stories/001 - A/001_X.typ")
    out = write_pdf(src, cache=False)
    template = repo / "typst_packages/local/mtgstory/tpl.typ"
    template.parent.mkdir(parents=True)
    template.write_text("tpl", encoding="utf-8")
    os.utime(src, (1_000, 1_000))
    os.utime(out, (2_000, 2_000))
    os.utime(template, (1_500, 1_500))
    assert classify(src) == status.OK
    os.utime(template, (3_000, 3_000))
    assert classify(src) == status.STALE


def test_collect_includes_set_books_and_chronological_volumes(repo):
    typ(repo, "stories/001 - A/001_X.typ")
    typ(repo, "stories/001_A.typ")
    typ(repo, "stories/chronological/01 - Era.typ")
    report = status.collect()
    assert report["sets"]["[livros de set] stories"]["no_pdf"] == ["stories/001_A.typ"]
    assert report["sets"]["[cronológico] stories/chronological"]["no_pdf"] == ["stories/chronological/01 - Era.typ"]
    assert report["sets"]["[livros de set] stories"]["no_epub"] == []


def test_epub_status_matches_pipeline_fingerprint(tmp_path, monkeypatch):
    """EpubPipeline.convert e EpubChecker.classify precisam concordar (OK logo após converter)."""
    from mtg_epub import pipeline as pipeline_module
    from mtg_epub.metadata import extract_metadata
    from mtg_epub.pipeline import EpubPipeline
    from mtg_epub.themes import DEFAULT_FONTS_DIR

    root = tmp_path / "repo"
    source = root / "stories" / "001 - A" / "001_X.typ"
    source.parent.mkdir(parents=True)
    source.write_text("Hello", encoding="utf-8")
    monkeypatch.setattr(pdf, "REPO_ROOT", root)

    def fake_build(*, output_path, **_):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"epub")
        return []

    monkeypatch.setattr(pipeline_module, "build_epub", fake_build)
    epubs = root / "epubs"
    pipe = EpubPipeline(epubs, fonts_dir=DEFAULT_FONTS_DIR, max_image_size=status.EPUB_MAX_IMAGE_SIZE, validate=False)
    output = status.epub_output_path(source, epubs)
    result = pipe.convert([source], output, extract_metadata(source, None))
    assert result.status == "generated", result.error

    checker = status.EpubChecker(epubs, root / "scraped_manifest.json")
    assert checker.classify(source) == status.OK
    source.write_text("Hello again", encoding="utf-8")
    assert checker.classify(source) == status.STALE
