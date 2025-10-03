# PoC Architecture Overview

## Goals
- Deliver a single-channel chatbot that answers manufacturing supply-chain questions with document citations.
- Base the system on Verba (Weaviate + RAG pipeline) while preparing for agentic extensions.
- Support small pilot cohort (<= 20 users) and curated document subset (< 500 docs, < 200 MB).

## High-Level Components
1. **User Channel** — start with Verba web UI. Provide Slack bridge once responses are reliable.
2. **Orchestration Layer** — Verba backend orchestrates retrieval + generation. Extend with custom tools for ERP lookups when APIs become available.
3. **Vector Store (Weaviate)** — hosts embeddings for pilot document corpus and glossary terms.
4. **Local Model Runtime (Ollama)** — default LLM + embedding models for on-premise experimentation (e.g. `llama3`, `nomic-embed-text`).
5. **Document Processing Pipeline** — ingestion script normalizes PDFs, spreadsheets, and HTML exports, enriches metadata (version, effective date, product codes).
6. **Observability** — structured logging + feedback capture stored in `internal_poc/data/reference/feedback/` (to be externalized later).

## Retrieval Strategy
- **Hybrid Search**: combine vector similarity + metadata filtering (product family, doc type, version, region).
- **Glossary Boosting**: treat glossary terms as high-priority context to decode abbreviations (e.g., `LT` → lead time).
- **Freshness Handling**: apply `effective_date` and `version` fields to prioritize latest documents; keep `is_superseded` flag for compliance.

## Response Construction
- Generate answers with explicit sourced snippets; enforce JSON schema for citations to ease UI rendering.
- Include optional tabular response when user prompt matches lead time or capacity estimation intents.
- Provide confidence score by exposing top similarity and generation logprob metadata.

## Data Flow
```
User Prompt → Verba Backend → Retriever (Weaviate) → Context Packager → LLM via Ollama → Response + Citations → UI
                                                          ↓
                                                  Feedback Logger
```

## Deployment Footprint
- **Local Docker Compose** for PoC. Containers: `verba-backend`, `verba-frontend`, `weaviate`, `text-image workers (optional)`, `ollama` (host runtime).
- Host machine requires 16 GB RAM, 8 vCPU recommended for smooth embedding builds.

## Extension Hooks
- ERP/SCM adapter: define interface in `internal_poc/scripts/tooling/erp_client.py` (stub forthcoming) to support agent tool calls.
- SLA monitor: stream interaction events to lightweight SQLite or Postgres for analytics (phase 2).
- Authentication integration: replace default frontend auth with SSO (phase 3) using reverse proxy.
