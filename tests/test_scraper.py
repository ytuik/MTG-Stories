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
