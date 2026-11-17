import json
from pathlib import Path

import pytest

from mtg_epub import chronology, cli
from mtg_epub.chronology import (
    ArchiveStory,
    ChronologyItem,
    TimelineEntry,
    build_chronology,
    match_entries,
    parse_timeline,
    volumes,
)

WIKI = "https://magic.wizards.com/en/news/magic-story/"

TIMELINE_HTML = f"""
<div class="mw-parser-output">
<h2><span class="mw-headline">Timeline</span></h2>
<h3><span class="mw-headline">Era One (1 AR to 10 AR)</span></h3>
<p><b>1 AR</b></p>
<ul>
<li><a class="external" href="{WIKI}alpha-tale-2020-01-01">Alpha Tale</a></li>
<li><a class="external" href="{WIKI}beta-tale-2020-02-01">Beta Tale</a> (past portion)</li>
<li><a class="external" href="https://example.com/ignored">Ignored</a></li>
</ul>
<h4><span class="mw-headline">First Arc</span></h4>
<p><b>5 AR</b></p>
<ul>
<li><a class="external" href="{WIKI}gamma-tale-2020-03-01">Gamma Tale</a> †</li>
<li><b>Bloomburrow</b><ul><li><a class="external" href="{WIKI}episode-1-2024-08-01">Episode 1</a></li></ul></li>
</ul>
<h3><span class="mw-headline">Era Two</span></h3>
<p><b>9 AR</b></p>
<ul>
<li><a class="external" href="{WIKI}beta-tale-2020-02-01">Beta Tale</a></li>
<li><b>Duskmourn</b><ul><li><a class="external" href="{WIKI}episode-1-2024-09-01">Episode 1</a></li></ul></li>
</ul>
<h3><span class="mw-headline">Undated</span></h3>
<ul><li><a class="external" href="{WIKI}undated-tale-2020-04-01">Undated Tale</a></li></ul>
<h2><span class="mw-headline">Notes</span></h2>
<ul><li><a class="external" href="{WIKI}after-notes-2020-05-01">After Notes</a></li></ul>
</div>
"""


def story(title, set_name, number=1, folder=None, year=2020):
    folder = folder or f"001 - {set_name}"
    return ArchiveStory(
        path=f"stories/{folder}/{number:03d}_{title}.typ",
        title=title,
        set_name=set_name,
        set_folder=folder,
        number=number,
        year=year,
    )


def item(position, title, era, arc=None, path=None, set_name="S"):
    return ChronologyItem(
        position=position,
        path=path or f"stories/001 - S/{position:03d}_{title}.typ",
        title=title,
        set_name=set_name,
        era=era,
        arc=arc,
        date=None,
        placement="timeline",
    )


# ---------------------------------------------------------------- parse_timeline

def test_parse_timeline_extracts_era_arc_date_and_flags():
    entries = parse_timeline(TIMELINE_HTML)
    by_title = {(e.title, e.era): e for e in entries}

    assert [e.title for e in entries] == [
        "Alpha Tale", "Beta Tale", "Gamma Tale", "Episode 1", "Beta Tale", "Episode 1", "Undated Tale",
    ]  # links externos a outros domínios e depois de "Notes" ficam de fora
    assert [e.index for e in entries] == list(range(7))

    alpha = by_title[("Alpha Tale", "Era One (1 AR to 10 AR)")]
    assert (alpha.arc, alpha.date, alpha.portion, alpha.alternate, alpha.set_name) == (None, "1 AR", None, False, None)

    beta_part = entries[1]
    assert beta_part.portion == "past portion"

    gamma = entries[2]
    assert gamma.arc == "First Arc" and gamma.date == "5 AR" and gamma.alternate is True

    assert entries[3].set_name == "Bloomburrow" and entries[3].arc == "First Arc"
    # h3 novo zera o arco
    assert entries[4].era == "Era Two" and entries[4].arc is None and entries[4].date == "9 AR"
    assert entries[5].set_name == "Duskmourn"
    assert entries[6].era == "Undated"


# ---------------------------------------------------------------- casamento

def test_same_title_in_two_sets_resolved_by_context_set():
    bloom = story("Episode 1", "Bloomburrow", folder="057 - Bloomburrow")
    dusk = story("Episode 1", "Duskmourn", folder="058 - Duskmourn")
    entries = parse_timeline(TIMELINE_HTML)

    matches = match_entries(entries, [bloom, dusk])

    assert matches[3] is bloom
    assert matches[5] is dusk


