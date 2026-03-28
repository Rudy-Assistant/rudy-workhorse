import pytest
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path
import json
import sys

import rudy.ocr as mod

# Mock external libraries at import time to avoid ImportError in module
sys.modules["easyocr"] = MagicMock()
sys.modules["pdfplumber"] = MagicMock()
sys.modules["PyPDF2"] = MagicMock()
sys.modules["docx2txt"] = MagicMock()
sys.modules["docx"] = MagicMock()
sys.modules["striprtf"] = MagicMock()
sys.modules["striprtf.striprtf"] = MagicMock()
sys.modules["ebooklib"] = MagicMock()
sys.modules["ebooklib.epub"] = MagicMock()
sys.modules["bs4"] = MagicMock()
sys.modules["pptx"] = MagicMock()


class TestImageOCR:
    """Tests for ImageOCR class."""

    def test_init_default_languages(self):
        """Test ImageOCR initialization with default languages."""
        ocr = mod.ImageOCR()
        assert ocr.languages == ["en"]
        assert ocr._reader is None

    def test_init_custom_languages(self):
        """Test ImageOCR initialization with custom languages."""
        ocr = mod.ImageOCR(languages=["en", "fr", "de"])
        assert ocr.languages == ["en", "fr", "de"]

    def test_get_reader_success(self):
        """Test _get_reader successfully imports and caches easyocr."""
        mock_reader = MagicMock()
        with patch("easyocr.Reader", return_value=mock_reader):
            ocr = mod.ImageOCR(languages=["en"])
            reader = ocr._get_reader()

            assert reader is mock_reader

    def test_get_reader_import_error(self):
        """Test _get_reader raises RuntimeError when easyocr not installed."""
        with patch("builtins.__import__", side_effect=ImportError):
            ocr = mod.ImageOCR()
            with pytest.raises(RuntimeError, match="easyocr not installed"):
                ocr._get_reader()

    def test_get_reader_caches_reader(self):
        """Test _get_reader caches the reader instance."""
        mock_reader = MagicMock()
        with patch("easyocr.Reader", return_value=mock_reader) as mock_reader_class:
            ocr = mod.ImageOCR()
            reader1 = ocr._get_reader()
            reader2 = ocr._get_reader()

            assert reader1 is reader2
            # Reader should only be created once
            assert mock_reader_class.call_count == 1

    def test_read_image_with_results(self):
        """Test read_image with valid OCR results."""
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([(0, 0), (100, 0), (100, 50), (0, 50)], "Hello", 0.95),
            ([(0, 60), (100, 60), (100, 110), (0, 110)], "World", 0.92),
        ]

        with patch("easyocr.Reader", return_value=mock_reader):
            ocr = mod.ImageOCR()
            result = ocr.read_image("test.png", detail=True)

            assert result["text"] == "Hello World"
            assert result["confidence"] == 0.935  # (0.95 + 0.92) / 2
            assert result["block_count"] == 2
            assert len(result["blocks"]) == 2
            assert result["blocks"][0]["text"] == "Hello"
            assert result["blocks"][0]["confidence"] == 0.95
            assert result["source"] == "test.png"

    def test_read_image_without_detail(self):
        """Test read_image with detail=False."""
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([(0, 0), (100, 0), (100, 50), (0, 50)], "Hello", 0.95),
        ]

        with patch("easyocr.Reader", return_value=mock_reader):
            ocr = mod.ImageOCR()
            result = ocr.read_image("test.png", detail=False)

            assert result["text"] == "Hello"
            assert result["blocks"] == []
            assert result["block_count"] == 1

    def test_read_image_empty_result(self):
        """Test read_image with no results."""
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = []

        with patch("easyocr.Reader", return_value=mock_reader):
            ocr = mod.ImageOCR()
            result = ocr.read_image("blank.png")

            assert result["text"] == ""
            assert result["confidence"] == 0
            assert result["block_count"] == 0

    def test_read_image_bbox_rounding(self):
        """Test read_image correctly rounds bounding box coordinates."""
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([(0.5, 1.7), (100.3, 0.2), (100.9, 50.1), (0.1, 50.8)], "Text", 0.88),
        ]

        with patch("easyocr.Reader", return_value=mock_reader):
            ocr = mod.ImageOCR()
            result = ocr.read_image("test.png")

            bbox = result["blocks"][0]["bbox"]
            assert bbox == [[0, 1], [100, 0], [100, 50], [0, 50]]

    def test_read_batch(self):
        """Test read_batch processes multiple images."""
        mock_reader = MagicMock()
        mock_reader.readtext.side_effect = [
            [([(0, 0), (100, 0), (100, 50), (0, 50)], "Image1", 0.9)],
            [([(0, 0), (100, 0), (100, 50), (0, 50)], "Image2", 0.85)],
        ]

        with patch("easyocr.Reader", return_value=mock_reader):
            ocr = mod.ImageOCR()
            results = ocr.read_batch(["img1.png", "img2.png"])

            assert len(results) == 2
            assert results[0]["text"] == "Image1"
            assert results[1]["text"] == "Image2"


