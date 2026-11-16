from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tqdm import tqdm

import dataclasses

from . import REPO_ROOT, chronology
from .manifest import load_manifest, manifest_item_for
from .metadata import collection_metadata, extract_metadata, omnibus_metadata, readable_set_name
from .models import StoryMetadata
from .pipeline import EpubPipeline, collect_typst_files, write_report, run_epubcheck, validate_epub
from .slugs import slugify
from .typst_html import TMP_TYP_SUFFIX

DEFAULT_STORIES_DIR = REPO_ROOT / "stories"
DEFAULT_GUIDES_DIR = REPO_ROOT / "planeswalkers_guides"
DEFAULT_CARD_LORE_DIR = REPO_ROOT / "card_lore"
DEFAULT_FONTS_DIR = REPO_ROOT / "fonts"
DEFAULT_MANIFEST = REPO_ROOT / "scraped_manifest.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "epubs"
DEFAULT_EPUBCHECK_JAR = REPO_ROOT / "tools" / "epubcheck-5.4.0" / "epubcheck.jar"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_slug(path: Path) -> str:
    """Slug do set a partir do nome da pasta (ex.: '058-duskmourn-...' -> 'duskmourn-...')."""
    return re.sub(r"^\d+[-_\s]*", "", path.name)


def _collection_key(value: str) -> str:
    """Normaliza um slug/nome para comparação: minúsculas, sem números iniciais, sem pontuação."""
    value = re.sub(r"^\d+[-_\s]*", "", value)   # remove "058-", "058 ", "058_"
    value = value.casefold().replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _appendix_target(folder_name: str, story_slugs: list[str]) -> str | None:
    """
    Recebe o nome da pasta do guide/card_lore e a lista de slugs de sets.
    Devolve o slug do set alvo, ou None (caso de Ulgrotha e livros autônomos).
    """
    # 1. Remove número inicial (ex.: "057 - ", "001 - ")
    no_num = re.sub(r"^\d+[-_\s]*", "", folder_name).strip()
    # 2. Remove prefixo de guias de planeswalker (com ou sem 's, hífen ou espaço)
    cleaned = re.sub(
        r"^planeswalkers?(?:['’]s)?[\s\-_]*(?:guides?[\s\-_]*(?:to)?[\s\-_]*)?",
        "",
        no_num,
        flags=re.IGNORECASE,
    ).strip()
    key = _collection_key(cleaned)

    # Ulgrotha vira livro autônomo (não anexado a nenhum set existente)
    if "ulgrotha" in key:
        return None

    direct = {_collection_key(s): s for s in story_slugs}
    if key in direct:
        return direct[key]

    if "zendikar" in key:
        return next((s for s in story_slugs if _collection_key(s) == "battle for zendikar"), None)
    if "new phyrexia" in key or "phyrexia" in key:
        return next((s for s in story_slugs if "phyrexia" in _collection_key(s)), None)
    return None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Converte fontes Typst de MTG Stories para EPUB3")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", type=Path, help="Arquivo Typst específico")
    source.add_argument("--set", dest="set_name", help="Nome exato ou parcial da coleção")
    source.add_argument("--all", action="store_true", help="Converte todas as coleções")
    source.add_argument("--chronological", action="store_true", help="Gera um EPUB por volume na ordem cronológica (data/chronology.json)")
    source.add_argument("--collection", action="store_true", help="Gera a coleção Magic Stories, um EPUB por set")
    parser.add_argument("--compress-images", action="store_true", help="Comprime imagens do acervo com Pillow para otimizar tamanho em e-readers")
    parser.add_argument("--max-image-size", type=int, default=1400, help="Maior lado, em px, das imagens do EPUB (padrão: 1400)")
    parser.add_argument("--no-images", action="store_true", help="Gera o EPUB sem imagens (remove as figuras)")
    parser.add_argument("--combine", action="store_true", help="Gera também um EPUB omnibus")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stories-dir", type=Path, default=DEFAULT_STORIES_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--fonts-dir", type=Path, default=DEFAULT_FONTS_DIR)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--jobs", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--epubcheck", type=Path, nargs="?", const=DEFAULT_EPUBCHECK_JAR)
    parser.add_argument("--validate", type=Path)
    return parser


# ---------------------------------------------------------------------------
# Seleção de sets
# ---------------------------------------------------------------------------