def test_real_tie_returns_no_match():
    a = story("Episode 1", "Set A", folder="001 - Set A")
    b = story("Episode 1", "Set B", folder="002 - Set B")
    entry = TimelineEntry(0, "Era", None, None, None, "Episode 1", f"{WIKI}episode-1", None)

    assert match_entries([entry], [a, b]) == {}


def test_title_with_semicolon_or_matches_short_timeline_title():
    long_title = story("Prisoner of the Skep; or, How I Lost My Mind", "Set A")
    entry = TimelineEntry(0, "Era", None, None, None, "Prisoner of the Skep", f"{WIKI}prisoner-2020-01-01")

    assert match_entries([entry], [long_title]) == {0: long_title}


# ---------------------------------------------------------------- build_chronology

def test_build_chronology_primary_versus_portion_neighbor_and_publication():
    alpha = story("Alpha Tale", "Alpha Set", folder="001 - Alpha Set")
    beta = story("Beta Tale", "Beta Set", folder="002 - Beta Set")
    bloom1 = story("Episode 1", "Bloomburrow", 1, "057 - Bloomburrow")
    bloom2 = story("Episode 2", "Bloomburrow", 2, "057 - Bloomburrow")  # fora da timeline
    orphan = story("Orphan Story", "Zeta", 1, "099 - Zeta")  # set inteiro ausente
    undated = story("Undated Tale", "Alpha Set", 5, "001 - Alpha Set")
    entries = parse_timeline(TIMELINE_HTML)

    items = build_chronology(entries, [alpha, beta, bloom1, bloom2, orphan, undated])
    by_title = {i.title: i for i in items}

    assert [i.position for i in items] == list(range(1, len(items) + 1))
    # Beta: a entrada principal (Era Two) vence a "past portion"; a parte vira portions
    assert by_title["Beta Tale"].era == "Era Two" and by_title["Beta Tale"].placement == "timeline"
    assert len(by_title["Beta Tale"].portions) == 1 and "past portion" in by_title["Beta Tale"].portions[0]
    assert by_title["Beta Tale"].url == f"{WIKI}beta-tale-2020-02-01"
    # Episode 2 não está na timeline: logo depois do Episode 1 do mesmo set
    assert by_title["Episode 2"].placement == "set-neighbor"
    order = [i.title for i in items]
    assert order.index("Episode 2") == order.index("Episode 1") + 1
    assert by_title["Episode 2"].era == "Era One (1 AR to 10 AR)" and by_title["Episode 2"].arc == "First Arc"
    assert by_title["Episode 2"].url is None
    # Set ausente: depois da última datada e antes de "Undated"
    assert by_title["Orphan Story"].placement == "publication"
    assert by_title["Orphan Story"].era == "Not yet in the timeline"
    assert order.index("Orphan Story") < order.index("Undated Tale")
    assert order.index("Orphan Story") > order.index("Beta Tale")


# ---------------------------------------------------------------- volumes

def test_volumes_ancient_history_clean_names_and_cont():
    items = [
        item(1, "a", "Mythohistory (c. -25,000 AR to c. -5000 AR)"),
        item(2, "b", '"Empty Quarter" (c. 3000 AR to c. 4000 AR)'),
        item(3, "c", "Rift Era (4206 AR to 4500 AR)", arc="Mirari Saga"),
        item(4, "d", "Mending Era (4500 AR to Present)"),
        item(5, "e", "Gatewatch Era", arc="Eldrazi Arc"),
        item(6, "f", "Gatewatch Era", arc="Eldrazi Arc"),
        item(7, "g", '"Metronome"', arc="Omenpath Arc"),
        item(8, "h", "Gatewatch Era", arc="Eldrazi Arc"),
        item(9, "i", "Not yet in the timeline"),
        item(10, "j", "Undated"),
    ]

    vols = volumes(items)

    assert [(v.number, v.name, [i.title for i in v.items]) for v in vols] == [
        (1, "Ancient History", ["a", "b", "c"]),
        (2, "Mending Era", ["d"]),
        (3, "Eldrazi Arc", ["e", "f"]),
        (4, "Omenpath Arc", ["g"]),
        (5, "Eldrazi Arc (cont.)", ["h"]),
        (6, "Not yet in the timeline", ["i"]),
        (7, "Undated", ["j"]),
    ]


def test_clean_name_strips_range_and_quotes():
    assert chronology.clean_name("Mending Era (4500 AR to Present)") == "Mending Era"
    assert chronology.clean_name('"Metronome"') == "Metronome"
    assert chronology.clean_name("Gatewatch Era") == "Gatewatch Era"


# ---------------------------------------------------------------- wrappers

