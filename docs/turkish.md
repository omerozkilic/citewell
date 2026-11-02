# Turkish support

Citewell treats Turkish as a first-class language, not an afterthought.

| Problem | What Citewell does |
|---|---|
| `"ISPARTA".lower()` → `isparta` (should be `ısparta`), `"İ".lower()` → `i̇` | `tr_lower` maps `I→ı`, `İ→i` before indexing and querying; PostgreSQL never sees ambiguous capitals. |
| Agglutinative morphology (`parolalarımız`, `izinlerinizi`) | PostgreSQL's Snowball `turkish` stemmer for keyword search; multilingual dense embeddings for the rest; quote selection uses prefix stems. |
| Legacy encodings | Text files fall back to Windows-1254 before Latin-1. |
| PDF extraction artefacts | NFC normalisation, hyphenation repair across lines, line reflow. |
| Numbers and amounts (`3.500 TL`) | Sentence splitting does not break on thousands separators. |
| Cross-lingual questions | bge-m3 / multilingual-e5 embed Turkish and English into the same space; collections can have different text-search languages and be searched together. |

## Known limitations

- Queries typed **without Turkish characters** (`ogrenci` for `öğrenci`) hurt keyword search; dense
  retrieval usually still finds the passage. Accent-insensitive matching is on the roadmap.
- The Snowball stemmer is rule-based; very irregular forms may not conflate. Hybrid search exists
  precisely to compensate.
