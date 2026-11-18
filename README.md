# MTG Stories

This is an archive of MTG stories publicly available on the Wizards of the Coast website, compiled into PDF and EPUB versions. Images are available either embedded in the documents or as separate files.

Stories are sorted into the `stories` folder by set name and in published order.

* Stories from Magic 2013 to Modern Masters 2015 are sorted with [MTG Wiki](https://mtg.wiki/page/Magic_Story).
* Stories from Magic Origins to March of the Machine: The Aftermath are sorted with [MTGLore](https://mtglore.com/chronological/).
* Stories from Wilds of Eldraine going forward are sorted with [MTG Story](https://mtgstory.com).

If you want to download all the PDFs/EPUBs or complete stories in one big file (with or without images), check the [Releases](https://github.com/ytuik/MTG-Stories/releases) page.

This repository is a fork of [polarkac/MTG-Stories](https://github.com/polarkac/MTG-Stories); credit for the original archive goes to its author.

---

## Website

A browsable catalog of all the stories lives in [`site/`](site/) and is published at https://mendevsky.github.io/MTG-Stories-GUI/.

It is a static site built with React, Vite, Tailwind CSS and React Router. The list of sets and stories is generated from the `stories/` folder by `scripts/build_catalog.py`, so new stories show up automatically after the next build.

### Run it locally

Requirements: Python 3.10+ and Node.js (LTS).

```bash
python scripts/build_catalog.py   # generates site/public/catalog.json
cd site
npm install
npm run dev
```

### Deployment

Every push to `master` runs `.github/workflows/deploy.yml`, which regenerates the catalog, builds the site and publishes it to GitHub Pages. To enable it on a repository, go to Settings → Pages and set the source to "GitHub Actions".

This is an unofficial fan project. The stories are © Wizards of the Coast.


## Python Tools (Scraper & EPUB Converter)

This repository includes Python scripts to automate downloading new stories and converting Typst files into standard EPUB3 ebooks.

### Requirements & Installation

1. **Python 3.10+**
2. **Python dependencies** (scraper and EPUB converter; the converter uses the `typst` Python package and `ebooklib`, no Pandoc needed):

```bash
pip install -r requirements.txt
```

3. **Optional - Java**, only needed to run [EpubCheck](https://github.com/w3c/epubcheck) validation (`--epubcheck`). The `tools/` directory is not versioned: download EpubCheck 5.4.0 from the [W3C EpubCheck releases](https://github.com/w3c/epubcheck/releases) and extract it into `tools/epubcheck-5.4.0/` to use `--epubcheck` without an argument, or pass the path to the jar explicitly (`--epubcheck path/to/epubcheck.jar`).

### EPUB conversion

The historical command remains supported:

```bash
python typ2epub.py --file "stories/057 - Bloomburrow/001_Episode 1- Calamity Comes to Valley.typ"
python typ2epub.py --set Bloomburrow --combine
python typ2epub.py --all --jobs 2
python typ2epub.py --set Bloomburrow --epubcheck
python typ2epub.py --validate "epubs/Bloomburrow.epub"
```

With `--no-images` every EPUB gets the ` - text only` suffix (like the PDFs), so it never overwrites the illustrated EPUB; an EPUB that fell back to no images is flagged as degraded in the cache, shown as stale by `status` and retried on the next run.

The converter writes a JSON report and an incremental cache in the output directory. Failed conversions are reported at the end and return exit code `1`. EPUBs also receive structural validation for the `mimetype`, container, OPF, navigation and absolute paths.

The implementation is split into `mtg_epub/`: metadata and manifest handling, balanced Typst sanitization, Typst-to-HTML conversion, image handling, cache and EPUB validation.

Image compression: `--compress-images` (with Pillow) shrinks the images for e-readers. **Warning:** it rewrites the images of the archive in place (under `stories/`, `planeswalkers_guides/` and `card_lore/`), not just the EPUB copies. A cache records already-compressed files so they are not recompressed on later runs. Commit or back up first if you want to keep the originals.

```bash
python typ2epub.py --set Bloomburrow --compress-images
```

Collection-specific EPUB themes and the current coverage matrix are documented in [EPUB_THEMES.md](EPUB_THEMES.md). Themes are selected automatically from the collection name; use `--fonts-dir` to point to optional local font archives.

### Chronological reading order

The in-universe reading order of every story comes from the Timeline/Sourced page of the MTG Wiki and is stored in `data/chronology.json`. Stories are grouped into volumes (eras/arcs). `data/chronology.json` also has `missing_from_archive`, the stories listed in the timeline that are not in this archive.

```bash
python -m mtg_epub.chronology --update      # download the timeline and rewrite data/chronology.json
python typ2epub.py --chronological          # one EPUB per volume in <output-dir>/chronological/
python -m mtg_epub.chronology --wrappers    # one Typst wrapper per volume in stories/chronological/ (for PDF)
```

### Scraper

`scraper.py` downloads the stories still missing from the archive and generates `.typ` files under `stories/`, updating `scraped_manifest.json`.

```bash
python scraper.py              # scrape all missing stories
python scraper.py --rf         # only Reality Fracture
python scraper.py --force      # overwrite existing .typ files
```

By default, stories whose `.typ` file already exists are skipped; pass `--force` to scrape them again and overwrite the files.

With `--rebuild`, every newly scraped story gets its PDF, the PDF of its set book and the EPUBs (story + set omnibus) right away. `--rebuild-only` scrapes nothing and only rebuilds what is missing or out of date. Rebuild failures are listed at the end and return exit code `1`, but the scrape and the manifest are kept.

```bash
python scraper.py --rf --rebuild
python scraper.py --rebuild-only
```

### Archive status

`python -m mtg_epub.status` shows, per set, how many stories have no PDF, an outdated PDF, no EPUB or an outdated EPUB (using `.pdf-cache.json` and `epubs/.epub-cache.json`, falling back to file times). It also lists failed items in `scraped_manifest.json` and the timeline stories missing from the archive, grouped by era and set.

```bash
python -m mtg_epub.status              # summary per set
python -m mtg_epub.status --verbose    # every pending item
python -m mtg_epub.status --json       # write status.json
python -m mtg_epub.status --write-md   # refresh the automatic block of MISSING_STORIES.md
python -m mtg_epub.status --strict     # exit 1 if any PDF/EPUB is pending or the manifest has failures
```

`--write-md` only rewrites the text between `<!-- status:auto:start -->` and `<!-- status:auto:end -->`; the hand-written notes (paid works, audio, card lore) are kept.

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

# List of sets (in published order)

- Magic 2013
- Return to Ravnica
- Gatecrash
- Dragon's Maze
- Modern Masters
- Magic 2014
- Theros
- Commander (2013 Edition)
- Born of the Gods
- Duel Decks: Jace vs. Vraska
- Journey into Nyx
- Conspiracy
- Magic 2015
- Khans of Tarkir
- Commander (2014 Edition)
- Fate Reforged
- Dragons of Tarkir
- Modern Masters 2015
- Magic Origins
- Prologue to Battle for Zendikar
- Battle for Zendikar
- Commander (2015 Edition)
- Oath of the Gatewatch
- Shadows Over Innistrad
- Eternal Masters
- Eldritch Moon
- Conspiracy: Take the Crown
- Kaladesh
- Aether Revolt
- Amonkhet
- Hour of Devastation
- Ixalan
- Rivals of Ixalan
- Dominaria
- Core 2019
- Guilds of Ravnica
- Ravnica Allegiance
- War of the Spark
- Throne of Eldraine
- Theros: Beyond Death
- Ikoria: Lair of Behemoths
- Zendikar Rising
- Kaldheim
- Strixhaven: School of Mages
- Innistrad: Midnight Hunt
- Innistrad: Crimson Vow
- Kamigawa: Neon Dynasty
- Streets of New Capenna
- Pride Across the Multiverse
- Dominaria United
- The Brothers’ War
- Phyrexia: All Will Be One
- March of the Machine
- March of the Machine: The Aftermath
- Wilds of Eldraine
- Lost Caverns of Ixalan
- Murders at Karlov Manor
- Outlaws of Thunder Junction
- Bloomburrow
- Duskmourn: House of Horror
- Aetherdrift
- Tarkir: Dragonstorm
- Edge of Eternities
- Lorwyn Eclipsed
- Secrets of Strixhaven
- Reality Fracture

# Typst

I used [Typst](https://typst.app/) as typesetting system (modern version of LaTeX). Every story has source file `.typ` which can be used to compile your own PDF.

## Compiling

You do not have to install the templates in your system Typst directory: the repository already ships them in the layout Typst expects for `--package-path` (`typst_packages/local/<name>/<version>/`). The `.typ` sources import these exact versions:

- `@local/mtgstory:0.2.0` - used by the stories (`typst_packages/local/mtgstory/0.2.0`)
- `@local/mtgset:0.1.0` - used by the set wrappers in the root of `stories/` (`typst_packages/local/mtgset/0.1.0`): cover, table of contents, PDF bookmarks and continuous page numbering
- `@local/mtgguide:0.1.0` - used by `planeswalkers_guides` (`typst_packages/local/mtgguide/0.1.0`)

Download latest release of Typst https://github.com/typst/typst/releases for your OS. It is command line tool, so you will have to have some knowledge to use it. Also you might want to add Typst executable to your system PATH variable.

Switch to the repository root (the directory where `stories` is) and compile:

```
cd /path/to/MTG-Stories
typst compile --root . --package-path typst_packages --package-cache-path typst_packages/cache --font-path fonts "stories/042 - Strixhaven- School of Mages/001_Episode 1- Class Is in Session.typ"
```

This will create compiled PDF beside the Typst source file with a same name. `--font-path fonts` makes the book typography use the per-set fonts (Crimson Text for the body text; titles use the set's font, e.g. Cinzel or Cormorant Garamond). Fonts that ship as `.zip` (Old English Text MT, Planet Kosmos, VCR OSD Mono...) must be extracted to a folder and added with another `--font-path`; without them the titles fall back to Crimson Text, so nothing breaks. `typ2pdf.py` (below) does all of this for you.

To compile stories without images, use command flag `--input with_images=false`. For example:

```
typst compile --root . --package-path typst_packages --package-cache-path typst_packages/cache --font-path fonts --input with_images=false "stories/042 - Strixhaven- School of Mages/001_Episode 1- Class Is in Session.typ"
```

### PDF look

Stories are typeset like a book (A4, Crimson Text 10.5 pt, justified and hyphenated, drop cap on the first paragraph, ornament between scenes, page number only in the footer). Each set gets its own title font and accent color, generated from the EPUB themes in `mtg_epub/themes.py`, which is the single source of truth:

```
python -m mtg_epub.typst_themes             # regenerates typst_packages/local/mtgstory/0.2.0/themes.typ
python -m mtg_epub.typst_themes --wrappers  # also sets `cover:` (first image of the set's first story) in the set wrappers
```

Rerun it after editing `mtg_epub/themes.py` or adding a set. The same templates are compiled to HTML by the EPUB converter; everything page-specific is skipped there, so the EPUB is not affected.

A set wrapper compiles to a whole book (cover, table of contents, bookmarks):

```
typst compile --root . --package-path typst_packages --package-cache-path typst_packages/cache --font-path fonts "stories/057_Bloomburrow.typ"
```

## Building PDFs

PDFs are build outputs and are no longer versioned (they are in `.gitignore`); after cloning, generate them with `python typ2pdf.py --missing --jobs 4`.

`typ2pdf.py` compiles the stories in bulk using the `typst` Python package (no CLI install or manual package copying needed): it uses `typst_packages/` as the package path, `fonts/` (plus fonts extracted from the `.zip` files in it) and `root` = repository root. The PDF is written beside the `.typ` (`X.pdf`); with `--no-images` it becomes `X - text only.pdf`.

```
python typ2pdf.py --file "stories/057 - Bloomburrow/001_Episode 1- Calamity Comes to Valley.typ"
python typ2pdf.py --set bloomburrow --jobs 4      # partial, case-insensitive folder match
python typ2pdf.py --all --guides --card-lore      # or just --missing for what has no PDF yet
python typ2pdf.py --set-books --set bloom         # set wrappers stories/NNN_*.typ (--set filters them)
python typ2pdf.py --chronological --no-images --pdfa --output-dir build/pdf
```

Targets: `--file`, `--set`, `--all` (excludes `chronological`), `--set-books`, `--chronological`, `--guides`, `--card-lore`, `--missing`. `--pdfa` requests PDF/A-2b (`pdf_standards=["a-2b"]`); if an image makes that fail, the error appears in the item. `--output-dir` mirrors the repository-relative path. Compilation runs in threads (`--jobs N`).

An incremental cache (`.pdf-cache.json`) skips targets whose PDF exists and whose inputs (the `.typ`, its `#include`s, referenced images, `typst_packages/`, fonts, options) did not change; use `--force` to rebuild. A summary is printed at the end and `pdf-report.json` records status, error and duration per item. Exit code is 1 if anything failed and 2 for invalid arguments or no target.

# Contribution

If you find any mistake or you want to contribute, feel free to send a pull request. You can also open an issue on GitHub.
