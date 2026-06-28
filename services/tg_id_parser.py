from dataclasses import dataclass
from typing import List, Optional, Union


@dataclass
class TgFileRef:
    chat_id: Union[int, str]
    message_ids: List[int]
    is_split: bool = False
    is_split_zip: bool = False
    is_zip: bool = False
    zip_entry_filename: Optional[str] = None


def _parse_chat_id(chat_id: str) -> Union[int, str]:
    try:
        return int(chat_id)
    except ValueError:
        return chat_id


def parse_tg_id(tg_id: str) -> Optional[TgFileRef]:
    if not tg_id.startswith("tgfile_"):
        return None

    zip_entry_filename = None
    base_id = tg_id
    if "//" in tg_id:
        base_id, zip_entry_filename = tg_id.split("//", 1)

    parts = base_id.split("_")
    if len(parts) < 3:
        return None

    ref = TgFileRef(
        chat_id="",
        message_ids=[],
        zip_entry_filename=zip_entry_filename or None,
    )

    if parts[1] == "splitzip":
        if len(parts) < 4:
            return None
        ref.is_split = True
        ref.is_split_zip = True
        ref.is_zip = True
        ref.chat_id = _parse_chat_id(parts[2])
        ref.message_ids = _parse_message_ids(parts[3])
    elif parts[1] == "split":
        if len(parts) < 4:
            return None
        ref.is_split = True
        ref.chat_id = _parse_chat_id(parts[2])
        ref.message_ids = _parse_message_ids(parts[3])
    elif parts[1] == "zip":
        if len(parts) < 4:
            return None
        ref.is_zip = True
        ref.chat_id = _parse_chat_id(parts[2])
        ref.message_ids = _parse_message_ids(parts[3])
    else:
        ref.chat_id = _parse_chat_id(parts[1])
        ref.message_ids = _parse_message_ids(parts[2])

    if not ref.message_ids:
        return None

    return ref


def _parse_message_ids(msg_ids_str: str) -> List[int]:
    return [int(x) for x in msg_ids_str.split(",") if x.strip().isdigit()]
