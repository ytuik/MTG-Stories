#!/usr/bin/env python3
"""
MTG Stories Scraper & Typst Generator (Refactored)
==================================================
Extrator resiliente de contos oficiais de Magic: The Gathering.
Utiliza BeautifulSoup4 para navegação na DOM, Requests com Connection Pooling,
e Tenacity para tolerância a falhas de rede (retries automáticos).
"""

import os
import sys
import re
import json
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, NavigableString
from tenacity import retry, stop_after_attempt, wait_exponential
from dateutil import parser as date_parser

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7',
}

# Resolução dinâmica de caminhos (Remove o Path Hardcoded)
ROOT_DIR = Path(__file__).resolve().parent
STORIES_DIR = ROOT_DIR / "stories"
GUIDES_DIR = ROOT_DIR / "planeswalkers_guides"
MANIFEST_FILE = ROOT_DIR / "scraped_manifest.json"
MISSING_MD_FILE = ROOT_DIR / "MISSING_STORIES.md"

# Intervalo (segundos) entre requisições, para não sobrecarregar o servidor
REQUEST_DELAY_SECONDS = 1.0

# ==========================================
# CATÁLOGO E METADADOS
# ==========================================
CATALOG_MISSING = [
    # --- REALITY FRACTURE (SET 064) ---
    {
        "id": "rf-episode-01",
        "type": "story",
        "title": "Reality Fracture | Episode 1: Tam, Alive",
        "clean_title": "Episode 1: Tam, Alive",
        "set_name": "Reality Fracture",
        "set_folder": "064 - Reality Fracture",
        "story_number": "001",
        "author": "Alison Lührs",
        "date": "2026-08-31",
        "url": "https://magic.wizards.com/en/news/magic-story/reality-fracture-episode-1-tam-alive",
        "category": "webfiction"
    },
    {
        "id": "rf-episode-02",
        "type": "story",
        "title": "Reality Fracture | Episode 2: Purge Yourself of Doubt",
        "clean_title": "Episode 2: Purge Yourself of Doubt",
        "set_name": "Reality Fracture",
        "set_folder": "064 - Reality Fracture",
        "story_number": "002",
        "author": "Alison Lührs",
        "date": "2026-09-01",
        "url": "https://magic.wizards.com/en/news/magic-story/reality-fracture-episode-2-purge-yourself-of-doubt",
        "category": "webfiction"
    },
    {
        "id": "rf-episode-10",
        "type": "story",
        "title": "Reality Fracture | Episode 10: Happy Birthday",
        "clean_title": "Episode 10: Happy Birthday",
        "set_name": "Reality Fracture",
        "set_folder": "064 - Reality Fracture",
        "story_number": "010",
        "author": "Alison Lührs",
        "date": "2026-09-11",
        "url": "https://magic.wizards.com/en/news/magic-story/reality-fracture-episode-10-happy-birthday",
        "category": "webfiction"
    }
    # Encurtado para legibilidade. Mantenha seu catálogo completo aqui.
]

UNSCRAPABLE_MEDIA = [
    {
        "title": "Strixhaven: Omens of Chaos",
        "format": "Romance Comercial / Livro",
        "author": "Seanan McGuire",
        "publisher": "Random House Worlds",
        "date": "2026-04-07",
        "reason": "Obra literária comercial protegida por direitos autorais.",
        "url": "https://mtglore.com/story/strixhaven-omens-of-chaos/"
    }
]

# Configura uma sessão HTTP para reuso de conexões (Connection Pooling)
http_session = requests.Session()
http_session.headers.update(HEADERS)

