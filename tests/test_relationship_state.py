import tempfile
import unittest
from unittest.mock import patch

from relationships.models import DEFAULT_OWNER_RELATIONSHIP, DEFAULT_RELATIONSHIP
from relationships.state import (
    bump_stream_count,
    compute_friendship,
    load_relationship,
    save_relationship,
    user_file_exists,
)


class RelationshipStateTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def test_defaults_when_no_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            record = load_relationship("nova")
            self.assertEqual(record["relationship"], DEFAULT_RELATIONSHIP)
            self.assertEqual(record["stream_count"], 0)
            self.assertEqual(record["observations"], [])
            self.assertFalse(user_file_exists("nova"))

    def test_round_trip_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            record = load_relationship("nova")
            record["relationship"]["affection"] = 0.94
            record["relationship"]["trust"] = 0.28
            record["stream_count"] = 12
            save_relationship("nova", record)

            self.assertTrue(user_file_exists("nova"))
            reloaded = load_relationship("nova")
            self.assertEqual(reloaded["relationship"]["affection"], 0.94)
            self.assertEqual(reloaded["relationship"]["trust"], 0.28)
            self.assertEqual(reloaded["stream_count"], 12)

    def test_clamping_on_out_of_range_values(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            record = load_relationship("clamped")
            record["relationship"]["affection"] = 5.0
            record["relationship"]["hate"] = -3.0
            save_relationship("clamped", record)

            reloaded = load_relationship("clamped")
            self.assertEqual(reloaded["relationship"]["affection"], 1.0)
            self.assertEqual(reloaded["relationship"]["hate"], 0.0)

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            from utils.helpers import atomic_write_text, resolve_write_path
            from utils.paths import Paths

            path = resolve_write_path(f"{Paths.RELATIONSHIPS_DIR}/corrupt.json")
            atomic_write_text(path, "{not valid json")

            record = load_relationship("corrupt")
            self.assertEqual(record["relationship"], DEFAULT_RELATIONSHIP)

    def test_contradictory_state_preserved_unchanged(self):
        # Spec section 6: contradictory primitives must not be "corrected".
        contradictory = {
            "hate": 0.96,
            "trust": 0.28,
            "interest": 0.94,
            "closeness_desire": 0.81,
            "familiarity": 0.92,
            "respect": 0.13,
            "reciprocity": 0.5,
            "enjoyment": 0.5,
            "reliability": 0.5,
            "affection": 0.0,
            "resentment": 0.0,
        }
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            record = load_relationship("enemy")
            record["relationship"] = dict(contradictory)
            save_relationship("enemy", record)

            reloaded = load_relationship("enemy")
            self.assertEqual(reloaded["relationship"], contradictory)

    def test_friendship_recomputed_never_persisted_as_source_of_truth(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            record = load_relationship("nova")
            record["friendship"] = {"utility": 0.0, "pleasure": 0.0, "virtue": 0.0}
            record["relationship"]["enjoyment"] = 1.0
            record["relationship"]["interest"] = 1.0
            record["relationship"]["affection"] = 1.0
            save_relationship("nova", record)

            reloaded = load_relationship("nova")
            # Whatever was written to "friendship" on disk is irrelevant —
            # it's recomputed fresh from the primitives on every load.
            self.assertGreater(reloaded["friendship"]["pleasure"], 0.9)

    def test_bump_stream_count_increments_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            first = bump_stream_count("nova")
            second = bump_stream_count("nova")
            self.assertEqual(first["stream_count"], 1)
            self.assertEqual(second["stream_count"], 2)

    def test_owner_gets_elevated_baseline_on_first_ever_load(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            stranger = load_relationship("random_viewer", is_owner=False)
            owner = load_relationship("mordraga0", is_owner=True)

            self.assertEqual(stranger["relationship"], DEFAULT_RELATIONSHIP)
            self.assertEqual(owner["relationship"], DEFAULT_OWNER_RELATIONSHIP)
            self.assertGreater(owner["relationship"]["familiarity"], stranger["relationship"]["familiarity"])
            self.assertGreater(owner["relationship"]["affection"], stranger["relationship"]["affection"])

    def test_is_owner_ignored_once_a_real_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            record = load_relationship("mordraga0", is_owner=True)
            record["relationship"]["affection"] = 0.1
            save_relationship("mordraga0", record)

            reloaded = load_relationship("mordraga0", is_owner=True)
            self.assertEqual(reloaded["relationship"]["affection"], 0.1)

    def test_compute_friendship_mapping(self):
        friendship = compute_friendship(
            {
                "reciprocity": 1.0,
                "reliability": 1.0,
                "trust": 1.0,
                "enjoyment": 0.0,
                "interest": 0.0,
                "affection": 0.0,
                "respect": 0.0,
            }
        )
        self.assertEqual(friendship["utility"], 1.0)
        self.assertEqual(friendship["pleasure"], 0.0)


if __name__ == "__main__":
    unittest.main()
