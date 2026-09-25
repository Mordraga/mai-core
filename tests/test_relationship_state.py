from relationship_test_base import RelationshipTestCase

from relationships import state
from relationships.models import RELATIONSHIP_DEFAULTS


class RelationshipStateTests(RelationshipTestCase):
    def test_defaults_applied_for_new_user(self):
        record = state.load_user_record("brand_new_user")
        self.assertEqual(record["relationship"], RELATIONSHIP_DEFAULTS)
        self.assertEqual(record["observations"], [])
        self.assertFalse(record["restrictions"]["explicit_minor"])

    def test_migration_preserves_existing_fields_and_adds_defaults(self):
        legacy_record = {
            "username": "legacy_user",
            "messages": [{"message": "hi", "timestamp": 1.0}],
            "stream_count": 5,
        }
        migrated = state.migrate_user_record(legacy_record, "legacy_user")
        self.assertEqual(migrated["stream_count"], 5)
        self.assertEqual(migrated["messages"], legacy_record["messages"])
        self.assertEqual(migrated["relationship"]["trust"], 0.5)

    def test_update_relationship_clamps_to_bounds(self):
        state.update_relationship("clamp_user", {"trust": 10.0, "hate": -10.0})
        relationship = state.get_relationship("clamp_user")
        self.assertEqual(relationship["trust"], 1.0)
        self.assertEqual(relationship["hate"], 0.0)

    def test_update_relationship_is_incremental(self):
        state.update_relationship("inc_user", {"affection": 0.1})
        state.update_relationship("inc_user", {"affection": 0.1})
        relationship = state.get_relationship("inc_user")
        self.assertAlmostEqual(relationship["affection"], 0.2, places=6)

    def test_add_observation_persists_and_caps(self):
        for i in range(5):
            state.add_observation("obs_user", {"type": "pet_peeve", "salience": 0.5, "index": i})
        record = state.load_user_record("obs_user")
        self.assertEqual(len(record["observations"]), 5)
        self.assertEqual(record["observations"][-1]["index"], 4)

    def test_derive_friendship_does_not_mutate_primitives(self):
        state.update_relationship("friend_user", {"trust": 0.2, "affection": 0.3})
        friendship = state.sync_friendship("friend_user")
        relationship = state.get_relationship("friend_user")
        self.assertIn("utility", friendship)
        self.assertIn("pleasure", friendship)
        self.assertIn("virtue", friendship)
        # primitives unchanged by deriving friendship dims
        self.assertAlmostEqual(relationship["trust"], 0.7, places=6)

    def test_list_known_usernames(self):
        state.load_user_record("a")
        state.save_user_record("a", state.load_user_record("a"))
        state.save_user_record("b", state.load_user_record("b"))
        usernames = set(state.list_known_usernames())
        self.assertEqual(usernames, {"a", "b"})
