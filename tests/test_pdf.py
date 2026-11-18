import os
import json
from pathlib import Path

import pytest
import typst

from mtg_epub import pdf


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "typst_packages" / "local").mkdir(parents=True)
    (root / "typst_packages" / "local" / "pkg.typ").write_text("pkg")
    (root / "fonts").mkdir()

    def typ(rel, text="body"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    typ("stories/001 - Magic 2013/001_A.typ", '#include "inc.typ"\n#image("img/a.jpg")')
    typ("stories/001 - Magic 2013/inc.typ", "included")
    typ("stories/001 - Magic 2013/001_A.tmp.typ")
    typ("stories/057 - Bloomburrow/001_B.typ")
    typ("stories/001_Magic 2013.typ")
    typ("stories/057_Bloomburrow.typ")
    typ("stories/chronological/01 - Era.typ")
    typ("planeswalkers_guides/001 - Guide/001 - Guide.typ")
    typ("card_lore/061 - Lore/001 - Lore.typ")
    img = root / "stories/001 - Magic 2013/img/a.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"jpg")

    monkeypatch.setattr(pdf, "REPO_ROOT", root)
    calls = []

    def fake_compile(input, output=None, **kwargs):
        calls.append({"input": input, "output": output, **kwargs})
        Path(output).write_bytes(b"%PDF-fake")

    monkeypatch.setattr(typst, "compile", fake_compile)
    monkeypatch.setattr(pdf, "_test_calls", calls, raising=False)
    return root


def names(paths):
    return sorted(p.relative_to(pdf.REPO_ROOT).as_posix() for p in paths)


def args(*argv):
    return pdf.build_parser().parse_args(list(argv))


def test_select_set_partial_case_insensitive(repo):
    assert names(pdf.resolve_targets(args("--set", "BLOOM"))) == ["stories/057 - Bloomburrow/001_B.typ"]


def test_select_all_excludes_chronological_and_tmp(repo):
    got = names(pdf.resolve_targets(args("--all")))
    assert got == ["stories/001 - Magic 2013/001_A.typ", "stories/001 - Magic 2013/inc.typ",
                   "stories/057 - Bloomburrow/001_B.typ"]


def test_select_set_books_and_filter(repo):
    assert names(pdf.resolve_targets(args("--set-books"))) == ["stories/001_Magic 2013.typ", "stories/057_Bloomburrow.typ"]
    assert names(pdf.resolve_targets(args("--set-books", "--set", "bloom"))) == ["stories/057_Bloomburrow.typ"]


def test_select_chronological_guides_card_lore(repo):
    got = names(pdf.resolve_targets(args("--chronological", "--guides", "--card-lore")))
    assert got == ["card_lore/061 - Lore/001 - Lore.typ", "planeswalkers_guides/001 - Guide/001 - Guide.typ",
                   "stories/chronological/01 - Era.typ"]


def test_missing_filters_existing_pdfs(repo):
    assert pdf.main(["--file", str(repo / "stories/057 - Bloomburrow/001_B.typ")]) == 0
    pdf._test_calls.clear()
    assert pdf.main(["--missing"]) == 0
    built = {Path(c["input"]).name for c in pdf._test_calls}
    assert "001_B.typ" not in built
    assert {"001_A.typ", "inc.typ", "001 - Guide.typ", "001 - Lore.typ"} <= built
    assert "01 - Era.typ" not in built  # sem outro alvo, missing = all+guides+card-lore


def test_output_names(repo):
    src = repo / "stories/057 - Bloomburrow/001_B.typ"
    assert pdf.output_path(src).name == "001_B.pdf"
    assert pdf.output_path(src, with_images=False).name == "001_B - text only.pdf"
    out = repo.parent / "out"
    assert pdf.output_path(src, output_dir=out) == out / "stories/057 - Bloomburrow/001_B.pdf"


def test_no_target_and_invalid_args_exit_2(repo):
    assert pdf.main([]) == 2
    assert pdf.main(["--bogus"]) == 2
    assert pdf.main(["--file", str(repo / "nao-existe.typ")]) == 2


def test_fingerprint_changes(repo):
    src = repo / "stories/001 - Magic 2013/001_A.typ"

    def fp(**kw):
        opts = {"with_images": True, "pdfa": False, "static": "s"}
        opts.update(kw)
        return pdf.fingerprint(src, **opts)

    base = fp()
    assert fp() == base
    assert fp(with_images=False) != base
    assert fp(pdfa=True) != base
    assert fp(static="t") != base
    inc = src.with_name("inc.typ")
    inc.write_text("changed")
    changed_inc = fp()
    assert changed_inc != base
    img = src.parent / "img/a.jpg"
    img.write_bytes(b"jpg-bigger")
    assert fp() != changed_inc
    img.unlink()
    assert fp() != changed_inc  # "missing" também entra


def test_static_signature_tracks_packages(repo):
    before = pdf.static_signature()
    (repo / "typst_packages/local/pkg.typ").write_text("pkg changed")
    assert pdf.static_signature() != before


def test_second_run_skips_and_force_rebuilds(repo):
    src = str(repo / "stories/057 - Bloomburrow/001_B.typ")
    assert pdf.main(["--file", src]) == 0
    assert len(pdf._test_calls) == 1
    assert json.loads((repo / "pdf-report.json").read_text(encoding="utf-8"))["summary"]["generated"] == 1
    assert pdf.main(["--file", src]) == 0
    assert len(pdf._test_calls) == 1
    assert json.loads((repo / "pdf-report.json").read_text(encoding="utf-8"))["summary"]["skipped"] == 1
    assert pdf.main(["--file", src, "--force"]) == 0
    assert len(pdf._test_calls) == 2
    (repo / "stories/057 - Bloomburrow/001_B.typ").write_text("new")
    assert pdf.main(["--file", src]) == 0
    assert len(pdf._test_calls) == 3


def test_compile_failure_reports_and_cleans_tmp(repo, monkeypatch):
    def boom(input, output=None, **kw):
        Path(output).write_bytes(b"partial")
        raise RuntimeError("imagem inválida")

    monkeypatch.setattr(typst, "compile", boom)
    src = repo / "stories/057 - Bloomburrow/001_B.typ"
    assert pdf.main(["--file", str(src), "--pdfa", "--jobs", "2"]) == 1
    assert not list(repo.rglob("*.tmp.pdf"))
    assert not src.with_suffix(".pdf").exists()
    item = json.loads((repo / "pdf-report.json").read_text(encoding="utf-8"))["items"][0]
    assert item["status"] == "failed" and "imagem inválida" in item["error"]
    assert not (repo / ".pdf-cache.json").exists() or json.loads((repo / ".pdf-cache.json").read_text()) == {}


def test_pdf_standards_only_with_pdfa(repo):
    src = str(repo / "stories/057 - Bloomburrow/001_B.typ")
    pdf.main(["--file", src])
    assert "pdf_standards" not in pdf._test_calls[-1]
    assert pdf._test_calls[-1]["sys_inputs"] == {"with_images": "true"}
    pdf.main(["--file", src, "--pdfa"])
    assert pdf._test_calls[-1]["pdf_standards"] == ["a-2b"]
    pdf.main(["--file", src, "--no-images"])
    assert pdf._test_calls[-1]["sys_inputs"] == {"with_images": "false"}
    assert pdf._test_calls[-1]["root"] == str(repo)


def test_static_signature_ignores_mtime_and_package_cache(repo):
    pkg = repo / "typst_packages/local/pkg.typ"
    before = pdf.static_signature()
    os.utime(pkg, (5_000, 5_000))  # "tocar" sem mudar o conteúdo
    assert pdf.static_signature() == before
    cache_file = repo / "typst_packages/cache/preview/x/pkg.typ"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("baixado")
    assert pdf.static_signature() == before  # typst_packages/cache é ignorado


def test_static_signature_fonts_use_name_size_and_head_hash(repo):
    font = repo / "fonts/a.ttf"
    font.write_bytes(b"x" * 70_000)
    before = pdf.static_signature()
    os.utime(font, (5_000, 5_000))
    assert pdf.static_signature() == before
    font.write_bytes(b"x" * 70_001)  # tamanho muda
    assert pdf.static_signature() != before


def test_cache_records_options_and_reads_old_entries(repo):
    src = repo / "stories/057 - Bloomburrow/001_B.typ"
    out = pdf.output_path(src)
    cache = pdf.Cache(repo / pdf.CACHE_NAME)
    cache.update(out, "abc", {"with_images": True, "pdfa": True})
    assert cache.entry(out) == ("abc", {"with_images": True, "pdfa": True})
    cache.update(out, "old")  # formato antigo: só a string
    assert cache.entry(out) == ("old", {})
    out.write_bytes(b"%PDF")
    assert cache.is_fresh(out, "old")
