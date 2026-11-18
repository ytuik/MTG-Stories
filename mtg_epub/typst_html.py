"""Compila um capítulo .typ para HTML usando o compilador Typst real.
Remove dependências inacessíveis e blocos de configuração corrompidos.
"""
from __future__ import annotations

import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import typst
from bs4 import BeautifulSoup

# Sufixo dos arquivos temporários criados ao lado do .typ durante a compilação
TMP_TYP_SUFFIX = ".tmp.typ"


@dataclass
class CompiledChapter:
    title: str | None
    authors: str | None
    body_html: str  # conteúdo interno do <body>
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False  # True quando caiu no fallback sem imagens

def _matching_close_paren(text: str, opening: int) -> int:
    """Encontra o fechamento seguro de estruturas aninhadas, ignorando strings.

    Dentro de um bloco de conteúdo `[...]` aspas são texto comum (`[5" tall]`),
    então só abrem string fora de colchetes.
    """
    depth = 0
    brackets = 0
    in_string = False
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if in_string:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == '"': in_string = False
            continue
        if brackets:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == "[": brackets += 1
            elif char == "]": brackets -= 1
            continue
        if char == '"': in_string = True
        elif char == "[": brackets = 1
        elif char == "(": depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0: return index
    return -1

def _apply_typst_polyfills(content: str) -> str:
    # 1. Removedor Inteligente de Imports (múltiplas linhas)
    while True:
        match = re.search(r'#import\s+"@local/(?:mtgstory|mtgguide)[^"]+"', content)
        if not match:
            break
        start = match.start()
        cursor = match.end()
        depth = 0
        while cursor < len(content):
            char = content[cursor]
            if char == '(': depth += 1
            elif char == ')': depth -= 1
            elif char == '\n' and depth == 0: break
            cursor += 1
        content = content[:start] + content[cursor:]

    # 2. Remoção Total do bloco #show: conf para blindar contra syntax errors dos .typ originais
    while True:
        match = re.search(r'#show:\s*(?:\w+\s*=>\s*)?conf(?:.*?)\s*\(', content)
        if not match:
            break
        start = match.start()
        opening = content.find("(", start)
        closing = _matching_close_paren(content, opening)
        if closing < 0:
            break
        content = content[:start] + content[closing + 1:]

    # 3. Polyfills blindados contra argumentos nomeados
    polyfill = """
// --- START POLYFILL ---
#let letter_block(..args) = block[#args.pos().join()]
#let epigraph(..args) = block[#args.pos().join()]
#let magic_quote(..args) = block[#args.pos().join()]
// --- END POLYFILL ---
"""
    return polyfill + "\n" + content

def _resolve_image_path(raw_path: str, source: Path) -> str:
    from .slugs import slugify
    clean = raw_path.strip("\"'").replace('\\"', "'").replace('"', "'")
    
    if (source.parent / clean).exists():
        return clean
    
    variant1 = clean.replace("'", "")
    if (source.parent / variant1).exists():
        return variant1

    slug_parts = "/".join(slugify(part) for part in clean.split("/"))
    if (source.parent / slug_parts).exists():
        return slug_parts

    filename = Path(clean).name
    try:
        for sub in source.parent.iterdir():
            if sub.is_dir() and (sub / filename).exists():
                return f"{sub.name}/{filename}"
    except OSError:
        pass
            
    return clean


_IMAGE_CALL_RE = re.compile(
    r"""(image\s*\(\s*)(["'].*?\.(?:jpg|jpeg|png|webp|gif)["']?)(\s*(?:,|\)))""",
    re.IGNORECASE,
)


def _fix_image_calls(content: str, source: Path) -> str:
    def fix_img(m):
        prefix = m.group(1)
        raw_inside = m.group(2)
        suffix = m.group(3)
        resolved = _resolve_image_path(raw_inside, source)
        return f'{prefix}"{resolved}"{suffix}'

    return _IMAGE_CALL_RE.sub(fix_img, content)


def referenced_images(source: Path) -> list[Path]:
    """Imagens referenciadas pelo .typ, com a mesma resolução usada na compilação.

    Pode incluir caminhos inexistentes (imagem ausente)."""
    content = source.read_text(encoding="utf-8", errors="replace")
    found: dict[Path, None] = {}
    for match in _IMAGE_CALL_RE.finditer(content):
        found[source.parent / _resolve_image_path(match.group(2), source)] = None
    return list(found)


def _matching_close_bracket(text: str, opening: int) -> int:
    """Fecha um bloco de conteúdo `[...]` do Typst, aceitando colchetes aninhados e escapados."""
    depth = 0
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _caption_of(call_inner: str) -> str | None:
    """Extrai o texto de `caption: [...]` de dentro dos argumentos de #figure(...)."""
    match = re.search(r"caption\s*:\s*\[", call_inner)
    if not match:
        return None
    opening = match.end() - 1
    closing = _matching_close_bracket(call_inner, opening)
    return call_inner[opening + 1:closing] if closing > 0 else None


