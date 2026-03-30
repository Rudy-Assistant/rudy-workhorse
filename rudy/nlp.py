"""
NLP Module — Natural language processing for command understanding,
text analysis, sentiment analysis, and entity extraction.

Capabilities:
  - Intent classification: Understand what a command is asking for
  - Entity extraction: Pull names, dates, amounts, locations from text
  - Sentiment analysis: Gauge tone of emails, messages, articles
  - Text summarization: Condense long documents
  - Keyword extraction: Find key themes in text
  - Similarity matching: Find related documents/commands
  - Language detection: Identify language of text
"""

import json
import os
import re
from collections import Counter

from pathlib import Path
from typing import List, Tuple

from rudy.paths import DESKTOP  # noqa: E402

class SentimentAnalyzer:
    """Analyze sentiment of text."""

    def __init__(self):
        self._vader = None
        self._textblob = None

    def _get_vader(self):
        if self._vader is None:
            try:
                from nltk.sentiment.vader import SentimentIntensityAnalyzer
                self._vader = SentimentIntensityAnalyzer()
            except (ImportError, LookupError):
                try:
                    import nltk
                    nltk.download("vader_lexicon", quiet=True)
                    from nltk.sentiment.vader import SentimentIntensityAnalyzer
                    self._vader = SentimentIntensityAnalyzer()
                except Exception:
                    pass
        return self._vader

    def analyze(self, text: str) -> dict:
        """
        Analyze sentiment. Returns compound score (-1 to 1)
        and label (positive/negative/neutral).
        """
        # Try VADER first (great for social media, informal text)
        vader = self._get_vader()
        if vader:
            scores = vader.polarity_scores(text)
            compound = scores["compound"]
            if compound >= 0.05:
                label = "positive"
            elif compound <= -0.05:
                label = "negative"
            else:
                label = "neutral"
            return {
                "compound": round(compound, 4),
                "positive": round(scores["pos"], 4),
                "negative": round(scores["neg"], 4),
                "neutral": round(scores["neu"], 4),
                "label": label,
                "engine": "vader",
            }

        # Fallback to TextBlob
        try:
            from textblob import TextBlob
            blob = TextBlob(text)
            polarity = blob.sentiment.polarity
            subjectivity = blob.sentiment.subjectivity
            if polarity > 0.1:
                label = "positive"
            elif polarity < -0.1:
                label = "negative"
            else:
                label = "neutral"
            return {
                "compound": round(polarity, 4),
                "subjectivity": round(subjectivity, 4),
                "label": label,
                "engine": "textblob",
            }
        except ImportError:
            return {"error": "No sentiment engine available (install nltk or textblob)"}

    def analyze_batch(self, texts: List[str]) -> List[dict]:
        return [self.analyze(t) for t in texts]

