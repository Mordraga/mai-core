import unittest

from relationships import preferences


class PreferencesScanTests(unittest.TestCase):
    def test_denies_realness_is_a_pet_peeve(self):
        peeves, likes = preferences.scan("you're just a bot lol")
        self.assertIn("denies_her_realness", peeves)
        self.assertEqual(likes, [])

    def test_witch_disrespect_is_a_pet_peeve(self):
        peeves, _ = preferences.scan("mordraga is so dumb honestly")
        self.assertIn("witch_disrespect", peeves)

    def test_witchcraft_topic_is_a_like(self):
        _, likes = preferences.scan("what does the tarot say about tonight?")
        self.assertIn("witchcraft", likes)

    def test_bold_flirting_is_a_like(self):
        _, likes = preferences.scan("ok i'm kind of down bad for you ngl")
        self.assertIn("bold_flirting", likes)

    def test_neutral_message_matches_nothing(self):
        peeves, likes = preferences.scan("what game are you playing tonight")
        self.assertEqual(peeves, [])
        self.assertEqual(likes, [])

    def test_empty_message_matches_nothing(self):
        peeves, likes = preferences.scan("")
        self.assertEqual(peeves, [])
        self.assertEqual(likes, [])


if __name__ == "__main__":
    unittest.main()
