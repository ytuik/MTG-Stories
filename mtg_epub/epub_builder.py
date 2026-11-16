"""Monta um EPUB3 a partir de capítulos HTML já compilados pelo Typst real.

Substitui o antigo fluxo Typst -> pandoc: aqui o Typst já fez a conversão
para HTML de verdade, então esta camada só precisa saber empacotar HTML em
EPUB — o que o ebooklib já faz de forma madura. Este módulo não manipula o
HTML com regex; só monta a estrutura do livro (capítulos, capa, navegação).
"""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from bs4 import BeautifulSoup
from ebooklib import epub

from .image_compressor import DEFAULT_MAX_DIM, compress_image_bytes
from .typst_html import CompiledChapter, compile_chapter_html


@dataclass
class BookMetadata:
    identifier: str
    title: str
    author: str = "Wizards of the Coast"
    language: str = "en"
    cover_image_path: Path | None = None
    series: str | None = None
    series_index: int | float | None = None
    date: str | None = None


@dataclass
class ChapterSource:
    typ_path: Path
    chapter_title: str  # título mostrado no sumário/TOC


def _font_mime_type(path: Path) -> str:
    """Retorna o mime-type correto para o EpubCheck não reclamar."""
    ext = path.suffix.lower()
    if ext == ".otf": return "font/otf"
    if ext == ".ttf": return "font/ttf"
    if ext in {".woff", ".woff2"}: return f"font/{ext[1:]}"
    return "application/octet-stream"


_DATA_URI_RE = re.compile(r"^data:(image/[\w.+-]+)\s*;\s*base64,(.*)$", re.IGNORECASE | re.DOTALL)


def _process_images(
    body_html: str,
    book: epub.EpubBook,
    registry: dict[str, str],
    chapter_name: str,
    max_image_size: int,
    with_images: bool,
) -> tuple[str, list[str]]:
    """Troca `<img src="data:...">` por arquivos em images/ (comprimidos e deduplicados).

    `registry` mapeia sha1 do conteudo original -> caminho no EPUB, compartilhado por todo
    o livro. Falha na decodificacao mantem o data URI e devolve um aviso.
    Com `with_images=False`, remove as figuras e imagens."""
    if not with_images:
        soup = BeautifulSoup(body_html, "lxml")
        for img in soup.find_all("img"):
            if img.parent is None:
                continue
            (img.find_parent("figure") or img).decompose()
        return (soup.body.decode_contents() if soup.body is not None else ""), []

    if "data:image" not in body_html:
        return body_html, []

    warnings: list[str] = []
    soup = BeautifulSoup(body_html, "lxml")
    for img in soup.find_all("img"):
        match = _DATA_URI_RE.match((img.get("src") or "").strip())
        if not match:
            continue
        mime, payload = match.group(1).lower(), match.group(2)
        try:
            raw = base64.b64decode(re.sub(r"\s+", "", payload), validate=True)
            digest = hashlib.sha1(raw).hexdigest()[:16]
            path = registry.get(digest)
            if path is None:
                if mime == "image/svg+xml":
                    data, ext, out_mime = raw, "svg", "image/svg+xml"
                else:
                    data, ext, out_mime = compress_image_bytes(raw, max_dim=max_image_size)
                path = f"images/{digest}.{ext}"
                book.add_item(epub.EpubImage(
                    uid=f"img_{digest}", file_name=path, media_type=out_mime, content=data,
                ))
                registry[digest] = path
            img["src"] = path
        except Exception as error:  # noqa: BLE001
            warnings.append(f"{chapter_name}: imagem embutida nao pode ser extraida ({error}); mantido data URI")
    return soup.body.decode_contents(), warnings


def build_epub(
    metadata: BookMetadata,
    chapters: list[ChapterSource],
    root: Path,
    output_path: Path,
    css_content: str,
    fonts: list[Path] | None = None,
    max_image_size: int = DEFAULT_MAX_DIM,
    with_images: bool = True,
) -> list[str]:
    """Monta o EPUB e devolve os avisos (ex.: capítulos compilados sem imagens)."""
    book = epub.EpubBook()
    book.set_identifier(metadata.identifier)
    book.set_title(metadata.title)
    book.set_language(metadata.language)
    book.add_author(metadata.author)

    if metadata.date:
        book.add_metadata("DC", "date", metadata.date)

    if metadata.series:
        # Metadados Calibre (e-readers populares)
        book.add_metadata(None, "meta", metadata.series, {"name": "calibre:series"})
        if metadata.series_index is not None:
            book.add_metadata(None, "meta", str(metadata.series_index), {"name": "calibre:series_index"})
        # Metadados EPUB3 padrão W3C
        book.add_metadata(None, "meta", metadata.series, {"property": "belongs-to-collection", "id": "c01"})
        book.add_metadata(None, "meta", "series", {"refines": "#c01", "property": "collection-type"})
        if metadata.series_index is not None:
            book.add_metadata(None, "meta", str(metadata.series_index), {"refines": "#c01", "property": "group-position"})

    if metadata.cover_image_path is not None:
        book.set_cover(
            metadata.cover_image_path.name,
            metadata.cover_image_path.read_bytes(),
        )
    
    # 1. Adiciona o CSS (agora dinâmico com o tema do set)
    style = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=css_content)
    book.add_item(style)

    # 2. Embutir as Fontes Temáticas no EPUB
    if fonts:
        for font_path in fonts:
            font_item = epub.EpubItem(
                uid=font_path.stem,
                file_name=f"fonts/{font_path.name}",
                media_type=_font_mime_type(font_path),
                content=font_path.read_bytes()
            )
            book.add_item(font_item)

    # 3. Processar e adicionar os Capítulos
    epub_chapters = []
    build_warnings: list[str] = []
    image_registry: dict[str, str] = {}
    for index, chapter in enumerate(chapters, start=1):
        compiled: CompiledChapter = compile_chapter_html(chapter.typ_path, root)
        build_warnings.extend(compiled.warnings)
        body_html, image_warnings = _process_images(
            compiled.body_html, book, image_registry, chapter.typ_path.name, max_image_size, with_images,
        )
        build_warnings.extend(image_warnings)

        item = epub.EpubHtml(
            title=chapter.chapter_title,
            file_name=f"chap_{index:04d}.xhtml",
            lang=metadata.language,
        )
        
        item.content = (
            f"<html><body>"
            f"<h1>{xml_escape(chapter.chapter_title)}</h1>\n"
            f"{body_html}"
            f"</body></html>"
        )
        
        item.add_item(style)
        book.add_item(item)
        epub_chapters.append(item)
        
    book.toc = tuple(epub_chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *epub_chapters]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book)
    return build_warnings