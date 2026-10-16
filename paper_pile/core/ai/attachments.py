"""Files attached to a chat message (nothing is saved: the text is read once and sent as context).

Only text is accepted: a binary file or one that is too large is refused with a reason the UI can
show. No UI imports here.
"""

from dataclasses import dataclass

MAX_FILE_BYTES = 200 * 1024


class AttachmentError(ValueError):
    """The file cannot be attached; the message says why."""


@dataclass(frozen=True, slots=True)
class FileRef:
    name: str
    text: str

    def size(self) -> str:
        kb = len(self.text.encode("utf-8")) / 1024
        return f"{kb:.0f} KB" if kb >= 1 else "<1 KB"


def read_text_file(name: str, data: bytes) -> FileRef:
    """Decode an uploaded file as text (UTF-8), or say why it cannot be used."""
    if len(data) > MAX_FILE_BYTES:
        raise AttachmentError(f"{name} is larger than {MAX_FILE_BYTES // 1024} KB.")
    if b"\x00" in data:
        raise AttachmentError(f"{name} is not a text file.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AttachmentError(f"{name} is not UTF-8 text.") from None
    if not text.strip():
        raise AttachmentError(f"{name} is empty.")
    return FileRef(name, text)
