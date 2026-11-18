"""Compilação em lote dos .typ do acervo para PDF (via pacote Python ``typst``).

O PDF fica ao lado do .typ (``X.typ`` -> ``X.pdf``; com ``--no-images``,
``X - text only.pdf``) ou espelhado em ``--output-dir``. Um cache incremental em
``.pdf-cache.json`` evita recompilar o que não mudou; ``pdf-report.json`` registra
o resultado de cada item da última execução.

Uso:
    python typ2pdf.py --file "stories/057 - Bloomburrow/001_....typ"
    python typ2pdf.py --set bloomburrow --jobs 4
    python typ2pdf.py --missing --pdfa
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from . import REPO_ROOT, TEXT_ONLY_SUFFIX
from .chronology import WRAPPERS_DIRNAME

# Suba este valor sempre que uma mudança neste módulo puder alterar o PDF gerado
# para a mesma entrada; ele entra no fingerprint do cache.
PDF_BUILD_VERSION = "1.0.0"

# "a-2b" (PDF/A-2b) é aceito pelo typst 0.15 instalado (testado: a-2b, a-2u, a-2a).
PDFA_STANDARD = "a-2b"

CACHE_NAME = ".pdf-cache.json"
REPORT_NAME = "pdf-report.json"
FONT_SUFFIXES = {".ttf", ".otf"}

_INCLUDE_RE = re.compile(r'#(?:include|import)\s+"([^"@]+\.typ)"')
_IMAGE_RE = re.compile(r'image\(\s*"((?:[^"\\]|\\.)*)"')

STATUS_GENERATED = "generated"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass
class Item:
    source: Path
    output: Path
    status: str = ""
    error: str = ""
    duration: float = 0.0


# --------------------------------------------------------------------------- alvos

def _is_buildable(path: Path) -> bool:
    return path.is_file() and path.suffix == ".typ" and not path.name.endswith(".tmp.typ")


def _typs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.typ") if _is_buildable(p))


def _story_dirs(set_filter: str | None = None) -> list[Path]:
    stories = REPO_ROOT / "stories"
    if not stories.is_dir():
        return []
    needle = set_filter.casefold() if set_filter else None
    return sorted(
        d for d in stories.iterdir()
        if d.is_dir() and d.name != WRAPPERS_DIRNAME and (needle is None or needle in d.name.casefold())
    )


def select_stories(set_filter: str | None = None) -> list[Path]:
    return [t for d in _story_dirs(set_filter) for t in _typs(d)]


def select_set_books(set_filter: str | None = None) -> list[Path]:
    needle = set_filter.casefold() if set_filter else None
    return [
        p for p in _typs(REPO_ROOT / "stories")
        if re.match(r"\d+_", p.name) and (needle is None or needle in p.stem.casefold())
    ]


def select_chronological() -> list[Path]:
    return _typs(REPO_ROOT / "stories" / WRAPPERS_DIRNAME)


def _select_nested(root_name: str) -> list[Path]:
    root = REPO_ROOT / root_name
    if not root.is_dir():
        return []
    return [t for d in sorted(p for p in root.iterdir() if p.is_dir()) for t in _typs(d)]


def select_guides() -> list[Path]:
    return _select_nested("planeswalkers_guides")


def select_card_lore() -> list[Path]:
    return _select_nested("card_lore")


def output_path(source: Path, *, with_images: bool = True, output_dir: Path | None = None) -> Path:
    name = source.stem + ("" if with_images else TEXT_ONLY_SUFFIX) + ".pdf"
    if output_dir is None:
        return source.with_name(name)
    try:
        rel = source.resolve().relative_to(REPO_ROOT.resolve()).parent
    except ValueError:  # fora do repositório: fica na raiz do diretório de saída
        rel = Path()
    return Path(output_dir) / rel / name


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    """Aplica as flags de alvo; devolve a lista (sem duplicatas, em ordem) antes do --missing."""
    found: list[Path] = []
    for raw in args.file or []:
        p = Path(raw)
        found.append(p if p.is_absolute() else Path.cwd() / p)
    explicit = bool(found or args.set or args.all or args.set_books or args.chronological
                    or args.guides or args.card_lore)
    if args.missing and not explicit:
        args.all = args.guides = args.card_lore = True
    if args.set_books:
        # com --set-books, --set filtra os livros (não seleciona contos soltos)
        found += select_set_books(args.set)
    elif args.set:
        found += select_stories(args.set)
    if args.all:
        found += select_stories()
    if args.chronological:
        found += select_chronological()
    if args.guides:
        found += select_guides()
    if args.card_lore:
        found += select_card_lore()
    seen: set[Path] = set()
    unique = []
    for p in found:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


# --------------------------------------------------------------------- fingerprint

_HASH_MEMO: dict[tuple[str, int, int, int], str] = {}
FONT_HASH_BYTES = 64 * 1024


def _file_digest(path: Path, st: os.stat_result, limit: int | None) -> str:
    """sha256 do conteúdo (ou dos primeiros ``limit`` bytes); memoizado por (caminho, tamanho, mtime)."""
    key = (str(path), st.st_size, st.st_mtime_ns, limit or 0)
    digest = _HASH_MEMO.get(key)
    if digest is None:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            h.update(fh.read(limit) if limit else fh.read())
        digest = _HASH_MEMO[key] = h.hexdigest()
    return digest


def tree_signature(folder: Path, *, head_bytes: int | None = None, include_size: bool = False,
                   exclude: tuple[str, ...] = ()) -> str:
    """Hash do conteúdo (caminho relativo + sha256 dos bytes) dos arquivos sob ``folder``.

    O mtime não entra: apenas "tocar" um arquivo não invalida o cache. Com ``head_bytes`` só os
    primeiros bytes são lidos (e o tamanho entra no hash, ``include_size``); ``exclude`` ignora
    subpastas de primeiro nível (ex.: ``cache``).
    """
    h = hashlib.sha256()
    if folder.is_dir():
        for p in sorted(folder.rglob("*")):
            try:
                rel = p.relative_to(folder)
                if rel.parts[0] in exclude or not p.is_file():
                    continue
                st = p.stat()
                digest = _file_digest(p, st, head_bytes)
            except OSError:
                continue
            size = f"|{st.st_size}" if include_size else ""
            h.update(f"{rel.as_posix()}{size}|{digest};".encode())
    return h.hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve_ref(typ: Path, ref: str) -> Path:
    ref = ref.replace('\\"', '"')
    return (REPO_ROOT / ref.lstrip("/")) if ref.startswith("/") else typ.parent / ref


def collect_dependencies(source: Path) -> tuple[list[Path], list[Path]]:
    """Devolve (.typ alcançados por include/import, incluindo o próprio; imagens referenciadas)."""
    typs: list[Path] = []
    images: list[Path] = []
    seen: set[Path] = set()
    stack = [source]
    while stack:
        cur = stack.pop()
        key = cur.resolve()
        if key in seen:
            continue
        seen.add(key)
        typs.append(cur)
        try:
            text = _read_text(cur)
        except OSError:
            continue
        for ref in _INCLUDE_RE.findall(text):
            stack.append(_resolve_ref(cur, ref))
        for ref in _IMAGE_RE.findall(text):
            images.append(_resolve_ref(cur, ref))
    typs.sort(key=lambda p: str(p))
    images = sorted(set(images), key=lambda p: str(p))
    return typs, images


def fingerprint(source: Path, *, with_images: bool, pdfa: bool, static: str) -> str:
    """``static`` = assinatura de pacotes + fontes (calculada uma vez por execução)."""
    h = hashlib.sha256()
    h.update(f"build={PDF_BUILD_VERSION}\nwith_images={with_images}\npdfa={pdfa}\n".encode())
    h.update(static.encode())
    typs, images = collect_dependencies(source)
    for t in typs:
        h.update(f"typ:{t.name}\n".encode())
        try:
            h.update(t.read_bytes())
        except OSError:
            h.update(b"missing")
    for img in images:
        try:
            st = img.stat()
            h.update(f"img:{img.as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
        except OSError:
            h.update(f"img:{img.as_posix()}|missing\n".encode())
    return h.hexdigest()


def static_signature() -> str:
    """Pacotes Typst (conteúdo, sem ``cache/``) + fontes (nome, tamanho e sha256 dos primeiros 64 KB)."""
    h = hashlib.sha256()
    h.update(f"typst_packages:{tree_signature(REPO_ROOT / 'typst_packages', exclude=('cache',))}\n".encode())
    h.update(f"fonts:{tree_signature(REPO_ROOT / 'fonts', head_bytes=FONT_HASH_BYTES, include_size=True)}\n".encode())
    return h.hexdigest()


# ------------------------------------------------------------------------ cache

class Cache:
    """JSON simples ``{chave_do_pdf: fingerprint | {fp, with_images, pdfa}}`` com gravação atômica e lock."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def key(output: Path) -> str:
        try:
            return output.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            return str(output.resolve())

    def entry(self, output: Path) -> tuple[str, dict] | None:
        """(fingerprint, opções) da entrada; entradas antigas (só string) não têm opções."""
        raw = self.data.get(self.key(output))
        if isinstance(raw, str):
            return raw, {}
        if isinstance(raw, dict) and isinstance(raw.get("fp"), str):
            return raw["fp"], {k: v for k, v in raw.items() if k != "fp"}
        return None

    def is_fresh(self, output: Path, fp: str) -> bool:
        entry = self.entry(output)
        return output.exists() and entry is not None and entry[0] == fp

    def update(self, output: Path, fp: str, options: dict | None = None) -> None:
        value = {"fp": fp, **options} if options else fp
        with self._lock:
            self._with_file_lock(lambda: self._write({self.key(output): value}))

    def _write(self, changes: dict) -> None:
        current = self._load()  # mescla com o que outro processo gravou
        current.update(changes)
        self.data = current
        tmp = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp.write_text(json.dumps(current, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def _with_file_lock(self, fn, timeout: float = 15.0, stale: float = 60.0) -> None:
        lock = self.path.with_name(self.path.name + ".lock")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > stale:
                        lock.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"lock do cache ocupado: {lock}")
                time.sleep(0.05)
        try:
            fn()
        finally:
            lock.unlink(missing_ok=True)


# ----------------------------------------------------------------------- compilação

def extract_fonts(dest: Path) -> list[Path]:
    """Extrai .ttf/.otf de todos os zips de fonts/ em ``dest``; devolve os font_paths."""
    fonts = REPO_ROOT / "fonts"
    paths: list[Path] = []
    if not fonts.is_dir():
        return paths
    paths.append(fonts)
    for z in sorted(fonts.glob("*.zip")):
        try:
            with zipfile.ZipFile(z) as zf:
                for i, info in enumerate(zf.infolist()):
                    name = Path(info.filename)
                    if info.is_dir() or name.suffix.lower() not in FONT_SUFFIXES:
                        continue
                    target = dest / f"{z.stem}-{i}-{name.name}"
                    with zf.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
        except (zipfile.BadZipFile, OSError) as exc:
            print(f"aviso: não foi possível extrair {z.name}: {exc}", file=sys.stderr)
    if any(dest.iterdir()):
        paths.append(dest)
    return paths


def compile_one(item: Item, *, with_images: bool, pdfa: bool, font_paths: list[Path]) -> None:
    import typst  # import tardio: resolvido em tempo de chamada (facilita monkeypatch)

    tmp = item.output.with_name(f"{item.output.stem}.{uuid.uuid4().hex[:8]}.tmp.pdf")
    item.output.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        root=str(REPO_ROOT),
        font_paths=[str(p) for p in font_paths],
        sys_inputs={"with_images": "true" if with_images else "false"},
        package_path=str(REPO_ROOT / "typst_packages"),
    )
    cache_dir = REPO_ROOT / "typst_packages" / "cache"
    if cache_dir.is_dir():
        kwargs["package_cache_path"] = str(cache_dir)
    if pdfa:
        kwargs["pdf_standards"] = [PDFA_STANDARD]
    try:
        typst.compile(str(item.source), output=str(tmp), **kwargs)
        os.replace(tmp, item.output)
    finally:
        tmp.unlink(missing_ok=True)


