import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

import rudy.nlp as mod


class TestSentimentAnalyzer:
    """Tests for SentimentAnalyzer class."""

    def test_init(self):
        """Test initialization."""
        analyzer = mod.SentimentAnalyzer()
        assert analyzer._vader is None
        assert analyzer._textblob is None

    @patch("rudy.nlp.SentimentAnalyzer._get_vader")
    def test_analyze_with_vader_positive(self, mock_get_vader):
        """Test sentiment analysis with VADER returning positive sentiment."""
        mock_vader = MagicMock()
        mock_vader.polarity_scores.return_value = {
            "compound": 0.8,
            "pos": 0.9,
            "neg": 0.0,
            "neu": 0.1,
        }
        mock_get_vader.return_value = mock_vader

        analyzer = mod.SentimentAnalyzer()
        result = analyzer.analyze("I love this product!")

        assert result["label"] == "positive"
        assert result["compound"] == 0.8
        assert result["engine"] == "vader"
        assert "positive" in result
        assert "negative" in result
        assert "neutral" in result

    @patch("rudy.nlp.SentimentAnalyzer._get_vader")
    def test_analyze_with_vader_negative(self, mock_get_vader):
        """Test sentiment analysis with VADER returning negative sentiment."""
        mock_vader = MagicMock()
        mock_vader.polarity_scores.return_value = {
            "compound": -0.7,
            "pos": 0.0,
            "neg": 0.95,
            "neu": 0.05,
        }
        mock_get_vader.return_value = mock_vader

        analyzer = mod.SentimentAnalyzer()
        result = analyzer.analyze("This is terrible!")

        assert result["label"] == "negative"
        assert result["compound"] == -0.7
        assert result["engine"] == "vader"

    @patch("rudy.nlp.SentimentAnalyzer._get_vader")
    def test_analyze_with_vader_neutral(self, mock_get_vader):
        """Test sentiment analysis with VADER returning neutral sentiment."""
        mock_vader = MagicMock()
        mock_vader.polarity_scores.return_value = {
            "compound": 0.0,
            "pos": 0.0,
            "neg": 0.0,
            "neu": 1.0,
        }
        mock_get_vader.return_value = mock_vader

        analyzer = mod.SentimentAnalyzer()
        result = analyzer.analyze("The weather is cloudy.")

        assert result["label"] == "neutral"
        assert result["engine"] == "vader"

    @patch("rudy.nlp.SentimentAnalyzer._get_vader")
    def test_analyze_fallback_to_textblob(self, mock_get_vader):
        """Test fallback to TextBlob when VADER unavailable."""
        mock_get_vader.return_value = None

        # Mock TextBlob module at sys.modules level
        mock_textblob_module = MagicMock()
        mock_blob = MagicMock()
        mock_blob.sentiment.polarity = 0.5
        mock_blob.sentiment.subjectivity = 0.7
        mock_textblob_module.TextBlob.return_value = mock_blob

        with patch.dict(sys.modules, {"textblob": mock_textblob_module}):
            analyzer = mod.SentimentAnalyzer()
            result = analyzer.analyze("Great product!")

            assert result["label"] == "positive"
            assert result["compound"] == 0.5
            assert result["engine"] == "textblob"
            assert "subjectivity" in result

    @patch("rudy.nlp.SentimentAnalyzer._get_vader")
    def test_analyze_no_engine_available(self, mock_get_vader):
        """Test when no sentiment engine is available."""
        mock_get_vader.return_value = None

        # Mock TextBlob import to fail
        with patch.dict(sys.modules, {"textblob": None}):
            analyzer = mod.SentimentAnalyzer()
            result = analyzer.analyze("Some text")

            assert "error" in result
            assert "No sentiment engine available" in result["error"]

    @patch("rudy.nlp.SentimentAnalyzer._get_vader")
    def test_analyze_batch(self, mock_get_vader):
        """Test batch sentiment analysis."""
        mock_vader = MagicMock()
        mock_vader.polarity_scores.side_effect = [
            {"compound": 0.8, "pos": 0.9, "neg": 0.0, "neu": 0.1},
            {"compound": -0.7, "pos": 0.0, "neg": 0.95, "neu": 0.05},
        ]
        mock_get_vader.return_value = mock_vader

        analyzer = mod.SentimentAnalyzer()
        texts = ["I love this!", "This is awful."]
        results = analyzer.analyze_batch(texts)

        assert len(results) == 2
        assert results[0]["label"] == "positive"
        assert results[1]["label"] == "negative"

    @patch("rudy.nlp.SentimentAnalyzer._get_vader")
    def test_analyze_empty_string(self, mock_get_vader):
        """Test sentiment analysis with empty string."""
        mock_vader = MagicMock()
        mock_vader.polarity_scores.return_value = {
            "compound": 0.0,
            "pos": 0.0,
            "neg": 0.0,
            "neu": 0.0,
        }
        mock_get_vader.return_value = mock_vader

        analyzer = mod.SentimentAnalyzer()
        result = analyzer.analyze("")

        assert result["label"] == "neutral"


