"""Compressor e otimizador de imagens com Pillow para e-readers."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps

from . import REPO_ROOT

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
DEFAULT_CACHE_PATH = REPO_ROOT / ".image-compress-cache.json"
CACHE_SAVE_EVERY = 25  # imagens processadas entre gravações parciais do cache
DEFAULT_MAX_DIM = 1400
DEFAULT_QUALITY = 80


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cache_key(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_cache(cache_path: Path) -> dict[str, dict]:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache_path: Path, cache: dict[str, dict]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(cache_path.name + ".tmp")
        tmp_path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, cache_path)
    except OSError as exc:
        print(f"[Compressor][Aviso] Não foi possível gravar o cache {cache_path}: {exc}", file=sys.stderr)


def _cache_entry(path: Path, max_dim: int, quality: int) -> dict:
    return {"sha256": _file_sha256(path), "max_dim": max_dim, "quality": quality}


def _is_cached(cache: dict, key: str, path: Path, max_dim: int, quality: int) -> bool:
    """Entradas no formato antigo (string) contam como inválidas: reprocessa."""
    entry = cache.get(key)
    if not isinstance(entry, dict):
        return False
    return entry == _cache_entry(path, max_dim, quality)


def record_compressed(
    path: Path,
    max_dim: int = DEFAULT_MAX_DIM,
    quality: int = DEFAULT_QUALITY,
    cache_path: Path | None = None,
) -> None:
    """Registra no cache o hash de um arquivo já comprimido, para não recomprimir depois."""
    path = Path(path)
    cache_path = Path(cache_path) if cache_path is not None else DEFAULT_CACHE_PATH
    cache = _load_cache(cache_path)
    cache[_cache_key(path, cache_path.parent)] = _cache_entry(path, max_dim, quality)
    _save_cache(cache_path, cache)


def _has_meaningful_alpha(image: Image.Image) -> bool:
    """Verifica se uma imagem RGBA/LA possui transparência perceptível."""
    if image.mode not in ("RGBA", "LA"):
        return False
    alpha = image.getchannel("A")
    extrema = alpha.getextrema()
    # Se o valor mínimo de alfa é 255, a imagem é totalmente opaca
    return extrema[0] < 255


_ORIGINAL_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
}


def compress_image_bytes(
    data: bytes,
    max_dim: int = DEFAULT_MAX_DIM,
    quality: int = DEFAULT_QUALITY,
) -> tuple[bytes, str, str]:
    """Versão pura de `_compress`: recebe bytes e devolve (bytes, extensão, mime).

    Reduz para no máximo `max_dim` no maior lado. Mantém PNG quando há alpha
    relevante (`_has_meaningful_alpha`); o resto vira JPEG. Levanta exceção se a
    imagem não puder ser decodificada.
    """
    with Image.open(io.BytesIO(data)) as opened:
        original_format = (opened.format or "").upper()
        img = ImageOps.exif_transpose(opened)
        img.load()
        if img.mode in ("P", "PA") and "transparency" in img.info:
            img = img.convert("RGBA")
        elif img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        resized = img.width > max_dim or img.height > max_dim
        if resized:
            img = img.copy()
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        if _has_meaningful_alpha(img):
            img.save(buffer, format="PNG", optimize=True)
            result = (buffer.getvalue(), "png", "image/png")
        else:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=False)
            result = (buffer.getvalue(), "jpg", "image/jpeg")
        # Sem resize e maior que o original: mantém os bytes originais.
        original = _ORIGINAL_FORMATS.get(original_format)
        if not resized and original is not None and len(result[0]) > len(data):
            return data, original[0], original[1]
        return result


def compress_image(
    input_path: Path,
    output_path: Path | None = None,
    max_dim: int = DEFAULT_MAX_DIM,
    quality: int = DEFAULT_QUALITY,
) -> bool:
    """
    Comprime e redimensiona uma imagem mantendo proporção e qualidade para e-readers.

    - Se output_path for None, sobrescreve input_path de forma atômica.
    - Reduz dimensões se exceder max_dim (LANCZOS).
    - Converte WebP e imagens sem transparência para JPEG otimizado.
    - Remove metadados EXIF pesados/desnecessários.
    """
    return _compress(input_path, output_path, max_dim, quality)[0]


def _compress(
    input_path: Path,
    output_path: Path | None,
    max_dim: int,
    quality: int,
) -> tuple[bool, bool]:
    """Devolve (alterou, ok). ok=False indica falha (não deve ir para o cache)."""
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path is not None else input_path

    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False, True

    try:
        with Image.open(input_path) as img:
            # Corrige rotação baseada em EXIF antes de manipular
            img = ImageOps.exif_transpose(img)

            # Redimensiona mantendo proporção apenas se ultrapassar max_dim
            orig_w, orig_h = img.size
            if orig_w > max_dim or orig_h > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            ext = output_path.suffix.lower()
            buffer = io.BytesIO()

            if ext == ".png":
                # Salva estritamente como PNG para garantir assinatura mágica de PNG válida
                if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                    img = img.convert("RGBA" if _has_meaningful_alpha(img) else "RGB")
                img.save(buffer, format="PNG", optimize=True)
            elif ext == ".webp":
                img.save(buffer, format="WEBP", quality=quality, method=6)
            else:
                # JPEG
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(
                    buffer,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=False,
                )

            compressed_bytes = buffer.getvalue()

            # Só sobrescreve se o arquivo compactado for menor ou se mudou dimensões
            orig_size = input_path.stat().st_size if input_path.exists() else 0
            if orig_size == 0 or len(compressed_bytes) < orig_size or (orig_w, orig_h) != img.size:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                temp_output = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
                temp_output.write_bytes(compressed_bytes)
                temp_output.replace(output_path)
                return True, True

            return False, True
    except Exception as exc:
        print(f"[Compressor][Aviso] Falha ao comprimir {input_path.name}: {exc}", file=sys.stderr)
        return False, False


def batch_compress_directories(
    directories: Sequence[Path],
    max_dim: int = DEFAULT_MAX_DIM,
    quality: int = DEFAULT_QUALITY,
    verbose: bool = True,
    cache_path: Path | None = None,
) -> dict:
    """
    Comprime em lote todas as imagens nas pastas especificadas.

    Recomprimir um JPEG/WebP a cada execução acumula perda de qualidade. Por isso
    guardamos em `cache_path` (padrão: .image-compress-cache.json na raiz do repo)
    o sha256 de cada arquivo após o processamento com sucesso, junto de max_dim e
    quality; se hash e parâmetros baterem, pula. Falhas não entram no cache.
    """
    cache_path = Path(cache_path) if cache_path is not None else DEFAULT_CACHE_PATH
    cache_base = cache_path.parent
    cache = _load_cache(cache_path)
    all_images: list[Path] = []
    for d in directories:
        d = Path(d)
        if not d.exists():
            continue
        for ext in SUPPORTED_EXTENSIONS:
            all_images.extend(d.rglob(f"*{ext}"))
            all_images.extend(d.rglob(f"*{ext.upper()}"))

    # Deduplica
    unique_images = sorted(set(all_images))
    total_files = len(unique_images)
    if total_files == 0:
        return {"total": 0, "compressed": 0, "skipped": 0, "saved_bytes": 0}

    compressed_count = 0
    skipped_count = 0
    total_saved_bytes = 0

    iterator = tqdm(unique_images, desc="Comprimindo imagens", unit="img") if (tqdm and verbose) else unique_images

    processed = 0
    try:
        for img_path in iterator:
            key = _cache_key(img_path, cache_base)
            if _is_cached(cache, key, img_path, max_dim, quality):
                skipped_count += 1
                continue
            orig_size = img_path.stat().st_size
            changed, ok = _compress(img_path, None, max_dim, quality)
            if changed:
                compressed_count += 1
                new_size = img_path.stat().st_size
                total_saved_bytes += max(0, orig_size - new_size)
            if ok:
                cache[key] = _cache_entry(img_path, max_dim, quality)
            processed += 1
            if processed % CACHE_SAVE_EVERY == 0:
                _save_cache(cache_path, cache)
    finally:  # Ctrl+C ou exceção não perdem o progresso
        try:
            _save_cache(cache_path, cache)
        except OSError as error:
            print(f"[Compressor][Aviso] não foi possível gravar o cache {cache_path}: {error}", file=sys.stderr)

    if verbose:
        saved_mb = total_saved_bytes / (1024 * 1024)
        print(f"[Compressor] Concluído: {compressed_count}/{total_files} imagens otimizadas ({skipped_count} já processadas). Economia: {saved_mb:.2f} MB")

    return {
        "total": total_files,
        "compressed": compressed_count,
        "skipped": skipped_count,
        "saved_bytes": total_saved_bytes,
    }


if __name__ == "__main__":
    dirs = [Path(arg) for arg in sys.argv[1:]] if len(sys.argv) > 1 else [Path("stories"), Path("planeswalkers_guides"), Path("card_lore")]
    batch_compress_directories(dirs)
