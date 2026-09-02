import unittest
import struct
from pathlib import Path

from utils.source_groups import GOVERNMENT_SOURCES
from utils.source_icons import (
    DEFENSE_SOURCE,
    INTERIOR_SOURCE,
    SOURCE_EMBLEMS,
)


class SourceIconTests(unittest.TestCase):
    def test_every_government_source_has_an_emblem(self):
        self.assertEqual(set(SOURCE_EMBLEMS), set(GOVERNMENT_SOURCES))

    def test_trutnev_uses_the_government_emblem(self):
        self.assertEqual(
            SOURCE_EMBLEMS["Трутнев"],
            SOURCE_EMBLEMS["Правительство РФ"],
        )

    def test_security_emblems_use_their_approved_grid_cells(self):
        self.assertEqual(DEFENSE_SOURCE, "Минобороны РФ")
        self.assertEqual(SOURCE_EMBLEMS[DEFENSE_SOURCE], (4, 0))
        self.assertEqual(SOURCE_EMBLEMS[INTERIOR_SOURCE], (0, 1))

    def test_sprite_coordinates_stay_inside_the_grid(self):
        for source, (column, row) in SOURCE_EMBLEMS.items():
            with self.subTest(source=source):
                self.assertIn(column, range(6))
                self.assertIn(row, range(5))

    def test_sprite_has_six_by_five_square_cells(self):
        sprite_path = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "source-emblems.png"
        )
        png = sprite_path.read_bytes()
        width, height = struct.unpack(">II", png[16:24])
        self.assertEqual((width, height), (1374, 1145))
        self.assertEqual(width // 6, height // 5)


if __name__ == "__main__":
    unittest.main()
