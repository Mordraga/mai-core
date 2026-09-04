import tempfile
import unittest
from unittest.mock import patch

from relationships.crypt_mood import (
    DEFAULT_CURRENT_CRYPT,
    apply_and_persist_current_crypt_delta,
    decay_current_crypt,
    nudge_from_partcore,
    read_current_crypt_state,
    touch_current_crypt_heartbeat,
)
from relationships.models import PartcoreResult, PartVote


class DecayCurrentCryptTests(unittest.TestCase):
    def test_zero_elapsed_is_a_no_op(self):
        state = {"current_warmth": 0.9, "current_friction": 0.6}
        result = decay_current_crypt(state, 0.0)
        self.assertAlmostEqual(result["current_warmth"], 0.9)
        self.assertAlmostEqual(result["current_friction"], 0.6)

    def test_relaxes_toward_neutral_over_time(self):
        state = {"current_warmth": 0.9, "current_friction": 0.6}
        result = decay_current_crypt(state, elapsed_seconds=3600)
        self.assertLess(result["current_warmth"], 0.9)
        self.assertGreater(result["current_warmth"], DEFAULT_CURRENT_CRYPT["current_warmth"])
        self.assertLess(result["current_friction"], 0.6)
        self.assertGreater(result["current_friction"], DEFAULT_CURRENT_CRYPT["current_friction"])

    def test_never_overshoots_past_neutral(self):
        state = {"current_warmth": 0.9, "current_friction": 0.6}
        result = decay_current_crypt(state, elapsed_seconds=10_000_000)
        self.assertAlmostEqual(result["current_warmth"], DEFAULT_CURRENT_CRYPT["current_warmth"], places=3)
        self.assertAlmostEqual(result["current_friction"], DEFAULT_CURRENT_CRYPT["current_friction"], places=3)

    def test_relaxes_toward_neutral_from_below_too(self):
        state = {"current_warmth": 0.1, "current_friction": 0.0}
        result = decay_current_crypt(state, elapsed_seconds=3600)
        self.assertGreater(result["current_warmth"], 0.1)
        self.assertLessEqual(result["current_warmth"], DEFAULT_CURRENT_CRYPT["current_warmth"])


class PersistenceTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def test_defaults_when_no_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            state = read_current_crypt_state()
            self.assertEqual(state["current_warmth"], DEFAULT_CURRENT_CRYPT["current_warmth"])
            self.assertEqual(state["current_friction"], DEFAULT_CURRENT_CRYPT["current_friction"])

    def test_touch_heartbeat_persists_and_returns_state(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            first = touch_current_crypt_heartbeat()
            self.assertIsNotNone(first["last_touched_at"])
            second = read_current_crypt_state()
            self.assertEqual(second["last_touched_at"], first["last_touched_at"])

    def test_apply_and_persist_delta_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            apply_and_persist_current_crypt_delta({"current_friction": 0.1})
            state = read_current_crypt_state()
            self.assertAlmostEqual(state["current_friction"], DEFAULT_CURRENT_CRYPT["current_friction"] + 0.1)


class NudgeFromPartcoreTests(unittest.TestCase):
    def _isolated_root(self, tmp):
        return patch.dict("os.environ", {"MAI_APP_ROOT": tmp})

    def test_crash_snap_raises_friction(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Crash", "snap", "[crash:snap]"), secondary=[])
            state = nudge_from_partcore(result)
            self.assertGreater(state["current_friction"], DEFAULT_CURRENT_CRYPT["current_friction"])

    def test_crash_crash_raises_friction_more_than_annoyed(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            annoyed = nudge_from_partcore(PartcoreResult(active=PartVote("Crash", "annoyed", ""), secondary=[]))
        with tempfile.TemporaryDirectory() as tmp2, self._isolated_root(tmp2):
            crashed = nudge_from_partcore(PartcoreResult(active=PartVote("Crash", "crash", ""), secondary=[]))
        self.assertGreater(crashed["current_friction"], annoyed["current_friction"])

    def test_bond_engage_raises_warmth(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            result = PartcoreResult(active=PartVote("Bond", "engage", ""), secondary=[])
            state = nudge_from_partcore(result)
            self.assertGreater(state["current_warmth"], DEFAULT_CURRENT_CRYPT["current_warmth"])

    def test_no_active_part_leaves_state_untouched(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            before = read_current_crypt_state()
            nudge_from_partcore(PartcoreResult(active=None, secondary=[]))
            after = read_current_crypt_state()
            self.assertEqual(before["current_warmth"], after["current_warmth"])
            self.assertEqual(before["current_friction"], after["current_friction"])

    def test_familiar_active_is_not_a_warmth_signal(self):
        with tempfile.TemporaryDirectory() as tmp, self._isolated_root(tmp):
            before = read_current_crypt_state()
            nudge_from_partcore(PartcoreResult(active=PartVote("Familiar", "engage", ""), secondary=[]))
            after = read_current_crypt_state()
            self.assertEqual(before["current_warmth"], after["current_warmth"])


if __name__ == "__main__":
    unittest.main()