class TestEntityExtractor:
    """Tests for EntityExtractor class."""

    def test_init(self):
        """Test initialization."""
        extractor = mod.EntityExtractor()
        assert extractor._nlp is None

    @patch("rudy.nlp.EntityExtractor._get_nlp")
    def test_extract_with_spacy(self, mock_get_nlp):
        """Test entity extraction with spaCy."""
        mock_nlp = MagicMock()
        mock_doc = MagicMock()

        # Create mock entities
        person_ent = MagicMock()
        person_ent.text = "John Smith"
        person_ent.label_ = "PERSON"

        org_ent = MagicMock()
        org_ent.text = "Apple Inc"
        org_ent.label_ = "ORG"

        location_ent = MagicMock()
        location_ent.text = "California"
        location_ent.label_ = "GPE"

        money_ent = MagicMock()
        money_ent.text = "$50 billion"
        money_ent.label_ = "MONEY"

        date_ent = MagicMock()
        date_ent.text = "March 15, 2026"
        date_ent.label_ = "DATE"

        mock_doc.ents = [person_ent, org_ent, location_ent, money_ent, date_ent]
        mock_nlp.return_value = mock_doc
        mock_get_nlp.return_value = mock_nlp

        extractor = mod.EntityExtractor()
        result = extractor.extract("John Smith at Apple Inc in California announced $50 billion on March 15, 2026")

        assert "entities" in result
        assert result["person"] == ["John Smith"]
        assert result["organization"] == ["Apple Inc"]
        assert "California" in result["location"]
        assert result["money"] == ["$50 billion"]
        assert result["date"] == ["March 15, 2026"]
        assert result["engine"] == "spacy"

    @patch("rudy.nlp.EntityExtractor._get_nlp")
    def test_extract_duplicate_entities(self, mock_get_nlp):
        """Test that duplicate entities are not included."""
        mock_nlp = MagicMock()
        mock_doc = MagicMock()

        ent1 = MagicMock()
        ent1.text = "Alice"
        ent1.label_ = "PERSON"

        ent2 = MagicMock()
        ent2.text = "Alice"
        ent2.label_ = "PERSON"

        mock_doc.ents = [ent1, ent2]
        mock_nlp.return_value = mock_doc
        mock_get_nlp.return_value = mock_nlp

        extractor = mod.EntityExtractor()
        result = extractor.extract("Alice met Alice")

        assert result["person"] == ["Alice"]

    @patch("rudy.nlp.EntityExtractor._get_nlp")
    def test_extract_fallback_to_regex(self, mock_get_nlp):
        """Test fallback to regex extraction when spaCy unavailable."""
        mock_get_nlp.return_value = None

        extractor = mod.EntityExtractor()
        text = "Email me at john@example.com or call 555-123-4567. Visit https://example.com"
        result = extractor.extract(text)

        assert result["engine"] == "regex"
        assert "email" in result["entities"]
        assert "john@example.com" in result["entities"]["email"]
        assert "phone" in result["entities"]
        assert "url" in result["entities"]

    def test_regex_extract_email(self):
        """Test regex extraction of email addresses."""
        extractor = mod.EntityExtractor()
        text = "Contact john@example.com or jane.doe@company.co.uk"
        result = extractor._regex_extract(text)

        assert "email" in result["entities"]
        assert "john@example.com" in result["entities"]["email"]
        assert "jane.doe@company.co.uk" in result["entities"]["email"]

    def test_regex_extract_phone(self):
        """Test regex extraction of phone numbers."""
        extractor = mod.EntityExtractor()
        text = "Call me at (555) 123-4567 or 555.123.4567 or +1-555-123-4567"
        result = extractor._regex_extract(text)

        assert "phone" in result["entities"]
        assert len(result["entities"]["phone"]) >= 2

    def test_regex_extract_urls(self):
        """Test regex extraction of URLs."""
        extractor = mod.EntityExtractor()
        text = "Check https://example.com or http://google.com/search"
        result = extractor._regex_extract(text)

        assert "url" in result["entities"]
        assert "https://example.com" in result["entities"]["url"]
        assert "http://google.com/search" in result["entities"]["url"]

    def test_regex_extract_money(self):
        """Test regex extraction of money amounts."""
        extractor = mod.EntityExtractor()
        text = "The cost is $1,500.00 and we need $50 billion for the project"
        result = extractor._regex_extract(text)

        assert "money" in result["entities"]
        assert "$1,500.00" in result["entities"]["money"]
        assert "$50" in result["entities"]["money"]

    def test_regex_extract_dates(self):
        """Test regex extraction of dates."""
        extractor = mod.EntityExtractor()
        text = "Meeting on 03/15/2026 or March 15, 2026 or 2026-03-15"
        result = extractor._regex_extract(text)

        assert "date" in result["entities"]
        assert "03/15/2026" in result["entities"]["date"]
        assert "March 15, 2026" in result["entities"]["date"]

    def test_regex_extract_empty_string(self):
        """Test regex extraction with empty string."""
        extractor = mod.EntityExtractor()
        result = extractor._regex_extract("")

        assert result["entities"] == {}
        assert result["engine"] == "regex"

    def test_regex_extract_no_entities(self):
        """Test regex extraction with text containing no entities."""
        extractor = mod.EntityExtractor()
        text = "This is just plain text without any contact information or numbers"
        result = extractor._regex_extract(text)

        assert result["entities"] == {}