def test_write_wrappers_content_escape_and_cleanup(tmp_path):
    out = tmp_path / "stories" / "chronological"
    out.mkdir(parents=True)
    (out / "old.typ").write_text("antigo", encoding="utf-8")
    (out / "keep.txt").write_text("fica", encoding="utf-8")
    other = tmp_path / "stories" / "outro.typ"
    other.write_text("fora da pasta", encoding="utf-8")
    items = [
        item(1, "a", "Mending Era (x)", path="stories/057 - Bloomburrow/001_Episode 1- Calamity.typ"),
        item(2, "b", "Mending Era (x)", path='stories/009 - Say "Hi"/002_back\\slash.typ'),
    ]

    written = chronology.write_wrappers(items, out)

    assert [p.name for p in written] == ["01 - Mending Era.typ"]
    assert sorted(p.name for p in out.iterdir()) == ["01 - Mending Era.typ", "keep.txt"]
    assert other.read_text(encoding="utf-8") == "fora da pasta"
    assert written[0].read_text(encoding="utf-8").splitlines() == [
        '#import "@local/mtgset:0.1.0": conf',
        '#show: doc => conf("Mending Era", doc)',
        "",
        '#include "../057 - Bloomburrow/001_Episode 1- Calamity.typ"',
        '#include "../009 - Say \\"Hi\\"/002_back\\\\slash.typ"',
    ]


def test_wrappers_cli_uses_chronology_file(tmp_path, monkeypatch):
    data = tmp_path / "data" / "chronology.json"
    chronology.write_chronology([item(1, "a", "Undated")], [], data)
    monkeypatch.setattr(chronology, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(chronology, "CHRONOLOGY_FILE", data)

    assert chronology.main(["--wrappers"]) == 0
    assert (tmp_path / "stories" / "chronological" / "01 - Undated.typ").is_file()


def test_wrappers_cli_without_json_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(chronology, "CHRONOLOGY_FILE", tmp_path / "missing.json")
    assert chronology.main(["--wrappers"]) == 2


def test_load_archive_ignores_wrapper_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(chronology, "REPO_ROOT", tmp_path)
    stories = tmp_path / "stories"
    (stories / "001 - Set").mkdir(parents=True)
    (stories / "001 - Set" / "001_A.typ").write_text('#show: doc => conf("A", doc)', encoding="utf-8")
    (stories / "chronological").mkdir()
    (stories / "chronological" / "01 - Vol.typ").write_text("#include", encoding="utf-8")

    assert [s.title for s in chronology.load_archive(stories)] == ["A"]


# ---------------------------------------------------------------- --chronological

def _fake_repo(tmp_path, monkeypatch):
    stories = tmp_path / "stories"
    for rel in ("001 - Set A/001_One.typ", "001 - Set A/002_Two.typ", "002 - Set B/001_Three.typ"):
        path = stories / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'#show: doc => conf("{path.stem}", author: "X", doc)\ntexto', encoding="utf-8")
    items = [
        item(1, "Three", "Rift Era (x)", path="stories/002 - Set B/001_Three.typ", set_name="Set B"),
        item(2, "Gone", "Rift Era (x)", path="stories/002 - Set B/009_Gone.typ", set_name="Set B"),  # .typ sumiu
        item(3, "One", "Mending Era (x)", path="stories/001 - Set A/001_One.typ", set_name="Set A"),
        item(4, "Two", "Mending Era (x)", path="stories/001 - Set A/002_Two.typ", set_name="Set A"),
    ]
    data = tmp_path / "data" / "chronology.json"
    chronology.write_chronology(items, [], data)
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(chronology, "CHRONOLOGY_FILE", data)
    return stories


def test_chronological_builds_tasks_in_volume_order(tmp_path, monkeypatch, capsys):
    stories = _fake_repo(tmp_path, monkeypatch)
    captured = {}

    def fake_run(pipeline, tasks, jobs, force):
        captured["tasks"] = tasks
        return []

    monkeypatch.setattr(cli, "_run_tasks", fake_run)
    monkeypatch.setattr(cli, "EpubPipeline", lambda *a, **k: object())
    monkeypatch.setattr(cli, "load_manifest", lambda path: {})
    out = tmp_path / "out"

    code = cli.main(["--chronological", "--output-dir", str(out), "--stories-dir", str(stories), "--jobs", "1"])

    assert code == 0
    first, second = captured["tasks"]
    sources, output, meta, titles = first
    assert output == out / "chronological" / "01 - Ancient History.epub"
    assert [s.name for s in sources] == ["001_Three.typ"]  # "Gone" foi pulado
    assert titles == ["Three (Set B)"]
    assert meta.title == "MTG Story Chronological 01: Ancient History"
    assert meta.series == "MTG Story — Chronological"
    assert meta.series_index == 1 and meta.set_name == "Chronological"

    sources, output, meta, titles = second
    assert output.name == "02 - Mending Era.epub"
    assert [s.name for s in sources] == ["001_One.typ", "002_Two.typ"]
    assert titles == ["One (Set A)", "Two (Set A)"]
    assert meta.series_index == 2
    assert "Gone" in capsys.readouterr().err  # aviso


