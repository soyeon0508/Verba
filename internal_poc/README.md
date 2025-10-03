# Manufacturing Knowledge Bot PoC

This directory hosts the working area for the manufacturing-focused PoC built on top of the [Verba](../README.md) project.

## Layout

- `config/` — environment templates and YAML overrides for Verba + orchestration jobs.
- `docs/` — architecture notes, onboarding checklist, and operating procedures.
- `data/` — curated sample content used for the prototype. Split into `glossary/` (terminology) and `reference/` (documents, tables, BOM extracts).
- `scripts/` — utility scripts for bootstrapping the Weaviate instance, loading documents, and running quality checks.

## Getting Started

1. Create a Python 3.11 virtual environment at repo root and install Verba in editable mode:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
2. Copy `config/.env.template` to `.env` at the Verba root and adjust values to your environment (Ollama endpoints, OpenAI keys, etc.).
3. Start the local stack (Weaviate + Verba backend + frontend) via Docker Compose:
   ```bash
   docker compose --env-file internal_poc/config/.env.template up -d --build
   ```
   Replace the env-file path with the actual `.env` you maintain.
4. Run the ingestion helper to push sample documents and glossary terms:
   ```bash
   python internal_poc/scripts/ingest_sample_data.py --source internal_poc/data
   ```
5. Visit `http://localhost:3000` to explore the prototype UI.

## Next Steps

- Review `docs/poc_architecture.md` for the recommended manufacturing-specific workflow.
- Populate `data/reference/` with a small but representative document set (spec sheets, SOPs, lead time policies).
- Establish a rotation for refreshing embeddings when documents change (see `docs/operations_playbook.md`).
- Capture pilot feedback in `docs/pilot_feedback.md` and feed high-confidence updates back into the knowledge base.
