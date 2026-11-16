"""Slugify de nomes do acervo (função pura, sem dependências do pacote)."""
from __future__ import annotations

import re
from pathlib import Path

# Extensão plausível de arquivo: ponto + 1 a 5 caracteres alfanuméricos, sem espaços
_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{1,5}")


def slugify(name: str) -> str:
    """
    Converte para [a-z0-9]+ separado por '-', sem '-' nas pontas, usando python-slugify.

    IMPORTANTE: se 'name' é um arquivo com extensão, preserva a extensão.
      '058 - Duskmourn- House of Horror.typ' -> '058-duskmourn-house-of-horror.typ'
      '01.jpg'                                -> '01.jpg'
      '058 - Duskmourn- House of Horror'     -> '058-duskmourn-house-of-horror'  (pasta)
    """
    from slugify import slugify as py_slugify
    p = Path(name)
    stem = p.stem
    suffix = p.suffix  # inclui o '.'; vazio se não houver extensão
    # Só é extensão se parecer uma (ex.: '.typ', '.jpg'). Em 'Jace vs. Vraska' o
    # trecho '. Vraska' faz parte do nome e deve virar separador, não sufixo.
    if suffix and not _EXTENSION_RE.fullmatch(suffix):
        stem, suffix = name, ""

    clean_stem = stem.replace("'", "").replace("’", "").replace('"', "")
    slug_stem = py_slugify(clean_stem, separator="-", lowercase=True)
    if not slug_stem:
        # Fallback: nome original em minúsculas (evita slug vazio)
        slug_stem = stem.casefold().strip()

    return f"{slug_stem}{suffix.lower()}" if suffix else slug_stem
