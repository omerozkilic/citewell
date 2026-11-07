from citewell.text import best_quote, clean_text, reflow, split_sentences, tokenize, tr_lower


def test_tr_lower_dotted_and_dotless_i() -> None:
    assert tr_lower("ISPARTA İSTANBUL") == "ısparta istanbul"
    assert tr_lower("IŞIK", "english") == "işik"  # non-Turkish collections use plain lower()


def test_clean_text_joins_hyphenated_words_and_collapses_space() -> None:
    raw = "Çalış-\nanlar   yıllık izin\r\n\n\n\nkullanır."
    assert clean_text(raw) == "Çalışanlar yıllık izin\n\nkullanır."


def test_clean_text_normalises_unicode() -> None:
    decomposed = "ş"  # s + combining cedilla
    assert clean_text(decomposed) == "ş"


def test_reflow_joins_wrapped_lines_but_keeps_headings() -> None:
    text = "2. Yıllık İzin\nKıdemi bir yıldan beş yıla kadar olan çalışanlar\nyılda 14 gün izin kullanır.\nYeni cümle."
    assert reflow(text) == (
        "2. Yıllık İzin\nKıdemi bir yıldan beş yıla kadar olan çalışanlar yılda 14 gün izin kullanır.\nYeni cümle."
    )


def test_split_sentences_turkish() -> None:
    text = "Deneme süresi iki aydır. İzinler İK portalından istenir! Neden? Çünkü kayıt gerekir."
    assert split_sentences(text) == [
        "Deneme süresi iki aydır.",
        "İzinler İK portalından istenir!",
        "Neden?",
        "Çünkü kayıt gerekir.",
    ]


def test_split_sentences_does_not_split_decimals() -> None:
    assert split_sentences("Üst sınır 3.500 TL'dir. Sonra.") == ["Üst sınır 3.500 TL'dir.", "Sonra."]


def test_tokenize() -> None:
    assert tokenize("İzin, IŞIK; 14 gün") == ["izin", "ışık", "14", "gün"]


def test_best_quote_picks_matching_sentence() -> None:
    text = (
        "Bu el kitabı yıllık olarak güncellenir. Deneme süresi işe başlangıçtan itibaren iki aydır. "
        "Fazla mesai yönetici onayı ile yapılır."
    )
    q = best_quote(text, "deneme süresi ne kadar", max_chars=60)
    assert q == "Deneme süresi işe başlangıçtan itibaren iki aydır."


def test_best_quote_grows_window_and_truncates() -> None:
    text = "Birinci cümle. İkinci cümle burada. Üçüncü."
    assert best_quote(text, "ikinci", max_chars=200) == text
    long = "kelime " * 100
    q = best_quote(long, "kelime", max_chars=50)
    assert len(q) <= 50 and q.endswith("…")


def test_best_quote_empty_query_returns_first_sentence() -> None:
    assert best_quote("A cümlesi. B cümlesi.", "", max_chars=100) == "A cümlesi."


def test_fold_strips_turkish_diacritics() -> None:
    from citewell.text import fold

    assert fold("Öğrencilerin İŞÇİ ISPARTA Çalışanları") == "ogrencilerin isci isparta calisanlari"
    assert fold("café Ünlü", "english") == "cafe unlu"


def test_fold_mapping_matches_migration() -> None:
    from pathlib import Path

    from citewell.text import FOLD_FROM, FOLD_TO

    assert len(FOLD_FROM) == len(FOLD_TO)
    sql = (Path(__file__).parent.parent / "src/citewell/migrations/0003_folded_search.sql").read_text()
    assert f"'{FOLD_FROM}'" in sql
    assert f"'{FOLD_TO}'" in sql


def test_best_quote_matches_queries_without_diacritics() -> None:
    text = "Bu el kitabı yıllık güncellenir. Uçak biletleri ekonomi sınıfında alınır. Son cümle."
    assert (
        best_quote(text, "ucak biletleri hangi sinifta", max_chars=50)
        == "Uçak biletleri ekonomi sınıfında alınır."
    )
