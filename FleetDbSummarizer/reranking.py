"""
Re-ranking Module
Phase 3: High-Precision Re-ranking with Cross-Encoder
"""

import logging
import time
from typing import List, Tuple, Dict, Any
from sentence_transformers import CrossEncoder
import os
import json
from dotenv import load_dotenv
try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None

from FleetDbSummarizer.config import RERANKER_MODEL, TOP_N_RERANK, TOP_K_FINAL, DEVICE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    Phase 3: High-Precision Re-ranking
    - Cross-Encoder re-ranking for top N candidates
    """
    
    def __init__(self, model_name: str = RERANKER_MODEL):
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        self.openai_model = os.getenv("OPENAI_MODEL_RERANK") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        self.openai_client = None
        if api_key and OpenAI is not None:
            try:
                self.openai_client = OpenAI(api_key=api_key)
                logger.info(f"Initialized OpenAI reranker with model: {self.openai_model}")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client for reranking: {e}")
                self.openai_client = None
        if not self.openai_client:
            try:
                logger.info(f"Loading Cross-Encoder model from local cache: {model_name} on {DEVICE}")
                self.reranker = CrossEncoder(model_name, device=DEVICE, local_files_only=True)
                logger.info(f"Cross-Encoder model loaded successfully from local cache on {DEVICE}")
            except Exception as e:
                logger.warning(f"Model not found in local cache: {e}. Attempting to download...")
                self.reranker = CrossEncoder(model_name, device=DEVICE)
                logger.info(f"Downloaded and loaded Cross-Encoder model: {model_name}")
    
    def rerank(self, 
               query: str,
               candidate_chunks: List[str],
               top_n: int = TOP_N_RERANK,
               top_k_final: int = TOP_K_FINAL) -> List[Tuple[int, float]]:
        """
        Re-rank candidate chunks using Cross-Encoder
        Returns list of (original_index, score) tuples sorted by score
        """
        rerank_start = time.time()
        logger.info(f"Re-ranking {len(candidate_chunks)} candidate chunks...")
        if not candidate_chunks:
            return []
        if self.openai_client:
            try:
                limited = candidate_chunks[:top_n]
                items = [
                    {"index": i, "text": text[:1200] if text else ""}
                    for i, text in enumerate(limited)
                ]
                system_prompt = "You are a re-ranker. Score each candidate's relevance to the query between 0 and 1. Return JSON array sorted by score desc with objects {index, score}."
                user_prompt = json.dumps({"query": query, "candidates": items}, ensure_ascii=False)
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
                resp = self.openai_client.chat.completions.create(
                    model=self.openai_model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=800,
                    top_p=1.0
                )
                content = (resp.choices[0].message.content or "").strip() if getattr(resp, "choices", None) else ""
                scored: List[Tuple[int, float]] = []
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        for obj in data:
                            idx = int(obj.get("index", -1))
                            sc = float(obj.get("score", 0.0))
                            if 0 <= idx < len(limited):
                                scored.append((idx, sc))
                except Exception:
                    pass
                if not scored:
                    import re
                    for m in re.finditer(r"index\s*[:=]\s*(\d+).*?score\s*[:=]\s*([01](?:\.\d+)?)", content, re.I | re.S):
                        idx = int(m.group(1))
                        sc = float(m.group(2))
                        if 0 <= idx < len(limited):
                            scored.append((idx, sc))
                if not scored:
                    scored = [(i, 0.0) for i in range(len(limited))]
                scored.sort(key=lambda x: x[1], reverse=True)
                mapped = [(i, s) for i, s in scored]
                top_k = min(top_k_final, len(mapped))
                final_results = mapped[:top_k]
                rerank_elapsed = time.time() - rerank_start
                logger.info(f"⏱️  Re-ranking complete via OpenAI in {rerank_elapsed:.2f}s. Selected top {top_k} chunks")
                return final_results
            except Exception as e:
                logger.error(f"OpenAI reranking failed: {e}. Falling back to Cross-Encoder if available.")
        pairs = [[query, chunk] for chunk in candidate_chunks]
        scores = self.reranker.predict(pairs)
        ranked_results = [(i, float(score)) for i, score in enumerate(scores)]
        ranked_results.sort(key=lambda x: x[1], reverse=True)
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

