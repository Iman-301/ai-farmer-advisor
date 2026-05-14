"""
Postgres + pgvector retrieval for the agronomy KB (SRS FR08/FR10).
Default embedder: paraphrase-multilingual-MiniLM-L12-v2 (384-d). It is not Amharic-specialized
but works reasonably for short queries vs OCR/manual text; weaknesses show up as high L2
distance and wrong-doc ties—address with retrieval hints, reranking, and (optionally) a
stronger multilingual retriever after full re-ingest.

Upgrade path (same 384-d, requires wipe + re-ingest + matching env at query time):
  KB_EMBEDDING_MODEL=intfloat/multilingual-e5-small
  KB_EMBEDDING_QUERY_PREFIX=query:
  KB_EMBEDDING_PASSAGE_PREFIX=passage:
  KB_EMBEDDING_NORMALIZE=true

Do not change embedding model/normalization on an existing kb_chunks table without re-embedding.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger("rag_pg")

POSTGRES_URL = os.environ.get("POSTGRES_URL", "").strip()
RAG_PG_MAX_L2_DISTANCE = float(os.environ.get("RAG_PG_MAX_L2_DISTANCE", "1.35"))
EMBEDDING_MODEL_NAME = os.environ.get(
    "KB_EMBEDDING_MODEL",
    "rasyosef/roberta-amharic-text-embedding-base",
)
EMBEDDING_DIM = 768
# Optional: intfloat/multilingual-e5-small is also 384-d but needs prefixes + full re-ingest.
#   KB_EMBEDDING_QUERY_PREFIX="query: "
#   KB_EMBEDDING_PASSAGE_PREFIX="passage: "
#   KB_EMBEDDING_NORMALIZE=true
KB_EMBEDDING_QUERY_PREFIX = (os.environ.get("KB_EMBEDDING_QUERY_PREFIX") or "").strip()
KB_EMBEDDING_PASSAGE_PREFIX = (os.environ.get("KB_EMBEDDING_PASSAGE_PREFIX") or "").strip()
KB_EMBEDDING_NORMALIZE = os.environ.get("KB_EMBEDDING_NORMALIZE", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

_psycopg = None
_schema_ready = False
_embedder = None


def _get_existing_kb_chunks_dim(cur) -> int | None:
    """
    Return current kb_chunks.embedding vector dim if table exists, else None.
    pgvector dimension is encoded in atttypmod. Depending on pgvector version/build,
    it may be stored as (dim + 4) or dim. We detect both.
    """
    cur.execute("SELECT to_regclass('public.kb_chunks');")
    exists = cur.fetchone()[0]
    if not exists:
        return None
    cur.execute(
        """
        SELECT a.atttypmod
        FROM pg_attribute a
        WHERE a.attrelid = 'public.kb_chunks'::regclass
          AND a.attname = 'embedding'
          AND a.attnum > 0
          AND NOT a.attisdropped;
        """
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    typmod = int(row[0])
    # typmod == -1 means "unspecified"
    if typmod <= 0:
        return None
    cand_a = typmod - 4
    cand_b = typmod
    # Prefer common embedding dims
    for c in (cand_a, cand_b):
        if c in (128, 256, 384, 512, 768, 1024):
            return c
    # Fallback: cand_a is the documented encoding for many pgvector versions
    return cand_a if cand_a > 0 else cand_b


def _load_psycopg():
    global _psycopg
    if _psycopg is None:
        try:
            import psycopg
            _psycopg = psycopg
        except ImportError:
            _psycopg = False
    return _psycopg if _psycopg is not False else None


def pg_configured() -> bool:
    return bool(POSTGRES_URL)


def pg_driver_ok() -> bool:
    return _load_psycopg() is not None


def kb_pg_enabled() -> bool:
    return pg_configured() and pg_driver_ok()


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedder


def embed_texts(texts: list[str], *, for_query: bool = False) -> list[list[float]]:
    model = _get_embedder()
    prefix = KB_EMBEDDING_QUERY_PREFIX if for_query else KB_EMBEDDING_PASSAGE_PREFIX
    if prefix:
        texts = [prefix + (t or "") for t in texts]
    vectors = model.encode(
        texts,
        normalize_embeddings=KB_EMBEDDING_NORMALIZE,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def _conn():
    psycopg = _load_psycopg()
    if not psycopg:
        raise RuntimeError("psycopg is not installed")
    return psycopg.connect(POSTGRES_URL)


def init_pg_schema() -> None:
    """Create extension and tables if missing (idempotent)."""
    global _schema_ready
    if not kb_pg_enabled():
        logger.info("Postgres KB disabled (POSTGRES_URL unset or psycopg missing).")
        return
    if _schema_ready:
        return
    psycopg = _load_psycopg()
    with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            # If schema exists with a different vector dim, we must recreate/alter.
            existing_dim = _get_existing_kb_chunks_dim(cur)
            if existing_dim is not None and existing_dim != EMBEDDING_DIM:
                recreate = (os.environ.get("RAG_PG_RECREATE_SCHEMA") or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                )
                msg = (
                    f"kb_chunks.embedding is vector({existing_dim}) but this service is configured for "
                    f"vector({EMBEDDING_DIM}). You changed embedding models/dimensions.\n"
                    f"- Fix option A (recommended): set RAG_PG_RECREATE_SCHEMA=true and restart to recreate tables, "
                    f"then re-ingest.\n"
                    f"- Fix option B: drop the Postgres volume (docker compose down -v) and start fresh.\n"
                    f"- Fix option C: manually ALTER the column to vector({EMBEDDING_DIM}) and re-ingest."
                )
                if not recreate:
                    raise RuntimeError(msg)
                logger.warning("%s", msg)
                cur.execute("DROP TABLE IF EXISTS kb_chunks CASCADE;")
                cur.execute("DROP TABLE IF EXISTS kb_documents CASCADE;")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_documents (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    title TEXT NOT NULL,
                    source_org TEXT,
                    source_url TEXT,
                    language TEXT NOT NULL DEFAULT 'am',
                    status TEXT NOT NULL DEFAULT 'approved',
                    original_filename TEXT,
                    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
                    chunk_index INT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector(%s) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(document_id, chunk_index)
                );
                """
                % (EMBEDDING_DIM,),
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS kb_chunks_document_id_idx
                ON kb_chunks(document_id);
                """
            )
    _schema_ready = True
    logger.info("Postgres KB schema ready (pgvector).")


def count_approved_chunks() -> int:
    if not kb_pg_enabled():
        return 0
    init_pg_schema()
    psycopg = _load_psycopg()
    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE d.status = 'approved';
                """
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def count_documents() -> int:
    if not kb_pg_enabled():
        return 0
    init_pg_schema()
    psycopg = _load_psycopg()
    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM kb_documents WHERE status = 'approved';")
            row = cur.fetchone()
            return int(row[0]) if row else 0


