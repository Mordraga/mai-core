import tempfile
import threading
import unittest
from unittest.mock import patch

from relationships.models import DEFAULT_NEEDS, NEEDS_FIELDS
from relationships.needs import (
    apply_and_persist_needs_delta,
    apply_engagement_delta,
    apply_needs_delta,
    apply_presence_tick,
    decay_needs,
    read_needs_state,
    spice_level_from_needs,
    touch_needs_heartbeat,
    write_needs_state,
)


class NeedsStateTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def test_defaults_when_no_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            state = read_needs_state()
            self.assertEqual(state, DEFAULT_NEEDS)

    def test_round_trip_persistence(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            state = read_needs_state()
            state["frustration"] = 0.9
            state["loneliness"] = 0.4
            write_needs_state(state)

            reloaded = read_needs_state()
            self.assertEqual(reloaded["frustration"], 0.9)
            self.assertEqual(reloaded["loneliness"], 0.4)

    def test_clamping_on_out_of_range_values(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            write_needs_state({"happiness": 5.0, "anger": -1.0})
            reloaded = read_needs_state()
            self.assertEqual(reloaded["happiness"], 1.0)
            self.assertEqual(reloaded["anger"], 0.0)

    def test_decay_needs_is_monotonic_over_elapsed_time(self):
        state = dict(DEFAULT_NEEDS)
        state["arousal"] = 0.8  # decays toward 0
        state["boredom"] = 0.0  # rises toward 1

        after_short = decay_needs(state, 100.0)
        after_long = decay_needs(state, 10000.0)

        self.assertLess(after_short["arousal"], state["arousal"])
        self.assertLessEqual(after_long["arousal"], after_short["arousal"])
        self.assertGreater(after_short["boredom"], state["boredom"])
        self.assertGreaterEqual(after_long["boredom"], after_short["boredom"])

    def test_decay_needs_stays_clamped(self):
        state = dict(DEFAULT_NEEDS)
        state["arousal"] = 0.01
        decayed = decay_needs(state, 10_000_000.0)
        self.assertGreaterEqual(decayed["arousal"], 0.0)
        for value in decayed.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_decay_needs_zero_elapsed_is_a_no_op(self):
        state = dict(DEFAULT_NEEDS)
        state["happiness"] = 0.42
        self.assertEqual(decay_needs(state, 0.0), state)

    def test_apply_needs_delta_bounded(self):
        state = dict(DEFAULT_NEEDS)
        result = apply_needs_delta(state, {"frustration": 2.0, "energy": -5.0})
        self.assertEqual(result["frustration"], 1.0)
        self.assertEqual(result["energy"], 0.0)

    def test_spice_level_from_needs_range(self):
        low = spice_level_from_needs({**DEFAULT_NEEDS, "arousal": 0.0, "happiness": 0.0})
        high = spice_level_from_needs({**DEFAULT_NEEDS, "arousal": 1.0, "happiness": 1.0})
        self.assertGreaterEqual(low, 1)
        self.assertLessEqual(high, 11)
        self.assertLess(low, high)

    def test_apply_and_persist_needs_delta_round_trips_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = apply_and_persist_needs_delta({"happiness": 0.1, "energy": -0.1})
            reloaded = read_needs_state()
            self.assertEqual(result, reloaded)
            self.assertAlmostEqual(reloaded["happiness"], DEFAULT_NEEDS["happiness"] + 0.1)
            self.assertAlmostEqual(reloaded["energy"], DEFAULT_NEEDS["energy"] - 0.1)

    def test_apply_presence_tick_quiet_raises_boredom_loneliness_social_need(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            before = read_needs_state()
            after = apply_presence_tick(is_quiet=True)
            self.assertGreater(after["boredom"], before["boredom"])
            self.assertGreater(after["loneliness"], before["loneliness"])
            self.assertGreater(after["social_need"], before["social_need"])

    def test_apply_presence_tick_active_lowers_loneliness_social_need(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            write_needs_state({**DEFAULT_NEEDS, "loneliness": 0.5, "social_need": 0.5})
            before = read_needs_state()
            after = apply_presence_tick(is_quiet=False)
            self.assertLess(after["loneliness"], before["loneliness"])
            self.assertLess(after["social_need"], before["social_need"])

    def test_apply_engagement_delta_is_larger_than_a_presence_tick(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            write_needs_state({**DEFAULT_NEEDS, "loneliness": 0.5, "social_need": 0.5})
            before = read_needs_state()
            after = apply_engagement_delta()
            self.assertGreater(before["loneliness"] - after["loneliness"], 0.005)
            self.assertGreater(before["social_need"] - after["social_need"], 0.005)
            self.assertGreater(after["happiness"], before["happiness"])

    def test_touch_needs_heartbeat_survives_concurrent_calls(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            write_needs_state(dict(DEFAULT_NEEDS))

            errors: list[Exception] = []

            def _hit():
                try:
                    touch_needs_heartbeat(None)
                except Exception as exc:  # pragma: no cover - failure path only
                    errors.append(exc)

            threads = [threading.Thread(target=_hit) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [])
            final = read_needs_state()
            for field in NEEDS_FIELDS:
                self.assertGreaterEqual(final[field], 0.0)
                self.assertLessEqual(final[field], 1.0)


if __name__ == "__main__":
    unittest.main()
