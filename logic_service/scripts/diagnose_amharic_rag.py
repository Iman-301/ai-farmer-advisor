#!/usr/bin/env python3
"""
Diagnostic script for Amharic RAG retrieval issues.

This script performs component-level diagnostics to identify root causes:
1. PDF Extraction Quality Check
2. Text Normalization Impact Analysis
3. Chunking Quality Check
4. Embedding Quality Analysis
5. Distance Threshold Calibration

Usage:
  python scripts/diagnose_amharic_rag.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any
import json

# Ensure Windows consoles don't crash on unicode output.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add logic_service to path
LOGIC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(LOGIC_ROOT) not in sys.path:
    sys.path.insert(0, str(LOGIC_ROOT))

from rag_pg import (
    retrieve_for_query,
    chunk_amharic_text,
    embed_texts,
    kb_pg_enabled,
    count_approved_chunks,
    POSTGRES_URL,
)
from nlu import normalize_ethiopic_input
from scripts.ingest_kb_folder import extract_text_from_file, iter_kb_files, default_ingest_folder


def _safe_print(s: str) -> None:
    """
    Windows consoles often default to cp1252/cp1256; avoid crashing on unicode symbols.
    """
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def _module_status() -> list[str]:
    out: list[str] = []
    try:
        import pdfminer  # noqa: F401

        out.append("pdfminer: OK")
    except Exception as exc:
        out.append(f"pdfminer: MISSING/ERROR ({exc!r})")
    try:
        import fitz  # noqa: F401

        out.append("PyMuPDF(fitz): OK")
    except Exception as exc:
        out.append(f"PyMuPDF(fitz): MISSING/ERROR ({exc!r})")
    return out


def _ethiopic_ratio(text: str) -> float:
    if not text:
        return 0.0
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return 0.0
    et = [c for c in non_ws if "\u1200" <= c <= "\u137f"]
    return len(et) / len(non_ws)


def _suspicious_ascii_ratio(text: str) -> float:
    """
    Heuristic: if we extracted mostly ASCII letters/digits/punct, it's likely a legacy-font PDF
    where Ethiopic glyphs were mapped onto Latin codepoints.
    """
    if not text:
        return 0.0
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return 0.0
    ascii_like = [c for c in non_ws if " " <= c <= "~"]
    return len(ascii_like) / len(non_ws)


# Test queries for diagnostics
TEST_QUERIES = [
    {
        "query": "የድህረ ምርት ኪሳራ እንዴት መቀነስ እችላለሁ?",
        "query_en": "How can I reduce post-harvest losses?",
        "expected_keywords": ["ኪሳራ", "ድህረ ምርት", "መቀነስ"],
    },
    {
        "query": "ጥቅል 1 ምን ይጨምራል?",
        "query_en": "What does bundle 1 include?",
        "expected_keywords": ["ጥቅል 1", "የአፈር", "የውሃ"],
    },
    {
        "query": "LandPKS መተግበሪያ እንዴት እጠቀማለሁ?",
        "query_en": "How do I use the LandPKS app?",
        "expected_keywords": ["LandPKS", "መተግበሪያ"],
    },
]


def print_section(title: str):
    """Print a section header."""
    _safe_print(f"\n{'='*80}")
    _safe_print(f"{title}")
    _safe_print(f"{'='*80}\n")


def print_subsection(title: str):
    """Print a subsection header."""
    _safe_print(f"\n{'-'*80}")
    _safe_print(f"{title}")
    _safe_print(f"{'-'*80}\n")


def check_extraction_quality(*, max_pdfs: int = 0, dump_text: bool = False, dump_dir: Path | None = None):
    """
    Diagnostic 1: PDF Extraction Quality Check
    
    Checks if PDF extraction preserves Amharic characters correctly.
    """
    print_section("DIAGNOSTIC 1: PDF EXTRACTION QUALITY CHECK")

    _safe_print("Extractor dependency status:")
    for line in _module_status():
        _safe_print(f"  - {line}")
    _safe_print("")
    
    folder = Path(default_ingest_folder())
    if not folder.is_dir():
        print(f"❌ KB folder not found: {folder}")
        return
    
    pdf_files = [f for f in iter_kb_files(folder) if f.suffix.lower() == ".pdf"]
    
    if not pdf_files:
        print(f"❌ No PDF files found in {folder}")
        return
    
    if max_pdfs and max_pdfs > 0:
        pdf_files = pdf_files[:max_pdfs]
    print(f"Found {len(pdf_files)} PDF files. Checking all selected PDFs...\n")
    
    issues_found = []
    
    if dump_text:
        out_dir = dump_dir or (LOGIC_ROOT / "diagnostic_pdf_text")
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"Dumping extracted text to: {out_dir}\n")
    else:
        out_dir = None

    for pdf_path in pdf_files:
        print(f"Checking: {pdf_path.name}")
        
        try:
            extracted_text = extract_text_from_file(pdf_path)
            
            # Check 1: Ethiopic character presence
            ethiopic_ratio = _ethiopic_ratio(extracted_text)
            ascii_ratio = _suspicious_ascii_ratio(extracted_text)
            
            print(f"  ✓ Extracted {len(extracted_text)} characters")
            print(f"  ✓ Ethiopic ratio: {ethiopic_ratio:.1%}")
            print(f"  ✓ ASCII-like ratio: {ascii_ratio:.1%}")
            
            # Check 2: Suspicious patterns (extra spaces, missing characters)
            double_spaces = extracted_text.count("  ")
            triple_spaces = extracted_text.count("   ")
            nulls = extracted_text.count("\x00")
            
            if double_spaces > len(extracted_text) / 100:
                print(f"  ⚠️  Many double spaces found: {double_spaces}")
                issues_found.append(f"{pdf_path.name}: Excessive double spaces")
            
            if triple_spaces > 10:
                print(f"  ⚠️  Triple spaces found: {triple_spaces}")
                issues_found.append(f"{pdf_path.name}: Triple spaces (possible missing chars)")

            if nulls:
                print(f"  ⚠️  NUL bytes found: {nulls}")
                issues_found.append(f"{pdf_path.name}: NUL bytes in extracted text")

            # Check 3: Likely legacy font mapping (Ethiopic too low, ASCII too high)
            if len(extracted_text) > 200 and ethiopic_ratio < 0.10 and ascii_ratio > 0.60:
                print("  ❌ Likely legacy-font / wrong encoding extraction (looks mostly ASCII).")
                issues_found.append(f"{pdf_path.name}: Likely legacy-font extraction (mostly ASCII)")

            if len(extracted_text) < 50:
                print("  ❌ Too little text extracted (scanned PDF or extraction failure).")
                issues_found.append(f"{pdf_path.name}: Too little extracted text (<50 chars)")
            
            # Check 3: Sample text
            sample_head = extracted_text[:500]
            mid_start = max(0, (len(extracted_text) // 2) - 250)
            sample_mid = extracted_text[mid_start : mid_start + 500]
            print("  Sample text (head 250 chars):")
            print(f"    {sample_head[:250].replace(chr(10), ' ')}")
            print("  Sample text (middle 250 chars):")
            print(f"    {sample_mid[:250].replace(chr(10), ' ')}")

            if out_dir is not None:
                out_path = out_dir / f"{pdf_path.stem}.extracted.txt"
                out_path.write_text(extracted_text, encoding="utf-8", errors="ignore")
                print(f"  ✓ Wrote: {out_path.name}")
            
        except Exception as exc:
            _safe_print(f"  Extraction failed: {exc}")
            issues_found.append(f"{pdf_path.name}: Extraction error - {exc!r}")
        
        print()
    
    if issues_found:
        print(f"\n⚠️  ISSUES FOUND:")
        for issue in issues_found:
            print(f"  - {issue}")
    else:
        print(f"\n✓ No obvious extraction issues detected")
    
    return issues_found


def check_normalization_impact():
    """
    Diagnostic 2: Normalization Impact Analysis
    
    Checks if normalize_ethiopic_input() removes important distinctions.
    """
    print_section("DIAGNOSTIC 2: NORMALIZATION IMPACT ANALYSIS")
    
    # Test cases with semantically distinct characters
    test_cases = [
        ("ዓመት", "year (with ዓ)"),
        ("አመት", "hundred (with አ)"),
        ("ሃይል", "power (with ሃ)"),
        ("ሀይል", "power (with ሀ)"),
        ("ጸሐይ", "sun (with ጸ)"),
        ("ፀሐይ", "sun (with ፀ)"),
    ]
    
    print("Testing character folding:\n")
    
    folding_issues = []
    
    for original, description in test_cases:
        normalized = normalize_ethiopic_input(original)
        changed = original != normalized
        
        print(f"  {original} ({description})")
        print(f"    → {normalized} {'[CHANGED]' if changed else '[UNCHANGED]'}")
        
        if changed:
            folding_issues.append(f"{original} → {normalized} ({description})")
        print()
    
    # Test retrieval with/without normalization
    if kb_pg_enabled() and count_approved_chunks() > 0:
        print_subsection("Retrieval Impact Test")
        
        for test_query in TEST_QUERIES[:2]:
            query = test_query["query"]
            query_en = test_query["query_en"]
            
            print(f"Query: {query}")
            print(f"English: {query_en}\n")
            
            # Retrieve with normalization (current behavior)
            hits_normalized, dist_normalized = retrieve_for_query(query, top_k=4)
            
            print(f"  With normalization:")
            print(f"    Best distance: {dist_normalized:.3f}")
            if hits_normalized:
                print(f"    Top result: {hits_normalized[0].get('original_filename', 'N/A')}")
            
            # Note: Can't easily test without normalization without modifying code
            # This would require temporarily disabling normalization
            print()
    
    if folding_issues:
        print(f"\n⚠️  CHARACTER FOLDING DETECTED:")
        for issue in folding_issues:
            print(f"  - {issue}")
        print(f"\n  This may remove semantically important distinctions.")
    else:
        print(f"\n✓ No character folding detected")
    
    return folding_issues


def check_chunking_quality():
    """
    Diagnostic 3: Chunking Quality Check
    
    Analyzes chunk boundaries for semantic coherence.
    """
    print_section("DIAGNOSTIC 3: CHUNKING QUALITY CHECK")
    
    # Sample Amharic text with headers and lists
    sample_text = """
