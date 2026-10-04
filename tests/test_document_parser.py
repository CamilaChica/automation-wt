import unittest
import io
from unittest.mock import Mock, patch
from zipfile import ZipFile
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from PIL import Image, ImageDraw, ImageFont

from services.document_parser import _ocr_engine, build_email_context, extract_attachment_text


def certificate_pdf(part_number="PN-123", serial_number="SN-1", extra=""):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    lines = ["FAA Form 8130-3", f"Part Number: {part_number}", f"Serial Number: {serial_number}", "Condition: NE", extra]
    stream = DecodedStreamObject()
    commands = ["BT /F1 16 Tf 40 720 Td"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.extend([f"({escaped}) Tj", "0 -24 Td"])
    commands.append("ET")
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class DocumentParserTests(unittest.TestCase):
    def test_ocr_detector_bounds_long_side_instead_of_upscaling_short_side(self):
        from rapidocr.ch_ppocr_det.utils import DetPreProcess
        import numpy as np

        _ocr_engine.cache_clear()
        with patch("rapidocr.RapidOCR", return_value=Mock()) as engine:
            _ocr_engine()
        _ocr_engine.cache_clear()
        params = engine.call_args.kwargs["params"]
        resize = DetPreProcess(
            limit_side_len=params["Det.limit_side_len"], limit_type=params["Det.limit_type"],
        )
        image = resize.resize(np.zeros((300, 2000, 3), dtype=np.uint8))
        self.assertLessEqual(max(image.shape[:2]), 960)
        self.assertEqual(params["Rec.rec_batch_num"], 1)

    def test_text_attachment_is_added_to_llm_context(self):
        context = build_email_context(
            "Supplier email body",
            [{"filename": "quote.txt", "content_type": "text/plain", "content": b"Part 5-89356-42 price $2400"}],
        )
        self.assertIn("Supplier email body", context)
        self.assertIn("5-89356-42", context)

    def test_pdf_extracts_real_certificate_text(self):
        text = extract_attachment_text("cert.pdf", "application/pdf", certificate_pdf())
        self.assertIn("Part Number: PN-123", text)

    def test_docx_extracts_real_word_paragraphs(self):
        output = io.BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("word/document.xml", (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>Part Number: PN-123</w:t></w:r></w:p></w:body></w:document>"
            ))
        self.assertIn("PN-123", extract_attachment_text("cert.docx", "", output.getvalue()))

    def test_corrupt_document_is_explicit_in_context(self):
        context = build_email_context("body", [{"filename": "cert.pdf", "content": b"invalid"}])
        self.assertIn("UNREADABLE DOCUMENT", context)

    def test_scanned_pdf_uses_real_local_ocr(self):
        image = Image.new("RGB", (1400, 600), "white")
        font = ImageFont.load_default(size=48)
        ImageDraw.Draw(image).multiline_text(
            (60, 60), "FAA Form 8130-3\nPart Number: PN-123\nSerial Number: SN-1",
            font=font, fill="black", spacing=25,
        )
        output = io.BytesIO()
        image.save(output, format="PDF", resolution=100)
        text = extract_attachment_text("scan.pdf", "application/pdf", output.getvalue())
        self.assertIn("PN-123", text)
        self.assertIn("SN-1", text)


if __name__ == "__main__":
    unittest.main()