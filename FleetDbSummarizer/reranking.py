"""
Re-ranking Module
Phase 3: High-Precision Re-ranking with Cross-Encoder
"""

import logging
import time
from typing import List, Tuple, Dict, Any
from sentence_transformers import CrossEncoder

from FleetDbSummarizer.config import RERANKER_MODEL, TOP_N_RERANK, TOP_K_FINAL, DEVICE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    Phase 3: High-Precision Re-ranking
    - Cross-Encoder re-ranking for top N candidates
    Uses cross-encoder/ms-marco-MiniLM-L-6-v2 on CPU
    """
    
    def __init__(self, model_name: str = RERANKER_MODEL):
        """
        Initialize Cross-Encoder reranker
        
        Args:
            model_name: Name of the Cross-Encoder model to use (default: from config)
        """
        try:
            logger.info(f"Loading Cross-Encoder model from local cache: {model_name} on {DEVICE}")
            self.reranker = CrossEncoder(model_name, device=DEVICE, local_files_only=True)
            logger.info(f"Cross-Encoder model loaded successfully from local cache on {DEVICE}")
        except Exception as e:
            logger.warning(f"Model not found in local cache: {e}. Attempting to download...")
            self.reranker = CrossEncoder(model_name, device=DEVICE)
            logger.info(f"Downloaded and loaded Cross-Encoder model: {model_name} on {DEVICE}")
    
    def rerank(self, 
               query: str,
               candidate_chunks: List[str],
               top_n: int = TOP_N_RERANK,
               top_k_final: int = TOP_K_FINAL) -> List[Tuple[int, float]]:
        """
        Re-rank candidate chunks using Cross-Encoder
        Returns list of (original_index, score) tuples sorted by score
        
        Args:
            query: User query string
            candidate_chunks: List of candidate chunk texts to re-rank
            top_n: Maximum number of candidates to consider (not used, kept for compatibility)
            top_k_final: Number of top results to return
            
        Returns:
            List of (original_index, score) tuples sorted by score (descending)
        """
        rerank_start = time.time()
        logger.info(f"Re-ranking {len(candidate_chunks)} candidate chunks using Cross-Encoder on {DEVICE}...")
        
        if not candidate_chunks:
            return []
        
        # Create query-chunk pairs for Cross-Encoder
        pairs = [[query, chunk] for chunk in candidate_chunks]
        
        # Get relevance scores from Cross-Encoder
        scores = self.reranker.predict(pairs, show_progress_bar=False)
        
        # Create list of (index, score) tuples
        ranked_results = [(i, float(score)) for i, score in enumerate(scores)]
        
        # Sort by score (descending)
        ranked_results.sort(key=lambda x: x[1], reverse=True)
        
        # Return top K results
        top_k = min(top_k_final, len(ranked_results))
        final_results = ranked_results[:top_k]
        
        rerank_elapsed = time.time() - rerank_start
        logger.info(f"⏱️  Re-ranking complete in {rerank_elapsed:.2f}s. Selected top {top_k} chunks")
        
        return final_results
    
    def rerank_with_metadata(self,
                             query: str,
                             candidate_chunks: List[Dict[str, Any]],
                             top_n: int = TOP_N_RERANK,
                             top_k_final: int = TOP_K_FINAL) -> List[Dict[str, Any]]:
        """
        Re-rank candidate chunks with metadata preserved
        Returns list of ranked chunk dictionaries
        """
        if not candidate_chunks:
            return []
        
        # Extract texts
        chunk_texts = [chunk.get('text', '') for chunk in candidate_chunks]
        
        # Re-rank
        ranked_indices = self.rerank(query, chunk_texts, top_n, top_k_final)
        
        # Reconstruct chunks with scores
        ranked_chunks = []
        for original_idx, score in ranked_indices:
            chunk = candidate_chunks[original_idx].copy()
            chunk['rerank_score'] = score
            ranked_chunks.append(chunk)
        
        return ranked_chunks