_INVALID_FILENAME_CHARS = re.compile(r'[<>"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Nome compatível com Windows no padrão do acervo: ':' vira '-', mantém
    espaços, maiúsculas, vírgulas e apóstrofos; remove os caracteres inválidos."""
    name = name.replace(":", "-")
    name = _INVALID_FILENAME_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name or "Untitled"


def story_filename(story_num: str, title: str) -> str:
    """Nome-base (sem extensão) no padrão do acervo: 'NNN_Título original'."""
    return f"{story_num}_{sanitize_filename(title)}"


def typst_string(s: str) -> str:
    """Escapa texto para uso dentro de uma string Typst "..."."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


_TYPST_MARKUP_CHARS = re.compile(r"([\\#*_@<$`\[\]~])")


def escape_typst_text(s: str) -> str:
    """Escapa caracteres de marcação Typst em texto corrido."""
    s = _TYPST_MARKUP_CHARS.sub(r"\\\1", s)
    # '//' e '/*' abrem comentários no Typst: escapa a '/' que antecede '/' ou '*'
    return _TYPST_COMMENT_SLASH.sub(r"\\/", s)


_TYPST_COMMENT_SLASH = re.compile(r"/(?=[/*])")
_PARAGRAPH_MARKER = re.compile(r"^(?:([=\-+/])|(\d+)\.)(?=\s)")


def escape_paragraph_start(text: str) -> str:
    """Escapa marcadores que, no início do parágrafo, virariam título/lista/termo."""
    match = _PARAGRAPH_MARKER.match(text)
    if not match:
        return text
    if match.group(1):
        return "\\" + text
    return f"{match.group(2)}\\." + text[match.end():]


def load_manifest() -> dict:
    if not MANIFEST_FILE.exists():
        return {"last_run": None, "scraped_items": {}, "unscrapable_media": UNSCRAPABLE_MEDIA}
    try:
        data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        data.setdefault("scraped_items", {})
        data.setdefault("unscrapable_media", UNSCRAPABLE_MEDIA)
        return data
    except (OSError, json.JSONDecodeError) as error:
        print(f"[Aviso] Manifesto inválido; um novo será criado: {error}")
        return {"last_run": None, "scraped_items": {}, "unscrapable_media": UNSCRAPABLE_MEDIA}


def save_manifest(manifest: dict) -> None:
    manifest["last_run"] = datetime.now(timezone.utc).isoformat()
    temporary = MANIFEST_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(MANIFEST_FILE)


def update_manifest(manifest: dict, result: dict) -> None:
    item_id = result.get("id")
    if not item_id:
        return
    existing = manifest.setdefault("scraped_items", {}).get(item_id)
    if result.get("status") == "skipped" and existing is not None:
        return  # um item pulado não sobrescreve o registro de uma execução anterior
    existing = existing or {}
    existing.update(result)
    manifest["scraped_items"][item_id] = existing
    save_manifest(manifest)

# ==========================================
# EXTRAÇÃO E REDE (Com Retry Automático)
# ==========================================
@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1.5, min=2, max=10))
def fetch_html(url: str) -> str:
    """Busca o HTML com tolerância a falhas e rate-limits."""
    response = http_session.get(url, timeout=15)
    response.raise_for_status()
    return response.text

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=5))
def download_image(url: str, dest_path: Path) -> bool:
    """Baixa imagem direto para o disco resolvendo URLs relativas."""
    if url.startswith("//"):
        url = "https:" + url
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    time.sleep(REQUEST_DELAY_SECONDS)

    response = http_session.get(url, stream=True, timeout=20)
    response.raise_for_status()
    
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    try:
        from mtg_epub.image_compressor import (
            DEFAULT_MAX_DIM, DEFAULT_QUALITY, _compress, record_compressed,
        )
        _changed, ok = _compress(dest_path, None, DEFAULT_MAX_DIM, DEFAULT_QUALITY)
        if ok:
            record_compressed(dest_path)
    except Exception as e:
        print(f"[Aviso] Otimização de imagem ignorada para {dest_path.name}: {e}")
    return True

def resolve_wizards_url_from_mtglore(mtglore_url: str) -> str:
    try:
        html = fetch_html(mtglore_url)
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            if '/news/magic-story/' in a['href'] or '/news/feature/' in a['href']:
                return a['href']
    except Exception as e:
        print(f"[Aviso] Falha ao resolver URL Wizards via MTGLore ({mtglore_url}): {e}")
    return mtglore_url

def parse_date_string(date_str: str) -> tuple[int, int, int]:
    """Parseamento inteligente de datas usando dateutil."""
    try:
        dt = date_parser.parse(date_str)
        return dt.day, dt.month, dt.year
    except Exception:
        return 1, 1, 2026

