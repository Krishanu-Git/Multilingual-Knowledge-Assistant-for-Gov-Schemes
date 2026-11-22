# Data curation and ingestion

Do not crawl myScheme or bulk-copy its pages: its [current terms](https://www.myscheme.gov.in/terms-of-use) prohibit bots/scrapers or automatic page access/copying unless expressly authorized in writing. The workspace starts without an authorized export or authentic scheme records. Keep `data/curated/` empty until a curator verifies sources. JSON and CSV import are supported, as are permitted local PDF, text, Markdown and HTML documents. An official myScheme page-derived record should retain the original URL in `official_source_url`; supplementary department documents have their own title, type and source URL and must not be described as myScheme publications.

1. Copy `data/templates/schemes.json` and fill factual fields from a checked source, preserving unknowns as null.
2. Assign a stable `scheme_id`. Imported records default to `unverified`; successful import is not verification.
3. Set `verification_status=verified` only after checking current applicability and version, and record `source_last_verified_date` plus `verification_evidence`. Use `needs_review` for unresolved gaps/conflicts; `outdated` when authentic content no longer applies; `superseded` when a newer identified document replaces it.
4. Import: `python scripts/import_schemes.py path/to/curated.json` (or CSV).
5. Ingest an authorized, local document: `python scripts/ingest_documents.py stable-id path/to/source.pdf --title 'Document title' --url https://official.example/source`.

Imports and content-hash based chunk identifiers are repeatable. Reingesting a scheme replaces its chunks; keep conflicting versions as separately curated records/documents and flag them for review instead of merging rules. PDF extraction is text extraction only; scanned PDFs need OCR performed by the curator before ingestion. Document intake does not verify authenticity.
