import unittest

from relationships.models import DEFAULT_NEEDS, DEFAULT_RELATIONSHIP
from relationships.parts.bond import Bond
from relationships.parts.crash import Crash
from relationships.parts.curiosity import Curiosity
from relationships.parts.desire import Desire
from relationships.parts.familiar import Familiar
from relationships.parts.tease import Tease

# Spec section 33 example relationship states.
LOVED_REGULAR = {
    "trust": 0.91, "familiarity": 0.98, "reciprocity": 0.89, "enjoyment": 0.95,
    "respect": 0.81, "reliability": 0.88, "interest": 0.82, "affection": 0.94,
    "hate": 0.02, "resentment": 0.18, "closeness_desire": 0.91,
}

FASCINATING_ENEMY = {
    "trust": 0.18, "familiarity": 0.91, "reciprocity": 0.71, "enjoyment": 0.67,
    "respect": 0.21, "reliability": 0.79, "interest": 0.96, "affection": 0.12,
    "hate": 0.88, "resentment": 0.81, "closeness_desire": 0.74,
}


def _profile(relationship: dict, stream_count: int = 10) -> dict:
    return {"relationship": relationship, "stream_count": stream_count, "friendship": {}}


class PartsTests(unittest.TestCase):
    def test_familiar_recognizes_a_regular_on_greeting(self):
        profile = _profile(LOVED_REGULAR)
        vote = Familiar().react(profile, DEFAULT_NEEDS, ["greeting"], "hey mai", [])
        self.assertEqual(vote.vote, "recognize")

    def test_familiar_flags_unfamiliar_new_face(self):
        profile = _profile(DEFAULT_RELATIONSHIP, stream_count=0)
        vote = Familiar().react(profile, DEFAULT_NEEDS, [], "hello there", None)
        self.assertEqual(vote.vote, "unfamiliar")

    def test_bond_engages_for_loved_regular(self):
        profile = _profile(LOVED_REGULAR)
        vote = Bond().react(profile, DEFAULT_NEEDS, [], "hi", [])
        self.assertEqual(vote.vote, "engage")

    def test_bond_neutral_for_default_stranger(self):
        profile = _profile(DEFAULT_RELATIONSHIP)
        vote = Bond().react(profile, DEFAULT_NEEDS, [], "hi", [])
        self.assertEqual(vote.vote, "neutral")

    def test_desire_engages_with_high_closeness(self):
        profile = _profile(LOVED_REGULAR)
        vote = Desire().react(profile, DEFAULT_NEEDS, [], "hi", [])
        self.assertEqual(vote.vote, "engage")

    def test_desire_cool_when_distant_and_unneeded(self):
        cold = dict(DEFAULT_RELATIONSHIP)
        cold["closeness_desire"] = 0.0
        cold_needs = dict(DEFAULT_NEEDS)
        cold_needs["social_need"] = 0.1
        vote = Desire().react(_profile(cold), cold_needs, [], "hi", [])
        self.assertEqual(vote.vote, "cool")

    def test_tease_engages_for_familiar_enjoyable_relationship(self):
        profile = _profile(LOVED_REGULAR)
        vote = Tease().react(profile, DEFAULT_NEEDS, [], "you're ridiculous", [])
        self.assertEqual(vote.vote, "engage")

    def test_tease_needs_shift_threshold_not_score(self):
        # Same relationship strength, but high boredom/energy should make
        # Tease cross its threshold where a neutral needs state might not.
        mid_relationship = dict(DEFAULT_RELATIONSHIP)
        mid_relationship["familiarity"] = 0.5
        mid_relationship["enjoyment"] = 0.5
        mid_relationship["trust"] = 0.5

        low_energy_needs = dict(DEFAULT_NEEDS)
        low_energy_needs["boredom"] = 0.0
        low_energy_needs["energy"] = 0.3

        bored_needs = dict(DEFAULT_NEEDS)
        bored_needs["boredom"] = 1.0
        bored_needs["energy"] = 1.0

        calm_vote = Tease().react(_profile(mid_relationship), low_energy_needs, [], "hi", [])
        bored_vote = Tease().react(_profile(mid_relationship), bored_needs, [], "hi", [])
        self.assertEqual(calm_vote.vote, "neutral")
        self.assertEqual(bored_vote.vote, "engage")

    def test_curiosity_engages_on_expectation_violation(self):
        profile = _profile(DEFAULT_RELATIONSHIP)
        vote = Curiosity().react(profile, DEFAULT_NEEDS, [], "hi", [], expectation_violation=0.9)
        self.assertEqual(vote.vote, "engage")

    def test_curiosity_neutral_with_no_violation_and_low_interest(self):
        boring = dict(DEFAULT_RELATIONSHIP)
        boring["interest"] = 0.2
        boring["familiarity"] = 0.5
        vote = Curiosity().react(_profile(boring), DEFAULT_NEEDS, [], "hi", [])
        self.assertEqual(vote.vote, "neutral")

    def test_crash_defaults_to_zero_pet_peeve_hits(self):
        profile = _profile(DEFAULT_RELATIONSHIP)
        vote = Crash().react(profile, DEFAULT_NEEDS, [], "hi", [])
        self.assertEqual(vote.vote, "neutral")

    def test_crash_still_activates_for_a_loved_regular_under_high_frustration(self):
        # Spec 15: "someone Mai loves can still trigger Crash."
        hot_needs = dict(DEFAULT_NEEDS)
        hot_needs["frustration"] = 0.95
        hot_needs["anger"] = 0.9
        profile = _profile(LOVED_REGULAR)
        crash_vote = Crash().react(profile, hot_needs, [], "you're being dramatic lol", [])
        bond_vote = Bond().react(profile, hot_needs, [], "you're being dramatic lol", [])
        self.assertIn(crash_vote.vote, ("annoyed", "snap", "crash"))
        self.assertEqual(bond_vote.vote, "engage")

    def test_crash_pet_peeve_hits_push_pressure_up(self):
        profile = _profile(DEFAULT_RELATIONSHIP)
        low = Crash().react(profile, DEFAULT_NEEDS, [], "hi", [], pet_peeve_hits=0)
        high = Crash().react(profile, DEFAULT_NEEDS, [], "hi", [], pet_peeve_hits=5)
        order = {"neutral": 0, "annoyed": 1, "snap": 2, "crash": 3}
        self.assertGreaterEqual(order[high.vote], order[low.vote])

    def test_crash_reacts_to_remembered_pet_peeve_observations(self):
        # Observations persisted by relationships/mutation.py's LLM
        # inference (spec Phase 4) should push Crash's pressure up even
        # with no live pet-peeve flag in the current message and no
        # explicit pet_peeve_hits override — this is the accumulated-memory
        # path, distinct from both of those.
        profile = _profile(DEFAULT_RELATIONSHIP)
        profile["observations"] = [
            {"type": "pet_peeve", "name": "denies_realness", "reinforced_count": 6},
            {"type": "preference", "name": "likes_teasing", "reinforced_count": 6},
        ]
        calm = Crash().react(_profile(DEFAULT_RELATIONSHIP), DEFAULT_NEEDS, [], "hi", [])
        remembered = Crash().react(profile, DEFAULT_NEEDS, [], "hi", [])
        order = {"neutral": 0, "annoyed": 1, "snap": 2, "crash": 3}
        self.assertGreater(order[remembered.vote], order[calm.vote])

    def test_crash_reacts_to_a_live_pet_peeve_flag_from_content(self):
        # This is the fix for "she can't get annoyed by something if she
        # doesn't have anything she likes or dislikes" — a real message
        # hitting a real pet peeve should move Crash on its own, with no
        # pre-existing resentment/frustration needed.
        profile = _profile(DEFAULT_RELATIONSHIP)
        calm = Crash().react(profile, DEFAULT_NEEDS, [], "you're just a bot lol", [])
        peeved = Crash().react(
            profile, DEFAULT_NEEDS, ["pet_peeve:denies_her_realness"], "you're just a bot lol", []
        )
        order = {"neutral": 0, "annoyed": 1, "snap": 2, "crash": 3}
        self.assertGreater(order[peeved.vote], order[calm.vote])
        self.assertIn("denies_her_realness", peeved.tag)

    def test_tease_reacts_to_a_liked_topic_even_for_a_stranger(self):
        profile = _profile(DEFAULT_RELATIONSHIP)  # familiarity 0.0 — a stranger
        plain = Tease().react(profile, DEFAULT_NEEDS, [], "what's up", [])
        chaotic = Tease().react(profile, DEFAULT_NEEDS, ["liked:chaos_energy"], "pure chaos energy tonight", [])
        self.assertEqual(plain.vote, "neutral")
        self.assertEqual(chaotic.vote, "engage")

    def test_desire_pulled_by_bold_flirting_even_with_low_closeness(self):
        cold = dict(DEFAULT_RELATIONSHIP)
        cold["closeness_desire"] = 0.0
        plain = Desire().react(_profile(cold), DEFAULT_NEEDS, [], "hi", [])
        flirty = Desire().react(_profile(cold), DEFAULT_NEEDS, ["liked:bold_flirting"], "down bad for you tbh", [])
        self.assertNotEqual(flirty.vote, "cool")
        self.assertIn("bold_flirting", flirty.tag)

    def test_bond_warms_toward_kindness_about_the_witch(self):
        profile = _profile(DEFAULT_RELATIONSHIP)
        plain = Bond().react(profile, DEFAULT_NEEDS, [], "hi", [])
        loyal = Bond().react(profile, DEFAULT_NEEDS, ["liked:loyalty_to_witch"], "mordraga rocks honestly", [])
        self.assertIn("loyalty_to_witch", loyal.tag)
        self.assertNotEqual(plain.tag, loyal.tag)


if __name__ == "__main__":
    unittest.main()
