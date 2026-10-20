from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.document_processor import extract_local_document


def test_extract_local_document_reads_advertised_text_formats(tmp_path):
    for filename, body, language in (
        ("config.yaml", "service:\n  enabled: true\n", "yaml"),
        ("script.sh", "#!/bin/sh\necho ready\n", "bash"),
        ("settings.xml", "<settings enabled=\"true\"/>\n", "xml"),
    ):
        path = tmp_path / filename
        path.write_text(body, encoding="utf-8")

        result = extract_local_document(str(path))

        assert body.strip() in result
        assert f"```{language}" in result
        assert "[Attached document file]" not in result


def test_extract_local_document_reads_real_pdf_text(tmp_path):
    path = tmp_path / "brief.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 72 720 Td (Odysseus PDF extraction smoke 2026) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)

    result = extract_local_document(str(path))

    assert "[PDF content]" in result
    assert "Odysseus PDF extraction smoke 2026" in result