def _strip_broken_images(txt: str) -> str:
    """Troca #figure(image(...), caption: [...]) pela legenda em itálico e remove #image(...).

    Usa _matching_close_paren para achar o fim das chamadas, então parênteses
    aninhados (`image("a(b).png", width: calc.min(1, 2))`) não quebram a troca.
    """
    out: list[str] = []
    cursor = 0
    figure_re = re.compile(r"#figure\s*\(")
    while True:
        match = figure_re.search(txt, cursor)
        if not match:
            break
        opening = match.end() - 1
        closing = _matching_close_paren(txt, opening)
        if closing < 0:
            break
        inner = txt[opening + 1:closing]
        if re.match(r"\s*image\s*\(", inner):
            caption = _caption_of(inner)
            out.append(txt[cursor:match.start()])
            if caption:
                out.append(f"\n// [Imagem omitida]\n#align(center)[#emph[{caption.strip()}]]\n")
            cursor = closing + 1
        else:
            out.append(txt[cursor:closing + 1])
            cursor = closing + 1
    out.append(txt[cursor:])
    txt = "".join(out)

    out = []
    cursor = 0
    image_re = re.compile(r"#image\s*\(")
    while True:
        match = image_re.search(txt, cursor)
        if not match:
            break
        closing = _matching_close_paren(txt, match.end() - 1)
        if closing < 0:
            break
        out.append(txt[cursor:match.start()])
        cursor = closing + 1
    out.append(txt[cursor:])
    return "".join(out)


def _apply_structural_fixes(soup: BeautifulSoup) -> None:
    """POV em negrito vira <h2>; separadores SVG (polyline dentro de div) viram <hr>."""
    for p_tag in soup.find_all("p"):
        children = p_tag.contents
        if len(children) == 1 and children[0].name in ["strong", "b"]:
            h2_tag = soup.new_tag("h2")
            h2_tag.string = children[0].get_text(strip=True)
            p_tag.replace_with(h2_tag)

    for polyline in soup.find_all("polyline"):
        if polyline.parent and polyline.parent.name == "svg":
            svg_container = polyline.parent
            if svg_container.parent and svg_container.parent.name == "div":
                hr_tag = soup.new_tag("hr")
                svg_container.parent.replace_with(hr_tag)


def compile_chapter_html(source: Path, root: Path) -> CompiledChapter:
    """Compila um arquivo .typ e manipula a AST do HTML para aplicar regras de estruturação."""

    content = source.read_text(encoding="utf-8", errors="replace")
    clean_content = _apply_typst_polyfills(content)
    clean_content = _fix_image_calls(clean_content, source)

    # O arquivo temporário precisa ficar ao lado do original: os caminhos de imagem
    # e imports do Typst são relativos ao arquivo compilado. Nome único por chamada
    # para não colidir entre workers; sempre removido no finally.
    tmp_path = source.with_name(f"{source.name}.{uuid.uuid4().hex[:8]}{TMP_TYP_SUFFIX}")
    warnings: list[str] = []
    degraded = False

    try:
        tmp_path.write_text(clean_content, encoding="utf-8")
        try:
            raw_html = typst.compile(str(tmp_path), format="html", root=str(root))
        except typst.TypstError as err:
            err_msg = str(err).lower()
            if not any(keyword in err_msg for keyword in ["image", "png", "jpeg", "decode", "file not found", "cannot find"]):
                raise
            message = (
                f"{source.name}: erro de imagem ao compilar; capítulo gerado sem imagens "
                f"(erro original: {str(err).strip()})"
            )
            warnings.append(message)
            degraded = True
            print(f"[typst_html][Aviso] {message}", file=sys.stderr)
            tmp_path.write_text(_strip_broken_images(clean_content), encoding="utf-8")
            raw_html = typst.compile(str(tmp_path), format="html", root=str(root))
    finally:
        tmp_path.unlink(missing_ok=True)

    soup = BeautifulSoup(raw_html, "lxml")
    _apply_structural_fixes(soup)

    title_tag = soup.find("title")
    authors_tag = soup.find("meta", attrs={"name": "authors"})
    body = soup.find("body")

    if body is None:
        raise ValueError(f"HTML sem <body>: {source}")

    return CompiledChapter(
        title=title_tag.get_text() if title_tag else None,
        authors=authors_tag["content"] if authors_tag else None,
        body_html=body.decode_contents(),
        warnings=warnings,
        degraded=degraded,
    )
