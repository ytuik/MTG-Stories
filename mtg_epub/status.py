"""Relatório do estado do acervo: PDFs/EPUBs ausentes ou desatualizados, falhas do
scraper e contos da timeline que ainda não estão no acervo.

Uso:
    python -m mtg_epub.status                 # resumo por set
    python -m mtg_epub.status --verbose       # lista os itens
    python -m mtg_epub.status --json          # grava status.json
    python -m mtg_epub.status --write-md      # atualiza o bloco automático de MISSING_STORIES.md
    python -m mtg_epub.status --strict        # exit 1 se houver pendências de build/falhas

Nada é compilado: o estado vem dos caches (.pdf-cache.json, epubs/.epub-cache.json),
com fallback para mtime quando o cache não tem entrada do item.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import pdf

OK, MISSING, STALE = "ok", "missing", "stale"

MD_START = "<!-- status:auto:start -->"
MD_END = "<!-- status:auto:end -->"
STATUS_JSON = "status.json"
EPUB_MAX_IMAGE_SIZE = 1400  # mesmo padrão de --max-image-size no cli

# Campos de pendência de build (contam para --strict)
BUILD_FIELDS = ("no_pdf", "stale_pdf", "no_epub", "stale_epub")


def _root() -> Path:
    return pdf.REPO_ROOT


def _rel(path: Path) -> str:
    return pdf._rel(path)


# ---------------------------------------------------------------------- PDF / EPUB

def _newest_dependency_mtime(source: Path) -> float:
    typs, _ = pdf.collect_dependencies(source)
    times = []
    for t in typs:
        try:
            times.append(t.stat().st_mtime)
        except OSError:
            continue
    return max(times, default=0.0)


def _newest_template_mtime() -> float:
    """Arquivo mais novo de typst_packages/local (template do livro/conto)."""
    times = []
    folder = _root() / "typst_packages" / "local"
    if folder.is_dir():
        for p in folder.rglob("*"):
            try:
                if p.is_file():
                    times.append(p.stat().st_mtime)
            except OSError:
                continue
    return max(times, default=0.0)


def _by_mtime(source: Path, output: Path, *, check_template: bool = False) -> str:
    try:
        newest = _newest_dependency_mtime(source)
        if check_template:
            newest = max(newest, _newest_template_mtime())
        return STALE if newest > output.stat().st_mtime else OK
    except OSError:
        return MISSING


def recorded_pdf_options(source: Path, cache: "pdf.Cache") -> dict:
    """Opções gravadas no cache para o PDF do conto (vazio para entradas antigas ou ausentes)."""
    entry = cache.entry(pdf.output_path(source))
    return entry[1] if entry else {}


def classify_pdf(source: Path, cache: "pdf.Cache", static: str) -> str:
    output = pdf.output_path(source)
    if not output.exists():
        return MISSING
    entry = cache.entry(output)
    if entry is None:
        return _by_mtime(source, output, check_template=True)
    recorded, options = entry
    try:
        fp = pdf.fingerprint(source, with_images=bool(options.get("with_images", True)),
                             pdfa=bool(options.get("pdfa", False)), static=static)
    except OSError:
        return _by_mtime(source, output, check_template=True)
    return OK if fp == recorded else STALE


def epub_output_path(source: Path, epubs_dir: Path) -> Path:
    """Convenção do cli (--set): <epubs>/<pasta do set>/<nome do conto>.epub."""
    return epubs_dir / source.parent.name / source.with_suffix(".epub").name


def _epub_fingerprint(source: Path, manifest: dict, pipeline) -> str:
    """Mesmo fingerprint de EpubPipeline.convert, sem converter."""
    from .manifest import manifest_item_for
    from .metadata import extract_metadata

    metadata = extract_metadata(source, manifest_item_for(source, manifest))
    return pipeline.compute_fingerprint([source], metadata)


class EpubChecker:
    def __init__(self, epubs_dir: Path, manifest_path: Path):
        self.epubs_dir = epubs_dir
        self.manifest: dict = {}
        self.pipeline = None
        try:
            from .manifest import load_manifest
            from .pipeline import EpubPipeline
            from .themes import DEFAULT_FONTS_DIR

            self.manifest = load_manifest(manifest_path)
            self.pipeline = EpubPipeline(epubs_dir, fonts_dir=DEFAULT_FONTS_DIR,
                                         max_image_size=EPUB_MAX_IMAGE_SIZE)
        except Exception as exc:  # noqa: BLE001 - sem fingerprint, cai para mtime
            print(f"aviso: fingerprint de EPUB indisponível ({exc}); usando mtime", file=sys.stderr)

    def classify(self, source: Path) -> str:
        output = epub_output_path(source, self.epubs_dir)
        if not output.exists():
            return MISSING
        if self.pipeline is None:
            return _by_mtime(source, output)
        recorded = self.pipeline.cache.get(str(output.resolve()))
        if recorded is None:
            return _by_mtime(source, output)
        try:
            return OK if _epub_fingerprint(source, self.manifest, self.pipeline) == recorded else STALE
        except Exception:  # noqa: BLE001
            return _by_mtime(source, output)


# ---------------------------------------------------------------------- manifest / timeline

def failed_manifest_items(manifest_path: Path) -> list[dict]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("scraped_items", {}) if isinstance(data, dict) else {}
    return [
        {"id": key, "title": item.get("title", ""), "error": item.get("error", ""),
         "source_url": item.get("source_url", "")}
        for key, item in items.items()
        if isinstance(item, dict) and item.get("status") == "failed"
    ]


def missing_timeline(chronology_path: Path) -> dict[str, dict[str, list[dict]]]:
    """{era: {set: [conto, ...]}} na ordem do arquivo (já cronológica)."""
    try:
        data = json.loads(chronology_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    grouped: dict[str, dict[str, list[dict]]] = {}
    for item in data.get("missing_from_archive", []) if isinstance(data, dict) else []:
        era = item.get("era") or "Sem era"
        set_name = item.get("set_name") or "Sem set"
        grouped.setdefault(era, {}).setdefault(set_name, []).append(
            {k: item.get(k) for k in ("title", "date", "url")}
        )
    return grouped


# ---------------------------------------------------------------------- coleta

def _group_name(source: Path, kind: str) -> str:
    if kind == "set_book":
        return "[livros de set] stories"
    if kind == "chronological":
        return "[cronológico] stories/chronological"
    return source.parent.name if kind == "set" else f"[{kind}] {source.parent.name}"


def collect() -> dict:
    root = _root()
    cache = pdf.Cache(root / pdf.CACHE_NAME)
    static = pdf.static_signature()
    epubs = EpubChecker(root / "epubs", root / "scraped_manifest.json")

    sources = (
        [(s, "set") for s in pdf.select_stories()]
        + [(s, "set_book") for s in pdf.select_set_books()]
        + [(s, "chronological") for s in pdf.select_chronological()]
        + [(s, "guide") for s in pdf.select_guides()]
        + [(s, "card_lore") for s in pdf.select_card_lore()]
    )
    sets: dict[str, dict] = {}
    for source, kind in sources:
        entry = sets.setdefault(_group_name(source, kind), {
            "kind": kind, "total": 0, **{f: [] for f in BUILD_FIELDS}, "pdfa": [],
        })
        entry["total"] += 1
        rel = _rel(source)
        if recorded_pdf_options(source, cache).get("pdfa"):
            entry["pdfa"].append(rel)  # o rebuild repete --pdfa
        pdf_state = classify_pdf(source, cache, static)
        if pdf_state == MISSING:
            entry["no_pdf"].append(rel)
        elif pdf_state == STALE:
            entry["stale_pdf"].append(rel)
        if kind == "set":  # guias e card lore só saem em EPUB combinado (--collection)
            epub_state = epubs.classify(source)
            if epub_state == MISSING:
                entry["no_epub"].append(rel)
            elif epub_state == STALE:
                entry["stale_epub"].append(rel)

    return {
        "sets": sets,
        "failed": failed_manifest_items(root / "scraped_manifest.json"),
        "missing_timeline": missing_timeline(root / "data" / "chronology.json"),
    }


def pending_count(report: dict) -> int:
    builds = sum(len(entry[f]) for entry in report["sets"].values() for f in BUILD_FIELDS)
    return builds + len(report["failed"])


def sets_needing_rebuild(report: dict) -> dict[str, dict[str, list[str]]]:
    """{pasta do set: {'pdf': [typ...], 'epub': [typ...]}} só para itens pendentes."""
    out: dict[str, dict[str, list[str]]] = {}
    for name, entry in report["sets"].items():
        pdfs = entry["no_pdf"] + entry["stale_pdf"]
        epubs = entry["no_epub"] + entry["stale_epub"]
        if pdfs or epubs:
            out[name] = {"pdf": pdfs, "epub": epubs, "kind": entry["kind"],
                         "pdfa": [rel for rel in pdfs if rel in entry.get("pdfa", [])]}
    return out


# ---------------------------------------------------------------------- saída

def format_summary(report: dict, verbose: bool = False) -> str:
    lines: list[str] = []
    sets = report["sets"]
    lines.append("== Acervo por set (total | sem PDF | PDF velho | sem EPUB | EPUB velho) ==")
    clean = 0
    for name, e in sets.items():
        counts = [len(e[f]) for f in BUILD_FIELDS]
        if not any(counts):
            clean += 1
            continue
        lines.append(f"{name}: {e['total']} | {counts[0]} | {counts[1]} | {counts[2]} | {counts[3]}")
        if verbose:
            labels = dict(zip(BUILD_FIELDS, ("sem PDF", "PDF desatualizado", "sem EPUB", "EPUB desatualizado")))
            for f in BUILD_FIELDS:
                for rel in e[f]:
                    lines.append(f"    {labels[f]}: {rel}")
    lines.append(f"({clean} de {len(sets)} grupos sem pendências)")

    lines.append("")
    lines.append(f"== Falhas no scraped_manifest.json: {len(report['failed'])} ==")
    for f in report["failed"] if verbose else []:
        lines.append(f"    {f['id']}: {f['error']}")

    total_missing = sum(len(v) for sets_ in report["missing_timeline"].values() for v in sets_.values())
    lines.append("")
    lines.append(f"== Contos da timeline ausentes do acervo: {total_missing} ==")
    for era, by_set in report["missing_timeline"].items():
        lines.append(f"{era}: {sum(len(v) for v in by_set.values())}")
        if verbose:
            for set_name, items in by_set.items():
                lines.append(f"    {set_name}")
                for it in items:
                    lines.append(f"        - {it['title']} ({it['date']})")
    return "\n".join(lines)


def render_md_block(report: dict) -> str:
    """Bloco automático do MISSING_STORIES.md. Só contém o que é estável (sem datas de geração)."""
    lines = [
        MD_START,
        "## Estado automático (gerado por `python -m mtg_epub.status --write-md`)",
        "",
        "_Não edite entre os marcadores; o texto manual fica fora deles._",
        "",
        "### Contos da timeline oficial ausentes do acervo",
        "",
    ]
    grouped = report["missing_timeline"]
    total = sum(len(v) for by_set in grouped.values() for v in by_set.values())
    lines.append(f"Total: **{total}** conto(s).")
    for era, by_set in grouped.items():
        lines += ["", f"#### {era}", ""]
        for set_name, items in by_set.items():
            lines.append(f"- **{set_name}**")
            for it in items:
                title = it["title"]
                link = f"[{title}]({it['url']})" if it.get("url") else title
                lines.append(f"  - {link} ({it['date']})")
    lines += ["", "### Falhas do scraper (`scraped_manifest.json`)", ""]
    if report["failed"]:
        for f in report["failed"]:
            lines.append(f"- `{f['id']}`: {f['error'] or 'sem detalhe'}")
    else:
        lines.append("Nenhuma.")
    lines.append(MD_END)
    return "\n".join(lines)


def apply_md_block(text: str, block: str) -> str:
    """Substitui o bloco entre os marcadores; sem marcadores, insere antes da primeira
    seção `---` (ou no fim). O restante do texto é preservado byte a byte."""
    start, end = text.find(MD_START), text.find(MD_END)
    if start != -1 and end > start:
        return text[:start] + block + text[end + len(MD_END):]
    match = re.search(r"^---\s*$", text, flags=re.M)
    if match:
        return text[:match.start()] + block + "\n\n" + text[match.start():]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def write_md(report: dict, path: Path) -> bool:
    """Devolve True se o arquivo mudou."""
    try:
        raw = path.read_bytes().decode("utf-8")
    except OSError:
        raw = "# Catálogo de Histórias Faltantes e Mídias Não-Scrappeáveis\n\n"
    crlf = "\r\n" in raw  # preserva a convenção de quebra de linha do arquivo
    text = raw.replace("\r\n", "\n")
    new = apply_md_block(text, render_md_block(report))
    if crlf:
        new = new.replace("\n", "\r\n")
    if new == raw and path.exists():
        return False
    path.write_bytes(new.encode("utf-8"))
    return True


# ---------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m mtg_epub.status", description="Estado do acervo (PDF/EPUB/scraper/timeline).")
    p.add_argument("--verbose", "-v", action="store_true", help="lista os itens pendentes")
    p.add_argument("--json", action="store_true", help=f"grava {STATUS_JSON} na raiz do repositório")
    p.add_argument("--write-md", action="store_true", help="atualiza o bloco automático de MISSING_STORIES.md")
    p.add_argument("--strict", action="store_true", help="exit 1 se houver PDF/EPUB pendente ou falha no manifest")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # console cp1252 não quebra com títulos Unicode
    report = collect()
    print(format_summary(report, verbose=args.verbose))
    if args.json:
        path = _root() / STATUS_JSON
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nGravado: {path}")
    if args.write_md:
        path = _root() / "MISSING_STORIES.md"
        changed = write_md(report, path)
        print(f"\n{path.name}: {'atualizado' if changed else 'sem mudanças'}")
    return 1 if args.strict and pending_count(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
