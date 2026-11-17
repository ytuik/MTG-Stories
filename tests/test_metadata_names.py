from mtg_epub.metadata import collect_set_names


def test_collect_set_names_from_folders(tmp_path):
    (tmp_path / "stories" / "021 - Battle for Zendikar").mkdir(parents=True)
    (tmp_path / "planeswalkers_guides" / "Planeswalker's Guide to Ulgrotha").mkdir(parents=True)
    names = collect_set_names(tmp_path)
    assert names["battle-for-zendikar"] == "Battle for Zendikar"
    assert "ulgrotha" in "".join(names) or "guide-to-ulgrotha" in names
