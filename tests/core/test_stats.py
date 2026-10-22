from paper_pile.core.stats import word_count


def test_words_skip_front_matter_and_marks() -> None:
    assert word_count("---\ntitle: Many words here\n---\n# Hello world\n\n- one\n> two\n") == 4
    assert word_count("| a | b |\n| --- | --- |\n") == 2
    assert word_count("আমি বাংলায় লিখি") == 3
    assert word_count("") == 0
    assert word_count("---\n---\n") == 0
