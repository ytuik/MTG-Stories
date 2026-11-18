from __future__ import annotations

import json
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path

from . import REPO_ROOT
from .models import StoryMetadata
from .slugs import slugify

# Raiz do workspace (um nível acima do pacote)
WORKSPACE_ROOT = REPO_ROOT
SET_NAMES_FILE = WORKSPACE_ROOT / "set-names.json"
_NUMERIC_PREFIX_RE = re.compile(r"^\d+[-_\s]*")
_GUIDE_PREFIX_RE = re.compile(r"^planeswalkers?-guide-to-", re.IGNORECASE)
_set_names_cache: dict[str, str] | None = None


def _readable_from_raw(folder_name: str) -> str:
    """Nome legível a partir do nome da pasta:
      "Planeswalker's Guide to Ulgrotha" -> "Ulgrotha"
      "021 - Battle for Zendikar"        -> "Battle for Zendikar"
    """
    cleaned = _NUMERIC_PREFIX_RE.sub("", folder_name).strip(" -_")
    cleaned = cleaned.replace("'", "").replace("\u2019", "")
    cleaned = _GUIDE_PREFIX_RE.sub("", cleaned).strip(" -_")
    return cleaned.strip()


def collect_set_names(root: Path) -> dict[str, str]:
    """Mapeia slug do set -> nome legível, a partir das pastas do acervo."""
    result: dict[str, str] = {}

    stories_base = root / "stories"
    if stories_base.exists():
        for folder in stories_base.iterdir():
            if not folder.is_dir():
                continue
            readable = _readable_from_raw(folder.name)
            slug = slugify(readable)
            if slug:
                result[slug] = readable

    for top in ("planeswalkers_guides", "card_lore"):
        base = root / top
        if not base.exists():
            continue
        for folder in base.iterdir():
            if not folder.is_dir():
                continue
            readable = _readable_from_raw(folder.name)
            slug = slugify(readable)
            if slug:
                result.setdefault(slug, readable)

    return result


def _warn(message: str) -> None:
    warnings.warn(message, RuntimeWarning, stacklevel=3)


