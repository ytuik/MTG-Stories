import json

import pytest
from bs4 import BeautifulSoup

import scraper


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(scraper, "REQUEST_DELAY_SECONDS", 0)


def test_story_filename_follows_archive_pattern():
    assert scraper.story_filename("001", "Episode 1: Tam, Alive") == "001_Episode 1- Tam, Alive"
    assert scraper.story_filename("002", "Who Is Jace?") == "002_Who Is Jace"
    assert scraper.story_filename("003", 'Barrin"s Tall Tale') == "003_Barrins Tall Tale"
    assert scraper.story_filename("004", "Liliana's Origin: The Fourth Pact") == "004_Liliana's Origin- The Fourth Pact"


def test_sanitize_filename_removes_windows_invalid_chars():
    assert scraper.sanitize_filename(r'a<b>c/d\e|f*g?h') == "abcdefgh"
    assert scraper.sanitize_filename("064 - Reality Fracture") == "064 - Reality Fracture"


def test_typst_string_escapes_backslash_and_quote():
    assert scraper.typst_string(r'He said "hi" \ bye') == r'He said \"hi\" \\ bye'


def _convert(html):
    return scraper.convert_bs4_to_typst(BeautifulSoup(html, "html.parser").find("p"))


def test_paragraph_escapes_markup_characters():
    out = _convert("<p>Use #hash and *star* at me@x.com costs $5 [a] ~ _u_ `c` &lt;t&gt;</p>")
    for ch in ["#", "*", "@", "$", "[", "]", "~", "_", "`", "<"]:
        assert "\\" + ch in out
    assert "#hash" not in out.replace(r"\#hash", "")


def test_emphasis_from_em_is_preserved_but_inner_text_escaped():
    out = _convert("<p>Hello <em>big #1</em> and <strong>bold</strong>.</p>")
    assert out == r"Hello _big \#1_ and *bold*."


def test_parse_article_html_minimal():
    html = """
    <html><head><meta property="og:title" content="Series | Episode 1: Start"></head>
    <body><article><p>First #paragraph.</p><h2>Part</h2><hr><p>Second.</p></article></body></html>
    """
    parsed = scraper.parse_article_html(html)
    assert parsed["metadata"]["clean_title"] == "Episode 1: Start"
    types = [e["type"] for e in parsed["elements"]]
    assert types == ["paragraph", "heading_1", "divider", "paragraph"]
    assert parsed["elements"][0]["text"] == r"First \#paragraph."


ITEM = {
    "id": "x-1",
    "type": "story",
    "clean_title": "Episode 1: Start",
    "set_name": "Test Set",
    "set_folder": "001 - Test Set",
    "story_number": "001",
    "author": 'A "Quoted" Author',
    "date": "2026-01-02",
    "url": "https://example.invalid/a",
}
HTML = "<html><body><article><p>Body text.</p></article></body></html>"


