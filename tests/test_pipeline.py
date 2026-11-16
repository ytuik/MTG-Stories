from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from pathlib import Path

from mtg_epub import REPO_ROOT
from mtg_epub.pipeline import EpubPipeline, typst_root, validate_epub


def test_validate_epub_accepts_required_structure(tmp_path):
    epub = tmp_path / "valid.epub"
    with ZipFile(epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", "<container/>", compress_type=ZIP_DEFLATED)
        archive.writestr("EPUB/content.opf", "<package/>", compress_type=ZIP_DEFLATED)
        archive.writestr("EPUB/nav.xhtml", "<html/>", compress_type=ZIP_DEFLATED)

    assert validate_epub(epub) == []


def test_validate_epub_reports_missing_structure(tmp_path):
    epub = tmp_path / "invalid.epub"
    with ZipFile(epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_DEFLATED)

    problems = validate_epub(epub)

    assert "mimetype precisa estar sem compressão" in problems
    assert "container.xml ausente" in problems
    assert "package OPF ausente" in problems


def test_typst_root_is_repo_root_for_files_inside_repo():
    assert typst_root([REPO_ROOT / "stories" / "x" / "001_a.typ"]) == REPO_ROOT


def test_typst_root_covers_files_outside_repo(tmp_path):
    root = typst_root([tmp_path / "a.typ"])
    assert root in Path(tmp_path).parents or root == tmp_path
    assert (tmp_path / "a.typ").resolve().is_relative_to(root.resolve())
    assert REPO_ROOT.resolve().is_relative_to(root.resolve())


def test_typst_root_falls_back_to_parent_without_common_ancestor(monkeypatch, tmp_path):
    def boom(paths):
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr("mtg_epub.pipeline.os.path.commonpath", boom)
    assert typst_root([tmp_path / "a.typ"]) == tmp_path


def test_image_signature_tracks_changes_and_missing_images(tmp_path):
    typ = tmp_path / "001_a.typ"
    typ.write_text('#image("pic.png")' + chr(10) + '#image("gone.png")', encoding="utf-8")
    (tmp_path / "pic.png").write_bytes(b"one")
    first = EpubPipeline._images_signature([typ])
    assert any(entry.endswith("gone.png:missing") for entry in first)
    (tmp_path / "pic.png").write_bytes(b"longer content")
    assert EpubPipeline._images_signature([typ]) != first
