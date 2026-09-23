"""Real Poppler/Tesseract integration; no external API or source PDF is required."""
import re
import shutil
import subprocess

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from special_situations.config import Config
from special_situations.documents import extract


@pytest.mark.skipif(not (shutil.which("pdftoppm") and shutil.which("tesseract")), reason="OCR binaries unavailable")
def test_real_image_only_pdf_ocr(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 20 Tf 45 700 Td (The board approved a scheme of demerger.) Tj 0 -30 Td "
                    b"(Shareholder approval is still required.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    text_pdf = tmp_path / "text.pdf"
    writer.write(text_pdf)
    assert extract(text_pdf, Config())["method"] == "text"
    subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-r", "120", "-gray",
                    str(text_pdf), str(tmp_path / "scan")], check=True, capture_output=True, timeout=60)
    data = (tmp_path / "scan.pgm").read_bytes()
    match = re.match(rb"P5\s+(\d+)\s+(\d+)\s+255\s", data)
    assert match
    width, height = map(int, match.groups())
    image = DecodedStreamObject()
    image.set_data(data[match.end():])
    image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                  NameObject("/Width"): NumberObject(width), NameObject("/Height"): NumberObject(height),
                  NameObject("/ColorSpace"): NameObject("/DeviceGray"), NameObject("/BitsPerComponent"): NumberObject(8)})
    scanned = PdfWriter()
    scanned_page = scanned.add_blank_page(width=612, height=792)
    scanned_page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({
        NameObject("/Scan"): scanned._add_object(image)})})
    stream = DecodedStreamObject()
    stream.set_data(b"q 612 0 0 792 0 0 cm /Scan Do Q")
    scanned_page[NameObject("/Contents")] = scanned._add_object(stream)
    scanned_path = tmp_path / "scanned.pdf"
    scanned.write(scanned_path)
    assert not PdfReader(scanned_path).pages[0].extract_text().strip()
    recovered = extract(scanned_path, Config())
    assert recovered["method"] == "ocr"
    assert "scheme of demerger" in recovered["text"]
