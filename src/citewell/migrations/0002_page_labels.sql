-- Printed page labels from the PDF (/PageLabels), e.g. "iv" or "12", when they differ
-- from the physical page number stored in chunks.page.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_label text;
