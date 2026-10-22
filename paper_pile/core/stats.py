"""Numbers for the status bar: how many words a note has."""

from paper_pile.core.parser import body_start


def word_count(text: str) -> int:
    """Words in the note's body (front matter left out): runs of non-space characters that hold
    at least one letter or digit, so markdown marks (``#``, ``-``, ``>``, ``|``) do not count and
    any script (Bengali vowel signs included) does."""
    body = text[body_start(text) :]
    return sum(1 for token in body.split() if any(c.isalnum() for c in token))
