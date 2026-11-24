from decimal import Decimal as D

from django.test import SimpleTestCase

from . import units
from .units import UnitError


class UnitTests(SimpleTestCase):
    def test_mass_and_volume(self):
        self.assertEqual(units.convert(1200, "g", "kg"), D("1.2"))
        self.assertEqual(units.convert("1.2", "kg", "g"), D("1200"))
        self.assertEqual(units.convert(10500, "ml", "litre"), D("10.5"))
        self.assertEqual(units.convert("10.5", "litre", "ml"), D("10500"))

    def test_count_and_carton(self):
        self.assertEqual(units.convert(188, "packet", "piece"), D("188"))
        self.assertEqual(units.convert(10, "carton", "packet", carton_size=20), D("200"))
        self.assertEqual(units.convert(200, "packet", "carton", carton_size=20), D("10"))
        self.assertEqual(units.convert(190, "packet", "carton", carton_size=20), D("9.5"))

    def test_cartons_for(self):
        self.assertEqual(units.cartons_for(188, 20), (9, 8))
        self.assertEqual(units.cartons_for(200, 20), (10, 0))
        with self.assertRaises(UnitError):
            units.cartons_for(188, 0)

    def test_errors(self):
        with self.assertRaises(UnitError):
            units.convert(1, "kg", "litre")
        with self.assertRaises(UnitError):
            units.convert(1, "bucket", "kg")
        with self.assertRaises(UnitError):
            units.convert(1, "carton", "packet")          # carton size missing
        with self.assertRaises(TypeError):
            units.convert(1.5, "kg", "g")                  # floats are refused

    def test_to_base_and_aliases(self):
        self.assertEqual(units.to_base(500, "g", "kg"), D("0.500"))
        self.assertEqual(units.convert(2, "Litres", "ml"), D("2000"))
        self.assertEqual(units.convert(3, "pcs", "piece"), D("3"))