def build_item(item: Item, cache: Cache, static: str, *, with_images: bool, pdfa: bool,
               force: bool, font_paths: list[Path]) -> Item:
    start = time.perf_counter()
    try:
        fp = fingerprint(item.source, with_images=with_images, pdfa=pdfa, static=static)
        if not force and cache.is_fresh(item.output, fp):
            item.status = STATUS_SKIPPED
        else:
            compile_one(item, with_images=with_images, pdfa=pdfa, font_paths=font_paths)
            cache.update(item.output, fp, {"with_images": with_images, "pdfa": pdfa})
            item.status = STATUS_GENERATED
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira item do relatório
        item.status = STATUS_FAILED
        item.error = (f"{type(exc).__name__}: {exc}").strip()[:2000]
    item.duration = round(time.perf_counter() - start, 3)
    return item


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="typ2pdf", description="Compila os contos .typ do acervo para PDF.")
    p.add_argument("--file", nargs="+", metavar="PATH", help="um ou mais .typ específicos")
    p.add_argument("--set", metavar="NOME", help="contos de um set (nome parcial da pasta, sem diferenciar maiúsculas)")
    p.add_argument("--all", action="store_true", help="todos os contos de stories/*/ (exceto chronological)")
    p.add_argument("--set-books", action="store_true", help="wrappers de set stories/NNN_*.typ (--set filtra)")
    p.add_argument("--chronological", action="store_true", help="stories/chronological/*.typ")
    p.add_argument("--guides", action="store_true", help="planeswalkers_guides/*/*.typ")
    p.add_argument("--card-lore", action="store_true", help="card_lore/*/*.typ")
    p.add_argument("--missing", action="store_true",
                   help="só alvos sem PDF; sozinho equivale a --all --guides --card-lore")
    p.add_argument("--no-images", action="store_true", help="sem imagens (saída 'X - text only.pdf')")
    p.add_argument("--pdfa", action="store_true", help=f"PDF/A ({PDFA_STANDARD})")
    p.add_argument("--output-dir", metavar="DIR", help="espelha o caminho relativo ao repositório neste diretório")
    p.add_argument("--force", action="store_true", help="ignora o cache incremental")
    p.add_argument("--jobs", type=int, default=1, metavar="N", help="compilações em paralelo (threads)")
    return p


