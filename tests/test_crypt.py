import unittest

from relationship_test_base import RelationshipTestCase

from relationships import crypt
from relationships import state
from relationships.models import RELATIONSHIP_DEFAULTS


class PopulationCenterTests(unittest.TestCase):
    def test_no_trimming_under_ten(self):
        counts = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        self.assertAlmostEqual(crypt._population_center(counts), sum(counts) / len(counts))

    def test_no_trimming_ten_to_nineteen(self):
        counts = list(range(1, 15))  # 14 users
        self.assertAlmostEqual(crypt._population_center(counts), sum(counts) / len(counts))

    def test_trims_top_and_bottom_ten_percent_at_twenty_plus(self):
        counts = list(range(1, 21))  # 20 users, 1..20
        trim = max(1, int(20 * 0.10))  # 2
        expected = sum(counts[trim: 20 - trim]) / (20 - 2 * trim)
        self.assertAlmostEqual(crypt._population_center(counts), expected)

    def test_empty_population(self):
        self.assertEqual(crypt._population_center([]), 0.0)


class CryptSwayTests(unittest.TestCase):
    def test_degenerate_sigma_gives_equal_sway(self):
        records = [{"username": "a", "stream_count": 5}, {"username": "b", "stream_count": 5}]
        sway = crypt.compute_crypt_sway(records)
        self.assertEqual(sway["a"], 1.0)
        self.assertEqual(sway["b"], 1.0)

    def test_users_near_center_get_higher_sway_than_outliers(self):
        records = [
            {"username": "center1", "stream_count": 10},
            {"username": "center2", "stream_count": 10},
            {"username": "center3", "stream_count": 11},
            {"username": "newcomer", "stream_count": 1},
            {"username": "ancient", "stream_count": 200},
        ]
        sway = crypt.compute_crypt_sway(records)
        self.assertGreater(sway["center1"], sway["newcomer"])
        self.assertGreater(sway["center1"], sway["ancient"])

    def test_empty_records(self):
        self.assertEqual(crypt.compute_crypt_sway([]), {})


class AggregateCryptRelationshipTests(RelationshipTestCase):
    def test_defaults_when_no_known_users(self):
        aggregate = crypt.aggregate_crypt_relationship()
        self.assertEqual(aggregate, dict(RELATIONSHIP_DEFAULTS))

    def test_aggregate_is_sway_weighted_mean(self):
        state.update_relationship("regular_one", {"affection": 0.4})  # -> 0.4
        state.update_relationship("regular_two", {"affection": 0.4})  # -> 0.4
        for username in ("regular_one", "regular_two"):
            record = state.load_user_record(username)
            record["stream_count"] = 10
            state.save_user_record(username, record)

        aggregate = crypt.aggregate_crypt_relationship()
        self.assertAlmostEqual(aggregate["affection"], 0.4, places=2)

    def test_ancient_regular_has_less_sway_but_keeps_own_relationship(self):
        # A brand-new, highly-representative population plus one long-established
        # outlier: the outlier's personal relationship values must not be erased,
        # but should pull the *aggregate* less than the representative cluster.
        for name in ("rep1", "rep2", "rep3"):
            state.update_relationship(name, {"affection": 0.9})
            record = state.load_user_record(name)
            record["stream_count"] = 10
            state.save_user_record(name, record)

        state.update_relationship("ancient", {"affection": 0.1})
        record = state.load_user_record("ancient")
        record["stream_count"] = 500
        state.save_user_record("ancient", record)

        aggregate = crypt.aggregate_crypt_relationship()
        # Ancient's low affection barely drags the average down, since it has low sway.
        self.assertGreater(aggregate["affection"], 0.5)
        # Ancient's own relationship is untouched.
        self.assertAlmostEqual(state.get_relationship("ancient")["affection"], 0.1, places=6)


if __name__ == "__main__":
    unittest.main()
