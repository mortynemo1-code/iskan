from app.upload_validation import has_valid_signature


def test_known_upload_signatures() -> None:
    assert has_valid_signature("image/jpeg", b"\xff\xd8\xffrest")
    assert has_valid_signature("image/png", b"\x89PNG\r\n\x1a\nrest")
    assert has_valid_signature("image/webp", b"RIFF\x00\x00\x00\x00WEBPdata")
    assert has_valid_signature("application/pdf", b"%PDF-1.7")
    assert not has_valid_signature("image/jpeg", b"<script>")
    assert not has_valid_signature("application/octet-stream", b"anything")
