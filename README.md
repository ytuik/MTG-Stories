# MTG Stories

This is an archive of MTG stories publicly available on the Wizards of the Coast website, compiled into PDF and EPUB versions. Images are available either embedded in the documents or as separate files.

Stories are sorted into the `stories` folder by set name and in published order.

* Stories from Magic 2013 to Modern Masters 2015 are sorted with [MTG Wiki](https://mtg.wiki/page/Magic_Story).
* Stories from Magic Origins to March of the Machine: The Aftermath are sorted with [MTGLore](https://mtglore.com/chronological/).
* Stories from Wilds of Eldraine going forward are sorted with [MTG Story](https://mtgstory.com).

If you want to download all the PDFs/EPUBs or complete stories in one big file (with or without images), check the [Releases](https://github.com/ytuik/MTG-Stories/releases) page.

This repository is a fork of [polarkac/MTG-Stories](https://github.com/polarkac/MTG-Stories); credit for the original archive goes to its author.

---

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

The converter writes a JSON report and an incremental cache in the output directory. Failed conversions are reported at the end and return exit code `1`. EPUBs also receive structural validation for the `mimetype`, container, OPF, navigation and absolute paths.

The implementation is split into `mtg_epub/`: metadata and manifest handling, balanced Typst sanitization, Typst-to-HTML conversion, image handling, cache and EPUB validation.

Image compression: `--compress-images` (with Pillow) shrinks the images for e-readers. **Warning:** it rewrites the images of the archive in place (under `stories/`, `planeswalkers_guides/` and `card_lore/`), not just the EPUB copies. A cache records already-compressed files so they are not recompressed on later runs. Commit or back up first if you want to keep the originals.

```bash
python typ2epub.py --set Bloomburrow --compress-images
```

Collection-specific EPUB themes and the current coverage matrix are documented in [EPUB_THEMES.md](EPUB_THEMES.md). Themes are selected automatically from the collection name; use `--fonts-dir` to point to optional local font archives.

### Scraper

`scraper.py` downloads the stories still missing from the archive and generates `.typ` files under `stories/`, updating `scraped_manifest.json`.

```bash
python scraper.py              # scrape all missing stories
python scraper.py --rf         # only Reality Fracture
python scraper.py --force      # overwrite existing .typ files
```

By default, stories whose `.typ` file already exists are skipped; pass `--force` to scrape them again and overwrite the files. The `--all` flag is currently a no-op.

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

First you must copy the package directories from `typst_packages/` into the local Typst package directory for your OS (`<packages>/local/<name>/<version>/`). If the directory does not exist, create it. The `.typ` sources import these exact versions:

- `@local/mtgstory:0.2.0` - used by the stories (`typst_packages/mtgstory/0.2.0`)
- `@local/mtgset:0.1.0` - used by the set wrappers in the root of `stories/` (`typst_packages/mtgset/0.1.0`)
- `@local/mtgguide:0.1.0` - used by `planeswalkers_guides` (`typst_packages/mtgguide/0.1.0`)

For example, on Linux the story package goes to `~/.local/share/typst/packages/local/mtgstory/0.2.0/`.

Windows: `%APPDATA%\typst\packages\`  
Linux: `~/.local/share/typst/packages/`  
MacOS: `~/Library/Application Support/typst/packages/`

Download latest release of Typst https://github.com/typst/typst/releases for your OS. It is command line tool, so you will have to have some knowledge to use it. Also you might want to add Typst executable to your system PATH variable.

After all that you can use `typst` command to compile the source file into PDF. Switch to a directory where `stories` directory is.

`cd /path/to/MTG-Stories`

And to compile:

`typst compile "stories/042 - Strixhaven: School of Mages/001_Episode 1: Class Is in Session.typ"`

This will create compiled PDF beside the Typst source file with a same name.

To compile stories without images, use command flag `--input with_images=false`. For example:

`typst compile --input with_images=false "stories/042 - Strixhaven: School of Mages/001_Episode 1: Class Is in Session.typ"`

# Contribution

If you find any mistake or you want to contribute, feel free to send a pull request. You can also open an issue on GitHub.
