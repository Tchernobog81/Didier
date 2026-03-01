import unittest

from core.text_compaction import compact_text
from core.text_compaction import split_sentences
from core.text_compaction import text_stats


class TextCompactionTests(unittest.TestCase):
    def test_split_sentences_handles_basic_punctuation(self) -> None:
        text = "Salut. Comment ca va ? Bien."
        self.assertEqual(split_sentences(text), ["Salut.", "Comment ca va ?", "Bien."])

    def test_text_stats_counts_chars_words_and_sentences(self) -> None:
        stats = text_stats("Salut Didier. Tu vas bien ?")
        self.assertEqual(stats["chars"], len("Salut Didier. Tu vas bien ?"))
        self.assertEqual(stats["words"], 6)
        self.assertEqual(stats["sentences"], 2)

    def test_compact_text_limits_sentences(self) -> None:
        text = "Une phrase. Deuxieme phrase. Troisieme phrase."
        compact = compact_text(text, max_sentences=2, max_chars=200)
        self.assertEqual(compact, "Une phrase. Deuxieme phrase.")

    def test_compact_text_limits_chars_and_adds_period(self) -> None:
        text = "Didier donne une reponse beaucoup trop longue pour ce budget de caracteres"
        compact = compact_text(text, max_sentences=3, max_chars=35)
        self.assertLessEqual(len(compact), 36)  # one extra char for trailing period when needed
        self.assertTrue(compact.endswith("."))


if __name__ == "__main__":
    unittest.main()