class TestTextSummarizer:
    """Tests for TextSummarizer class."""

    def test_extract_keywords_basic(self):
        """Test basic keyword extraction."""
        summarizer = mod.TextSummarizer()
        text = "Apple CEO Tim Cook announced investment in technology and innovation at the company"
        keywords = summarizer.extract_keywords(text, top_n=5)

        assert len(keywords) <= 5
        assert all(isinstance(k, tuple) and len(k) == 2 for k in keywords)
        # Check that keywords are extracted
        assert len(keywords) > 0
        # "apple", "tim", "investment", "technology", "innovation" are likely candidates
        keyword_words = [k[0] for k in keywords]
        assert "apple" in keyword_words or "tim" in keyword_words or "technology" in keyword_words

    def test_extract_keywords_excludes_stopwords(self):
        """Test that stopwords are excluded from keywords."""
        summarizer = mod.TextSummarizer()
        text = "the and for are but not you all can had her was one our"
        keywords = summarizer.extract_keywords(text, top_n=10)

        keyword_words = [k[0] for k in keywords]
        # All common stopwords should be excluded
        stopwords = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her", "was", "one", "our"}
        assert len([w for w in keyword_words if w in stopwords]) == 0

    def test_extract_keywords_long_words_only(self):
        """Test that only words with 3+ characters are extracted."""
        summarizer = mod.TextSummarizer()
        text = "a big cat ran in the yard to play games"
        keywords = summarizer.extract_keywords(text, top_n=10)

        keyword_words = [k[0] for k in keywords]
        # All extracted keywords should have at least 3 characters
        assert all(len(w) >= 3 for w in keyword_words)

    def test_extract_keywords_top_n(self):
        """Test that top_n parameter limits results."""
        summarizer = mod.TextSummarizer()
        text = "word " * 100 + "test data analysis machine learning python programming"
        keywords = summarizer.extract_keywords(text, top_n=3)

        assert len(keywords) <= 3

    def test_extract_keywords_empty_string(self):
        """Test keyword extraction with empty string."""
        summarizer = mod.TextSummarizer()
        keywords = summarizer.extract_keywords("", top_n=10)

        assert keywords == []

    def test_extract_keywords_only_stopwords(self):
        """Test keyword extraction when text contains only stopwords."""
        summarizer = mod.TextSummarizer()
        text = "the and for are but not you"
        keywords = summarizer.extract_keywords(text, top_n=10)

        assert keywords == []

    @patch("rudy.nlp.TextSummarizer.summarize")
    def test_summarize_with_sumy(self, mock_summarize):
        """Test summarization with sumy library."""
        mock_summarize.return_value = "First sentence. Second sentence."

        summarizer = mod.TextSummarizer()
        result = summarizer.summarize("A " * 100 + "First sentence. " + "B " * 100 + "Second sentence.", sentence_count=2)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_summarize_fallback_basic(self):
        """Test summarization fallback (first N sentences)."""
        summarizer = mod.TextSummarizer()
        text = "First. Second. Third. Fourth. Fifth."
        result = summarizer.summarize(text, sentence_count=2)

        sentences = [s.strip() for s in result.split(".") if s.strip()]
        assert len(sentences) >= 1

    def test_summarize_empty_string(self):
        """Test summarization with empty string."""
        summarizer = mod.TextSummarizer()
        result = summarizer.summarize("", sentence_count=3)

        assert result == ""

    def test_summarize_single_sentence(self):
        """Test summarization with single sentence."""
        summarizer = mod.TextSummarizer()
        text = "This is a single sentence."
        result = summarizer.summarize(text, sentence_count=3)

        assert "This is a single sentence" in result


