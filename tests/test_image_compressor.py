import tempfile
import unittest
from pathlib import Path
from PIL import Image

import json
from unittest import mock

from mtg_epub import image_compressor
from mtg_epub.image_compressor import compress_image, batch_compress_directories, record_compressed


class TestImageCompressor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_compress_large_image_resizes_and_reduces_size(self):
        large_path = self.dir_path / "large.jpg"
        # Cria imagem 2000x1000
        img = Image.new("RGB", (2000, 1000), color=(180, 50, 50))
        img.save(large_path, "JPEG", quality=95)

        orig_size = large_path.stat().st_size
        changed = compress_image(large_path, max_dim=1400, quality=80)
        self.assertTrue(changed)

        with Image.open(large_path) as result:
            w, h = result.size
            self.assertEqual(w, 1400)
            self.assertEqual(h, 700)
            self.assertEqual(result.format, "JPEG")

        new_size = large_path.stat().st_size
        self.assertLess(new_size, orig_size)

    def test_batch_compress_directories(self):
        sub = self.dir_path / "stories" / "sample"
        sub.mkdir(parents=True)
        img1 = sub / "01.jpg"
        Image.new("RGB", (1800, 1200), color="blue").save(img1, "JPEG")

        stats = batch_compress_directories(
            [self.dir_path], max_dim=1000, quality=75, verbose=False, cache_path=self.dir_path / "cache.json"
        )
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["compressed"], 1)
        self.assertGreater(stats["saved_bytes"], 0)

        with Image.open(img1) as res:
            self.assertLessEqual(max(res.size), 1000)

    def test_second_run_skips_files_already_processed(self):
        sub = self.dir_path / "stories"
        sub.mkdir()
        img = sub / "01.jpg"
        Image.new("RGB", (1800, 1200), color="blue").save(img, "JPEG")
        cache = self.dir_path / "cache.json"

        first = batch_compress_directories([sub], max_dim=1000, quality=75, verbose=False, cache_path=cache)
        after_first = img.read_bytes()
        second = batch_compress_directories([sub], max_dim=1000, quality=75, verbose=False, cache_path=cache)

        self.assertEqual(first["compressed"], 1)
        self.assertEqual(second["compressed"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(img.read_bytes(), after_first)  # sem recodificação, sem perda acumulada

    def test_modified_file_is_processed_again(self):
        sub = self.dir_path / "stories"
        sub.mkdir()
        img = sub / "01.jpg"
        Image.new("RGB", (1800, 1200), color="blue").save(img, "JPEG")
        cache = self.dir_path / "cache.json"
        batch_compress_directories([sub], max_dim=1000, quality=75, verbose=False, cache_path=cache)

        Image.new("RGB", (1800, 1200), color="red").save(img, "JPEG")
        again = batch_compress_directories([sub], max_dim=1000, quality=75, verbose=False, cache_path=cache)

        self.assertEqual(again["compressed"], 1)
        self.assertEqual(again["skipped"], 0)

    def test_changed_parameters_reprocess_image(self):
        sub = self.dir_path / "stories"
        sub.mkdir()
        Image.new("RGB", (1800, 1200), color="blue").save(sub / "01.jpg", "JPEG")
        cache = self.dir_path / "cache.json"
        batch_compress_directories([sub], max_dim=1000, quality=75, verbose=False, cache_path=cache)
        again = batch_compress_directories([sub], max_dim=800, quality=75, verbose=False, cache_path=cache)
        self.assertEqual(again["skipped"], 0)

    def test_legacy_string_cache_entry_is_reprocessed(self):
        sub = self.dir_path / "stories"
        sub.mkdir()
        img = sub / "01.jpg"
        Image.new("RGB", (1800, 1200), color="blue").save(img, "JPEG")
        cache = self.dir_path / "cache.json"
        cache.write_text(json.dumps({"stories/01.jpg": image_compressor._file_sha256(img)}), encoding="utf-8")
        result = batch_compress_directories([sub], max_dim=1000, quality=75, verbose=False, cache_path=cache)
        self.assertEqual(result["skipped"], 0)

    def test_failed_compression_is_not_cached(self):
        sub = self.dir_path / "stories"
        sub.mkdir()
        (sub / "01.jpg").write_bytes(b"not an image")
        cache = self.dir_path / "cache.json"
        batch_compress_directories([sub], verbose=False, cache_path=cache)
        data = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
        self.assertEqual(data, {})

    def test_record_compressed_prevents_recompression(self):
        sub = self.dir_path / "stories"
        sub.mkdir()
        img = sub / "01.jpg"
        Image.new("RGB", (1800, 1200), color="blue").save(img, "JPEG")
        cache = self.dir_path / "cache.json"
        record_compressed(img, cache_path=cache)
        result = batch_compress_directories([sub], verbose=False, cache_path=cache)
        self.assertEqual(result["skipped"], 1)


if __name__ == "__main__":
    unittest.main()


class TestCompressImageBytesKeepsSmallerOriginal(unittest.TestCase):
    def test_returns_original_when_result_is_larger_and_not_resized(self):
        import io
        from mtg_epub.image_compressor import compress_image_bytes

        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), (10, 20, 30)).save(buffer, "JPEG", quality=20, optimize=True)
        original = buffer.getvalue()
        data, ext, mime = compress_image_bytes(original, max_dim=1400, quality=95)
        if len(data) == len(original):  # recomprimir em qualidade 95 aumenta: devolve o original
            self.assertEqual(data, original)
        self.assertEqual((ext, mime), ("jpg", "image/jpeg"))
        self.assertLessEqual(len(data), len(original))
