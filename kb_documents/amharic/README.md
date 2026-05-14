# Amharic knowledge-base files (ingest → Postgres + pgvector)

Put files here (one file ≈ one source document). The ingest script skips `README.md`.

**Supported types:** `.pdf` (text layer), `.docx`, `.txt`, `.md` (UTF-8).

**Scanned PDFs** (pages are images, no selectable text) will extract almost nothing until you run OCR and save a `.txt` or a PDF with a text layer.

## Ingest (Docker)

From the repo root (`Voice-To-Voice-Farmer-Advisor`):

### RAG-only mode (recommended for testing)

This starts only **Postgres + logic_service** (no TTS/STT/telephony):

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml up -d
```

Then ingest:

```bash
docker compose -f docker-compose.yml -f docker-compose.rag.yml exec logic_service python scripts/ingest_kb_folder.py
```

Ask questions:

- `http://localhost:8002/docs` → POST `/ask`

### Full stack mode

1. Start Postgres (included in `docker compose up`): wait until healthy.
2. Run:

```bash
docker compose run --rm logic_service python scripts/ingest_kb_folder.py
```

Optional: `--wipe` clears all KB rows before loading.  
Optional: `--folder /path/to/other/folder` or set env `KB_INGEST_DIR`.

## After ingest

- Retrieval uses **Postgres** whenever `POSTGRES_URL` is set **and** there is at least one approved chunk; otherwise the service falls back to **Chroma** + `mock_kb.json`.
- Tune similarity with env **`RAG_PG_MAX_L2_DISTANCE`** (default `1.35`).

## SRS note

For production, prefer **`status = approved`** only after human review. New rows from this script are inserted as **`approved`** for development; you can later switch defaults to `pending` and add an admin approval flow.