def _target_sets(args: argparse.Namespace) -> list[Path]:
    if args.set_name:
        needle = slugify(args.set_name)
        candidates = [
            path for path in args.stories_dir.iterdir()
            if path.is_dir() and path.name != chronology.WRAPPERS_DIRNAME and needle in slugify(path.name)
        ]
        if len(candidates) != 1:
            raise ValueError(f"Coleção ambígua ou inexistente: {args.set_name}")
        return candidates
    return sorted(
        path for path in args.stories_dir.iterdir() if path.is_dir() and path.name != chronology.WRAPPERS_DIRNAME
    )


def _metadata(path: Path, manifest: dict) -> StoryMetadata:
    return extract_metadata(path, manifest_item_for(path, manifest))


# ---------------------------------------------------------------------------
# Tarefas de coleção
# ---------------------------------------------------------------------------

Task = tuple[list[Path], Path, StoryMetadata, "list[str] | None"]


def _sort_key(path: Path) -> int:
    m = re.match(r"^(\d+)", path.name)
    return int(m.group(1)) if m else 999


def _collect_appendices(
    guides_dir: Path,
    card_lore_dir: Path,
    story_slugs: list[str],
) -> dict[str, list[tuple[Path, str]]]:
    """Agrupa guias e card lore por slug do set alvo: {slug: [(fonte, tipo)]}."""
    appendices: dict[str, list[tuple[Path, str]]] = {}
    for root_dir, kind in ((guides_dir, "Guide"), (card_lore_dir, "Card Lore")):
        if not root_dir.exists():
            continue
        for folder in sorted(p for p in root_dir.iterdir() if p.is_dir()):
            typ_sources = sorted(p for p in folder.glob("*.typ") if not p.name.endswith(TMP_TYP_SUFFIX))
            if not typ_sources:
                continue
            target_slug = _appendix_target(folder.name, story_slugs)
            if target_slug is None:
                target_slug = _set_slug(folder)
            appendices.setdefault(target_slug, []).extend((source, kind) for source in typ_sources)
    return appendices


def _episode_set_task(
    folder: Path,
    appendix_sources: list[tuple[Path, str]],
    manifest: dict,
    output_dir: Path,
) -> Task | None:
    """Tarefa de um set com episódios (mais seus apêndices)."""
    set_name = readable_set_name(folder.name)
    sources = collect_typst_files(folder)
    story_metadata = [_metadata(source, manifest) for source in sources]
    chapter_titles = [m.title for m in story_metadata]
    first_episode = story_metadata[0] if story_metadata else None

    for source, kind in appendix_sources:
        item = _metadata(source, manifest)
        sources.append(source)
        chapter_titles.append(f"[{kind}] {item.title}")
        story_metadata.append(item)

    if not sources:
        return None
    metadata = collection_metadata(set_name, story_metadata, sources, _sort_key(folder), first_episode)
    return sources, output_dir / f"{set_name}.epub", metadata, chapter_titles


def _orphan_appendix_task(
    set_slug: str,
    appendix_sources: list[tuple[Path, str]],
    manifest: dict,
    output_dir: Path,
) -> Task | None:
    """Tarefa de apêndices sem set com episódios (ex.: Ulgrotha)."""
    sources = [source for source, _ in appendix_sources]
    if not sources:
        return None
    items = [_metadata(source, manifest) for source in sources]
    chapter_titles = [f"[{kind}] {item.title}" for (_, kind), item in zip(appendix_sources, items)]
    set_name = readable_set_name(set_slug)
    metadata = collection_metadata(set_name, items, sources, 999)
    return sources, output_dir / f"{set_name}.epub", metadata, chapter_titles


def _collection_tasks(
    stories_dir: Path,
    guides_dir: Path,
    card_lore_dir: Path,
    manifest: dict,
    output_dir: Path,
) -> list[Task]:
    story_folders = sorted(
        (p for p in stories_dir.iterdir() if p.is_dir() and p.name != chronology.WRAPPERS_DIRNAME), key=_sort_key
    )
    story_slugs = [_set_slug(f) for f in story_folders]
    appendices = _collect_appendices(guides_dir, card_lore_dir, story_slugs)

    tasks: list[Task] = []
    seen_targets: set[str] = set()

    # Fluxo 1: sets COM episódios
    for folder in story_folders:
        set_slug = _set_slug(folder)
        task = _episode_set_task(folder, appendices.get(set_slug, []), manifest, output_dir)
        if task is None:
            continue
        tasks.append(task)
        seen_targets.add(set_slug)

    # Fluxo 2: apêndices órfãos
    for set_slug, appendix_sources in appendices.items():
        if set_slug in seen_targets:
            continue
        task = _orphan_appendix_task(set_slug, appendix_sources, manifest, output_dir)
        if task is not None:
            tasks.append(task)

    return tasks