def _progress(total: int):
    try:
        from tqdm import tqdm
        return tqdm(total=total, unit="pdf", desc="PDF")
    except ImportError:
        return None


def run(args: argparse.Namespace) -> int:
    if args.jobs < 1:
        print("erro: --jobs deve ser >= 1", file=sys.stderr)
        return 2
    sources = resolve_targets(args)
    if not sources:
        print("erro: nenhum alvo selecionado (use --file, --set, --all, --set-books, "
              "--chronological, --guides, --card-lore ou --missing)", file=sys.stderr)
        return 2
    bad = [s for s in sources if not _is_buildable(s)]
    if bad:
        for s in bad:
            print(f"erro: arquivo .typ inválido ou inexistente: {s}", file=sys.stderr)
        return 2

    with_images = not args.no_images
    out_dir = Path(args.output_dir).resolve() if args.output_dir else None
    items = [Item(s, output_path(s, with_images=with_images, output_dir=out_dir)) for s in sources]
    if args.missing:
        items = [i for i in items if not i.output.exists()]

    cache = Cache(REPO_ROOT / CACHE_NAME)
    started = time.perf_counter()
    done: list[Item] = []
    if items:
        static = static_signature()
        with tempfile.TemporaryDirectory(prefix="typ2pdf-fonts-") as font_tmp:
            font_paths = extract_fonts(Path(font_tmp))
            bar = _progress(len(items))

            def work(it: Item) -> Item:
                return build_item(it, cache, static, with_images=with_images, pdfa=args.pdfa,
                                  force=args.force, font_paths=font_paths)

            try:
                if args.jobs == 1:
                    for it in items:
                        done.append(work(it))
                        if bar:
                            bar.update(1)
                else:
                    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                        for fut in as_completed([pool.submit(work, it) for it in items]):
                            done.append(fut.result())
                            if bar:
                                bar.update(1)
            finally:
                if bar:
                    bar.close()
    elapsed = time.perf_counter() - started

    order = {id(i): n for n, i in enumerate(items)}
    done.sort(key=lambda i: order[id(i)])
    counts = {s: sum(1 for i in done if i.status == s) for s in (STATUS_GENERATED, STATUS_SKIPPED, STATUS_FAILED)}
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": round(elapsed, 3),
        "summary": counts,
        "items": [
            {"source": _rel(i.source), "output": _rel(i.output), "status": i.status,
             "error": i.error, "duration_seconds": i.duration}
            for i in done
        ],
    }
    try:
        (REPO_ROOT / REPORT_NAME).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        print(f"aviso: não foi possível gravar {REPORT_NAME}: {exc}", file=sys.stderr)

    for i in done:
        if i.status == STATUS_FAILED:
            print(f"FALHA {_rel(i.source)}: {i.error.splitlines()[0] if i.error else ''}", file=sys.stderr)
    print(f"Gerados: {counts[STATUS_GENERATED]}  Pulados: {counts[STATUS_SKIPPED]}  "
          f"Falhas: {counts[STATUS_FAILED]}  Tempo: {elapsed:.1f}s")
    return 1 if counts[STATUS_FAILED] else 0


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
