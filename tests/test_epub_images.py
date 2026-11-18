import base64
import io

from bs4 import BeautifulSoup
from ebooklib import epub
from PIL import Image

from mtg_epub.epub_builder import _process_images
from mtg_epub.image_compressor import compress_image_bytes


def _uri(size=(40, 30), mode="RGB", color=(200, 10, 10), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, format=fmt)
    return "data:image/%s;base64,%s" % (fmt.lower(), base64.b64encode(buffer.getvalue()).decode())


def _run(html, with_images=True, max_size=1400):
    book = epub.EpubBook()
    out, warnings = _process_images(html, book, {}, "ch.typ", max_size, with_images)
    items = [i for i in book.get_items() if isinstance(i, epub.EpubImage)]
    return out, warnings, items


def test_duplicates_deduplicated_and_src_rewritten():
    a, b = _uri(color=(255, 0, 0)), _uri(color=(0, 0, 255))
    html = (
        f'<figure><img src="{a}" alt="um"><figcaption>Legenda</figcaption></figure>'
        f'<img src="{a}" alt="dois"><img src="{b}" alt="tres">'
    )
    out, warnings, items = _run(html)
    assert warnings == []
    assert len(items) == 2
    imgs = BeautifulSoup(out, "lxml").find_all("img")
    assert all(i["src"].startswith("images/") for i in imgs)
    assert imgs[0]["src"] == imgs[1]["src"] != imgs[2]["src"]
    assert imgs[0]["alt"] == "um"
    assert "Legenda" in out
    assert "data:image" not in out


def test_large_image_resized_to_max_side():
    out, _, items = _run(f'<img src="{_uri(size=(2000, 1000))}">')
    with Image.open(io.BytesIO(items[0].content)) as img:
        assert img.size == (1400, 700)
    assert items[0].file_name.endswith(".jpg")


def test_png_with_alpha_stays_png():
    data, ext, mime = compress_image_bytes(base64.b64decode(_uri(mode="RGBA", color=(1, 2, 3, 100)).split(",")[1]))
    assert (ext, mime) == ("png", "image/png")
    out, _, items = _run(f'<img src="{_uri(mode="RGBA", color=(1, 2, 3, 100))}">')
    assert items[0].file_name.endswith(".png")
    assert items[0].content.startswith(b"\x89PNG")


def test_corrupt_data_uri_kept_with_warning():
    bad = "data:image/jpeg;base64,AAAA!!notimage"
    out, warnings, items = _run(f'<img src="{bad}">')
    assert items == []
    assert len(warnings) == 1
    assert bad in out


def test_no_images_removes_figures():
    uri = _uri()
    html = f'<p>texto</p><figure><img src="{uri}"><figcaption>x</figcaption></figure><img src="{uri}">'
    out, warnings, items = _run(html, with_images=False)
    assert "<img" not in out and "<figure" not in out
    assert "texto" in out and items == []


def test_no_images_with_empty_body_does_not_crash():
    out, warnings, items = _run("", with_images=False)
    assert out == "" and warnings == [] and items == []