def _chronological_tasks(items: list, manifest: dict, output_dir: Path) -> list[Task]:
    """Uma tarefa por volume cronológico, reaproveitando collection_metadata."""
    tasks: list[Task] = []
    for vol in chronology.volumes(items):
        sources: list[Path] = []
        story_metadata: list[StoryMetadata] = []
        chapter_titles: list[str] = []
        for item in vol.items:
            source = REPO_ROOT / item.path
            if not source.is_file():
                print(f"[AVISO] {item.path} não existe; pulado no volume {vol.number:02d} - {vol.name}", file=sys.stderr)
                continue
            sources.append(source)
            story_metadata.append(_metadata(source, manifest))
            chapter_titles.append(f"{item.title} ({item.set_name})")
        if not sources:
            continue
        base = collection_metadata("Chronological", story_metadata, sources, vol.number, story_metadata[0])
        metadata = dataclasses.replace(
            base,
            title=f"MTG Story Chronological {vol.number:02d}: {vol.name}",
            series="MTG Story — Chronological",
        )
        name = f"{vol.number:02d} - {chronology._safe_filename(vol.name)}.epub"
        tasks.append((sources, output_dir / name, metadata, chapter_titles))
    return tasks


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _resolve_epubcheck(value: Path | None) -> Path | None:
    """Caminho absoluto do jar. O default já é absoluto (raiz do repo); caminhos dados pelo usuário são relativos ao cwd."""
    if value is None:
        return None
    return value if value.is_absolute() else (Path.cwd() / value).resolve()


def _epubcheck_unavailable(jar: Path) -> str | None:
    """Mensagem de erro se o epubcheck não puder rodar (jar ou java ausentes); None se estiver pronto."""
    if not jar.is_file():
        return (
            f"EpubCheck não encontrado: {jar}. Baixe o EpubCheck em "
            "https://github.com/w3c/epubcheck/releases, extraia em tools/epubcheck-5.4.0/ "
            "ou informe o caminho com --epubcheck <epubcheck.jar>; use --no-validate para pular a validação."
        )
    if shutil.which("java") is None:
        return "Java não encontrado no PATH; ele é necessário para executar o EpubCheck (ou use --no-validate)."
    return None


def _build_tasks(args: argparse.Namespace, manifest: dict) -> tuple[list[Task], Path]:
    """Monta as tarefas de conversão e o caminho do relatório para o modo escolhido."""
    if args.collection:
        collection_dir = args.output_dir / "Magic Stories Collection"
        tasks = _collection_tasks(
            args.stories_dir, DEFAULT_GUIDES_DIR, DEFAULT_CARD_LORE_DIR, manifest, collection_dir,
        )
        return tasks, args.report or collection_dir / "collection-report.json"

    if args.chronological:
        chrono_dir = args.output_dir / "chronological"
        tasks = _chronological_tasks(chronology.load_chronology(chronology.CHRONOLOGY_FILE), manifest, chrono_dir)
        return tasks, args.report or chrono_dir / "chronological-report.json"

    report = args.report or args.output_dir / "conversion-report.json"
    tasks: list[Task] = []
    if args.file:
        source = args.file.resolve()
        tasks.append(([source], args.output_dir / source.with_suffix(".epub").name, _metadata(source, manifest), None))
        return tasks, report

    for set_folder in _target_sets(args):
        sources = collect_typst_files(set_folder)
        for source in sources:
            output = args.output_dir / set_folder.name / source.with_suffix(".epub").name
            tasks.append(([source], output, _metadata(source, manifest), None))
        if args.combine and sources:
            metadata = omnibus_metadata(_metadata(sources[0], manifest), sources[0])
            tasks.append((sources, args.output_dir / set_folder.name / f"{set_folder.name} - Omnibus.epub", metadata, None))
    return tasks, report


