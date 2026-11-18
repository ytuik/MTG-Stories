import unittest
from pathlib import Path

from mtg_epub.slugs import slugify


class TestSlugNormalization(unittest.TestCase):
    def test_slugify_removes_quotes_and_spaces(self):
        self.assertEqual(slugify("004 - Dragon's Maze.typ"), "004-dragons-maze.typ")
        self.assertEqual(slugify("001_Episode 1- Calamity Comes to Valley.typ"), "001-episode-1-calamity-comes-to-valley.typ")
        self.assertEqual(slugify('003_Barrin"s Tall Tale.pdf'), "003-barrins-tall-tale.pdf")
        self.assertEqual(slugify("Planeswalker's Guide to Ulgrotha"), "planeswalkers-guide-to-ulgrotha")

    def test_slugify_dots_inside_names_are_separators(self):
        self.assertEqual(slugify("Duel Decks- Jace vs. Vraska"), "duel-decks-jace-vs-vraska")

    def test_slugify_keeps_real_file_extension(self):
        self.assertEqual(slugify("Jace vs. Vraska.typ"), "jace-vs-vraska.typ")
        self.assertEqual(slugify("01.JPG"), "01.jpg")


if __name__ == "__main__":
    unittest.main()
