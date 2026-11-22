# Requirements checklist from the supplied presentation

Reviewed all 12 slides in two passes. The deck frames the product around fragmented Central and State scheme information, low awareness, language barriers, eligibility complexity, and access to application guidance. Its proposed flow is a Streamlit experience, language/speech layer, multilingual-e5 retrieval, hybrid search, reranking/eligibility scoring, multilingual answer generation, and a scheme/profile/analytics data layer.

| Slide requirements | Implementation/status |
|---|---|
| Central and State schemes, discovery, categories and beneficiaries | Curator-importable schema and explorer; no authentic data was supplied, so catalog starts empty. |
| English source documents queried in Bengali/Hindi | BM25 works on Unicode terms; optional multilingual-e5-large dense retrieval supports cross-lingual semantic search when explicitly installed. Requires benchmark before quality claims. |
| RAG with source citations and multilingual answers | Grounded local Ollama adapter with excerpt-only fallback and real stored source links. |
| Eligibility personalization | Deterministic, source-verified structured conditions; no automatic approval claims. |
| Voice accessibility | Audio upload API and UI with editable transcription; optional local faster-whisper. Microphone recording control and real IndicConformer benchmark remain outstanding. |
| Translation and reranking | Architecture leaves room, not integrated; direct semantic retrieval is primary and no translation quality is assumed. |
| Streamlit, FastAPI, persistence, evaluation/MLOps | Streamlit and FastAPI, SQLite; evaluation tooling and local manifests. MLflow not integrated. |
| Deck's 10+ languages and 10,000 QA target | Future target, not implemented or measured. Initial interface is English/Bengali/Hindi. |

Trade-offs: the prompt's no-paid-service requirement replaces GPT/Gemini and Pinecone/Weaviate Cloud with local Ollama/SQLite and optional local embeddings. The prompt's explicit no-unauthorized-crawling rule replaces bulk portal scraping with manual/CSV/JSON/local-file curation.