# ==========================================
# PROCESSAMENTO DE DOM E TYPST
# ==========================================
def convert_bs4_to_typst(element) -> str:
    """Converte tags HTML para sintaxe Typst manipulando a árvore do BS4 diretamente."""
    # Remove lixo invisível
    for tag in element.find_all(['iframe', 'script', 'style']):
        tag.decompose()
        
    # Escapa a marcação Typst apenas nos nós de texto originais; a marcação
    # intencional (links/ênfase) é inserida depois.
    for node in list(element.find_all(string=True)):
        if type(node) is NavigableString:
            flat = re.sub(r"[\r\n]+", " ", str(node))
            node.replace_with(NavigableString(escape_typst_text(flat)))

    # Converte Links
    for a in element.find_all('a'):
        href = typst_string(a.get('href', ''))
        text = a.get_text(strip=True)
        if text:
            a.replace_with(f'#link("{href}")[{text}]')
        else:
            a.decompose()
            
    # Converte Negrito e Itálico
    for b in element.find_all(['b', 'strong']):
        b.replace_with(f'*{b.get_text(strip=True)}*')
    for i in element.find_all(['i', 'em']):
        i.replace_with(f'_{i.get_text(strip=True)}_')
        
    text = element.get_text()
    return escape_paragraph_start(re.sub(r'[ \t]+', ' ', text).strip())

def parse_article_html(html: str, default_metadata: dict = None) -> dict:
    meta = default_metadata.copy() if default_metadata else {}
    soup = BeautifulSoup(html, 'html.parser')
    
    # Extração de Título
    og_title = soup.find('meta', property='og:title')
    if og_title and not meta.get("clean_title"):
        raw_title = og_title.get('content', '')
        meta["clean_title"] = re.sub(r'^.*\|\s*', '', raw_title).strip()
    
    # Extração de Data
    time_tag = soup.find('time')
    if time_tag and not meta.get("date"):
        meta["date"] = time_tag.get_text(strip=True)
        
    # Extração de Autor
    author_tag = soup.find(class_=re.compile(r'author', re.IGNORECASE)) or soup.find(string=re.compile(r'By\s+', re.IGNORECASE))
    if author_tag and not meta.get("author"):
        meta["author"] = re.sub(r'^By\s+', '', author_tag.get_text(strip=True), flags=re.IGNORECASE)
    
    # Hero Image
    og_img = soup.find('meta', property='og:image')
    hero_image_url = og_img.get('content') if og_img else None

    # Corpo do Artigo
    article = soup.find(class_='article-body') or soup.find('article') or soup
    elements = []
    
    for tag in article.find_all(['p', 'h2', 'h3', 'hr', 'figure']):
        if tag.name == 'p':
            img = tag.find('img')
            if img:
                caption_match = re.search(r'(Art by:?[^<]+|Illustrated by[^<]+)', tag.get_text(), re.IGNORECASE)
                elements.append({
                    "type": "image",
                    "src": img.get('src'),
                    "caption": escape_typst_text(caption_match.group(1).strip()) if caption_match else ""
                })
            else:
                p_text = convert_bs4_to_typst(tag)
                if p_text:
                    if p_text.lower().startswith("art by") or p_text.lower().startswith("illustration by"):
                        if elements and elements[-1]["type"] == "image" and not elements[-1]["caption"]:
                            elements[-1]["caption"] = p_text
                            continue
                    elements.append({"type": "paragraph", "text": p_text})
        elif tag.name == 'hr':
            elements.append({"type": "divider"})
        elif tag.name == 'h2':
            elements.append({"type": "heading_1", "text": convert_bs4_to_typst(tag)})
        elif tag.name == 'h3':
            elements.append({"type": "heading_2", "text": convert_bs4_to_typst(tag)})
        elif tag.name == 'figure':
            img = tag.find('img')
            figcaption = tag.find('figcaption')
            if img:
                elements.append({
                    "type": "image",
                    "src": img.get('src'),
                    "caption": convert_bs4_to_typst(figcaption) if figcaption else ""
                })

    return {
        "metadata": meta,
        "hero_image": hero_image_url,
        "elements": elements
    }