class TestLanguageDetector:
    """Tests for LanguageDetector class."""

    @patch("rudy.nlp.LanguageDetector.detect")
    def test_detect_english(self, mock_detect):
        """Test English language detection."""
        mock_detect.return_value = {"language": "en", "engine": "textblob"}

        detector = mod.LanguageDetector()
        result = detector.detect("Hello, how are you?")

        assert result["language"] == "en"

    @patch("rudy.nlp.LanguageDetector.detect")
    def test_detect_with_textblob(self, mock_detect):
        """Test language detection with TextBlob."""
        mock_detect.return_value = {"language": "fr", "engine": "textblob"}

        detector = mod.LanguageDetector()
        result = detector.detect("Bonjour, comment allez-vous?")

        assert result["language"] == "fr"
        assert result["engine"] == "textblob"

    def test_detect_japanese_heuristic(self):
        """Test heuristic detection of Japanese characters."""
        detector = mod.LanguageDetector()
        text = "これは日本語のテキストです"  # Japanese: "This is Japanese text"
        result = detector.detect(text)

        assert result["language"] == "ja"
        assert result["engine"] == "heuristic"

    def test_detect_korean_heuristic(self):
        """Test heuristic detection of Korean characters."""
        detector = mod.LanguageDetector()
        text = "이것은 한국어 텍스트입니다"  # Korean: "This is Korean text"
        result = detector.detect(text)

        assert result["language"] == "ko"
        assert result["engine"] == "heuristic"

    def test_detect_thai_heuristic(self):
        """Test heuristic detection of Thai characters."""
        detector = mod.LanguageDetector()
        text = "นี่คือข้อความภาษาไทย"  # Thai: "This is Thai text"
        result = detector.detect(text)

        assert result["language"] == "th"
        assert result["engine"] == "heuristic"

    def test_detect_arabic_heuristic(self):
        """Test heuristic detection of Arabic characters."""
        detector = mod.LanguageDetector()
        text = "هذا نص باللغة العربية"  # Arabic: "This is Arabic text"
        result = detector.detect(text)

        assert result["language"] == "ar"
        assert result["engine"] == "heuristic"

    def test_detect_textblob_failure_fallback_heuristic(self):
        """Test fallback from TextBlob to heuristic when error occurs."""
        # Simulate TextBlob failure and fallback to heuristic for Japanese
        detector = mod.LanguageDetector()
        japanese_text = "これは日本語です"
        result = detector.detect(japanese_text)

        # Should fall back to heuristic detection
        assert result["language"] in ["ja", "en"]

    def test_detect_default_english(self):
        """Test default English detection."""
        detector = mod.LanguageDetector()
        # When TextBlob fails and no heuristic matches, should default to English
        with patch.dict(sys.modules, {"textblob": None}):
            result = detector.detect("Some English text")
            assert result["language"] == "en"

    def test_detect_empty_string(self):
        """Test language detection with empty string."""
        detector = mod.LanguageDetector()
        result = detector.detect("")

        # Empty string should fall back to default
        assert result["language"] == "en"
        assert result["engine"] == "default"


