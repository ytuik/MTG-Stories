"""Ordem de leitura cronológica (in-universe) do acervo.

Fonte: página "Timeline/Sourced" da MTG Wiki (mtg.fandom.com), que lista as
histórias oficiais na ordem em que acontecem no Multiverso. Cada link para
magic.wizards.com vira uma entrada da timeline, que é casada com um .typ do
acervo pelo título (e, em caso de empate, pelo nome do set).

Histórias do acervo que a timeline não lista (sets recentes demais, novelas
publicadas em capítulos etc.) são encaixadas logo depois da história anterior
do mesmo set que tenha posição na timeline; se o set inteiro estiver ausente,
vão para o fim, na ordem de publicação.

Uso:
    python -m mtg_epub.chronology --update          # baixa a timeline e regrava data/chronology.json
    python -m mtg_epub.chronology --html pagina.html # usa um HTML salvo em vez de baixar
    python -m mtg_epub.chronology --wrappers         # gera stories/chronological/NN - Nome.typ (PDF por volume)
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import REPO_ROOT, TEXT_ONLY_SUFFIX
from .typst_themes import _write_if_changed

TIMELINE_API = (
    "https://mtg.fandom.com/api.php?action=parse&page=Timeline/Sourced"
    "&prop=text&format=json&formatversion=2"
)
CHRONOLOGY_FILE = REPO_ROOT / "data" / "chronology.json"
# Pasta (dentro de stories/) dos wrappers Typst por volume; não é um set e fica fora do acervo.
WRAPPERS_DIRNAME = "chronological"
ANCIENT_HISTORY = "Ancient History"

_PORTION_RE = re.compile(
    r"\((?P<p>[^()]*(?:portion|portions|ago|Presently|Later)[^()]*)\)", re.IGNORECASE
)
_CONF_TITLE_RE = re.compile(r'conf\(\s*"((?:[^"\\]|\\.)*)"', re.S)
_CONF_SET_RE = re.compile(r'set_name:\s*"((?:[^"\\]|\\.)*)"')
_CONF_YEAR_RE = re.compile(r"year:\s*(\d{4})")
_URL_DATE_RE = re.compile(r"-(\d{4})-\d{2}-\d{2}/?$")


@dataclass
class TimelineEntry:
    index: int
    era: str
    arc: str | None
    date: str | None
    set_name: str | None
    title: str
    url: str
    portion: str | None = None
    alternate: bool = False


@dataclass
class ArchiveStory:
    path: str  # relativo à raiz do repo, com "/"
    title: str
    set_name: str
    set_folder: str
    number: int
    year: int | None


@dataclass
class ChronologyItem:
    position: int
    path: str
    title: str
    set_name: str
    era: str
    arc: str | None
    date: str | None
    placement: str  # "timeline" | "set-neighbor" | "publication"
    url: str | None = None
    portions: list[str] = field(default_factory=list)
    alternate: bool = False


# ---------------------------------------------------------------- normalização

def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace("’", "'").replace("—", " - ").replace("–", " - ")


def norm(text: str) -> str:
    """Chave de comparação: minúsculas, só letras e dígitos, sem artigo inicial."""
    key = re.sub(r"[^a-z0-9]", "", _fold(text).lower())
    return key[3:] if key.startswith("the") and len(key) > 6 else key


def title_keys(title: str) -> set[str]:
    """Variações de um título: inteiro e sem prefixos ("Set - Episode 1: X" -> "X")."""
    folded = _fold(title)
    keys = {norm(folded)}
    if ";" in folded:  # "Prisoner of the Skep; or, How I ..." -> "Prisoner of the Skep"
        keys.add(norm(folded.split(";", 1)[0]))
    for sep in (" - ", ": ", "-- "):
        if sep in folded:
            keys.add(norm(folded.split(sep, 1)[1]))
            keys.add(norm(folded.rsplit(sep, 1)[-1]))
    return {k for k in keys if len(k) >= 4}


# ---------------------------------------------------------------- parsing

def parse_timeline(html: str) -> list[TimelineEntry]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one(".mw-parser-output") or soup
    era = "Unknown"
    arc: str | None = None
    date: str | None = None
    entries: list[TimelineEntry] = []

    for el in root.find_all(["h2", "h3", "h4", "p", "ul"], recursive=False):
        if el.name == "h2":
            if el.get_text(" ", strip=True).startswith(("Notes", "References")):
                break
            continue
        if el.name in ("h3", "h4"):
            head = el.select_one(".mw-headline")
            text = (head or el).get_text(" ", strip=True)
            if el.name == "h3":
                era, arc = text, None
            else:
                arc = text
            continue
        if el.name == "p":
            if el.find("b"):
                date = re.sub(r"\[\s*\d+\s*\]", "", el.get_text(" ", strip=True)).strip()
            continue
        for li in el.find_all("li"):
            set_name = _enclosing_set(li)
            own_text = "".join(
                t if isinstance(t, str) else t.get_text(" ") for t in li.contents if getattr(t, "name", None) != "ul"
            )
            for a in li.find_all("a", class_="external", recursive=False):
                href = a.get("href", "")
                if "magic.wizards.com" not in href:
                    continue
                portion = _PORTION_RE.search(own_text)
                entries.append(
                    TimelineEntry(
                        index=len(entries),
                        era=era,
                        arc=arc,
                        date=date,
                        set_name=set_name,
                        title=a.get_text(" ", strip=True),
                        url=href,
                        portion=portion.group("p") if portion else None,
                        alternate="†" in own_text,
                    )
                )
    return entries


def _enclosing_set(li) -> str | None:
    """Nome do set em negrito do <li> pai (ex.: "Bloomburrow"), se houver."""
    node = li
    while node is not None and node.name in ("li", "ul"):
        if node.name == "li":
            bold = node.find("b", recursive=False)
            if bold:
                return bold.get_text(" ", strip=True)
        node = node.parent
    return None


def load_archive(stories_dir: Path | None = None) -> list[ArchiveStory]:
    stories_dir = stories_dir or REPO_ROOT / "stories"
    result: list[ArchiveStory] = []
    for path in sorted(stories_dir.glob("*/*.typ")):
        if path.name.endswith(".tmp.typ") or path.parent.name == WRAPPERS_DIRNAME:
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:1500]
        title = _CONF_TITLE_RE.search(head)
        set_name = _CONF_SET_RE.search(head)
        year = _CONF_YEAR_RE.search(head)
        num = re.match(r"(\d+)", path.name)
        result.append(
            ArchiveStory(
                path=path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path.as_posix(),
                title=title.group(1).replace('\\"', '"') if title else path.stem.split("_", 1)[-1],
                set_name=set_name.group(1) if set_name else path.parent.name.split(" - ", 1)[-1],
                set_folder=path.parent.name,
                number=int(num.group(1)) if num else 0,
                year=int(year.group(1)) if year else None,
            )
        )
    return result


# ---------------------------------------------------------------- casamento

def match_entries(entries: list[TimelineEntry], stories: list[ArchiveStory]) -> dict[int, ArchiveStory]:
    """Devolve índice da entrada -> história do acervo."""
    by_key: dict[str, list[ArchiveStory]] = {}
    for story in stories:
        for key in title_keys(story.title):
            by_key.setdefault(key, []).append(story)
    all_keys = list(by_key)

    matches: dict[int, ArchiveStory] = {}
    for entry in entries:
        slug = _URL_DATE_RE.sub("", entry.url.rstrip("/")).rsplit("/", 1)[-1].replace("-", " ")
        keys = title_keys(entry.title) | title_keys(slug)
        candidates = {id(s): s for k in keys for s in by_key.get(k, [])}
        if not candidates:
            for key in title_keys(entry.title):
                for close in difflib.get_close_matches(key, all_keys, n=3, cutoff=0.9):
                    for s in by_key[close]:
                        candidates[id(s)] = s
        if not candidates:
            continue
        best = _pick(entry, list(candidates.values()))
        if best is not None:
            matches[entry.index] = best
    return matches


def _pick(entry: TimelineEntry, candidates: list[ArchiveStory]) -> ArchiveStory | None:
    if len(candidates) == 1:
        return candidates[0]
    url_year = _URL_DATE_RE.search(entry.url)
    context = norm(" ".join(filter(None, [entry.set_name, entry.title, entry.arc])))

    def score(s: ArchiveStory) -> tuple:
        set_key = norm(s.set_name)
        set_hit = bool(set_key) and set_key in context
        year_gap = abs(int(url_year.group(1)) - s.year) if url_year and s.year else 99
        exact = norm(s.title) == norm(entry.title)
        return (set_hit, exact, -year_gap)

    ranked = sorted(candidates, key=score, reverse=True)
    top, second = score(ranked[0]), score(ranked[1])
    return ranked[0] if top != second else None  # empate real: não chuta


# ---------------------------------------------------------------- ordem final

def build_chronology(entries: list[TimelineEntry], stories: list[ArchiveStory]) -> list[ChronologyItem]:
    matches = match_entries(entries, stories)

    # Posição principal de cada história: a primeira entrada sem "(... portion)";
    # se só houver partes, a primeira delas. As demais viram "portions".
    primary: dict[str, TimelineEntry] = {}
    portions: dict[str, list[str]] = {}
    for entry in entries:
        story = matches.get(entry.index)
        if story is None:
            continue
        if entry.portion:
            portions.setdefault(story.path, []).append(f"{entry.portion} @ {entry.date or entry.era}")
        current = primary.get(story.path)
        if current is None or (current.portion and not entry.portion):
            primary[story.path] = entry

    ordered: list[tuple[float, ArchiveStory, TimelineEntry | None, str]] = [
        (float(e.index), next(s for s in stories if s.path == p), e, "timeline") for p, e in primary.items()
    ]
    placed = {p for p in primary}

    # Encaixa as que faltam logo após a história anterior do mesmo set.
    by_folder: dict[str, list[ArchiveStory]] = {}
    for s in stories:
        by_folder.setdefault(s.set_folder, []).append(s)
    # Sets ainda ausentes da timeline são os mais recentes: entram depois da
    # última história datada e antes da seção "Undated".
    undated = [e.index for e in entries if e.era.lower().startswith("undated")]
    tail = (undated[0] - 0.5) if undated else float(len(entries))
    step = 0.5 / (len(stories) + 1)
    for folder in sorted(by_folder):
        group = sorted(by_folder[folder], key=lambda s: (s.number, s.path))
        anchor: float | None = None
        anchor_entry: TimelineEntry | None = None
        offset = 0
        for s in group:
            if s.path in placed:
                anchor_entry = primary[s.path]
                anchor = float(anchor_entry.index)
                offset = 0
                continue
            offset += 1
            if anchor is not None:
                ordered.append((anchor + offset / 1000, s, anchor_entry, "set-neighbor"))
            else:
                tail += step
                ordered.append((tail, s, None, "publication"))

    ordered.sort(key=lambda t: (t[0], t[1].path))
    items: list[ChronologyItem] = []
    for pos, (_, story, entry, how) in enumerate(ordered, start=1):
        items.append(
            ChronologyItem(
                position=pos,
                path=story.path,
                title=story.title,
                set_name=story.set_name,
                era=entry.era if entry else "Not yet in the timeline",
                arc=entry.arc if entry else None,
                date=entry.date if entry else None,
                placement=how,
                url=entry.url if entry and how == "timeline" else None,
                portions=portions.get(story.path, []),
                alternate=bool(entry and entry.alternate and how == "timeline"),
            )
        )
    return items


def missing_from_archive(entries: list[TimelineEntry], stories: list[ArchiveStory]) -> list[TimelineEntry]:
    """Entradas da timeline (magic.wizards.com) sem .typ correspondente no acervo."""
    matched = match_entries(entries, stories)
    seen: set[str] = set()
    result = []
    for e in entries:
        if e.index in matched or e.url in seen:
            continue
        seen.add(e.url)
        result.append(e)
    return result


# ---------------------------------------------------------------- volumes

@dataclass
class Volume:
    number: int
    name: str
    items: list[ChronologyItem]


def clean_name(name: str) -> str:
    """"Mending Era (4500 AR to Present)" -> "Mending Era"; '"Metronome"' -> "Metronome"."""
    name = re.sub(r"\s*\([^()]*\)\s*$", "", name.strip())
    return name.replace('"', "").replace("“", "").replace("”", "").strip()


def volumes(items: list[ChronologyItem]) -> list[Volume]:
    """Agrupa a ordem cronológica em volumes de leitura (eras/arcos consecutivos)."""
    first_mending = next((i for i, it in enumerate(items) if clean_name(it.era).startswith("Mending")), None)
    result: list[Volume] = []
    seen: set[str] = set()
    current_key: str | None = None
    for index, item in enumerate(items):
        if first_mending is not None and index < first_mending:
            key = ANCIENT_HISTORY
        else:
            key = clean_name(item.arc or item.era)
        if result and key == current_key:
            result[-1].items.append(item)
            continue
        name = f"{key} (cont.)" if key in seen else key
        seen.add(key)
        current_key = key
        result.append(Volume(number=len(result) + 1, name=name, items=[item]))
    return result


def _typst_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "-", name)


def write_wrappers(items: list[ChronologyItem], out_dir: Path | None = None) -> list[Path]:
    """Gera um wrapper Typst por volume em stories/chronological/; apaga só os .typ e PDFs antigos da pasta."""
    out_dir = out_dir or REPO_ROOT / "stories" / WRAPPERS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    vols = volumes(items)
    stems = {f"{vol.number:02d} - {_safe_filename(vol.name)}" for vol in vols}
    for old in (*out_dir.glob("*.typ"), *out_dir.glob("*.pdf")):  # órfãos de volumes extintos
        stem = old.stem.removesuffix(TEXT_ONLY_SUFFIX) if old.suffix == ".pdf" else old.stem
        if stem not in stems:
            old.unlink()
    written: list[Path] = []
    for vol in vols:
        lines = [
            '#import "@local/mtgset:0.1.0": conf',
            f'#show: doc => conf("{_typst_string(vol.name)}", doc)',
            "",
        ]
        for item in vol.items:
            # O wrapper fica em stories/chronological/; as histórias em stories/<set>/<arquivo>.typ
            rel = "../" + item.path.removeprefix("stories/")
            lines.append(f'#include "{_typst_string(rel)}"')
        target = out_dir / f"{vol.number:02d} - {_safe_filename(vol.name)}.typ"
        _write_if_changed(target, ("\n".join(lines) + "\n").encode("utf-8"))
        written.append(target)
    return written


# ---------------------------------------------------------------- IO / CLI

def fetch_timeline_html(timeout: int = 30) -> str:
    import requests

    resp = requests.get(TIMELINE_API, timeout=timeout, headers={"User-Agent": "mtg-stories-archive/1.0"})
    resp.raise_for_status()
    return resp.json()["parse"]["text"]


def write_chronology(items: list[ChronologyItem], missing: list[TimelineEntry], path: Path = CHRONOLOGY_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "https://mtg.fandom.com/wiki/Timeline/Sourced",
        "stories": [asdict(i) for i in items],
        "missing_from_archive": [
            {"title": e.title, "url": e.url, "era": e.era, "date": e.date, "set_name": e.set_name} for e in missing
        ],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_chronology(path: Path = CHRONOLOGY_FILE) -> list[ChronologyItem]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ChronologyItem(**item) for item in data["stories"]]


def _regression_problem(entries: list, timeline_count: int, path: Path) -> str | None:
    """Motivo para não sobrescrever o arquivo existente, ou None se a nova timeline parece saudável."""
    if not entries:
        return "a timeline veio com 0 entradas (página alterada ou download quebrado?)"
    if not path.exists():
        return None
    try:
        old = sum(1 for i in load_chronology(path) if i.placement == "timeline")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if old and timeline_count < old * 0.8:
        return f"histórias posicionadas pela timeline caíram de {old} para {timeline_count} (mais de 20%)"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--wrappers", action="store_true", help="gera stories/chronological/NN - Nome.typ a partir de data/chronology.json")
    src.add_argument("--update", action="store_true", help="baixa a timeline da MTG Wiki")
    src.add_argument("--html", type=Path, help="HTML (ou JSON da API) salvo localmente")
    parser.add_argument("--output", type=Path, default=CHRONOLOGY_FILE)
    parser.add_argument("--force", action="store_true", help="grava mesmo que a timeline venha vazia ou perca >20%% das histórias posicionadas")
    args = parser.parse_args(argv)

    if args.wrappers:
        if not CHRONOLOGY_FILE.exists():
            print(f"[ERRO] {CHRONOLOGY_FILE} não existe; rode: python -m mtg_epub.chronology --update", file=sys.stderr)
            return 2
        written = write_wrappers(load_chronology(CHRONOLOGY_FILE))
        print(f"{len(written)} wrapper(s) gravado(s) em stories/{WRAPPERS_DIRNAME}/")
        return 0

    if args.update:
        html = fetch_timeline_html()
    else:
        raw = args.html.read_text(encoding="utf-8")
        html = json.loads(raw)["parse"]["text"] if raw.lstrip().startswith("{") else raw

    entries = parse_timeline(html)
    stories = load_archive()
    items = build_chronology(entries, stories)
    missing = missing_from_archive(entries, stories)
    counts = {k: sum(1 for i in items if i.placement == k) for k in ("timeline", "set-neighbor", "publication")}
    if not args.force:
        problem = _regression_problem(entries, counts["timeline"], args.output)
        if problem:
            print(f"[ERRO] {problem}; nada foi gravado (use --force para gravar mesmo assim)", file=sys.stderr)
            return 1
    write_chronology(items, missing, args.output)
    print(f"Timeline: {len(entries)} entradas | acervo: {len(stories)} histórias")
    print(f"  pela timeline: {counts['timeline']} | junto do set: {counts['set-neighbor']} | no fim: {counts['publication']}")
    print(f"  na timeline e ausentes do acervo: {len(missing)}")
    print(f"Gravado em {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