def _load_set_names() -> dict[str, str]:
    global _set_names_cache
    if _set_names_cache is not None:
        return _set_names_cache
    file_exists = SET_NAMES_FILE.exists()
    if file_exists:
        try:
            data = json.loads(SET_NAMES_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("o JSON não é um objeto chave -> nome")
            _set_names_cache = data
            return _set_names_cache
        except (OSError, ValueError) as error:  # JSONDecodeError e UnicodeDecodeError são ValueError
            _warn(f"{SET_NAMES_FILE} ilegível ou corrompido ({error}); nomes serão regenerados das pastas do acervo")
    # Carrega dinamicamente a partir das pastas do repositório
    try:
        _set_names_cache = collect_set_names(WORKSPACE_ROOT)
    except (OSError, ImportError) as error:
        _warn(f"não foi possível gerar os nomes de coleções ({error}); usando nomes derivados dos slugs")
        _set_names_cache = {}
        return _set_names_cache
    # Só grava quando o arquivo não existia: nunca sobrescreve um arquivo corrompido (preserva para diagnóstico).
    if not file_exists:
        try:
            SET_NAMES_FILE.write_text(json.dumps(_set_names_cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as error:
            _warn(f"não foi possível gravar {SET_NAMES_FILE}: {error}")
    return _set_names_cache


def readable_set_name(folder_or_slug: str) -> str:
    """Nome legível do set a partir do nome da pasta ou do slug.

    Usa set-names.json (busca exata, pelo slug e sem diferenciar maiúsculas);
    se não achar, cai num fallback determinístico derivado do próprio nome.
    """
    name = _NUMERIC_PREFIX_RE.sub("", folder_or_slug).strip(" -_")
    names = _load_set_names()
    if name in names:
        return names[name]
    clean_slug = slugify(name)
    if clean_slug in names:
        return names[clean_slug]
    for key, value in names.items():
        if key.casefold() == clean_slug.casefold():
            return value
    # Fallback: nome com espaços já é legível; slug vira Title Case
    if " " in name:
        return name
    return name.replace("-", " ").replace("_", " ").strip().title()


# Literal de string do Typst: entre aspas, com escapes como \" e \\
_TYPST_STRING = r'"((?:[^"\\]|\\.)*)"'
_TYPST_ESCAPE_RE = re.compile(r"\\(?:u\{([0-9a-fA-F]+)\}|(.))", re.DOTALL)
_TYPST_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}


def _unescape_typst(value: str) -> str:
    def repl(match: re.Match) -> str:
        if match.group(1):
            try:
                return chr(int(match.group(1), 16))
            except (ValueError, OverflowError):
                return match.group(0)
        char = match.group(2)
        return _TYPST_SIMPLE_ESCAPES.get(char, char)

    return _TYPST_ESCAPE_RE.sub(repl, value)


def _string_value(content: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*{_TYPST_STRING}", content)
    return _unescape_typst(match.group(1)).strip() if match else None


def _title_from_conf(content: str) -> str | None:
    marker = "#show: doc => conf"
    start = content.find(marker)
    if start < 0:
        return None
    opening = content.find("(", start + len(marker))
    if opening < 0:
        return None
    match = re.match(rf"\s*\(\s*{_TYPST_STRING}", content[opening:])
    return _unescape_typst(match.group(1)).strip() if match else None


def _date_from_content(content: str) -> str | None:
    match = re.search(
        r"(?:story_date|date)\s*:\s*datetime\s*\(\s*day:\s*(\d+),\s*month:\s*(\d+),\s*year:\s*(\d+)",
        content,
    )
    if not match:
        return None
    try:
        return datetime(
            int(match.group(3)), int(match.group(2)), int(match.group(1))
        ).date().isoformat()
    except ValueError:
        return None


def _cover_candidates(typ_path: Path) -> list[Path]:
    directories = [typ_path.parent / typ_path.stem, typ_path.parent / "images", typ_path.parent]
    candidates: list[Path] = []
    for directory in directories:
        try:
            if directory.is_dir():
                candidates.extend(
                    image for image in directory.iterdir()
                    if image.is_file() and image.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                )
        except OSError:
            continue
        if candidates:
            break
    return sorted(candidates, key=lambda path: path.name.lower())


def _safe_int(value: object, typ_path: Path, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        _warn(f"series_index inválido ({value!r}) para {typ_path.name}; usando {default}")
        return default


def extract_metadata(typ_path: Path, manifest_item: dict | None = None) -> StoryMetadata:
    content = typ_path.read_text(encoding="utf-8", errors="replace")
    manifest_item = manifest_item or {}

    # Slug puro do arquivo, sem prefixo numérico
    clean_name = _NUMERIC_PREFIX_RE.sub("", typ_path.stem).replace("-", " ").strip()

    parent_slug = _NUMERIC_PREFIX_RE.sub("", typ_path.parent.name)
    parent_name = readable_set_name(parent_slug) if parent_slug else typ_path.parent.name
    number_match = re.match(r"^(\d+)", typ_path.stem)

    title = manifest_item.get("title") or _title_from_conf(content) or clean_name
    set_name = manifest_item.get("set_name") or _string_value(content, "set_name") or parent_name
    author = manifest_item.get("author") or _string_value(content, "author") or "Wizards of the Coast"
    story_date = manifest_item.get("date") or _date_from_content(content)
    if not story_date:
        story_date = datetime.now(timezone.utc).date().isoformat()
    series_index = _safe_int(
        manifest_item.get("series_index") or (number_match.group(1) if number_match else 1),
        typ_path,
    )
    cover = manifest_item.get("cover_image")
    cover_candidates = _cover_candidates(typ_path)
    cover_path = Path(cover) if cover else (cover_candidates[0] if cover_candidates else None)

    return StoryMetadata(
        title=title,
        set_name=set_name or "Magic: The Gathering Stories",
        author=author,
        date=story_date,
        series=manifest_item.get("series") or set_name,
        series_index=series_index,
        source_file=typ_path,
        cover_image=cover_path,
        story_id=manifest_item.get("id"),
    )

def omnibus_metadata(first: StoryMetadata, source_file: Path) -> StoryMetadata:
    """Metadados do EPUB omnibus de um set, a partir do metadado do primeiro episódio."""
    return StoryMetadata(
        title=f"{first.set_name} (Complete Stories)",
        set_name=first.set_name,
        author="Wizards of the Coast",
        date=first.date,
        series=first.series,
        series_index=1,
        source_file=source_file,
        cover_image=first.cover_image,
    )


def collection_metadata(
    set_name: str,
    items: list[StoryMetadata],
    sources: list[Path],
    series_index: int,
    first_episode: StoryMetadata | None = None,
) -> StoryMetadata:
    """Metadados de um livro da coleção Magic Stories (autores únicos, capa e data do 1º episódio)."""
    authors: list[str] = []
    for item in items:
        if item.author not in authors:
            authors.append(item.author)
    if first_episode is not None:
        cover_image = first_episode.cover_image
    else:
        cover_image = next((m.cover_image for m in items if m.cover_image), None)
    return StoryMetadata(
        title=set_name,
        set_name=set_name,
        author=", ".join(authors),
        date=first_episode.date if first_episode else "",
        series="Magic Stories Collection",
        series_index=series_index,
        source_file=sources[0],
        cover_image=cover_image,
    )