def test_scrape_writes_file_with_archive_name(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "STORIES_DIR", tmp_path / "stories")
    monkeypatch.setattr(scraper, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(scraper, "fetch_html", lambda url: HTML)
    item = {k: v for k, v in ITEM.items() if k != "clean_title"}
    item["clean_title"] = "Episode 1: Start"
    result = scraper.scrape_single_item(item)
    assert result["status"] == "scraped"
    target = tmp_path / "stories" / "001 - Test Set" / "001_Episode 1- Start.typ"
    content = target.read_text(encoding="utf-8")
    assert r'author: "A \"Quoted\" Author"' in content
    assert "Body text." in content


def test_existing_file_is_skipped_unless_force(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "STORIES_DIR", tmp_path / "stories")
    monkeypatch.setattr(scraper, "ROOT_DIR", tmp_path)
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return HTML

    monkeypatch.setattr(scraper, "fetch_html", fake_fetch)
    target = tmp_path / "stories" / "001 - Test Set" / "001_Episode 1- Start.typ"
    target.parent.mkdir(parents=True)
    target.write_text("original", encoding="utf-8")

    result = scraper.scrape_single_item(dict(ITEM))
    assert result["status"] == "skipped"
    assert calls == []
    assert target.read_text(encoding="utf-8") == "original"

    result = scraper.scrape_single_item(dict(ITEM), force=True)
    assert result["status"] == "scraped"
    assert "Body text." in target.read_text(encoding="utf-8")


def test_empty_body_fails_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "STORIES_DIR", tmp_path / "stories")
    monkeypatch.setattr(scraper, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(scraper, "fetch_html", lambda url: "<html><body><article></article></body></html>")
    result = scraper.scrape_single_item(dict(ITEM, clean_title="Episode 1: Start"), force=True)
    assert result["status"] == "failed"
    assert "corpo do artigo vazio" in result["error"].lower()
    assert not (tmp_path / "stories").exists()


def test_missing_title_fails_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "STORIES_DIR", tmp_path / "stories")
    monkeypatch.setattr(scraper, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(scraper, "fetch_html", lambda url: HTML)
    result = scraper.scrape_single_item(dict(ITEM, clean_title=None))
    assert result["status"] == "failed"
    assert "título não encontrado" in result["error"].lower()
    assert not (tmp_path / "stories").exists()


def test_skipped_result_keeps_scraped_status_in_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "MANIFEST_FILE", tmp_path / "manifest.json")
    manifest = {"scraped_items": {"x-1": {"id": "x-1", "status": "scraped", "title": "T"}}}
    scraper.update_manifest(manifest, {"id": "x-1", "status": "skipped", "file_name": "a.typ"})
    assert manifest["scraped_items"]["x-1"] == {"id": "x-1", "status": "scraped", "title": "T"}
    assert not (tmp_path / "manifest.json").exists()

    scraper.update_manifest(manifest, {"id": "x-2", "status": "skipped", "file_name": "b.typ"})
    assert manifest["scraped_items"]["x-2"]["status"] == "skipped"


def test_newlines_in_text_become_spaces():
    html = "<p>line one" + chr(10) + "line two" + chr(13) + chr(10) + "line three</p>"
    assert _convert(html) == "line one line two line three"


def test_comment_openers_are_escaped():
    assert _convert("<p>a /* b */ c // d</p>") == r"a /\* b \*/ c \// d"
    assert scraper.escape_typst_text("a//b") == r"a\//b"
    assert scraper.escape_typst_text("a/*b") == r"a/\*b"  # '*' escapado já neutraliza '/*'
    assert scraper.escape_typst_text("a/b") == "a/b"


def test_paragraph_start_markers_are_escaped():
    assert _convert("<p>= not a heading</p>") == r"\= not a heading"
    assert _convert("<p>- not a list</p>") == r"\- not a list"
    assert _convert("<p>+ not a list</p>") == r"\+ not a list"
    assert _convert("<p>/ term: x</p>") == r"\/ term: x"
    assert _convert("<p>1. not numbered</p>") == r"1\. not numbered"
    assert _convert("<p>-5 degrees, 2.5 apples</p>") == "-5 degrees, 2.5 apples"



# ---------------------------------------------------------------- rebuild