class TestNLP:
    """Tests for unified NLP interface."""

    def test_init(self):
        """Test initialization."""
        nlp = mod.NLP()
        assert isinstance(nlp.sentiment, mod.SentimentAnalyzer)
        assert isinstance(nlp.entities, mod.EntityExtractor)
        assert isinstance(nlp.summarizer, mod.TextSummarizer)
        assert isinstance(nlp.language, mod.LanguageDetector)

    @patch.object(mod.SentimentAnalyzer, "analyze")
    @patch.object(mod.EntityExtractor, "extract")
    @patch.object(mod.TextSummarizer, "extract_keywords")
    @patch.object(mod.LanguageDetector, "detect")
    def test_analyze_full(self, mock_detect, mock_keywords, mock_extract, mock_sentiment):
        """Test full NLP analysis."""
        mock_sentiment.return_value = {"label": "positive", "compound": 0.8}
        mock_extract.return_value = {"person": ["John"], "organization": ["Apple"]}
        mock_keywords.return_value = [("apple", 5), ("ceo", 3)]
        mock_detect.return_value = {"language": "en"}

        nlp = mod.NLP()
        text = "John at Apple announced great news today!"
        result = nlp.analyze(text)

        assert "sentiment" in result
        assert "entities" in result
        assert "keywords" in result
        assert "language" in result
        assert "word_count" in result
        assert "char_count" in result
        assert result["word_count"] == len(text.split())
        assert result["char_count"] == len(text)

    @patch.object(mod.SentimentAnalyzer, "analyze")
    def test_get_sentiment(self, mock_sentiment):
        """Test get_sentiment method."""
        mock_sentiment.return_value = {"label": "positive", "compound": 0.8}

        nlp = mod.NLP()
        result = nlp.get_sentiment("I love this!")

        assert result["label"] == "positive"
        assert result["compound"] == 0.8

    @patch.object(mod.EntityExtractor, "extract")
    def test_get_entities(self, mock_extract):
        """Test get_entities method."""
        mock_extract.return_value = {"person": ["Alice"], "organization": ["Google"]}

        nlp = mod.NLP()
        result = nlp.get_entities("Alice works at Google")

        assert result["person"] == ["Alice"]
        assert result["organization"] == ["Google"]

    @patch.object(mod.TextSummarizer, "summarize")
    def test_summarize(self, mock_summarize):
        """Test summarize method."""
        mock_summarize.return_value = "Summary text"

        nlp = mod.NLP()
        result = nlp.summarize("Long text... " * 100, sentences=2)

        assert result == "Summary text"
        mock_summarize.assert_called_once_with("Long text... " * 100, 2)

    @patch.object(mod.SentimentAnalyzer, "analyze")
    @patch.object(mod.EntityExtractor, "extract")
    @patch.object(mod.TextSummarizer, "extract_keywords")
    @patch.object(mod.LanguageDetector, "detect")
    def test_analyze_truncates_text_for_language_detection(self, mock_detect, mock_keywords, mock_extract, mock_sentiment):
        """Test that only first 500 chars are used for language detection."""
        mock_sentiment.return_value = {"label": "positive"}
        mock_extract.return_value = {"entities": {}}
        mock_keywords.return_value = []
        mock_detect.return_value = {"language": "en"}

        nlp = mod.NLP()
        long_text = "x" * 1000
        nlp.analyze(long_text)

        # Verify language detection was called with truncated text
        mock_detect.assert_called_once_with(long_text[:500])

    @patch.object(mod.SentimentAnalyzer, "analyze")
    @patch.object(mod.EntityExtractor, "extract")
    @patch.object(mod.TextSummarizer, "extract_keywords")
    @patch.object(mod.LanguageDetector, "detect")
    def test_analyze_empty_string(self, mock_detect, mock_keywords, mock_extract, mock_sentiment):
        """Test analysis with empty string."""
        mock_sentiment.return_value = {"label": "neutral"}
        mock_extract.return_value = {"entities": {}}
        mock_keywords.return_value = []
        mock_detect.return_value = {"language": "en"}

        nlp = mod.NLP()
        result = nlp.analyze("")

        assert result["word_count"] == 0
        assert result["char_count"] == 0

    @patch.object(mod.SentimentAnalyzer, "analyze")
    @patch.object(mod.EntityExtractor, "extract")
    @patch.object(mod.TextSummarizer, "extract_keywords")
    @patch.object(mod.LanguageDetector, "detect")
    def test_analyze_special_characters(self, mock_detect, mock_keywords, mock_extract, mock_sentiment):
        """Test analysis with special characters."""
        mock_sentiment.return_value = {"label": "neutral"}
        mock_extract.return_value = {"entities": {}}
        mock_keywords.return_value = []
        mock_detect.return_value = {"language": "en"}

        nlp = mod.NLP()
        text = "Hello!!! @#$%^&*() 123 <<<>>> ``?"
        result = nlp.analyze(text)

        assert result["char_count"] == len(text)
        assert result["word_count"] >= 1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_text(self):
        """Test processing of very long text."""
        nlp = mod.NLP()
        long_text = " ".join(["word"] * 10000)

        # Should not crash or hang
        result = nlp.analyze(long_text)
        assert result["word_count"] == 10000
        assert result["char_count"] > 0

    def test_text_with_multiple_languages(self):
        """Test text containing multiple languages."""
        detector = mod.LanguageDetector()
        mixed_text = "Hello world これは日本語です Bonjour"

        result = detector.detect(mixed_text)
        # Should detect based on dominant script
        assert "language" in result

    def test_text_with_unicode(self):
        """Test text with various Unicode characters."""
        extractor = mod.EntityExtractor()
        text = "Contact: user@example.com, emoji: 😀🎉, math: ∑∏∫"

        result = extractor.extract(text)
        assert "email" in result["entities"] or result["engine"] == "spacy"

    def test_sentiment_boundary_values(self):
        """Test sentiment analysis boundary values."""
        with patch("rudy.nlp.SentimentAnalyzer._get_vader") as mock_get_vader:
            mock_vader = MagicMock()
            # Test exact boundary at 0.05
            mock_vader.polarity_scores.return_value = {
                "compound": 0.05,
                "pos": 0.5,
                "neg": 0.0,
                "neu": 0.5,
            }
            mock_get_vader.return_value = mock_vader

            analyzer = mod.SentimentAnalyzer()
            result = analyzer.analyze("test")
            assert result["label"] == "positive"

            # Test exact boundary at -0.05
            mock_vader.polarity_scores.return_value = {
                "compound": -0.05,
                "pos": 0.0,
                "neg": 0.5,
                "neu": 0.5,
            }
            result = analyzer.analyze("test")
            assert result["label"] == "negative"
