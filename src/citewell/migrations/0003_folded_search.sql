-- Diacritic-insensitive keyword search: a second tsvector over text with Turkish (and common
-- Latin) diacritics folded, e.g. "öğrenci" -> "ogrenci". New rows are written by the application
-- with citewell.text.fold(); existing rows are back-filled here with the same character mapping.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv_folded tsvector;

UPDATE chunks c
SET tsv_folded = to_tsvector(
        col.language::regconfig,
        translate(
            lower(translate(concat_ws(' ', c.section, c.text), 'Iİ', 'ıi')),
            'çğıöşüâîûéèêëáàäóòôúùñ',
            'cgiosuaiueeeeaaaooouun'
        )
    )
FROM collections col
WHERE col.id = c.collection_id AND c.tsv_folded IS NULL;

CREATE INDEX IF NOT EXISTS chunks_tsv_folded_gin ON chunks USING gin (tsv_folded);
