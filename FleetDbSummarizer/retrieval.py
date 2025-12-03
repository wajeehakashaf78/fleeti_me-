"""
Retrieval Module
Phase 2: High-Recall Retrieval with Hybrid Search and RRF
"""

import logging
import time
from typing import List, Dict, Any, Tuple
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
import chromadb

from FleetDbSummarizer.config import K_DENSE, K_SPARSE, RRF_K

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HybridRetriever:
    """
    Phase 2: High-Recall Retrieval
    - Parallel query execution (Dense + Sparse)
    - Reciprocal Rank Fusion (RRF)
    """
    
    def __init__(self, embedding_model: SentenceTransformer, 
                 chroma_collection: Any,
                 bm25_index: BM25Okapi,
                 bm25_tokenized_corpus: List[List[str]]):
        self.embedding_model = embedding_model
        self.chroma_collection = chroma_collection
        self.bm25_index = bm25_index
        self.bm25_tokenized_corpus = bm25_tokenized_corpus
        self.chunks = []  # Will be set during retrieval
    
    def dense_search(self, query: str, k: int = K_DENSE) -> List[Tuple[str, float]]:
        """
        Dense Vector Search using ChromaDB
        Returns list of (chunk_id, score) tuples
        """
        dense_start = time.time()
        # Generate query embedding
        query_embedding = self.embedding_model.encode(
            query,
            convert_to_numpy=True,
            show_progress_bar=False
        ).tolist()
        
        # Search in ChromaDB
        results = self.chroma_collection.query(
            query_embeddings=[query_embedding],
            n_results=k
        )
        
        # Format results: (chunk_id, distance)
        # ChromaDB returns distances (lower is better), convert to scores
        dense_results = []
        if results['ids'] and len(results['ids']) > 0:
            ids = results['ids'][0]
            distances = results['distances'][0]
            
            for chunk_id, distance in zip(ids, distances):
                # Convert distance to similarity score (assuming cosine distance)
                # Lower distance = higher similarity
                score = 1.0 - distance if distance <= 1.0 else 1.0 / (1.0 + distance)
                dense_results.append((chunk_id, score))
        
        dense_elapsed = time.time() - dense_start
        logger.info(f"⏱️  Dense search completed in {dense_elapsed:.2f}s")
        return dense_results
    
    def sparse_search(self, query: str, k: int = K_SPARSE) -> List[Tuple[str, float]]:
        """
        Sparse BM25 Search
        Returns list of (chunk_id, score) tuples
        """
        sparse_start = time.time()
        # Tokenize query
        tokenized_query = query.lower().split()
        
        # Get BM25 scores
        scores = self.bm25_index.get_scores(tokenized_query)
        
        # Get top k indices
        top_k_indices = np.argsort(scores)[::-1][:k]
        
        # Format results: (chunk_id, score)
        sparse_results = []
        for idx in top_k_indices:
            score = float(scores[idx])
            chunk_id = str(idx)
            sparse_results.append((chunk_id, score))
        
        sparse_elapsed = time.time() - sparse_start
        logger.info(f"⏱️  Sparse search completed in {sparse_elapsed:.2f}s")
        return sparse_results
    
    def reciprocal_rank_fusion(self, 
                               dense_results: List[Tuple[str, float]],
                               sparse_results: List[Tuple[str, float]],
                               k: int = RRF_K) -> List[Tuple[str, float]]:
        """
        Reciprocal Rank Fusion (RRF)
        Combines ranked lists from dense and sparse searches
        Returns fused ranked list: [(chunk_id, rrf_score), ...]
        """
        rrf_start = time.time()
        # Create dictionaries for scores
        dense_scores = {}
        sparse_scores = {}
        
        # Build dense score map (by rank)
        for rank, (chunk_id, score) in enumerate(dense_results, start=1):
            dense_scores[chunk_id] = 1.0 / (k + rank)
        
        # Build sparse score map (by rank)
        for rank, (chunk_id, score) in enumerate(sparse_results, start=1):
            sparse_scores[chunk_id] = 1.0 / (k + rank)
        
        # Combine scores
        fused_scores = {}
        all_chunk_ids = set(dense_scores.keys()) | set(sparse_scores.keys())
        
        for chunk_id in all_chunk_ids:
            rrf_score = dense_scores.get(chunk_id, 0.0) + sparse_scores.get(chunk_id, 0.0)
            fused_scores[chunk_id] = rrf_score
        
        # Sort by RRF score (descending)
        fused_results = sorted(
            fused_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        rrf_elapsed = time.time() - rrf_start
        logger.info(f"⏱️  RRF fusion completed in {rrf_elapsed:.2f}s")
        return fused_results
    
    def retrieve(self, query: str, 
                 k_dense: int = K_DENSE,
                 k_sparse: int = K_SPARSE,
                 rrf_k: int = RRF_K) -> List[Tuple[str, float]]:
        """
        Phase 2: High-Recall Retrieval
        - Execute parallel queries (dense + sparse)
        - Fuse results with RRF
        Returns fused ranked list: [(chunk_id, rrf_score), ...]
        """
        logger.info(f"Retrieving for query: {query[:50]}...")
        
        # Parallel query execution
        dense_results = self.dense_search(query, k=k_dense)
        sparse_results = self.sparse_search(query, k=k_sparse)
        
        logger.info(f"Dense search returned {len(dense_results)} results")
        logger.info(f"Sparse search returned {len(sparse_results)} results")
        
        # Reciprocal Rank Fusion
        fused_results = self.reciprocal_rank_fusion(
            dense_results,
            sparse_results,
            k=rrf_k
        )
        
        logger.info(f"RRF fusion returned {len(fused_results)} results")
        
        return fused_results
    
    def get_chunk_texts(self, chunk_ids: List[str], chunks: List[Dict[str, Any]]) -> List[str]:
        """
        Retrieve chunk texts given chunk IDs
        """
        chunk_dict = {str(chunk['global_chunk_id']): chunk for chunk in chunks}
        texts = []
        
        for chunk_id in chunk_ids:
            if chunk_id in chunk_dict:
                texts.append(chunk_dict[chunk_id]['text'])
            else:
                # Fallback: try to get from ChromaDB
                try:
                    result = self.chroma_collection.get(ids=[chunk_id])
                    if result['documents']:
                        texts.append(result['documents'][0])
                    else:
                        texts.append("")
                except:
                    texts.append("")
        
        return texts