class TestPDFExtractor:
    """Tests for PDFExtractor class."""

    def test_extract_text_with_pdfplumber(self):
        """Test extract_text using pdfplumber."""
        mock_pdf = MagicMock()
        mock_page1 = MagicMock()
        mock_page2 = MagicMock()
        mock_page1.extract_text.return_value = "Page 1 text"
        mock_page2.extract_text.return_value = "Page 2 text"
        mock_pdf.pages = [mock_page1, mock_page2]

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_pdf
            extractor = mod.PDFExtractor()
            result = extractor.extract_text("test.pdf")

            assert result["text"] == "Page 1 text\n\nPage 2 text"
            assert result["page_count"] == 2
            assert len(result["pages"]) == 2
            assert result["pages"][0]["page"] == 1
            assert result["pages"][1]["page"] == 2
            assert result["source"] == "test.pdf"

    def test_extract_text_fallback_pypdf2(self):
        """Test extract_text falls back to PyPDF2 when pdfplumber unavailable."""
        mock_reader = MagicMock()
        mock_page1 = MagicMock()
        mock_page2 = MagicMock()
        mock_page1.extract_text.return_value = "Page 1 content"
        mock_page2.extract_text.return_value = "Page 2 content"
        mock_reader.pages = [mock_page1, mock_page2]

        with patch("pdfplumber.open", side_effect=ImportError):
            with patch("builtins.open", mock_open()):
                with patch("PyPDF2.PdfReader", return_value=mock_reader):
                    extractor = mod.PDFExtractor()
                    result = extractor.extract_text("test.pdf")

                    assert result["text"] == "Page 1 content\n\nPage 2 content"
                    assert result["page_count"] == 2

    def test_extract_text_no_libraries(self):
        """Test extract_text raises error when no PDF libraries available."""
        # Simulate both imports failing by raising ImportError
        with patch("pdfplumber.open", side_effect=ImportError):
            with patch("builtins.open", side_effect=ImportError):
                extractor = mod.PDFExtractor()
                with pytest.raises(RuntimeError, match="pdfplumber or PyPDF2 needed"):
                    extractor.extract_text("test.pdf")

    def test_extract_text_with_none_content(self):
        """Test extract_text handles pages with None content."""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = None
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_pdf
            extractor = mod.PDFExtractor()
            result = extractor.extract_text("test.pdf")

            assert result["text"] == ""
            assert result["pages"][0]["text"] == ""

    def test_extract_tables(self):
        """Test extract_tables extracts tables from PDF."""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        table_data = [["Header1", "Header2"], ["Row1Col1", "Row1Col2"]]
        mock_page.extract_tables.return_value = [table_data]
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_pdf
            extractor = mod.PDFExtractor()
            result = extractor.extract_tables("test.pdf")

            assert len(result) == 1
            assert result[0]["page"] == 1
            assert result[0]["table_index"] == 0
            assert result[0]["headers"] == ["Header1", "Header2"]
            assert result[0]["rows"] == [["Row1Col1", "Row1Col2"]]
            assert result[0]["row_count"] == 1

    def test_extract_tables_no_pdfplumber(self):
        """Test extract_tables returns error when pdfplumber not installed."""
        with patch("pdfplumber.open", side_effect=ImportError):
            extractor = mod.PDFExtractor()
            result = extractor.extract_tables("test.pdf")

            assert len(result) == 1
            assert "error" in result[0]
            assert "pdfplumber not installed" in result[0]["error"]

    def test_extract_tables_multiple_tables(self):
        """Test extract_tables with multiple tables on multiple pages."""
        mock_pdf = MagicMock()
        mock_page1 = MagicMock()
        mock_page2 = MagicMock()

        table1 = [["H1", "H2"], ["R1C1", "R1C2"]]
        table2 = [["H3", "H4"], ["R2C1", "R2C2"], ["R3C1", "R3C2"]]

        mock_page1.extract_tables.return_value = [table1]
        mock_page2.extract_tables.return_value = [table2]
        mock_pdf.pages = [mock_page1, mock_page2]

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_pdf
            extractor = mod.PDFExtractor()
            result = extractor.extract_tables("test.pdf")

            assert len(result) == 2
            assert result[0]["page"] == 1
            assert result[1]["page"] == 2
            assert result[1]["row_count"] == 2


