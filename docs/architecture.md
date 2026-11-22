# Architecture

```mermaid
flowchart LR
 U[Streamlit UI] --> API[FastAPI v1]
 API --> S[Assistant service]
 S --> R[Hybrid retrieval]
 R --> B[BM25 lexical search]
 R -. optional local .-> E[multilingual-e5-large]
 R --> DB[(SQLite scheme, source and chunk records)]
 S --> L[Local Ollama Qwen3]
 S --> C[Citations and abstention]
 API --> EL[Deterministic eligibility engine]
 API --> STT[Optional local Whisper]
 I[Curator JSON/CSV/local document] --> ING[Validation and ingestion]
 ING --> DB
```

The Streamlit question flow uses `POST /api/v1/chat/stream` and Server-Sent Events. FastAPI sends progress events for catalog search, ranking method, source review, prompt preparation, and generation. It sends the ranked source excerpts before streaming Ollama response fragments as token events. A final event carries the complete answer, citations, evidence status, warnings, provider, and timing. If evidence is insufficient, the endpoint streams a localized abstention. If Ollama is unavailable, it streams the retrieved excerpt fallback. The non-streaming `POST /api/v1/chat` endpoint remains available for clients that want one JSON response. Progress and retrieved evidence are shown; private model reasoning is not exposed.

```mermaid
sequenceDiagram
 participant U as User
 participant UI as Streamlit
 participant API as FastAPI
 participant R as Retriever
 participant L as Local LLM
 UI->>API: question + selected language
 API->>R: BM25 and optional dense search
 R-->>API: passages with provenance and status
 alt evidence sufficient
 API->>L: grounded prompt and passages (optional runtime)
 L-->>API: answer
 else insufficient evidence
 API-->>UI: localized abstention
 end
 API-->>UI: answer, source excerpts, citations, warnings
```

SQLite is the initial local store. BM25 is always available. Dense embeddings currently use on-demand local encoding, rather than persistent FAISS. Translation, reranking, PostgreSQL/pgvector, and experiment tracking are extension points, not implemented features.
