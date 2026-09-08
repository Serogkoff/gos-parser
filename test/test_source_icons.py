import unittest
from pathlib import Path

from utils.source_groups import GOVERNMENT_SOURCES
from utils.source_icons import (
    AGENCY_EMBLEMS,
    DEFENSE_SOURCE,
    SOURCE_EMBLEMS,
    source_emblem,
)


class SourceIconTests(unittest.TestCase):
    def test_every_government_source_has_an_emblem(self):
        self.assertEqual(set(SOURCE_EMBLEMS), set(GOVERNMENT_SOURCES))

    def test_trutnev_uses_the_government_emblem(self):
        self.assertEqual(
            SOURCE_EMBLEMS["Трутнев"],
            SOURCE_EMBLEMS["Правительство РФ"],
        )

    def test_defense_uses_dedicated_emblem(self):
        self.assertIn(DEFENSE_SOURCE, SOURCE_EMBLEMS)
        self.assertEqual(DEFENSE_SOURCE, "Минобороны РФ")

    def test_every_configured_emblem_file_exists(self):
        logo_dir = Path(__file__).parents[1] / "static" / "source-logos"
        for source, filename in SOURCE_EMBLEMS.items():
            with self.subTest(source=source):
                self.assertTrue((logo_dir / filename).is_file())

    def test_shared_emblems_reduce_the_set_to_27_files(self):
        self.assertEqual(len(set(SOURCE_EMBLEMS.values())), 27)

    def test_every_agency_source_has_an_emblem(self):
        expected = {
            "РИА Новости": "ria.png",
            "ТАСС": "tass.png",
            "Интерфакс": "interfax.png",
            "Yonhap": "yonhap.png",
            "Киодо (共同通信)": "kyodo.png",
        }
        self.assertEqual(AGENCY_EMBLEMS, expected)
        for source, filename in expected.items():
            with self.subTest(source=source):
                self.assertEqual(source_emblem(source), filename)

    def test_every_yahoo_section_uses_the_yahoo_emblem(self):
        self.assertEqual(source_emblem("Yahoo! JAPAN"), "yahoo.png")
        self.assertEqual(
            source_emblem("Yahoo! JAPAN · 時事通信"),
            "yahoo.png",
        )

    def test_every_agency_emblem_file_exists(self):
        logo_dir = Path(__file__).parents[1] / "static" / "source-logos"
        filenames = set(AGENCY_EMBLEMS.values()) | {"yahoo.png"}
        for filename in filenames:
            with self.subTest(filename=filename):
                self.assertTrue((logo_dir / filename).is_file())


if __name__ == "__main__":
    unittest.main()