class TestDocumentParser:
    """Tests for DocumentParser class."""

    def test_parse_unsupported_format(self):
        """Test parse returns error for unsupported file format."""
        parser = mod.DocumentParser()
        result = parser.parse("file.xyz")

        assert "error" in result
        assert "Unsupported format" in result["error"]
        assert result["source"] == "file.xyz"

    @patch.object(mod.DocumentParser, "_parse_pdf")
    def test_parse_pdf(self, mock_parse_pdf):
        """Test parse dispatches to _parse_pdf for PDF files."""
        mock_parse_pdf.return_value = {"text": "pdf content", "source": "test.pdf"}

        parser = mod.DocumentParser()
        result = parser.parse("test.pdf")

        mock_parse_pdf.assert_called_once_with("test.pdf")
        assert result["text"] == "pdf content"

    @patch.object(mod.DocumentParser, "_parse_docx")
    def test_parse_docx_extension(self, mock_parse_docx):
        """Test parse dispatches to _parse_docx for DOCX files."""
        mock_parse_docx.return_value = {"text": "docx content", "source": "test.docx"}

        parser = mod.DocumentParser()
        parser.parse("test.docx")

        mock_parse_docx.assert_called_once_with("test.docx")

    @patch.object(mod.DocumentParser, "_parse_text")
    def test_parse_txt(self, mock_parse_text):
        """Test parse dispatches to _parse_text for TXT files."""
        mock_parse_text.return_value = {"text": "txt content", "source": "test.txt"}

        parser = mod.DocumentParser()
        parser.parse("test.txt")

        mock_parse_text.assert_called_once_with("test.txt")

    @patch.object(mod.DocumentParser, "_parse_json")
    def test_parse_json(self, mock_parse_json):
        """Test parse dispatches to _parse_json for JSON files."""
        mock_parse_json.return_value = {
            "text": '{"key": "value"}',
            "source": "test.json",
            "format": "json"
        }

        parser = mod.DocumentParser()
        parser.parse("test.json")

        mock_parse_json.assert_called_once_with("test.json")

    @patch("builtins.open", new_callable=mock_open, read_data="Hello World")
    def test_parse_text_file(self, mock_file):
        """Test _parse_text reads file content."""
        parser = mod.DocumentParser()
        result = parser._parse_text("test.txt")

        assert result["text"] == "Hello World"
        assert result["source"] == "test.txt"
        assert result["format"] == "text"
        mock_file.assert_called_once_with("test.txt", encoding="utf-8", errors="replace")

    @patch("builtins.open", new_callable=mock_open)
    def test_parse_json_file(self, mock_file):
        """Test _parse_json parses JSON content."""
        json_data = {"name": "test", "value": 42}
        mock_file.return_value.__enter__.return_value.read.return_value = json.dumps(json_data)

        parser = mod.DocumentParser()
        with patch("json.load", return_value=json_data):
            result = parser._parse_json("test.json")

        assert result["source"] == "test.json"
        assert result["format"] == "json"

    def test_parse_docx_with_docx2txt(self):
        """Test _parse_docx uses docx2txt when available."""
        with patch("docx2txt.process", return_value="Document content") as mock_process:
            parser = mod.DocumentParser()
            result = parser._parse_docx("test.docx")

            assert result["text"] == "Document content"
            assert result["format"] == "docx"
            mock_process.assert_called_once_with("test.docx")

    def test_parse_docx_fallback_python_docx(self):
        """Test _parse_docx falls back to python-docx."""
        mock_doc = MagicMock()
        mock_paragraph1 = MagicMock()
        mock_paragraph2 = MagicMock()
        mock_paragraph1.text = "Paragraph 1"
        mock_paragraph2.text = "Paragraph 2"
        mock_doc.paragraphs = [mock_paragraph1, mock_paragraph2]

        with patch("docx2txt.process", side_effect=ImportError):
            with patch("docx.Document", return_value=mock_doc):
                parser = mod.DocumentParser()
                result = parser._parse_docx("test.docx")

                assert result["text"] == "Paragraph 1\nParagraph 2"
                assert result["format"] == "docx"

    def test_parse_docx_no_libraries(self):
        """Test _parse_docx returns error when no libraries available."""
        with patch("docx2txt.process", side_effect=ImportError):
            with patch("docx.Document", side_effect=ImportError):
                parser = mod.DocumentParser()
                result = parser._parse_docx("test.docx")

                assert "error" in result
                assert "docx2txt or python-docx needed" in result["error"]

    def test_parse_rtf(self):
        """Test _parse_rtf extracts text from RTF."""
        # Create a mock rtf_to_text function
        mock_rtf_to_text = MagicMock(return_value="RTF content")

        with patch("builtins.open", mock_open(read_data="{\\rtf1 test}")):
            # Patch at the module level where it will be imported
            with patch.dict("sys.modules", {"striprtf": MagicMock(), "striprtf.striprtf": MagicMock(rtf_to_text=mock_rtf_to_text)}):
                parser = mod.DocumentParser()
                result = parser._parse_rtf("test.rtf")

                assert result["text"] == "RTF content"
                assert result["format"] == "rtf"

    def test_parse_rtf_no_library(self):
        """Test _parse_rtf returns error when striprtf not installed."""
        with patch("builtins.open", mock_open(read_data="{\\rtf1 test}")):
            # Remove striprtf from sys.modules to simulate it not being installed
            with patch.dict("sys.modules", {"striprtf": None, "striprtf.striprtf": None}):
                parser = mod.DocumentParser()
                result = parser._parse_rtf("test.rtf")

                assert "error" in result
                assert "striprtf not installed" in result["error"]

    def test_parse_epub(self):
        """Test _parse_epub extracts text from EPUB."""
        mock_book = MagicMock()
        mock_item = MagicMock()
        mock_item.get_content.return_value = "<p>Chapter content</p>"
        mock_book.get_items_of_type.return_value = [mock_item]

        mock_soup = MagicMock()
        mock_soup.get_text.return_value = "Chapter content"

        with patch("ebooklib.epub.read_epub", return_value=mock_book):
            with patch("bs4.BeautifulSoup", return_value=mock_soup):
                parser = mod.DocumentParser()
                result = parser._parse_epub("test.epub")

                assert result["text"] == "Chapter content"
                assert result["format"] == "epub"

    def test_parse_pptx(self):
        """Test _parse_pptx extracts text from PowerPoint."""
        mock_prs = MagicMock()
        mock_slide = MagicMock()
        mock_shape1 = MagicMock()
        mock_shape2 = MagicMock()
        mock_shape1.has_text_frame = True
        mock_shape1.text = "Slide title"
        mock_shape2.has_text_frame = True
        mock_shape2.text = "Slide content"
        mock_slide.shapes = [mock_shape1, mock_shape2]
        mock_prs.slides = [mock_slide]

        with patch("pptx.Presentation", return_value=mock_prs):
            parser = mod.DocumentParser()
            result = parser._parse_pptx("test.pptx")

            assert "Slide title" in result["text"]
            assert "Slide content" in result["text"]
            assert result["format"] == "pptx"

    def test_parse_pptx_no_library(self):
        """Test _parse_pptx returns error when python-pptx not installed."""
        with patch("pptx.Presentation", side_effect=ImportError):
            parser = mod.DocumentParser()
            result = parser._parse_pptx("test.pptx")

            assert "error" in result
            assert "python-pptx not installed" in result["error"]

    def test_parse_html_with_beautifulsoup(self):
        """Test _parse_html uses BeautifulSoup when available."""
        mock_soup = MagicMock()
        mock_soup.return_value = []  # Return empty list when called with tag selector
        mock_soup.get_text.return_value = "HTML content"

        with patch("builtins.open", mock_open(read_data="<html><body>Test</body></html>")):
            with patch("bs4.BeautifulSoup", return_value=mock_soup):
                parser = mod.DocumentParser()
                result = parser._parse_html("test.html")

                assert result["text"] == "HTML content"
                assert result["format"] == "html"

    def test_parse_html_fallback_regex(self):
        """Test _parse_html falls back to regex when BeautifulSoup unavailable."""
        with patch("builtins.open", mock_open(read_data="<html><body>Test</body></html>")):
            with patch("bs4.BeautifulSoup", side_effect=ImportError):
                parser = mod.DocumentParser()
                result = parser._parse_html("test.html")

                assert result["format"] == "html"

    @patch("pathlib.Path.rglob")
    def test_batch_parse(self, mock_rglob):
        """Test batch_parse processes multiple files in directory."""
        mock_file1 = MagicMock(spec=Path)
        mock_file2 = MagicMock(spec=Path)
        mock_file1.suffix = ".txt"
        mock_file2.suffix = ".md"
        mock_file1.is_file.return_value = True
        mock_file2.is_file.return_value = True
        mock_rglob.return_value = [mock_file1, mock_file2]

        parser = mod.DocumentParser()
        with patch.object(parser, "parse") as mock_parse:
            mock_parse.side_effect = [
                {"text": "file1 content", "source": str(mock_file1)},
                {"text": "file2 content", "source": str(mock_file2)},
            ]
            results = parser.batch_parse("/test/dir", extensions=[".txt", ".md"])

        assert len(results) == 2
        assert mock_parse.call_count == 2

    @patch("pathlib.Path.rglob")
    def test_batch_parse_default_extensions(self, mock_rglob):
        """Test batch_parse uses default extensions."""
        mock_rglob.return_value = []

        parser = mod.DocumentParser()
        results = parser.batch_parse("/test/dir")

        assert results == []

    @patch("pathlib.Path.rglob")
    def test_batch_parse_filters_directories(self, mock_rglob):
        """Test batch_parse filters out directories."""
        mock_file = MagicMock(spec=Path)
        mock_dir = MagicMock(spec=Path)
        mock_file.suffix = ".txt"
        mock_dir.suffix = ".txt"
        mock_file.is_file.return_value = True
        mock_dir.is_file.return_value = False
        mock_rglob.return_value = [mock_file, mock_dir]

        parser = mod.DocumentParser()
        with patch.object(parser, "parse") as mock_parse:
            parser.batch_parse("/test/dir")

        # Only file should be parsed, not directory
        assert mock_parse.call_count == 1

    @patch("pathlib.Path.rglob")
    def test_batch_parse_filters_extensions(self, mock_rglob):
        """Test batch_parse filters by extension."""
        mock_txt = MagicMock(spec=Path)
        mock_xyz = MagicMock(spec=Path)
        mock_txt.suffix = ".txt"
        mock_xyz.suffix = ".xyz"
        mock_txt.is_file.return_value = True
        mock_xyz.is_file.return_value = True
        mock_rglob.return_value = [mock_txt, mock_xyz]

        parser = mod.DocumentParser()
        with patch.object(parser, "parse") as mock_parse:
            parser.batch_parse("/test/dir", extensions=[".txt"])

        # Only .txt should be parsed
        assert mock_parse.call_count == 1


