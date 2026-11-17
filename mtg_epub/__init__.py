"""Conversion pipeline for MTG Stories EPUB files."""
from pathlib import Path

__version__ = "1.0.0"

# Raiz do repositório (um nível acima do pacote), independente do cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Sufixo dos arquivos gerados sem imagens (PDF e EPUB "text only").
TEXT_ONLY_SUFFIX = " - text only"

# Versão da lógica de conversão. Entra no fingerprint do cache: suba este número
# sempre que uma mudança no pipeline alterar o EPUB gerado para a mesma entrada.
PIPELINE_VERSION = "1.5.0"
