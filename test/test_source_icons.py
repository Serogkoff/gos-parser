import unittest
from pathlib import Path

from utils.source_groups import GOVERNMENT_SOURCES
from utils.source_icons import DEFENSE_SOURCE, SOURCE_EMBLEMS


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


if __name__ == "__main__":
    unittest.main()
