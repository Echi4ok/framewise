def content_length_exceeds(value: str | bytes | None, limit: int) -> bool:
    """Compare an untrusted decimal header without parsing an unbounded integer."""
    if value is None:
        return False
    text = value.decode("latin-1") if isinstance(value, bytes) else value
    if not text.isascii() or not text.isdecimal():
        return False
    digits = text.lstrip("0") or "0"
    threshold = str(limit)
    return (len(digits), digits) > (len(threshold), threshold)