def retrieve_for_query(
    query_text: str,
    top_k: int = 4,
    max_l2_distance: float | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """
    Returns (hits, best_distance). Each hit:
      chunk_id, document_id, content, distance, title, source_org, source_url, language
    """
    if not kb_pg_enabled():
        return [], 999.0
    init_pg_schema()
    qvec = embed_texts([query_text], for_query=True)[0]
    lit = _vector_literal(qvec)

    psycopg = _load_psycopg()
    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            # Important: do NOT hard-filter by distance here.
            # Some good matches can be slightly above the cutoff; callers can decide
            # whether to escalate based on the best distance.
            cur.execute(
                """
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.content,
                    (c.embedding <-> %s::vector) AS distance,
                    d.title,
                    d.source_org,
                    d.source_url,
                    d.language,
                    d.original_filename
                FROM kb_chunks c
                INNER JOIN kb_documents d ON d.id = c.document_id
                WHERE d.status = 'approved'
                ORDER BY c.embedding <-> %s::vector
                LIMIT %s;
                """,
                (lit, lit, top_k),
            )
            rows = cur.fetchall()

    hits: list[dict[str, Any]] = []
    best = 999.0
    for row in rows:
        dist = float(row[3])
        if dist < best:
            best = dist
        hits.append(
            {
                "chunk_id": str(row[0]),
                "document_id": str(row[1]),
                "content": row[2],
                "distance": dist,
                "title": row[4],
                "source_org": row[5],
                "source_url": row[6],
                "language": row[7],
                "original_filename": row[8],
            }
        )

    return hits, (best if hits else 999.0)


def _char_window_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + chunk_size)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


