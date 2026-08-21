SIGNATURES = {
    "application/pdf": lambda data: data.startswith(b"%PDF-"),
    "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
    "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/webp": lambda data: len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    "application/zip": lambda data: data.startswith(b"PK\x03\x04"),
    "application/x-msi": lambda data: data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")),
}


def has_valid_signature(content_type: str, data: bytes) -> bool:
    validator = SIGNATURES.get(content_type)
    return validator is not None and validator(data)