@pytest.fixture
def rebuild_env(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(scraper, "STORIES_DIR", tmp_path / "stories")
    monkeypatch.setattr(scraper, "MANIFEST_FILE", tmp_path / "manifest.json")
    calls = {"pdf": [], "epub": [], "codes": {"pdf": 0, "epub": 0}}
    monkeypatch.setattr(scraper, "_pdf_main", lambda argv: calls["pdf"].append(argv) or calls["codes"]["pdf"])
    monkeypatch.setattr(scraper, "_epub_main", lambda argv: calls["epub"].append(argv) or calls["codes"]["epub"])
    return calls


def _make_typ(tmp_path, folder, name):
    p = tmp_path / "stories" / folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return p


def _fake_scrape(tmp_path, monkeypatch, statuses):
    """statuses: {item_id: (pasta, arquivo, status)}"""
    monkeypatch.setattr(scraper, "CATALOG_MISSING", [{"id": i, "type": "story"} for i in statuses])

    def fake(item, force=False):
        folder, name, st = statuses[item["id"]]
        typ = _make_typ(tmp_path, folder, name)
        return {"id": item["id"], "status": st, "output_file": typ.relative_to(tmp_path).as_posix()}

    monkeypatch.setattr(scraper, "scrape_single_item", fake)


def test_rebuild_runs_only_for_sets_with_new_stories(tmp_path, monkeypatch, rebuild_env):
    (tmp_path / "stories").mkdir()
    (tmp_path / "stories" / "064_Reality Fracture.typ").write_text("book", encoding="utf-8")
    _fake_scrape(tmp_path, monkeypatch, {
        "new": ("064 - Reality Fracture", "011_New.typ", "scraped"),
        "old": ("058 - Duskmourn", "012_Old.typ", "skipped"),
    })
    scraper.main(["--rebuild"])
    new_typ = str(tmp_path / "stories" / "064 - Reality Fracture" / "011_New.typ")
    assert rebuild_env["pdf"] == [["--file", new_typ], ["--set-books", "--set", "064_"]]
    assert rebuild_env["epub"] == [["--set", "064 - Reality Fracture", "--combine"]]


def test_no_rebuild_without_flag_or_new_stories(tmp_path, monkeypatch, rebuild_env):
    _fake_scrape(tmp_path, monkeypatch, {"new": ("064 - RF", "011_New.typ", "scraped")})
    scraper.main([])
    assert rebuild_env["pdf"] == [] and rebuild_env["epub"] == []
    _fake_scrape(tmp_path, monkeypatch, {"old": ("064 - RF", "012_Old.typ", "skipped")})
    scraper.main(["--rebuild"])
    assert rebuild_env["pdf"] == [] and rebuild_env["epub"] == []


def test_rebuild_failure_sets_exit_code_but_keeps_scrape(tmp_path, monkeypatch, rebuild_env, capsys):
    rebuild_env["codes"]["epub"] = 1
    _fake_scrape(tmp_path, monkeypatch, {"new": ("064 - RF", "011_New.typ", "scraped")})
    with pytest.raises(SystemExit) as exc:
        scraper.main(["--rebuild"])
    assert exc.value.code == 1
    assert "[Rebuild][Falhas]" in capsys.readouterr().out
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scraped_items"]["new"]["status"] == "scraped"


def _fake_status(monkeypatch, sets):
    from mtg_epub import status
    monkeypatch.setattr(status, "collect", lambda: {"sets": sets, "failed": [], "missing_timeline": {}})
    monkeypatch.setattr(scraper, "scrape_single_item", lambda *a, **k: pytest.fail("não deve raspar"))


def test_rebuild_only_without_pending_calls_nothing(monkeypatch, rebuild_env):
    _fake_status(monkeypatch, {"001 - A": {
        "kind": "set", "total": 1, "no_pdf": [], "stale_pdf": [], "no_epub": [], "stale_epub": []}})
    with pytest.raises(SystemExit) as exc:
        scraper.main(["--rebuild-only"])
    assert exc.value.code == 0
    assert rebuild_env["pdf"] == [] and rebuild_env["epub"] == []


def test_rebuild_only_rebuilds_pending_sets_only(tmp_path, monkeypatch, rebuild_env):
    _fake_status(monkeypatch, {
        "001 - A": {"kind": "set", "total": 2, "no_pdf": [], "stale_pdf": ["stories/001 - A/001_X.typ"],
                    "no_epub": [], "stale_epub": []},
        "002 - B": {"kind": "set", "total": 1, "no_pdf": [], "stale_pdf": [], "no_epub": [], "stale_epub": []},
    })
    with pytest.raises(SystemExit) as exc:
        scraper.main(["--rebuild-only"])
    assert exc.value.code == 0
    assert rebuild_env["pdf"] == [["--file", str(tmp_path / "stories/001 - A/001_X.typ")]]
    assert rebuild_env["epub"] == [["--set", "001 - A", "--combine"]]


def test_rebuild_adds_new_story_to_set_wrapper_before_building(tmp_path, monkeypatch, rebuild_env):
    stories = tmp_path / "stories"
    old = _make_typ(tmp_path, "064 - Reality Fracture", "001_Old.typ")
    wrapper = stories / "064_Reality Fracture.typ"
    wrapper.write_text(
        '#import "@local/mtgset:0.1.0": conf\n#show: doc => conf("Reality Fracture", doc)\n\n'
        f'#include "./064 - Reality Fracture/{old.name}"\n', encoding="utf-8")
    _fake_scrape(tmp_path, monkeypatch, {"new": ("064 - Reality Fracture", "011_New.typ", "scraped")})
    seen = []
    monkeypatch.setattr(scraper, "_pdf_main", lambda argv: seen.append(wrapper.read_text(encoding="utf-8")) or 0)
    scraper.main(["--rebuild"])
    assert '#include "./064 - Reality Fracture/011_New.typ"' in seen[0]
    assert seen[0].index("001_Old") < seen[0].index("011_New")