def _run_tasks(pipeline: EpubPipeline, tasks: list[Task], jobs: int, force: bool) -> list:
    """Executa as tarefas em paralelo com barras de progresso; devolve os ConversionResult na ordem."""
    import queue

    slots: "queue.Queue[int]" = queue.Queue()
    for i in range(jobs):
        slots.put(i)

    print(f"Iniciando compilação com {jobs} worker(s)...\n")

    main_pbar = tqdm(total=len(tasks), position=0, desc="Progresso Geral", unit="EPUB")
    worker_bars = []
    for i in range(jobs):
        b = tqdm(total=0, position=i + 1, bar_format="{desc}", leave=False)
        b.set_description_str(f"Worker {i+1}: ⏳ Aguardando...".ljust(70))
        worker_bars.append(b)

    def execute_task(task_info):
        sources, output, metadata, chapter_titles = task_info
        name = output.stem

        # O worker pega uma linha disponível
        slot = slots.get()
        try:
            # O ljust(70) preenche com espaços para apagar o nome do arquivo anterior caso fosse maior
            display_name = name[:45] + ("..." if len(name) > 45 else "")
            worker_bars[slot].set_description_str(f"Worker {slot+1}: ⚙️ {display_name}".ljust(70))

            # Compila (convert transforma qualquer falha em ConversionResult de erro)
            return pipeline.convert(sources, output, metadata, force=force, chapter_titles=chapter_titles)
        finally:
            # Sempre devolve a linha e atualiza o progresso, mesmo se algo escapar
            worker_bars[slot].set_description_str(f"Worker {slot+1}: ⏳ Aguardando...".ljust(70))
            main_pbar.update(1)
            slots.put(slot)

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = [executor.submit(execute_task, t) for t in tasks]
        results = [f.result() for f in futures]

    # Finaliza e limpa as barras de interface
    main_pbar.close()
    for b in worker_bars:
        b.close()

    # Pula as linhas que os workers usaram para evitar sobrepor texto no terminal
    print("\n" * jobs)
    return results


def _report_results(report: Path, results: list) -> int:
    """Grava o relatório, imprime erros e resumo; devolve o código de saída."""
    write_report(report, results)
    for result in results:
        if not result.success:
            print(f"[ERRO] {result.status}: {result.output} - {result.error}")

    failures = sum(not result.success for result in results)
    print(f"\nResumo: {len(results) - failures} sucesso(s), {failures} falha(s)")
    print(f"Relatório detalhado: {report}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.validate:
        problems = validate_epub(args.validate)
        if args.epubcheck:
            problems.extend(run_epubcheck(args.validate, _resolve_epubcheck(args.epubcheck)))
        if problems:
            for problem in problems:
                print(f"[ERRO] {problem}", file=sys.stderr)
            return 1
        print(f"[OK] EPUB válido: {args.validate}")
        return 0

    if args.compress_images and not (args.file or args.set_name or args.all or args.collection or args.chronological):
        from .image_compressor import batch_compress_directories
        print("[Otimização] Iniciando compressão de imagens do acervo...")
        batch_compress_directories([args.stories_dir, DEFAULT_GUIDES_DIR, DEFAULT_CARD_LORE_DIR])
        return 0

    if not (args.file or args.set_name or args.all or args.collection or args.chronological):
        build_parser().error("forneça --file, --set, --all, --collection, --chronological ou --compress-images")

    if args.chronological and not chronology.CHRONOLOGY_FILE.exists():
        print(
            f"[ERRO] {chronology.CHRONOLOGY_FILE} não existe; rode: python -m mtg_epub.chronology --update",
            file=sys.stderr,
        )
        return 2

    # --no-validate desliga validate_epub e o epubcheck; sem validação não há o que checar.
    epubcheck = None if args.no_validate else _resolve_epubcheck(args.epubcheck)
    if epubcheck is not None:
        problem = _epubcheck_unavailable(epubcheck)
        if problem:
            print(f"[ERRO] {problem}", file=sys.stderr)
            return 2

    if args.compress_images:
        from .image_compressor import batch_compress_directories
        print("[Otimização] Iniciando compressão de imagens do acervo...")
        batch_compress_directories([args.stories_dir, DEFAULT_GUIDES_DIR, DEFAULT_CARD_LORE_DIR])

    try:
        manifest = load_manifest(args.manifest)
        pipeline = EpubPipeline(
            args.output_dir,
            epubcheck=epubcheck,
            fonts_dir=args.fonts_dir,
            validate=not args.no_validate,
            max_image_size=args.max_image_size,
            with_images=not args.no_images,
        )
        max_system_workers = os.cpu_count() or 1
        jobs = args.jobs if args.jobs > 0 else max_system_workers

        tasks, report = _build_tasks(args, manifest)
        results = _run_tasks(pipeline, tasks, jobs, args.force)
        return _report_results(report, results)

    except (OSError, RuntimeError, ValueError) as error:
        print(f"[ERRO] {error}", file=sys.stderr)
        return 1
