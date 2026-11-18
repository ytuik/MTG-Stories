"""Generate site/public/catalog.json by reading the repository's stories/ folder."""

import json
import re
from pathlib import Path

# Path(__file__) is the path of this file; .parent.parent goes up two levels
# (scripts/ -> repository root).
ROOT = Path(__file__).resolve().parent.parent
STORIES_DIR = ROOT / "stories"
OUTPUT_FILE = ROOT / "site" / "public" / "catalog.json"

# "057 - Bloomburrow"  ->  group 1 = "057", group 2 = "Bloomburrow"
COLLECTION_PATTERN = re.compile(r"^(\d+) - (.+)$")
# "001_Episode 1- Calamity.typ"  ->  group 1 = "001", group 2 = "Episode 1- Calamity"
STORY_PATTERN = re.compile(r"^(\d+)_(.+)\.typ$")


def clean_text(text):
    """File names replace ':' with '- '. Here we undo that replacement."""
    return re.sub(r"(?<=\w)- ", ": ", text)


def make_slug(text):
    """'Dragon's Maze' -> 'dragons-maze' (for use in URLs)."""
    text = re.sub(r"['’]", "", text.lower())  # drop straight and curly apostrophes
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")



def read_stories(folder):
    stories = []
    for file in sorted(folder.glob("*.typ")):
        match = STORY_PATTERN.match(file.name)
        if not match:
            print(f"  skipped (name doesn't match pattern): {file.name}")
            continue
        stories.append(
            {
                # position in the list (1, 2, 3...), always unique
                "order": len(stories) + 1,
                "title": clean_text(match.group(2)).strip(),
                "file": file.name,
            }
        )
    return stories


def read_collections():
    collections = []
    for folder in sorted(STORIES_DIR.iterdir()):
        if not folder.is_dir():
            continue
        match = COLLECTION_PATTERN.match(folder.name)
        if not match:
            print(f"folder skipped (name doesn't match pattern): {folder.name}")
            continue
        name = clean_text(match.group(2))
        collections.append(
            {
                "order": int(match.group(1)),
                "name": name,
                "slug": make_slug(name),
                "folder": folder.name,
                "stories": read_stories(folder),
            }
        )
    return collections


def main():
    collections = read_collections()
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"collections": collections}, f, ensure_ascii=False, indent=2)
    total = sum(len(c["stories"]) for c in collections)
    print(f"{len(collections)} collections and {total} stories -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()