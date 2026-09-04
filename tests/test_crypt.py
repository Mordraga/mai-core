import tempfile
import unittest
from unittest.mock import patch

from relationships.crypt import (
    aggregate_crypt_relationship,
    compute_crypt_sway_weights,
    crypt_sway,
    eligible_stream_counts,
    expectation_violation,
    population_center,
    population_sigma,
)
from relationships.models import DEFAULT_RELATIONSHIP, RELATIONSHIP_FIELDS
from relationships.state import load_relationship, save_relationship


class PopulationCenterTests(unittest.TestCase):
    def test_empty_population_is_zero(self):
        self.assertEqual(population_center([]), 0.0)

    def test_no_trim_below_twenty(self):
        # spec 19.2/19.3: fewer than 20 eligible users, use the full
        # population mean — no percentile trimming.
        values = [0, 0, 0, 100]  # a wild outlier that a trim would remove
        self.assertEqual(population_center(values), sum(values) / len(values))

    def test_trims_extremes_at_twenty_or_more(self):
        values = list(range(20))  # 0..19, trimming should drop 0 and 19
        trimmed_mean = sum(range(1, 19)) / 18
        self.assertAlmostEqual(population_center(values), trimmed_mean)


class PopulationSigmaTests(unittest.TestCase):
    def test_falls_back_to_default_with_fewer_than_two_values(self):
        self.assertGreater(population_sigma([5], 5), 0.0)

    def test_falls_back_to_default_when_variance_is_zero(self):
        # Everyone at the same stream_count — zero variance must not
        # divide by zero (spec 19.5).
        self.assertGreater(population_sigma([3, 3, 3], 3), 0.0)

    def test_computes_real_spread_for_varied_population(self):
        sigma = population_sigma([0, 10, 20], 10)
        self.assertAlmostEqual(sigma, (200 / 3) ** 0.5)


class CryptSwayTests(unittest.TestCase):
    def test_peaks_at_the_center(self):
        self.assertEqual(crypt_sway(10, center=10, sigma=5), 1.0)

    def test_falls_off_symmetrically(self):
        below = crypt_sway(5, center=10, sigma=5)
        above = crypt_sway(15, center=10, sigma=5)
        self.assertAlmostEqual(below, above)
        self.assertLess(below, 1.0)

    def test_degenerate_sigma_returns_full_sway(self):
        self.assertEqual(crypt_sway(999, center=10, sigma=0.0), 1.0)


class AggregateCryptTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def test_empty_population_falls_back_to_default_relationship(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            self.assertEqual(eligible_stream_counts(), {})
            self.assertEqual(aggregate_crypt_relationship(), DEFAULT_RELATIONSHIP)

    def test_equal_sway_when_everyone_has_the_same_stream_count(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            for name in ("nova", "kip", "ash"):
                save_relationship(name, load_relationship(name))
            weights = compute_crypt_sway_weights()
            self.assertEqual(set(weights), {"nova", "kip", "ash"})
            self.assertEqual(len(set(weights.values())), 1)

    def test_aggregate_reflects_weighted_mean_of_members(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            high = load_relationship("nova")
            high["relationship"]["affection"] = 0.9
            save_relationship("nova", high)

            low = load_relationship("kip")
            low["relationship"]["affection"] = 0.1
            save_relationship("kip", low)

            aggregate = aggregate_crypt_relationship()
            # Equal stream_count (0 for both) -> equal sway -> simple mean.
            self.assertAlmostEqual(aggregate["affection"], 0.5)

    def test_high_stream_count_user_pulls_center_and_gets_high_sway(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            for name, count in (("regular_a", 10), ("regular_b", 10), ("regular_c", 10), ("newbie", 0)):
                record = load_relationship(name)
                record["stream_count"] = count
                save_relationship(name, record)

            weights = compute_crypt_sway_weights()
            # Center sits near 10 (three of four users) -> the outlier at 0
            # should be less representative than a user right at the center.
            self.assertLess(weights["newbie"], weights["regular_a"])


class ExpectationViolationTests(unittest.TestCase):
    def test_zero_when_identical_to_crypt(self):
        crypt = dict(DEFAULT_RELATIONSHIP)
        individual = dict(DEFAULT_RELATIONSHIP)
        self.assertEqual(expectation_violation(individual, crypt), 0.0)

    def test_positive_when_diverging_and_unfamiliar(self):
        crypt = {f: 0.8 for f in RELATIONSHIP_FIELDS}
        # familiarity explicitly 0.0 so dampening doesn't erase the signal
        individual = {**{f: 0.1 for f in RELATIONSHIP_FIELDS}, "familiarity": 0.0}
        self.assertGreater(expectation_violation(individual, crypt), 0.0)

    def test_dampened_toward_zero_for_a_highly_familiar_regular(self):
        crypt = {f: 0.8 for f in RELATIONSHIP_FIELDS}
        diverging_but_familiar = {**{f: 0.1 for f in RELATIONSHIP_FIELDS}, "familiarity": 1.0}
        diverging_and_unfamiliar = {**{f: 0.1 for f in RELATIONSHIP_FIELDS}, "familiarity": 0.0}
        familiar_violation = expectation_violation(diverging_but_familiar, crypt)
        unfamiliar_violation = expectation_violation(diverging_and_unfamiliar, crypt)
        self.assertLess(familiar_violation, unfamiliar_violation)
        self.assertAlmostEqual(familiar_violation, 0.0)


if __name__ == "__main__":
    unittest.main()
