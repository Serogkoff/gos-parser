import unittest

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

    def test_sprite_coordinates_stay_inside_the_grid(self):
        for source, (column, row) in SOURCE_EMBLEMS.items():
            with self.subTest(source=source):
                self.assertIn(column, range(6))
                self.assertIn(row, range(5))


if __name__ == "__main__":
    unittest.main()
