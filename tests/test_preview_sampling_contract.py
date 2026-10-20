"""Sampling boundary regression checks; live request replay is also required."""
import unittest
from src.generation_sampling import validate_temperature


class SamplingContractTests(unittest.TestCase):
    def test_requested_sampling_and_greedy_values_preserved(self):
        for value in (0, .2, 1., 1.5):
            self.assertEqual(validate_temperature(value), value)

    def test_invalid_values_rejected(self):
        for value in (None, True, '1.0', -1., float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_temperature(value)


if __name__ == '__main__':
    unittest.main()
