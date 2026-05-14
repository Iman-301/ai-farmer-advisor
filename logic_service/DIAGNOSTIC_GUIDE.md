# Amharic RAG Diagnostic Guide

## Overview

This guide explains how to run the diagnostic tests to identify root causes of Amharic RAG retrieval failures.

## Prerequisites

### 1. Database Setup

Ensure Postgres with pgvector is running:

```bash
# Start the database (if using Docker Compose)
docker compose up -d postgres

# Verify connection
set POSTGRES_URL=postgresql://kb:kb@localhost:5432/advisor_kb
```

### 2. Knowledge Base Ingestion

Ingest Amharic PDFs into the knowledge base:

```bash
# From repo root
cd Voice-To-Voice-Farmer-Advisor/logic_service

# Install dependencies
pip install -r requirements.txt

# Ingest PDFs
python scripts/ingest_kb_folder.py --folder ./kb_documents/amharic
```

### 3. Install Test Dependencies

```bash
pip install pytest
```

## Running Diagnostics

### Step 1: Run Diagnostic Script

The diagnostic script performs component-level analysis:

```bash
cd Voice-To-Voice-Farmer-Advisor/logic_service
python scripts/diagnose_amharic_rag.py
```

This will:
- Check PDF extraction quality (character preservation)
- Analyze normalization impact (character folding)
- Evaluate chunking quality (boundary issues)
- Measure embedding quality (semantic separation)
- Calibrate distance threshold (appropriate for Amharic)

**Output**: `diagnostic_results.json` with findings and recommendations

### Step 2: Run Property-Based Tests

Run the test suite to confirm bug existence and establish baseline:

```bash
cd Voice-To-Voice-Farmer-Advisor/logic_service
pytest tests/test_amharic_rag_diagnostics.py -v -s
```

**Expected Results**:
- **Bug Condition Tests (Property 1)**: SHOULD FAIL (proves bug exists)
  - `test_amharic_query_retrieval_accuracy` - Fails if Recall@4 < 70%
  - `test_distance_scores_appropriate` - Fails if relevant chunks have higher distances
  
- **Preservation Tests (Property 2)**: SHOULD PASS (establishes baseline)
  - `test_chunking_fallback_preserved` - Passes if non-Ethiopic chunking unchanged
  - `test_normalization_basic_behavior` - Passes if basic normalization unchanged
  - `test_embedding_dimensions_preserved` - Passes if embeddings are 384-d

## Interpreting Results

### Diagnostic Script Output

The script will identify which components are causing failures:

1. **Extraction Issues**: Missing characters, extra spaces, encoding problems
   → **Fix**: Implement Fix Option E (Extraction Enhancement)

2. **Normalization Over-Folding**: Semantically distinct characters folded together
   → **Fix**: Implement Fix Option C (Normalization Refinement)

3. **Chunking Boundary Issues**: Headers separated from content, lists split
   → **Fix**: Implement Fix Option D (Chunking Improvement)

4. **Low Embedding Quality**: Poor semantic separation for Amharic
   → **Fix**: Implement Fix Option A (Embedding Model Upgrade)

5. **Threshold Too Strict**: Relevant chunks filtered out by 1.35 threshold
   → **Fix**: Implement Fix Option B (Distance Threshold Adjustment)

### Test Suite Output

The test suite provides quantitative metrics:

- **Recall@4**: Percentage of queries retrieving at least 1 relevant chunk
- **Distance Distribution**: Average distances for relevant vs irrelevant chunks
- **Failure Examples**: Specific queries that failed with retrieved chunks

## Next Steps

Based on diagnostic findings, implement the recommended fixes in priority order:

1. Review `diagnostic_results.json` for recommendations
2. Implement fixes indicated by diagnostics (see tasks.md Phase 3)
3. Re-run tests to verify improvements
4. Ensure preservation tests still pass (no regressions)

## Troubleshooting

### "Postgres KB not available"

- Check POSTGRES_URL environment variable is set
- Verify Postgres is running: `docker compose ps`
- Ensure pgvector extension is installed

### "Knowledge base is empty"

- Run ingestion script: `python scripts/ingest_kb_folder.py`
- Check PDF files exist in `kb_documents/amharic/`
- Verify PDFs are not scanned images (need OCR)

### "Module not found" errors

- Install dependencies: `pip install -r requirements.txt`
- Ensure you're in the correct directory
- Check Python path includes logic_service

### Tests skip with "KB not available"

- This is expected if database is not running
- Tests will be skipped gracefully
- Set up database and re-run

## Manual Testing

If automated tests cannot run, you can manually test retrieval:

```python
from rag_pg import retrieve_for_query

# Test query
query = "የድህረ ምርት ኪሳራ እንዴት መቀነስ እችላለሁ?"
hits, distance = retrieve_for_query(query, top_k=4)

# Inspect results
for hit in hits:
    print(f"Distance: {hit['distance']:.3f}")
    print(f"Title: {hit['title']}")
    print(f"Content: {hit['content'][:200]}...")
    print()
```

## Contact

For questions or issues, refer to the spec documents:
- `Voice-To-Voice-Farmer-Advisor/.kiro/specs/amharic-rag-retrieval-fix/bugfix.md`
- `Voice-To-Voice-Farmer-Advisor/.kiro/specs/amharic-rag-retrieval-fix/design.md`
- `Voice-To-Voice-Farmer-Advisor/.kiro/specs/amharic-rag-retrieval-fix/tasks.md`
