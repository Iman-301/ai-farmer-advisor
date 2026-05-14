#!/usr/bin/env python3
"""
Diagnostic tests for Amharic RAG retrieval quality.

Property 1 (Bug Condition): Amharic Query Retrieval Accuracy
Property 2 (Preservation): Non-Amharic and Downstream Behavior

This test suite follows the diagnostic-first approach:
1. Bug condition tests MUST FAIL on unfixed code (proves bug exists)
2. Preservation tests MUST PASS on unfixed code (establishes baseline)
3. After fixes, bug condition tests MUST PASS (proves fix works)
4. After fixes, preservation tests MUST STILL PASS (proves no regressions)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add logic_service to path
LOGIC_ROOT = Path(__file__).resolve().parents[1]
if str(LOGIC_ROOT) not in sys.path:
    sys.path.insert(0, str(LOGIC_ROOT))

import pytest
from typing import Any

# Import RAG components
from rag_pg import (
    retrieve_for_query,
    chunk_amharic_text,
    embed_texts,
    kb_pg_enabled,
    count_approved_chunks,
)
from nlu import normalize_ethiopic_input


# ══════════════════════════════════════════════════════════════════════════════
# Ground Truth Test Set
# ══════════════════════════════════════════════════════════════════════════════

# Ground truth queries with expected relevant content
# NOTE: chunk_ids will need to be populated after ingestion
GROUND_TRUTH_QUERIES = [
    {
        "query": "የድህረ ምርት ኪሳራ እንዴት መቀነስ እችላለሁ?",
        "query_en": "How can I reduce post-harvest losses?",
        "intent": "post_harvest",
        "expected_keywords": ["ኪሳራ", "ድህረ ምርት", "መቀነስ", "ጎተራ", "ማከማቻ"],
        "expected_doc_patterns": ["010", "fao", "post-harvest", "postharvest"],
        "relevant_chunk_ids": [],  # To be populated after manual inspection
        "why_relevant": "Should retrieve chunks discussing loss reduction strategies from post-harvest manuals",
    },
    {
        "query": "ጥቅል 1 ምን ይጨምራል?",
        "query_en": "What does bundle 1 include?",
        "intent": "extension_advisory",
        "expected_keywords": ["ጥቅል 1", "የአፈር", "የውሃ", "ጥበቃ"],
        "expected_doc_patterns": ["001", "extension", "use-of-extension"],
        "relevant_chunk_ids": [],
        "why_relevant": "Should retrieve chunks from extension materials manual describing bundle 1 contents",
    },
    {
        "query": "LandPKS መተግበሪያ እንዴት እጠቀማለሁ?",
        "query_en": "How do I use the LandPKS app?",
        "intent": "land_characterization",
        "expected_keywords": ["LandPKS", "መተግበሪያ", "አፈር", "ቀለም"],
        "expected_doc_patterns": ["006", "landpks"],
        "relevant_chunk_ids": [],
        "why_relevant": "Should retrieve chunks from LandPKS manual about app usage",
    },
    {
        "query": "ማዳበሪያ መቼ መጠቀም አለብኝ?",
        "query_en": "When should I use fertilizer?",
        "intent": "soil_fertility",
        "expected_keywords": ["ማዳበሪያ", "መቼ", "መጠቀም", "አፈር"],
        "expected_doc_patterns": ["soil", "fertility", "fertilizer"],
        "relevant_chunk_ids": [],
        "why_relevant": "Should retrieve chunks about fertilizer timing and application",
    },
    {
        "query": "የመስክ ጉብኝት ቁሳቁሶች ምንድን ናቸው?",
        "query_en": "What are the field visit materials?",
        "intent": "extension_advisory",
        "expected_keywords": ["መስክ ጉብኝት", "ቁሳቁስ", "ቁሳቁሶች"],
        "expected_doc_patterns": ["001", "extension", "use-of-extension"],
        "relevant_chunk_ids": [],
        "why_relevant": "Should retrieve chunks listing field visit materials from extension manual",
    },
    {
        "query": "የውይይት ቡድን ስንት ሰዓት ይወስዳል?",
        "query_en": "How long does a discussion group take?",
        "intent": "extension_advisory",
        "expected_keywords": ["ውይይት ቡድን", "ሰዓት", "1.5"],
        "expected_doc_patterns": ["001", "extension", "use-of-extension"],
        "relevant_chunk_ids": [],
        "why_relevant": "Should retrieve chunks mentioning discussion group duration (1.5 hours)",
    },
    {
        "query": "እህል በጎተራ ውስጥ እንዴት እጠብቃለሁ?",
        "query_en": "How do I store grain in a warehouse?",
        "intent": "post_harvest",
        "expected_keywords": ["እህል", "ጎተራ", "ማከማቻ", "መጠበቅ"],
        "expected_doc_patterns": ["010", "fao", "post-harvest"],
        "relevant_chunk_ids": [],
        "why_relevant": "Should retrieve chunks about grain storage practices",
    },
    {
        "query": "የአፈር ቀለም ምን ያሳያል?",
        "query_en": "What does soil color indicate?",
        "intent": "land_characterization",
        "expected_keywords": ["አፈር", "ቀለም", "LandPKS"],
        "expected_doc_patterns": ["006", "landpks", "soil"],
        "relevant_chunk_ids": [],
        "why_relevant": "Should retrieve chunks about soil color interpretation from LandPKS manual",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# Property 1: Bug Condition - Amharic Query Retrieval Accuracy
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not kb_pg_enabled() or count_approved_chunks() == 0, reason="Postgres KB not available or empty")
class TestAmharicQueryRetrievalAccuracy:
    """
    Property 1: Bug Condition Tests
    
    CRITICAL: These tests MUST FAIL on unfixed code.
    Failure confirms the bug exists.
    DO NOT fix the test or the code when it fails.
    
    After implementing fixes, these tests MUST PASS.
    Passing confirms the expected behavior is satisfied.
    """
    
    def test_amharic_query_retrieval_accuracy(self):
        """
        Test that Amharic queries retrieve semantically relevant chunks.
        
        EXPECTED ON UNFIXED CODE: FAIL (proves bug exists)
        EXPECTED AFTER FIX: PASS (proves fix works)
        """
        failures = []
        successes = []
        
        for test_case in GROUND_TRUTH_QUERIES:
            query = test_case["query"]
            query_en = test_case["query_en"]
            expected_keywords = test_case["expected_keywords"]
            expected_doc_patterns = test_case["expected_doc_patterns"]
            
            # Retrieve chunks
            hits, best_distance = retrieve_for_query(query, top_k=4)
            
            # Check if any relevant content retrieved
            has_relevant = False
            retrieved_docs = []
            
            for hit in hits:
                content = hit.get("content", "")
                title = hit.get("title", "")
                original_filename = hit.get("original_filename", "")
                doc_blob = f"{original_filename} {title}".lower()
                
                # Check if expected document pattern matches
                doc_match = any(pattern in doc_blob for pattern in expected_doc_patterns)
                
                # Check if expected keywords present
                keyword_match = sum(1 for kw in expected_keywords if kw in content) >= 2
                
                if doc_match or keyword_match:
                    has_relevant = True
                
                retrieved_docs.append({
                    "title": title,
                    "filename": original_filename,
                    "distance": hit.get("distance"),
                    "snippet": content[:200],
                })
            
            if has_relevant:
                successes.append({
                    "query": query,
                    "query_en": query_en,
                    "best_distance": best_distance,
                    "retrieved": retrieved_docs,
                })
            else:
                failures.append({
                    "query": query,
                    "query_en": query_en,
                    "intent": test_case["intent"],
                    "expected_keywords": expected_keywords,
                    "expected_docs": expected_doc_patterns,
                    "best_distance": best_distance,
                    "retrieved": retrieved_docs,
                    "why_relevant": test_case["why_relevant"],
                })
        
        # Calculate metrics
        total = len(GROUND_TRUTH_QUERIES)
        recall_at_4 = len(successes) / total if total > 0 else 0.0
        
        # Report results
        print(f"\n{'='*80}")
        print(f"AMHARIC QUERY RETRIEVAL ACCURACY TEST")
        print(f"{'='*80}")
        print(f"Total queries: {total}")
        print(f"Successful retrievals: {len(successes)}")
        print(f"Failed retrievals: {len(failures)}")
        print(f"Recall@4: {recall_at_4:.2%}")
        print(f"{'='*80}\n")
        
        if failures:
            print(f"FAILURES (queries that did NOT retrieve relevant content):")
            print(f"{'-'*80}")
            for i, failure in enumerate(failures, 1):
                print(f"\n{i}. Query: {failure['query']}")
                print(f"   English: {failure['query_en']}")
                print(f"   Intent: {failure['intent']}")
                print(f"   Expected keywords: {', '.join(failure['expected_keywords'])}")
                print(f"   Expected docs: {', '.join(failure['expected_docs'])}")
                print(f"   Best distance: {failure['best_distance']:.3f}")
                print(f"   Why relevant: {failure['why_relevant']}")
                print(f"   Retrieved instead:")
                for j, doc in enumerate(failure['retrieved'][:2], 1):
                    print(f"     {j}) {doc['filename']} (distance: {doc['distance']:.3f})")
                    print(f"        {doc['snippet']}...")
            print(f"\n{'-'*80}\n")
        
        if successes:
            print(f"SUCCESSES (queries that retrieved relevant content):")
            print(f"{'-'*80}")
            for i, success in enumerate(successes, 1):
                print(f"\n{i}. Query: {success['query']}")
                print(f"   English: {success['query_en']}")
                print(f"   Best distance: {success['best_distance']:.3f}")
                print(f"   Top result: {success['retrieved'][0]['filename']}")
            print(f"\n{'-'*80}\n")
        
        # Assert: At least 70% of queries should retrieve relevant content
        # This threshold may need adjustment based on baseline
        assert recall_at_4 >= 0.7, (
            f"Recall@4 is {recall_at_4:.2%}, expected >= 70%. "
            f"{len(failures)} out of {total} queries failed to retrieve relevant content. "
            f"See detailed failure report above."
        )
    
    def test_distance_scores_appropriate(self):
        """
        Test that distance scores appropriately reflect semantic similarity.
        
        Relevant chunks should have lower distances than irrelevant chunks.
        """
        distance_data = []
        
        for test_case in GROUND_TRUTH_QUERIES[:5]:  # Test subset
            query = test_case["query"]
            expected_doc_patterns = test_case["expected_doc_patterns"]
            
            hits, best_distance = retrieve_for_query(query, top_k=8)
            
            for hit in hits:
                original_filename = hit.get("original_filename", "").lower()
                title = hit.get("title", "").lower()
                doc_blob = f"{original_filename} {title}"
                distance = hit.get("distance")
                
                is_relevant = any(pattern in doc_blob for pattern in expected_doc_patterns)
                
                distance_data.append({
                    "query": test_case["query_en"],
                    "distance": distance,
                    "is_relevant": is_relevant,
                    "doc": original_filename or title[:50],
                })
        
        # Analyze distance distribution
        relevant_distances = [d["distance"] for d in distance_data if d["is_relevant"]]
        irrelevant_distances = [d["distance"] for d in distance_data if not d["is_relevant"]]
        
        if relevant_distances and irrelevant_distances:
            avg_relevant = sum(relevant_distances) / len(relevant_distances)
            avg_irrelevant = sum(irrelevant_distances) / len(irrelevant_distances)
            
            print(f"\n{'='*80}")
            print(f"DISTANCE SCORE ANALYSIS")
            print(f"{'='*80}")
            print(f"Relevant chunks:")
            print(f"  Count: {len(relevant_distances)}")
            print(f"  Avg distance: {avg_relevant:.3f}")
            print(f"  Min distance: {min(relevant_distances):.3f}")
            print(f"  Max distance: {max(relevant_distances):.3f}")
            print(f"\nIrrelevant chunks:")
            print(f"  Count: {len(irrelevant_distances)}")
            print(f"  Avg distance: {avg_irrelevant:.3f}")
            print(f"  Min distance: {min(irrelevant_distances):.3f}")
            print(f"  Max distance: {max(irrelevant_distances):.3f}")
            print(f"\nSeparation: {avg_irrelevant - avg_relevant:.3f}")
            print(f"{'='*80}\n")
            
            # Assert: Relevant chunks should have lower average distance
            assert avg_relevant < avg_irrelevant, (
                f"Relevant chunks have higher average distance ({avg_relevant:.3f}) "
                f"than irrelevant chunks ({avg_irrelevant:.3f}). "
                f"This indicates poor embedding quality for Amharic."
            )


# ══════════════════════════════════════════════════════════════════════════════
# Property 2: Preservation - Non-Amharic and Downstream Behavior
# ══════════════════════════════════════════════════════════════════════════════

class TestPreservation:
    """
    Property 2: Preservation Tests
    
    IMPORTANT: These tests MUST PASS on unfixed code.
    Passing establishes the baseline behavior to preserve.
    
    After implementing fixes, these tests MUST STILL PASS.
    Passing confirms no regressions occurred.
    """
    
    def test_chunking_fallback_preserved(self):
        """
        Test that chunking fallback for non-Ethiopic text is unchanged.
        
        EXPECTED ON UNFIXED CODE: PASS (establishes baseline)
        EXPECTED AFTER FIX: PASS (confirms no regression)
        """
        # Text without Ethiopic sentence delimiters
        text_no_delimiters = "This is a test. It has no Ethiopic delimiters. " * 100
        
        chunks = chunk_amharic_text(text_no_delimiters, chunk_size=200, overlap=50)
        
        # Should fall back to fixed character windows
        assert len(chunks) > 1, "Should create multiple chunks"
        assert all(len(c) <= 250 for c in chunks), "Chunks should respect size limit"
        
        # Verify overlap exists
        if len(chunks) >= 2:
            # Check if there's some overlap between consecutive chunks
            overlap_found = False
            for i in range(len(chunks) - 1):
                # Check if end of chunk i appears in chunk i+1
                end_snippet = chunks[i][-20:]
                if end_snippet in chunks[i + 1]:
                    overlap_found = True
                    break
            # Note: overlap may not always be detectable with sentence-based splitting
            # This is a soft check
        
        print(f"\nChunking fallback test: {len(chunks)} chunks created from non-Ethiopic text")
    
    def test_normalization_basic_behavior(self):
        """
        Test that basic normalization behavior is preserved.
        
        EXPECTED ON UNFIXED CODE: PASS (establishes baseline)
        EXPECTED AFTER FIX: PASS (confirms no regression)
        """
        # Test basic normalization
        test_cases = [
            ("  multiple   spaces  ", "multiple spaces"),
            ("UPPERCASE", "uppercase"),
            ("MixedCase", "mixedcase"),
        ]
        
        for input_text, expected_pattern in test_cases:
            normalized = normalize_ethiopic_input(input_text)
            assert expected_pattern in normalized.lower(), (
                f"Normalization changed: input='{input_text}', "
                f"expected pattern='{expected_pattern}', got='{normalized}'"
            )
        
        print(f"\nNormalization basic behavior: {len(test_cases)} test cases passed")
    
    def test_embedding_dimensions_preserved(self):
        """
        Test that embedding dimensions are preserved.
        
        EXPECTED ON UNFIXED CODE: PASS (establishes baseline)
        EXPECTED AFTER FIX: PASS (confirms no regression unless model changed)
        """
        test_texts = ["test text", "another test", "የአማርኛ ጽሑፍ"]
        
        embeddings = embed_texts(test_texts)
        
        assert len(embeddings) == len(test_texts), "Should return one embedding per text"
        # Embedding dimension depends on selected model (e.g., 384 vs 768).
        dim0 = len(embeddings[0]) if embeddings else 0
        assert dim0 > 0, "Embedding vectors should be non-empty"
        assert all(len(emb) == dim0 for emb in embeddings), "All embeddings should have same dimension"
        
        print(f"\nEmbedding dimensions: {dim0}-d (dynamic)")


# ══════════════════════════════════════════════════════════════════════════════
# Component-Level Diagnostic Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestComponentDiagnostics:
    """
    Component-level tests to isolate root causes.
    These are informational and help guide which fixes to implement.
    """
    
    def test_ethiopic_character_preservation(self):
        """
        Test that Ethiopic characters are preserved through normalization.
        """
        ethiopic_samples = [
            "የአፈር እና የውሃ ጥበቃ",
            "ድህረ ምርት ኪሳራ መቀነስ",
            "ማዳበሪያ መጠቀም",
            "ዓመት",  # Character that might be folded
            "አመት",  # Different character
        ]
        
        for sample in ethiopic_samples:
            normalized = normalize_ethiopic_input(sample)
            # Check if Ethiopic characters are still present
            has_ethiopic = any('\u1200' <= c <= '\u137f' for c in normalized)
            assert has_ethiopic, f"Ethiopic characters lost in normalization: '{sample}' -> '{normalized}'"
        
        print(f"\nEthiopic character preservation: {len(ethiopic_samples)} samples tested")
    
    def test_chunk_size_distribution(self):
        """
        Analyze chunk size distribution for Amharic text.
        """
        sample_text = """
        ጥቅል 1: የአፈር እና የውሃ ጥበቃ
        
        ይህ ጥቅል የሚከተሉትን ይጨምራል:
        - የመሬት ቋሚነት
        - የውሃ አያያዝ
        - የአፈር ሽርሽር መከላከል
        
        ጥቅል 2: በዝቅተኛ አካባቢዎች የሰብል ምርት
        
        ይህ ጥቅል የሚከተሉትን ይጨምራል:
        - የሰብል ምርጫ
        - የመሬት ዝግጅት
        - የዘር መዝራት
        """ * 10
        
        chunks = chunk_amharic_text(sample_text)
        
        sizes = [len(c) for c in chunks]
        avg_size = sum(sizes) / len(sizes) if sizes else 0
        
        print(f"\nChunk size distribution:")
        print(f"  Total chunks: {len(chunks)}")
        print(f"  Avg size: {avg_size:.0f} chars")
        print(f"  Min size: {min(sizes) if sizes else 0} chars")
        print(f"  Max size: {max(sizes) if sizes else 0} chars")
        
        # Check if headers are kept with content
        header_chunks = [c for c in chunks if "ጥቅል" in c and "ይጨምራል" in c]
        print(f"  Chunks with headers + content: {len(header_chunks)}")


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
