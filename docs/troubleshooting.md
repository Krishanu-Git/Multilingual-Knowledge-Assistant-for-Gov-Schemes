# Troubleshooting

- **UI/API connection error:** start `uvicorn backend.main:app --reload` from the repository root, then `streamlit run frontend/app.py`.
- **No schemes:** catalog is intentionally empty until curator JSON/CSV records are imported.
- **No answer:** source documents must be ingested; inspect `python scripts/inspect_index.py`.
- **Ollama warning:** install Ollama separately, pull the configured model explicitly, start its local service, and set `GSA_LLM_MODEL` as needed. The UI still displays source excerpts if unavailable.
- **Embeddings unavailable:** `pip install -e '.[models]'`, set `GSA_EMBEDDINGS_ENABLED=true`, and ensure the selected model is locally accessible. Retrieval falls back to BM25 on errors.
- **Speech unavailable:** install optional dependencies and pre-cache faster-whisper weights, set `GSA_STT_PROVIDER=faster-whisper`; otherwise use text input.
- **Scanned PDF has no text:** OCR is not bundled. Use a permitted OCR workflow locally and retain a source page mapping before importing extracted text.
- **SQLite reset:** back up or remove only your own local database manually; it is ignored by Git.
