from relationship_test_base import RelationshipTestCase

from relationships import relationship_core
from relationships import state


class RelationshipCoreRoundTripTests(RelationshipTestCase):
    def test_build_cognitive_context_returns_text_and_partcore_result(self):
        context_text, partcore_result = relationship_core.build_cognitive_context(
            username="Nova",
            message="hey Mai!",
            recent_messages=["hi", "hows it going"],
            task="general",
            owner_username="mordraga",
        )
        self.assertIsInstance(context_text, str)
        self.assertIn("[relationship]", context_text)
        self.assertIsNotNone(partcore_result)

    def test_post_response_update_persists_positive_signal(self):
        before = state.get_relationship("Nova")["affection"]
        relationship_core.post_response_update(
            username="Nova",
            message="I love you Mai, you're the best",
            response="aw, you flatterer",
            task="general",
            partcore_result=None,
        )
        after = state.get_relationship("Nova")["affection"]
        self.assertGreater(after, before)

    def test_post_response_update_hostility_raises_resentment_and_lowers_trust(self):
        before = state.get_relationship("Grump")
        relationship_core.post_response_update(
            username="Grump",
            message="shut up you stupid bot",
            response="...",
            task="general",
            partcore_result=None,
        )
        after = state.get_relationship("Grump")
        self.assertGreater(after["resentment"], before["resentment"])
        self.assertLess(after["trust"], before["trust"])

    def test_mutation_is_not_double_applied_across_two_separate_turns(self):
        relationship_core.post_response_update(
            username="OnceOnly", message="love you mai", response="hi", task="general", partcore_result=None,
        )
        after_first = state.get_relationship("OnceOnly")["affection"]
        # A second, unrelated neutral turn should not re-apply the first turn's delta again.
        relationship_core.post_response_update(
            username="OnceOnly", message="what time is it", response="dunno", task="general", partcore_result=None,
        )
        after_second = state.get_relationship("OnceOnly")["affection"]
        self.assertEqual(after_first, after_second)

    def test_observe_event_follow_nudges_familiarity(self):
        before = state.get_relationship("NewFollower")["familiarity"]
        relationship_core.observe_event("NewFollower", "follow")
        after = state.get_relationship("NewFollower")["familiarity"]
        self.assertGreater(after, before)

    def test_observe_event_command_cooldown_blocked_eventually_flags_pet_peeve(self):
        for _ in range(3):
            relationship_core.observe_event("Spammer", "command_cooldown_blocked")
        record = state.load_user_record("Spammer")
        pet_peeves = [o for o in record["observations"] if o.get("type") == "pet_peeve"]
        self.assertEqual(len(pet_peeves), 1)