# ==========================================
# ESCRITA DE ARQUIVOS (Mantida a estrutura original)
# ==========================================
def generate_story_typst(parsed: dict, output_typ_path: Path, image_dir_rel: str) -> None:
    meta = parsed["metadata"]
    title = typst_string(meta.get("clean_title", "Untitled Story"))
    set_name = typst_string(meta.get("set_name", "Unknown Set"))
    author = typst_string(meta.get("author", "Unknown Author"))
    set_name_text = escape_typst_text(meta.get("set_name", "Unknown Set"))
    day, month, year = parse_date_string(meta.get("date", "2026-09-01"))
    
    typ_lines = [
        '#import "@local/mtgstory:0.2.0": conf',
        '#show: doc => conf(',
        f'    "{title}",',
        f'    set_name: "{set_name}",',
        f'    story_date: datetime(day: {day:02d}, month: {month:02d}, year: {year}),',
        f'    author: "{author}",',
        '    doc',
        ')',
        ''
    ]
    
    img_counter = 1
    image_folder_abs = output_typ_path.parent / image_dir_rel
    
    has_inline_images = any(el["type"] == "image" for el in parsed["elements"])
    if not has_inline_images and parsed.get("hero_image"):
        img_name = f"{img_counter:02d}.jpg"
        try:
            download_image(parsed["hero_image"], image_folder_abs / img_name)
            rel_img = f"{image_dir_rel}/{img_name}"
            typ_lines.append(f'#figure(image("{typst_string(rel_img)}", width: 100%), caption: [Art from {set_name_text}], supplement: none, numbering: none)\n')
            img_counter += 1
        except Exception as e:
            print(f"[Erro] Capa Hero ignorada: {e}")

    for el in parsed["elements"]:
        el_type = el["type"]
        if el_type == "paragraph":
            typ_lines.append(el["text"] + "\n")
        elif el_type == "divider":
            typ_lines.extend([
                '#v(0.35em)',
                '#line(length: 100%, stroke: rgb(90%, 90%, 90%))',
                '#v(0.35em)\n'
            ])
        elif el_type == "heading_1":
            typ_lines.append(f'= {el["text"]}\n')
        elif el_type == "heading_2":
            typ_lines.append(f'== {el["text"]}\n')
        elif el_type == "image":
            img_name = f"{img_counter:02d}.jpg"
            try:
                download_image(el["src"], image_folder_abs / img_name)
                rel_img = f"{image_dir_rel}/{img_name}"
                cap = el.get("caption", "").strip()
                cap_code = f'caption: [{cap}]' if cap else 'caption: none'
                typ_lines.append(f'#figure(image("{typst_string(rel_img)}", width: 100%), {cap_code}, supplement: none, numbering: none)\n')
                img_counter += 1
            except Exception as e:
                print(f"[Aviso] Falha ao baixar imagem do corpo ({el['src']}): {e}")

    output_typ_path.parent.mkdir(parents=True, exist_ok=True)
    output_typ_path.write_text("\n".join(typ_lines), encoding="utf-8")
    print(f"[OK] História gerada: {output_typ_path.name}")

def _target_path(item: dict, title: str) -> Path:
    set_folder = sanitize_filename(item.get("set_folder", f"Unknown - {item.get('set_name', 'Unknown')}"))
    story_num = item.get("story_number", "001")
    return STORIES_DIR / set_folder / f"{story_filename(story_num, title)}.typ"


def _manifest_path(target_typ: Path) -> str:
    try:
        return target_typ.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return target_typ.as_posix()


def _skipped_result(item_id: str, target_typ: Path) -> dict:
    print(f"[Pulado] Já existe: {target_typ.name} (use --force para sobrescrever)")
    return {
        "id": item_id,
        "status": "skipped",
        "file_name": target_typ.name,
        "output_file": _manifest_path(target_typ),
    }