def _normalize_kb_text_keep_paragraphs(text: str) -> str:
    """Trim and normalize spaces per line; keep newlines for paragraph / table structure (FR08)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank <= 2:
                out.append("")
            continue
        blank = 0
        out.append(ln)
    return "\n".join(out).strip()


_PACKAGE_OR_TABLE_HINT = re.compile(
    r"ጥቅል\s*[\d፩፪፫፬፭፮፯፰፱፲]|ሠንጠረዥ|ሰንጠረዥ|\|\s*---+"
)


def _paragraph_is_table_or_dense_list(para: str, max_soft: int) -> bool:
    """True for extension-style package tables and bullet-heavy blocks (SRS FR08 — avoid mid-row splits)."""
    p = para.strip()
    if not p or len(p) > max_soft:
        return False
    if _PACKAGE_OR_TABLE_HINT.search(p):
        return True
    lines = [ln.strip() for ln in p.split("\n") if ln.strip()]
    bullet_lines = sum(1 for ln in lines if "•" in ln or "·" in ln or ln.startswith("-"))
    return bullet_lines >= 3


def _chunk_table_or_list_block(block: str, chunk_size: int, overlap: int) -> list[str]:
    """Prefer newline boundaries so table rows / bullet lists stay intact (FR08)."""
    block = block.strip()
    if not block:
        return []
    if len(block) <= chunk_size:
        return [block]
    lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
    if len(lines) <= 1:
        return _char_window_chunks(re.sub(r"\s+", " ", block), chunk_size, overlap)
    chunks: list[str] = []
    buf = ""
    for ln in lines:
        cand = f"{buf}\n{ln}" if buf else ln
        if len(cand) <= chunk_size:
            buf = cand
        else:
            if buf:
                chunks.append(buf)
            if len(ln) > chunk_size:
                chunks.extend(_char_window_chunks(ln, chunk_size, overlap))
                buf = ""
            else:
                buf = ln
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c]


def _chunk_by_sentences_one_line(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Ethiopic / Latin sentence boundaries on a flattened paragraph (legacy behavior)."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    parts = re.split(r"(?<=[።፧፨.!?])\s+", text)
    units = [p.strip() for p in parts if p.strip()]
    if not units:
        return _char_window_chunks(text, chunk_size, overlap)
    chunks: list[str] = []
    buf = ""
    for u in units:
        if len(u) > chunk_size:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            chunks.extend(_char_window_chunks(u, chunk_size, overlap))
            continue
        candidate = (buf + " " + u).strip() if buf else u
        if len(candidate) <= chunk_size:
            buf = candidate
        else:
            if buf:
                chunks.append(buf.strip())
            buf = u
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def chunk_amharic_text(text: str, chunk_size: int = 600, overlap: int = 100) -> list[str]:
    """
    Chunk Amharic KB text for embedding (SRS FR08).

    - Keeps paragraph boundaries (newlines) so tables / ጥቅል lists are not flattened away.
    - Dense list or package-table paragraphs are split on line boundaries, not mid-row.
    - Other paragraphs use Ethiopic sentence ends (። ፧ ፨) before character windows.
    """
    text = _normalize_kb_text_keep_paragraphs(text)
    if not text:
        return []
    max_para_soft = int(chunk_size * 2.2)
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paras:
        paras = [re.sub(r"\s+", " ", text)]
    out: list[str] = []
    for para in paras:
        if _paragraph_is_table_or_dense_list(para, max_para_soft):
            out.extend(_chunk_table_or_list_block(para, chunk_size, overlap))
        else:
            out.extend(_chunk_by_sentences_one_line(para, chunk_size, overlap))
    merged = [c for c in out if c]
    return merged if merged else _char_window_chunks(re.sub(r"\s+", " ", text), chunk_size, overlap)