class TestDocumentIntelligence:
    """Tests for DocumentIntelligence class."""

    def test_init(self):
        """Test DocumentIntelligence initialization."""
        with patch("rudy.ocr.ImageOCR"), \
             patch("rudy.ocr.PDFExtractor"), \
             patch("rudy.ocr.DocumentParser"):
            di = mod.DocumentIntelligence()
            assert di.ocr is not None
            assert di.pdf is not None
            assert di.parser is not None

    @patch.object(mod.ImageOCR, "read_image")
    def test_read_image_file(self, mock_read_image):
        """Test read dispatches to OCR for image files."""
        mock_read_image.return_value = {"text": "image text", "source": "test.png"}

        with patch("rudy.ocr.ImageOCR"), \
             patch("rudy.ocr.PDFExtractor"), \
             patch("rudy.ocr.DocumentParser"):
            di = mod.DocumentIntelligence()
            di.ocr = MagicMock()
            di.ocr.read_image.return_value = {"text": "image text"}

            result = di.read("photo.jpg")

            assert result["text"] == "image text"
            di.ocr.read_image.assert_called_once_with("photo.jpg")

    @patch.object(mod.DocumentParser, "parse")
    def test_read_pdf_file(self, mock_parse):
        """Test read dispatches to parser for PDF files."""
        mock_parse.return_value = {"text": "pdf content", "source": "test.pdf"}

        with patch("rudy.ocr.ImageOCR"), \
             patch("rudy.ocr.PDFExtractor"), \
             patch("rudy.ocr.DocumentParser"):
            di = mod.DocumentIntelligence()
            di.parser = MagicMock()
            di.parser.parse.return_value = {"text": "pdf content"}

            result = di.read("document.pdf")

            assert result["text"] == "pdf content"
            di.parser.parse.assert_called_once_with("document.pdf")

    def test_read_all_directory(self):
        """Test read_all delegates to batch_parse."""
        with patch("rudy.ocr.ImageOCR"), \
             patch("rudy.ocr.PDFExtractor"), \
             patch("rudy.ocr.DocumentParser"):
            di = mod.DocumentIntelligence()
            di.parser = MagicMock()
            di.parser.batch_parse.return_value = [
                {"text": "file1", "source": "doc1.pdf"},
                {"text": "file2", "source": "doc2.txt"},
            ]

            result = di.read_all("/test/dir")

            assert len(result) == 2
            di.parser.batch_parse.assert_called_once_with("/test/dir")

    def test_read_image_extensions(self):
        """Test read recognizes all image extensions."""
        with patch("rudy.ocr.ImageOCR"), \
             patch("rudy.ocr.PDFExtractor"), \
             patch("rudy.ocr.DocumentParser"):
            di = mod.DocumentIntelligence()
            di.ocr = MagicMock()
            di.parser = MagicMock()

            image_exts = [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"]
            for ext in image_exts:
                di.ocr.reset_mock()
                di.read(f"test{ext}")
                di.ocr.read_image.assert_called_once()

    def test_read_document_extensions(self):
        """Test read dispatches non-image files to parser."""
        with patch("rudy.ocr.ImageOCR"), \
             patch("rudy.ocr.PDFExtractor"), \
             patch("rudy.ocr.DocumentParser"):
            di = mod.DocumentIntelligence()
            di.ocr = MagicMock()
            di.parser = MagicMock()

            doc_exts = [".pdf", ".docx", ".txt", ".md"]
            for ext in doc_exts:
                di.parser.reset_mock()
                di.read(f"test{ext}")
                di.parser.parse.assert_called_once()


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_read_image_with_empty_bboxes(self):
        """Test read_image handles OCR results with complex bounding boxes."""
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([(10.1, 20.9), (100.5, 20.3), (100.2, 50.7), (10.3, 50.1)], "Text", 0.99),
        ]

        with patch("easyocr.Reader", return_value=mock_reader):
            ocr = mod.ImageOCR()
            result = ocr.read_image("test.png")

            assert len(result["blocks"]) == 1
            bbox = result["blocks"][0]["bbox"]
            # All coordinates should be integers
            assert all(isinstance(p[0], int) and isinstance(p[1], int) for p in bbox)

    def test_parse_case_insensitive_extensions(self):
        """Test parse handles uppercase file extensions."""
        parser = mod.DocumentParser()

        with patch.object(parser, "_parse_pdf") as mock_parse:
            mock_parse.return_value = {"text": "content"}
            parser.parse("DOCUMENT.PDF")
            mock_parse.assert_called_once()

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_parse_text_file_not_found(self, mock_file):
        """Test _parse_text raises error when file not found."""
        parser = mod.DocumentParser()
        with pytest.raises(FileNotFoundError):
            parser._parse_text("nonexistent.txt")

    @patch("builtins.open", new_callable=mock_open, read_data="")
    def test_parse_empty_text_file(self, mock_file):
        """Test _parse_text handles empty files."""
        parser = mod.DocumentParser()
        result = parser._parse_text("empty.txt")
        assert result["text"] == ""

    def test_read_image_single_result(self):
        """Test read_image with single OCR result."""
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([(0, 0), (100, 0), (100, 50), (0, 50)], "Only text", 0.88),
        ]

        with patch("easyocr.Reader", return_value=mock_reader):
            ocr = mod.ImageOCR()
            result = ocr.read_image("single.png")

            assert result["block_count"] == 1
            assert result["confidence"] == 0.88

    def test_extract_tables_empty_page(self):
        """Test extract_tables with page containing no tables."""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = []
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_pdf
            extractor = mod.PDFExtractor()
            result = extractor.extract_tables("notables.pdf")

            assert result == []

    def test_extract_tables_empty_table(self):
        """Test extract_tables filters out empty tables."""
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [None, [["H1", "H2"]]]
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open") as mock_open:
            mock_open.return_value.__enter__.return_value = mock_pdf
            extractor = mod.PDFExtractor()
            result = extractor.extract_tables("test.pdf")

            # Only non-None tables should be included
            assert len(result) == 1
            assert result[0]["headers"] == ["H1", "H2"]
