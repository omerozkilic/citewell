"""Answerability: does the retrieved text cover what the question asks about? (no LLM, offline)

The **confidence** of a search is the best *term coverage* among the returned passages: the share
of the query's content words (question words and other stop words removed, Turkish-aware prefix
stems like the lexical reranker) that occur in the passage. With a cross-encoder reranker its
probability is used as well, whichever is higher, so that a paraphrased question the model
recognises as answered is not penalised for sharing few words.

``answerable`` is ``confidence >= CITEWELL_ANSWERABLE_THRESHOLD``. It is advice for the assistant
("the documents probably do not contain this"), never a filter: passages are always returned.
"""

from collections.abc import Iterable

from citewell.text import _stem, tokenize

STOP_WORDS = frozenset(
    [
        "ve",
        "ile",
        "veya",
        "ya",
        "ama",
        "fakat",
        "ki",
        "de",
        "da",
        "mi",
        "mı",
        "mu",
        "mü",
        "bir",
        "bu",
        "şu",
        "o",
        "ne",
        "nedir",
        "neden",
        "nasıl",
        "nerede",
        "nereye",
        "kim",
        "kaç",
        "kaçtır",
        "hangi",
        "hangisi",
        "için",
        "gibi",
        "kadar",
        "daha",
        "en",
        "çok",
        "az",
        "var",
        "yok",
        "olur",
        "olmalı",
        "olarak",
        "mıdır",
        "midir",
        "mudur",
        "müdür",
        "ise",
        "ben",
        "biz",
        "siz",
        "sen",
        "beni",
        "bana",
        "bize",
        "the",
        "a",
        "an",
        "of",
        "to",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "what",
        "when",
        "where",
        "who",
        "which",
        "how",
        "why",
        "do",
        "does",
        "did",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "and",
        "or",
        "not",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "can",
        "may",
        "must",
        "should",
        "will",
        "would",
        "many",
        "much",
        "any",
        "there",
        "their",
        "i",
        "we",
        "you",
        "they",
        "he",
        "she",
        "as",
        "if",
        "than",
        "then",
        "so",
    ]
)


def query_terms(query: str) -> frozenset[str]:
    """Distinct content-word stems of a query."""
    return frozenset(_stem(t) for t in tokenize(query) if len(t) > 1 and t not in STOP_WORDS)


def coverage(terms: frozenset[str], text: str) -> float:
    """Share of ``terms`` found among the stems of ``text`` (0 when the query has no content words)."""
    if not terms:
        return 0.0
    present = {_stem(t) for t in tokenize(text)}
    return len(terms & present) / len(terms)


def confidence(query: str, passages: Iterable[str], rerank_scores: Iterable[float] = ()) -> float:
    """Best term coverage over ``passages``, or the best reranker probability if that is higher."""
    terms = query_terms(query)
    best = max((coverage(terms, p) for p in passages), default=0.0)
    return round(max([best, *rerank_scores]), 4)
