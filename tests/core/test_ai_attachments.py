import pytest

from paper_pile.core.ai.attachments import MAX_FILE_BYTES, AttachmentError, read_text_file


def test_text_file_is_read() -> None:
    ref = read_text_file("a.md", "héllo\n".encode())
    assert ref.name == "a.md" and ref.text == "héllo\n" and ref.size() == "<1 KB"


def test_bom_is_dropped() -> None:
    assert read_text_file("a.txt", b"\xef\xbb\xbfhi").text == "hi"


@pytest.mark.parametrize(
    "data",
    [b"x" * (MAX_FILE_BYTES + 1), b"ab\x00cd", b"\xff\xfe\xfa", b"  \n"],
    ids=["large", "binary", "not-utf8", "empty"],
)
def test_unusable_files_are_refused(data: bytes) -> None:
    with pytest.raises(AttachmentError):
        read_text_file("f", data)