def test_chronological_without_json_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(chronology, "CHRONOLOGY_FILE", tmp_path / "nope.json")

    assert cli.main(["--chronological", "--output-dir", str(tmp_path / "out")]) == 2
    assert "chronology --update" in capsys.readouterr().err


def test_chronological_volumes_use_anthology_theme():
    from mtg_epub.themes import theme_for_set

    assert theme_for_set("Chronological").name == "anthology"


def test_write_wrappers_removes_orphan_pdfs(tmp_path):
    out = tmp_path / "stories" / "chronological"
    out.mkdir(parents=True)
    (out / "99 - Extinto.pdf").write_bytes(b"%PDF")
    (out / "keep.txt").write_text("fica", encoding="utf-8")
    chronology.write_wrappers([item(1, "a", "Undated")], out)
    assert not list(out.glob("*.pdf"))
    assert (out / "keep.txt").exists()


def test_write_wrappers_keeps_current_pdfs_and_unchanged_typ(tmp_path):
    from mtg_epub import TEXT_ONLY_SUFFIX

    out = tmp_path / "stories" / "chronological"
    out.mkdir(parents=True)
    items = [item(1, "a", "Undated")]
    typ = chronology.write_wrappers(items, out)[0]
    pdf_ok = out / f"{typ.stem}.pdf"
    pdf_text = out / f"{typ.stem}{TEXT_ONLY_SUFFIX}.pdf"
    pdf_old = out / f"99 - Extinto{TEXT_ONLY_SUFFIX}.pdf"
    for p in (pdf_ok, pdf_text, pdf_old):
        p.write_bytes(b"%PDF")
    (out / "98 - Extinto.typ").write_text("x", encoding="utf-8")
    mtime = typ.stat().st_mtime_ns

    chronology.write_wrappers(items, out)

    assert pdf_ok.exists() and pdf_text.exists()
    assert not pdf_old.exists() and not (out / "98 - Extinto.typ").exists()
    assert typ.stat().st_mtime_ns == mtime


def _run_update(tmp_path, monkeypatch, entries, *extra):
    out = tmp_path / "chronology.json"
    monkeypatch.setattr(chronology, "fetch_timeline_html", lambda: "<html/>")
    monkeypatch.setattr(chronology, "parse_timeline", lambda html: entries)
    monkeypatch.setattr(chronology, "load_archive", lambda: [])
    monkeypatch.setattr(chronology, "build_chronology", lambda e, s: [])
    monkeypatch.setattr(chronology, "missing_from_archive", lambda e, s: [])
    return out, chronology.main(["--update", "--output", str(out), *extra])


def test_update_aborts_on_empty_timeline(tmp_path, monkeypatch, capsys):
    out = tmp_path / "chronology.json"
    out.write_text("bom", encoding="utf-8")
    _, code = _run_update(tmp_path, monkeypatch, [])
    assert code == 1
    assert out.read_text(encoding="utf-8") == "bom"
    assert "0 entradas" in capsys.readouterr().err
    _, code = _run_update(tmp_path, monkeypatch, [], "--force")
    assert code == 0 and json.loads(out.read_text(encoding="utf-8"))["stories"] == []


def test_update_aborts_when_timeline_placements_drop(tmp_path, monkeypatch, capsys):
    out = tmp_path / "chronology.json"
    chronology.write_chronology([item(i, f"s{i}", "Undated") for i in range(10)], [], out)
    before = out.read_text(encoding="utf-8")
    monkeypatch.setattr(chronology, "fetch_timeline_html", lambda: "<html/>")
    monkeypatch.setattr(chronology, "parse_timeline", lambda html: ["e"])
    monkeypatch.setattr(chronology, "load_archive", lambda: [])
    monkeypatch.setattr(chronology, "build_chronology", lambda e, s: [item(i, f"s{i}", "Undated") for i in range(7)])
    monkeypatch.setattr(chronology, "missing_from_archive", lambda e, s: [])
    assert chronology.main(["--update", "--output", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == before
    assert "caíram de 10 para 7" in capsys.readouterr().err
    assert chronology.main(["--update", "--output", str(out), "--force"]) == 0