def scrape_single_item(item: dict, force: bool = False) -> dict:
    item_id = item.get("id", sanitize_filename(item.get("title", "custom")))
    print(f"\n--- Processando: {item.get('title', item_id)} ---")

    # Idempotência: se o título já é conhecido pelo catálogo, evita até a requisição
    if not force and item.get("clean_title"):
        known_target = _target_path(item, item["clean_title"])
        if known_target.exists():
            return _skipped_result(item_id, known_target)

    url = item.get("url")
    fetched_from = url
    try:
        print(f"Buscando URL: {url}")
        time.sleep(REQUEST_DELAY_SECONDS)
        html_content = fetch_html(url)
    except Exception as e:
        print(f"[Aviso] Falha primária: {e}")
        if item.get("mtglore_url"):
            resolved_url = resolve_wizards_url_from_mtglore(item["mtglore_url"])
            try:
                time.sleep(REQUEST_DELAY_SECONDS)
                html_content = fetch_html(resolved_url)
                fetched_from = resolved_url
            except Exception as e2:
                print(f"[Erro] Falha em URL resolvida: {e2}")
                return {"id": item_id, "status": "failed", "error": str(e2), "source_url": resolved_url}
        else:
            return {"id": item_id, "status": "failed", "error": str(e), "source_url": url}

    parsed = parse_article_html(html_content, default_metadata=item)

    title = parsed["metadata"].get("clean_title")
    if not title:
        return {"id": item_id, "status": "failed", "error": "Título não encontrado no HTML", "source_url": fetched_from}
    if not any(el["type"] in ("paragraph", "image") for el in parsed["elements"]):
        return {"id": item_id, "status": "failed", "error": "Corpo do artigo vazio após o parse", "source_url": fetched_from}

    target_typ = _target_path(item, title)
    if target_typ.exists() and not force:
        return _skipped_result(item_id, target_typ)

    generate_story_typst(parsed, target_typ, target_typ.stem)

    return {
        "id": item_id,
        "title": title,
        "author": parsed["metadata"].get("author"),
        "date": parsed["metadata"].get("date"),
        "set_name": parsed["metadata"].get("set_name"),
        "status": "scraped",
        "file_name": target_typ.name,
        "output_file": _manifest_path(target_typ),
        "source_url": fetched_from,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }

# ==========================================
# REBUILD (PDF + EPUB) DEPOIS DO SCRAPE
# ==========================================
def _pdf_main(argv: list[str]) -> int:
    from mtg_epub import pdf
    return pdf.main(argv)


def _epub_main(argv: list[str]) -> int:
    from mtg_epub import cli
    return cli.main(argv)


def _call_build(label: str, fn, argv: list[str], failures: list[str]) -> None:
    """Roda um build (main com argv) sem deixar a falha desfazer o resto."""
    print(f"[Rebuild] {label}")
    try:
        code = fn(argv)
    except BaseException as error:  # noqa: BLE001 - SystemExit do argparse também conta
        if isinstance(error, KeyboardInterrupt):
            raise
        failures.append(f"{label}: {type(error).__name__}: {error}")
        return
    if code:
        failures.append(f"{label}: código de saída {code}")


def _sync_set_wrappers(set_folders: list[Path]) -> None:
    """Põe os contos novos no wrapper stories/NNN_*.typ (cria o wrapper se faltar) antes do build."""
    from mtg_epub.typst_themes import sync_set_wrapper
    for folder in set_folders:
        try:
            sync_set_wrapper(folder, STORIES_DIR)
        except Exception as error:  # noqa: BLE001 - não impede o resto do rebuild
            print(f"[Rebuild] aviso: wrapper de {folder.name} não atualizado: {error}")


