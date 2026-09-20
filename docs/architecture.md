# Architecture

## Runtime flow

```text
allowed file path
      │
      ▼
parser → clean/redact → section/page metadata → overlapping chunks
      │                                      │
                                      └── SHA-256 + fingerprint gate       └── Mock/real Embedding
                                                     │
                                                     ▼
                                      SQLite chunks + vector_json
                                                     │
question ──► vector Top 10 ─┐                        │
                            ├─ deduplicate ─► 0.7 vector + 0.3 BM25
question ──► BM25 Top 10 ───┘                        │
                                                     ▼
                                      evidence gate / top 4–6
                                                     │
                                                     ▼
                                          LLM provider → citations
```

## Components

- `config.py` owns project-local paths, file size, extension, Agent step/retry limits, log scan limits and remote-model global authorization.
- `security.py` resolves absolute paths inside allowed roots, rejects traversal, sanitizes note names and redacts common secret fields.
- `rag/parser.py` handles UTF-8 text, Markdown sections, text PDF pages and C/H function sections with a recorded fallback strategy. `rag/chunker.py` keeps page/section metadata and 700/100-character defaults.
- `storage/metadata.py` stores documents and chunks transactionally in SQLite. An unchanged SHA-256 skips re-embedding only when the provider/model/dimension/parser/chunk fingerprint also matches; old schemas are migrated additively.
- `rag/retriever.py` computes vector cosine scores and a dependency-free BM25 score. `rag/reranker.py` normalizes both inputs and applies the explicit baseline formula.
- `rag/answer.py` filters results through meaningful technical/Chinese-token overlap before the LLM sees them. A missing evidence set returns the fixed refusal.
- `runtime.py` is the composition root. API, UI, Agent and evaluation use the same service boundaries.
- `agent/tools.py` contains only four registered tools. Read tools use cooperative deadlines and bounded file/byte scans; save_note is idempotent and never automatically retried. `workflow.py` controls a maximum of four steps.
- `storage/sessions.py` stores the most recent ten turns, deterministic summary, project/mode, Agent state and trace events in SQLite.
- `services.py` is the shared import and RAG conversation layer used by FastAPI and Streamlit.

## API request boundaries

The ingest API accepts a path relative to `data/inbox`; the log tool accepts a path relative to `data/logs`. Neither endpoint constructs a shell command. All API errors, including 404 and 405, are converted to stable `{error:{code,message},trace_id}` responses and receive an `X-Trace-ID` header. Remote model use requires both global and per-request authorization.

## Provider boundary

The default provider graph is:

```text
MockEmbeddingProvider → SQLiteIndex → HybridRetriever
MockLLMProvider       → LLMGateway → RAGAnswerService
```

OpenAI-compatible adapters are opt-in through environment configuration and a per-request external-processing flag. Tests use a local fake transport only; the current project has no evidence for real model quality.
