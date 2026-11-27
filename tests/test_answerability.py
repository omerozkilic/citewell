from __future__ import annotations

import pytest

from citewell.answerability import confidence, coverage, query_terms


def test_stop_words_and_short_tokens_are_not_query_terms() -> None:
    assert query_terms("Parolam en az kaç karakter olmalı?") == {"parol", "karak"}
    assert query_terms("What is the VPN deadline?") == {"vpn", "deadl"}
    assert query_terms("ne mı bir") == frozenset()


def test_coverage_is_the_share_of_terms_found_with_turkish_stems() -> None:
    terms = query_terms("laptop çalınırsa şifreleme")
    assert coverage(terms, "Çalınan Laptop bildirilir") == pytest.approx(2 / 3)
    assert coverage(terms, "tamamen alakasız bir metin") == 0.0
    assert coverage(query_terms("ogrenci izinleri"), "Öğrenci izinleri yılda iki kez") == 1.0  # folded
    assert coverage(frozenset(), "anything") == 0.0


def test_confidence_is_the_best_passage_or_reranker_score() -> None:
    passages = ["parola yöneticisi kullanılır", "hiçbir ilgisi yok"]
    assert confidence("parola yöneticisi", passages) == 1.0
    assert confidence("parola yöneticisi kuralı", passages) == pytest.approx(0.6667)
    assert confidence("parola yöneticisi kuralı", passages, rerank_scores=[0.9, 0.1]) == 0.9
    assert confidence("parola", [], []) == 0.0