class EntityExtractor:
    """Extract named entities from text."""

    def __init__(self):
        self._nlp = None

    def _get_nlp(self):
        if self._nlp is None:
            try:
                import spacy
                self._nlp = spacy.load("en_core_web_sm")
            except (ImportError, OSError):
                pass
        return self._nlp

    def extract(self, text: str) -> dict:
        """Extract entities: people, organizations, dates, money, locations."""
        nlp = self._get_nlp()
        if nlp:
            doc = nlp(text)
            entities = {}
            for ent in doc.ents:
                label = ent.label_
                if label not in entities:
                    entities[label] = []
                if ent.text not in entities[label]:
                    entities[label].append(ent.text)
            return {
                "entities": entities,
                "person": entities.get("PERSON", []),
                "organization": entities.get("ORG", []),
                "location": entities.get("GPE", []) + entities.get("LOC", []),
                "date": entities.get("DATE", []),
                "money": entities.get("MONEY", []),
                "engine": "spacy",
            }

        # Regex fallback for basic entities
        return self._regex_extract(text)

    def _regex_extract(self, text: str) -> dict:
        """Basic regex-based entity extraction."""
        entities = {}

        # Emails
        emails = re.findall(r'[\w.-]+@[\w.-]+\.\w+', text)
        if emails:
            entities["email"] = emails

        # Phone numbers
        phones = re.findall(r'(?:\+?1[-.]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text)
        if phones:
            entities["phone"] = phones

        # URLs
        urls = re.findall(r'https?://\S+', text)
        if urls:
            entities["url"] = urls

        # Money
        money = re.findall(r'\$[\d,]+(?:\.\d{2})?', text)
        if money:
            entities["money"] = money

        # Dates
        dates = re.findall(
            r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s*\d{4}\b',
            text, re.IGNORECASE
        )
        if dates:
            entities["date"] = dates

        return {"entities": entities, "engine": "regex"}

class TextSummarizer:
    """Summarize long text."""

    def summarize(self, text: str, sentence_count: int = 3) -> str:
        """Extract key sentences as summary."""
        try:
            from sumy.parsers.plaintext import PlaintextParser
            from sumy.nlp.tokenizers import Tokenizer
            from sumy.summarizers.lsa import LsaSummarizer
            from sumy.nlp.stemmers import Stemmer
            from sumy.utils import get_stop_words

            parser = PlaintextParser.from_string(text, Tokenizer("english"))
            stemmer = Stemmer("english")
            summarizer = LsaSummarizer(stemmer)
            summarizer.stop_words = get_stop_words("english")
            sentences = summarizer(parser.document, sentence_count)
            return " ".join(str(s) for s in sentences)
        except ImportError:
            # Fallback: first N sentences
            sentences = re.split(r'(?<=[.!?])\s+', text)
            return " ".join(sentences[:sentence_count])

    def extract_keywords(self, text: str, top_n: int = 10) -> List[Tuple[str, int]]:
        """Extract key terms from text."""
        # Simple TF-based extraction
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())

        # Remove stopwords
        stopwords = {
            "the", "and", "for", "are", "but", "not", "you", "all",
            "can", "had", "her", "was", "one", "our", "out", "has",
            "have", "been", "from", "this", "that", "with", "they",
            "will", "each", "make", "like", "long", "look", "many",
            "some", "than", "them", "then", "were", "what", "when",
            "who", "how", "its", "may", "into", "also", "more",
            "other", "would", "their", "which", "about", "these",
        }
        words = [w for w in words if w not in stopwords]

        counter = Counter(words)
        return counter.most_common(top_n)

class LanguageDetector:
    """Detect the language of text."""

    def detect(self, text: str) -> dict:
        """Detect language."""
        try:
            from textblob import TextBlob
            blob = TextBlob(text)
            lang = blob.detect_language()
            return {"language": lang, "engine": "textblob"}
        except Exception:
            pass

        # Heuristic fallback
        if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text):
            return {"language": "ja", "engine": "heuristic"}
        if re.search(r'[\uac00-\ud7af]', text):
            return {"language": "ko", "engine": "heuristic"}
        if re.search(r'[\u0e00-\u0e7f]', text):
            return {"language": "th", "engine": "heuristic"}
        if re.search(r'[\u0600-\u06ff]', text):
            return {"language": "ar", "engine": "heuristic"}

        return {"language": "en", "engine": "default"}

class NLP:
    """Unified NLP interface."""

    def __init__(self):
        self.sentiment = SentimentAnalyzer()
        self.entities = EntityExtractor()
        self.summarizer = TextSummarizer()
        self.language = LanguageDetector()

    def analyze(self, text: str) -> dict:
        """Full NLP analysis of text."""
        return {
            "sentiment": self.sentiment.analyze(text),
            "entities": self.entities.extract(text),
            "keywords": self.summarizer.extract_keywords(text),
            "language": self.language.detect(text[:500]),
            "word_count": len(text.split()),
            "char_count": len(text),
        }

    def summarize(self, text: str, sentences: int = 3) -> str:
        return self.summarizer.summarize(text, sentences)

    def get_sentiment(self, text: str) -> dict:
        return self.sentiment.analyze(text)

    def get_entities(self, text: str) -> dict:
        return self.entities.extract(text)

if __name__ == "__main__":
    nlp = NLP()
    test = "Apple CEO Tim Cook announced a $50 billion investment in California on March 15, 2026. Contact info@apple.com for details."
    print("NLP Module Test")
    print(f"Input: {test}\n")
    result = nlp.analyze(test)
    print(json.dumps(result, indent=2, default=str))
