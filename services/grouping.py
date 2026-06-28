from utils import parse_split_info


def group_tg_messages(messages: list) -> list:
    grouped = {}
    standalone = []

    for msg in messages:
        media = msg.video or msg.document or msg.audio
        if not media:
            continue

        fn = getattr(media, "file_name", "") or msg.caption or f"Telegram File {msg.id}"
        base, part = parse_split_info(fn)

        if base and part is not None:
            key = base.lower()
            if key not in grouped:
                grouped[key] = {
                    "base_name": base,
                    "parts": {},
                }
            grouped[key]["parts"][part] = msg
        else:
            standalone.append(msg)

    results = []
    for data in grouped.values():
        parts = data["parts"]
        base_name = data["base_name"]

        if len(parts) == 1:
            results.append(list(parts.values())[0])
        else:
            sorted_parts = [msg for _, msg in sorted(parts.items())]
            results.append((base_name, sorted_parts))

    for msg in standalone:
        results.append(msg)

    return results