ጥቅል 1: የአፈር እና የውሃ ጥበቃ

ይህ ጥቅል የሚከተሉትን ይጨምራል:
- የመሬት ቋሚነት
- የውሃ አያያዝ
- የአፈር ሽርሽር መከላከል

የመስክ ጉብኝቶች

የመስክ ጉብኝቶች ከጥቅል 1 እና ከጥቅል 2 የሚገኙ ቁሳቁሶችን ይጠቀማሉ። እነዚህም የሚከተሉትን ይጨምራሉ:
- ፍሊፕ ቻርት
- ፖስተሮች
- የውይይት መመሪያዎች

ጥቅል 2: በዝቅተኛ አካባቢዎች የሰብል ምርት

ይህ ጥቅል የሚከተሉትን ይጨምራል:
- የሰብል ምርጫ
- የመሬት ዝግጅት
- የዘር መዝራት
- የውሃ አያያዝ
""" * 5
    
    chunks = chunk_amharic_text(sample_text)
    
    print(f"Total chunks created: {len(chunks)}\n")
    
    # Analyze chunk sizes
    sizes = [len(c) for c in chunks]
    avg_size = sum(sizes) / len(sizes) if sizes else 0
    
    print(f"Chunk size statistics:")
    print(f"  Average: {avg_size:.0f} characters")
    print(f"  Min: {min(sizes) if sizes else 0} characters")
    print(f"  Max: {max(sizes) if sizes else 0} characters")
    print()
    
    # Check for header/content splits
    boundary_issues = []
    
    print("Checking for boundary issues:\n")
    
    for i, chunk in enumerate(chunks[:10], 1):  # Check first 10 chunks
        # Check if header is separated from content
        has_header = "ጥቅል" in chunk or "የመስክ ጉብኝቶች" in chunk
        has_list_intro = "ይጨምራል:" in chunk or "የሚከተሉትን" in chunk
        has_list_items = chunk.count("-") >= 2
        
        if has_list_intro and not has_list_items:
            issue = f"Chunk {i}: List intro without items"
            boundary_issues.append(issue)
            print(f"  ⚠️  {issue}")
            print(f"      Preview: {chunk[:150]}...")
            print()
        
        if has_header:
            # Check if header has following content
            lines = chunk.split("\n")
            if len(lines) < 3:
                issue = f"Chunk {i}: Header without sufficient content"
                boundary_issues.append(issue)
                print(f"  ⚠️  {issue}")
                print(f"      Preview: {chunk[:150]}...")
                print()
    
    if boundary_issues:
        print(f"\n⚠️  BOUNDARY ISSUES FOUND: {len(boundary_issues)}")
        print(f"  Chunks may split semantic units (headers from content, list intros from items)")
    else:
        print(f"\n✓ No obvious boundary issues detected")
    
    return boundary_issues


def check_embedding_quality():
    """
    Diagnostic 4: Embedding Quality Analysis
    
    Measures embedding space properties for Amharic text.
    """
    print_section("DIAGNOSTIC 4: EMBEDDING QUALITY ANALYSIS")
    
    # Test semantic similarity
    test_pairs = [
        # Similar meaning (should have low distance)
        ("የድህረ ምርት ኪሳራ", "ድህረ ምርት ኪሳራ መቀነስ", "similar"),
        ("የአፈር ጥበቃ", "የአፈር እና የውሃ ጥበቃ", "similar"),
        ("ማዳበሪያ መጠቀም", "ማዳበሪያ አጠቃቀም", "similar"),
        # Different meaning (should have high distance)
        ("የድህረ ምርት ኪሳራ", "LandPKS መተግበሪያ", "different"),
        ("የአፈር ጥበቃ", "የውይይት ቡድን", "different"),
        ("ማዳበሪያ መጠቀም", "የመስክ ጉብኝት", "different"),
    ]
    
    print("Testing semantic similarity:\n")
    
    similar_distances = []
    different_distances = []
    
    for text1, text2, relation in test_pairs:
        emb1 = embed_texts([text1], for_query=True)[0]
        emb2 = embed_texts([text2], for_query=True)[0]
        
        # Calculate L2 distance
        import numpy as np
        distance = float(np.linalg.norm(np.array(emb1) - np.array(emb2)))
        
        print(f"  {text1}")
        print(f"  {text2}")
        print(f"  → Distance: {distance:.3f} ({relation})")
        print()
        
        if relation == "similar":
            similar_distances.append(distance)
        else:
            different_distances.append(distance)
    
    # Analyze separation
    if similar_distances and different_distances:
        avg_similar = sum(similar_distances) / len(similar_distances)
        avg_different = sum(different_distances) / len(different_distances)
        separation = avg_different - avg_similar
        
        print(f"Distance statistics:")
        print(f"  Similar pairs: {avg_similar:.3f} (avg)")
        print(f"  Different pairs: {avg_different:.3f} (avg)")
        print(f"  Separation: {separation:.3f}")
        print()
        
        if separation < 0.3:
            print(f"  ⚠️  LOW SEPARATION: Embedding model may not distinguish Amharic semantics well")
            return "low_separation"
        else:
            print(f"  ✓ Reasonable separation between similar and different pairs")
            return "good_separation"
    
    return "insufficient_data"


def check_threshold_calibration():
    """
    Diagnostic 5: Distance Threshold Calibration
    
    Analyzes if the 1.35 threshold is appropriate for Amharic.
    """
    print_section("DIAGNOSTIC 5: DISTANCE THRESHOLD CALIBRATION")
    
    if not kb_pg_enabled() or count_approved_chunks() == 0:
        print("❌ Postgres KB not available or empty. Cannot test threshold.")
        return
    
    print(f"Current threshold: 1.35\n")
    
    all_distances = []
    
    for test_query in TEST_QUERIES:
        query = test_query["query"]
        query_en = test_query["query_en"]
        expected_keywords = test_query["expected_keywords"]
        
        print(f"Query: {query}")
        print(f"English: {query_en}")
        
        # Retrieve more candidates to see distance distribution
        hits, best_distance = retrieve_for_query(query, top_k=16)
        
        print(f"  Best distance: {best_distance:.3f}")
        print(f"  Retrieved {len(hits)} chunks")
        
        # Check if expected keywords appear in results
        relevant_found = False
        relevant_distances = []
        irrelevant_distances = []
        
        for hit in hits:
            content = hit.get("content", "")
            distance = hit.get("distance")
            
            # Check if chunk contains expected keywords
            keyword_matches = sum(1 for kw in expected_keywords if kw in content)
            is_relevant = keyword_matches >= 2
            
            if is_relevant:
                relevant_found = True
                relevant_distances.append(distance)
            else:
                irrelevant_distances.append(distance)
            
            all_distances.append({
                "query": query_en,
                "distance": distance,
                "is_relevant": is_relevant,
                "keyword_matches": keyword_matches,
            })
        
        if relevant_distances:
            avg_relevant = sum(relevant_distances) / len(relevant_distances)
            print(f"  Relevant chunks: {len(relevant_distances)}, avg distance: {avg_relevant:.3f}")
            
            # Check if any relevant chunks are above threshold
            above_threshold = [d for d in relevant_distances if d > 1.35]
            if above_threshold:
                print(f"  ⚠️  {len(above_threshold)} relevant chunks above 1.35 threshold!")
                print(f"      Distances: {[f'{d:.3f}' for d in above_threshold]}")
        else:
            print(f"  ⚠️  No relevant chunks found (based on keyword matching)")
        
        print()
    
    # Overall analysis
    if all_distances:
        relevant_dists = [d["distance"] for d in all_distances if d["is_relevant"]]
        irrelevant_dists = [d["distance"] for d in all_distances if not d["is_relevant"]]
        
        print_subsection("Overall Distance Distribution")
        
        if relevant_dists:
            print(f"Relevant chunks:")
            print(f"  Count: {len(relevant_dists)}")
            print(f"  Min: {min(relevant_dists):.3f}")
            print(f"  Avg: {sum(relevant_dists)/len(relevant_dists):.3f}")
            print(f"  Max: {max(relevant_dists):.3f}")
            print(f"  Above 1.35: {sum(1 for d in relevant_dists if d > 1.35)}")
            print()
        
        if irrelevant_dists:
            print(f"Irrelevant chunks:")
            print(f"  Count: {len(irrelevant_dists)}")
            print(f"  Min: {min(irrelevant_dists):.3f}")
            print(f"  Avg: {sum(irrelevant_dists)/len(irrelevant_dists):.3f}")
            print(f"  Max: {max(irrelevant_dists):.3f}")
            print()
        
        # Recommendation
        if relevant_dists:
            max_relevant = max(relevant_dists)
            if max_relevant > 1.35:
                print(f"⚠️  THRESHOLD TOO STRICT:")
                print(f"  Relevant chunks have distances up to {max_relevant:.3f}")
                print(f"  Recommended threshold: {max_relevant + 0.1:.2f} or higher")
                print(f"  OR remove hard threshold and rely on reranking")
                return "threshold_too_strict"
            else:
                print(f"✓ Threshold appears appropriate for these queries")
                return "threshold_ok"
    
    return "insufficient_data"


def main():
    """Run all diagnostics and generate report."""
    parser = argparse.ArgumentParser(description="Amharic RAG component diagnostics")
    parser.add_argument(
        "--max-pdfs",
        type=int,
        default=0,
        help="Limit number of PDFs checked in extraction diagnostic (0 = all)",
    )
    parser.add_argument(
        "--dump-pdf-text",
        action="store_true",
        help="Write extracted text for each PDF to logic_service/diagnostic_pdf_text/",
    )
    parser.add_argument(
        "--dump-dir",
        default="",
        help="Optional directory to write extracted PDF text (defaults to logic_service/diagnostic_pdf_text)",
    )
    parser.add_argument(
        "--only-extraction",
        action="store_true",
        help="Run only the PDF extraction diagnostic (fastest path to validate PDFs)",
    )
    args = parser.parse_args()

    _safe_print("\n" + "=" * 80)
    _safe_print("AMHARIC RAG DIAGNOSTIC REPORT")
    _safe_print("=" * 80)
    _safe_print("\nThis diagnostic will identify root causes of retrieval failures.")
    _safe_print("Each component will be tested independently.\n")
    
    # Check prerequisites
    if not kb_pg_enabled():
        _safe_print("ERROR: Postgres KB is not enabled.")
        _safe_print("  Set POSTGRES_URL environment variable and ensure psycopg is installed.")
        _safe_print("  Extraction diagnostics can still run without Postgres.")
        # Continue; extraction/normalization/chunking can run without DB.
    
    chunk_count = 0
    if kb_pg_enabled():
        chunk_count = count_approved_chunks()
        if chunk_count == 0:
            _safe_print("WARNING: Knowledge base is empty.")
            _safe_print("  Run ingest_kb_folder.py first to populate the KB.")
            _safe_print("  Some diagnostics will be skipped.\n")
        else:
            _safe_print(f"OK: Knowledge base ready: {chunk_count} chunks\n")
    
    # Run diagnostics
    results = {}
    
    try:
        dump_dir = Path(args.dump_dir).expanduser().resolve() if args.dump_dir else None
        results["extraction"] = check_extraction_quality(
            max_pdfs=args.max_pdfs,
            dump_text=bool(args.dump_pdf_text),
            dump_dir=dump_dir,
        )
    except Exception as exc:
        _safe_print(f"Extraction diagnostic failed: {exc}\n")
        results["extraction"] = f"error: {exc}"

    if args.only_extraction:
        print_section("DIAGNOSTIC SUMMARY")
        if isinstance(results.get("extraction"), list) and results["extraction"]:
            _safe_print("Extraction issues were detected. Review the printed report and dumped text files.")
        else:
            _safe_print("No obvious extraction issues detected. Next suspects: chunking + embedding + reranking.")
        output_file = LOGIC_ROOT / "diagnostic_results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({"results": results, "recommendations": []}, f, indent=2, ensure_ascii=False)
        _safe_print(f"\nSaved: {output_file}")
        return
    
    try:
        results["normalization"] = check_normalization_impact()
    except Exception as exc:
        _safe_print(f"Normalization diagnostic failed: {exc}\n")
        results["normalization"] = f"error: {exc}"
    
    try:
        results["chunking"] = check_chunking_quality()
    except Exception as exc:
        _safe_print(f"Chunking diagnostic failed: {exc}\n")
        results["chunking"] = f"error: {exc}"
    
    if kb_pg_enabled() and chunk_count > 0:
        try:
            results["embedding"] = check_embedding_quality()
        except Exception as exc:
            _safe_print(f"Embedding diagnostic failed: {exc}\n")
            results["embedding"] = f"error: {exc}"
    else:
        results["embedding"] = "skipped (kb unavailable/empty)"
    
    if kb_pg_enabled() and chunk_count > 0:
        try:
            results["threshold"] = check_threshold_calibration()
        except Exception as exc:
            _safe_print(f"Threshold diagnostic failed: {exc}\n")
            results["threshold"] = f"error: {exc}"
    else:
        results["threshold"] = "skipped (kb unavailable/empty)"
    
    # Generate summary
    print_section("DIAGNOSTIC SUMMARY & RECOMMENDATIONS")
    
    recommendations = []
    
    # Analyze results
    if results.get("extraction") and isinstance(results["extraction"], list) and len(results["extraction"]) > 0:
        print("⚠️  EXTRACTION ISSUES DETECTED")
        print("   → Implement Fix Option E: Extraction Enhancement")
        print("   → Add validation, try alternative libraries, add OCR fallback")
        recommendations.append("Fix Option E: Extraction Enhancement")
        print()
    
    if results.get("normalization") and isinstance(results["normalization"], list) and len(results["normalization"]) > 0:
        print("⚠️  NORMALIZATION OVER-FOLDING DETECTED")
        print("   → Implement Fix Option C: Normalization Refinement")
        print("   → Reduce character folding to only OCR variants")
        recommendations.append("Fix Option C: Normalization Refinement")
        print()
    
    if results.get("chunking") and isinstance(results["chunking"], list) and len(results["chunking"]) > 0:
        print("⚠️  CHUNKING BOUNDARY ISSUES DETECTED")
        print("   → Implement Fix Option D: Chunking Improvement")
        print("   → Implement header-aware chunking, handle lists")
        recommendations.append("Fix Option D: Chunking Improvement")
        print()
    
    if results.get("embedding") == "low_separation":
        print("⚠️  LOW EMBEDDING QUALITY FOR AMHARIC")
        print("   → Implement Fix Option A: Embedding Model Upgrade")
        print("   → Consider multilingual-e5-small or LaBSE")
        recommendations.append("Fix Option A: Embedding Model Upgrade")
        print()
    
    if results.get("threshold") == "threshold_too_strict":
        print("⚠️  DISTANCE THRESHOLD TOO STRICT")
        print("   → Implement Fix Option B: Distance Threshold Adjustment")
        print("   → Increase threshold or remove hard filtering")
        recommendations.append("Fix Option B: Distance Threshold Adjustment")
        print()
    
    if not recommendations:
        print("✓ No critical issues detected in diagnostics")
        print("  However, retrieval may still fail due to:")
        print("  - Insufficient training data for Amharic in embedding model")
        print("  - Complex interactions between components")
        print("  - Consider implementing Fix Option A (Embedding Model Upgrade) as preventive measure")
    else:
        print(f"RECOMMENDED FIXES (in priority order):")
        for i, rec in enumerate(recommendations, 1):
            print(f"  {i}. {rec}")
    
    _safe_print(f"\n{'='*80}\n")
    
    # Save results to file
    output_file = LOGIC_ROOT / "diagnostic_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "results": results,
            "recommendations": recommendations,
        }, f, indent=2, ensure_ascii=False)
    
    _safe_print(f"Diagnostic results saved to: {output_file}")


if __name__ == "__main__":
    main()