def rebuild_artifacts(pdf_files: list[Path], set_folders: list[Path],
                      pdfa_files: list[Path] | None = None) -> list[str]:
    """Gera PDFs (--file), o PDF do livro de cada set e os EPUBs do set (+ omnibus).

    Devolve a lista de falhas (vazia = tudo certo)."""
    failures: list[str] = []
    _sync_set_wrappers(set_folders)
    pdfa_set = {p.resolve() for p in pdfa_files or []}
    plain = [p for p in pdf_files if p.resolve() not in pdfa_set]
    archival = [p for p in pdf_files if p.resolve() in pdfa_set]
    if plain:
        _call_build(f"PDF de {len(plain)} arquivo(s)", _pdf_main,
                    ["--file", *[str(p) for p in plain]], failures)
    if archival:
        _call_build(f"PDF/A de {len(archival)} arquivo(s)", _pdf_main,
                    ["--pdfa", "--file", *[str(p) for p in archival]], failures)
    for folder in set_folders:
        number = folder.name.split(" - ", 1)[0].strip()
        if number.isdigit() and _set_book_exists(number):
            _call_build(f"PDF do livro do set {folder.name}", _pdf_main,
                        ["--set-books", "--set", f"{number}_"], failures)
        _call_build(f"EPUB do set {folder.name} (+ omnibus)", _epub_main,
                    ["--set", folder.name, "--combine"], failures)
    return failures


def _set_book_exists(number: str) -> bool:
    try:
        return any(p.name.startswith(f"{number}_") for p in STORIES_DIR.glob("*.typ"))
    except OSError:
        return False


def rebuild_after_scrape(results: list[dict]) -> list[str]:
    new_files = [ROOT_DIR / r["output_file"] for r in results
                 if r.get("status") == "scraped" and r.get("output_file")]
    new_files = [p for p in new_files if p.is_file()]
    if not new_files:
        print("[Rebuild] Nenhum conto novo; nada a reconstruir.")
        return []
    folders = list(dict.fromkeys(p.parent for p in new_files))
    return rebuild_artifacts(new_files, folders)


def rebuild_pending() -> list[str]:
    """--rebuild-only: reconstrói só o que o status acusa como ausente/desatualizado."""
    from mtg_epub import status
    report = status.collect()
    pending = status.sets_needing_rebuild(report)
    if not pending:
        print("[Rebuild] Nada pendente.")
        return []
    pdf_files = [ROOT_DIR / rel for entry in pending.values() for rel in entry["pdf"]]
    pdfa_files = [ROOT_DIR / rel for entry in pending.values() for rel in entry.get("pdfa", [])]
    set_folders = [STORIES_DIR / name for name, entry in pending.items()
                   if entry["kind"] == "set" and (entry["pdf"] or entry["epub"])]
    return rebuild_artifacts(pdf_files, set_folders, pdfa_files)


def _report_rebuild_failures(failures: list[str]) -> None:
    if failures:
        print("\n[Rebuild][Falhas]")
        for failure in failures:
            print(f"  - {failure}")


# ==========================================
# MAIN E ATUALIZAÇÃO DO MANIFESTO
# ==========================================
def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="MTG Stories Scraper")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--rf", action="store_true", help="Scrapea somente Reality Fracture")
    parser.add_argument("--force", action="store_true", help="Sobrescreve .typ já existentes")
    parser.add_argument("--rebuild", action="store_true",
                        help="Depois do scrape, gera PDF/EPUB dos contos novos e dos livros dos sets afetados")
    parser.add_argument("--rebuild-only", action="store_true",
                        help="Não raspa: reconstrói PDFs/EPUBs ausentes ou desatualizados (usa os caches)")
    args = parser.parse_args(argv)

    if args.rebuild_only:
        failures = rebuild_pending()
        _report_rebuild_failures(failures)
        sys.exit(1 if failures else 0)

    targets = [item for item in CATALOG_MISSING if not args.rf or item.get("set_name") == "Reality Fracture"]
    manifest = load_manifest()
    results = []

    for item in targets:
        if item.get("type") == "story":
            result = scrape_single_item(item, force=args.force)
            results.append(result)
            update_manifest(manifest, result)

    print(f"\n[Concluído] {len(results)} item(ns) processado(s). Manifesto atualizado: {MANIFEST_FILE}")
    rebuild_failures = rebuild_after_scrape(results) if args.rebuild else []
    _report_rebuild_failures(rebuild_failures)
    if rebuild_failures or any(result.get("status") == "failed" for result in results):
        sys.exit(1)

if __name__ == "__main__":
    main()
