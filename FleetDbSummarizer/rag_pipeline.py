"""
Main RAG Pipeline Orchestrator
Multi-Stage RAG Pipeline with Hybrid Retrieval, RRF, and Cross-Encoder Re-ranking
"""

import logging
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
from dotenv import load_dotenv
try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None
import time
# Load environment variables from .env file
# Try to load from project root directory
BASE_DIR = Path(__file__).parent
# env_path = BASE_DIR / ".env"
# load_dotenv(dotenv_path=env_path)

# Also try loading from current directory as fallback
if not os.getenv("OPENAI_API_KEY"):
    load_dotenv()

from FleetDbSummarizer.config import (
    COLLECTION_CHUNKS_DIR,
    COLLECTION_SCHEMAS_DIR,
    COLLECTION_INDEX_FILE,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    PARENT_CHUNK_SIZE,
    EMBEDDING_MODEL,
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
    TOP_N_RERANK,
    TOP_K_FINAL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    LOG_LEVEL,
    DOCS_DIR,
    DEVICE,
    JSON_OUTPUT_DIR
)
from FleetDbSummarizer.data_preparation import DataPreparation
from FleetDbSummarizer.retrieval import HybridRetriever
from FleetDbSummarizer.reranking import CrossEncoderReranker
from FleetDbSummarizer.utils import load_all_collection_files, load_collection_schemas, build_collection_json

import logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

# Note: We now use OpenAI for LLM generation. Transformers are not required.


class RAGPipeline:
    """
    Multi-Stage RAG Pipeline
    
    Phase 1: Data Preparation & Indexing (hierarchical chunking, dual indexing)
    Phase 2: High-Recall Retrieval (hybrid search with RRF)
    Phase 3: High-Precision Re-ranking (Cross-Encoder)
    Phase 4: Generation (LLM augmentation)
    """
    
    def __init__(self, build_indexes: bool = False):
        """
        Initialize RAG Pipeline
        
        Args:
            build_indexes: If True, rebuild indexes from scratch. If False, load existing.
        """
        # Load embedding model from local cache only (avoid network checks)
        try:
            self.embedding_model = SentenceTransformer(EMBEDDING_MODEL, device=DEVICE, local_files_only=True)
            logger.info(f"Loaded embedding model from local cache: {EMBEDDING_MODEL}")
        except Exception as e:
            logger.warning(f"Model not found in local cache: {e}. Attempting to download...")
            # Fallback to network download if not in cache
            self.embedding_model = SentenceTransformer(EMBEDDING_MODEL, device=DEVICE)
            logger.info(f"Downloaded and loaded embedding model: {EMBEDDING_MODEL}")
        self.data_prep = DataPreparation()
        self.retriever = None
        self.reranker = CrossEncoderReranker()
        self.chunks = []
        self.parent_chunks = {}
        self.bm25_index = None
        self.bm25_tokenized_corpus = []
        
        # LLM client (OpenAI)
        self.openai_client = None
        self.openai_model_name = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set. LLM generation will be disabled.")
        elif OpenAI is None:
            logger.warning("openai package not installed. Install with: pip install openai. LLM generation will be disabled.")
        else:
            try:
                self.openai_client = OpenAI(api_key=api_key)
                logger.info(f"Initialized OpenAI client with model: {self.openai_model_name}")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self.openai_client = None
        
        # Initialize indexes
        if build_indexes:
            self._build_indexes()
        else:
            self._load_indexes()
    
    def _build_indexes(self):
        """Phase 1: Build indexes from scratch"""
        logger.info("Building indexes from scratch...")
        
        # Build indexes
        indexes = self.data_prep.build_indexes()
        
        self.chunks = indexes['chunks']
        self.parent_chunks = indexes['parent_chunks']
        self.chroma_collection = indexes['chroma_collection']
        self.bm25_index = indexes['bm25_index']
        
        # Create BM25 tokenized corpus
        self.bm25_tokenized_corpus = [
            chunk['text'].lower().split() for chunk in self.chunks
        ]
        
        # Initialize retriever
        self.retriever = HybridRetriever(
            embedding_model=self.embedding_model,
            chroma_collection=self.chroma_collection,
            bm25_index=self.bm25_index,
            bm25_tokenized_corpus=self.bm25_tokenized_corpus
        )
        
        logger.info("Indexes built successfully!")
    
    def _load_indexes(self):
        """Load existing indexes"""
        logger.info("Loading existing indexes...")
        
        # Load ChromaDB
        CHROMA_PERSIST_DIR.mkdir(exist_ok=True)
        chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_PERSIST_DIR),
            settings=Settings(anonymized_telemetry=False)
        )
        
        try:
            self.chroma_collection = chroma_client.get_collection(CHROMA_COLLECTION_NAME)
            logger.info(f"Loaded ChromaDB collection: {CHROMA_COLLECTION_NAME}")
        except:
            logger.warning(f"ChromaDB collection not found. Building indexes...")
            self._build_indexes()
            return
        
        # Rebuild chunks from descriptions (not JSON files)
        from FleetDbSummarizer.utils import create_collection_description_chunks
        
        description_chunks = create_collection_description_chunks(COLLECTION_INDEX_FILE)
        
        all_chunks = []
        for idx, desc_chunk in enumerate(description_chunks):
            chunk = {
                'text': desc_chunk['text'],
                'collection_name': desc_chunk['collection_name'],
                'collection_group': desc_chunk.get('collection_group', ''),
                'is_base': desc_chunk.get('is_base', False),
                'global_chunk_id': idx,
                'description': desc_chunk.get('description', ''),
                'use_for': desc_chunk.get('use_for', []),
                'keywords': desc_chunk.get('keywords', [])
            }
            all_chunks.append(chunk)
            self.parent_chunks[idx] = desc_chunk['text']
        
        self.chunks = all_chunks
        
        # Rebuild BM25 index
        self.bm25_tokenized_corpus = [
            chunk['text'].lower().split() for chunk in self.chunks
        ]
        self.bm25_index = BM25Okapi(self.bm25_tokenized_corpus)
        
        # Initialize retriever
        self.retriever = HybridRetriever(
            embedding_model=self.embedding_model,
            chroma_collection=self.chroma_collection,
            bm25_index=self.bm25_index,
            bm25_tokenized_corpus=self.bm25_tokenized_corpus
        )
        
        logger.info(f"Loaded {len(self.chunks)} chunks and indexes")
    
    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        """
        Phase 2: High-Recall Retrieval
        - Parallel query execution (dense + sparse)
        - Reciprocal Rank Fusion (RRF)
        
        Returns: List of candidate chunks with metadata
        """
        # Hybrid retrieval with RRF
        fused_results = self.retriever.retrieve(query)
        
        # Get top N for re-ranking
        top_n_ids = [chunk_id for chunk_id, score in fused_results[:TOP_N_RERANK]]
        
        # Retrieve chunk texts and metadata
        candidate_chunks = []
        for chunk_id in top_n_ids:
            try:
                chunk_idx = int(chunk_id)
                if chunk_idx < len(self.chunks):
                    chunk = self.chunks[chunk_idx].copy()
                    chunk['rrf_score'] = next((s for id, s in fused_results if id == chunk_id), 0.0)
                    candidate_chunks.append(chunk)
            except:
                continue
        
        return candidate_chunks
    
    def rerank(self, query: str, candidate_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Phase 3: High-Precision Re-ranking
        - Cross-Encoder re-ranking
        
        Returns: Re-ranked list of chunks
        """
        if not candidate_chunks:
            return []
        
        # Re-rank using Cross-Encoder
        ranked_chunks = self.reranker.rerank_with_metadata(
            query,
            candidate_chunks,
            top_n=TOP_N_RERANK,
            top_k_final=TOP_K_FINAL
        )
        
        return ranked_chunks
    
    def get_parent_chunks(self, ranked_chunks: List[Dict[str, Any]]) -> List[str]:
        """
        Get parent chunks for final context (Small-to-Big retrieval)
        """
        parent_texts = []
        
        for chunk in ranked_chunks:
            chunk_id = chunk.get('global_chunk_id')
            if chunk_id in self.parent_chunks:
                parent_texts.append(self.parent_chunks[chunk_id])
            else:
                # Fallback to chunk text
                parent_texts.append(chunk.get('text', ''))
        
        return parent_texts
    
    def filter_chunks_by_collections(self, chunks: List[Dict[str, Any]], 
                                     target_collections: List[str]) -> List[Dict[str, Any]]:
        """
        Filter chunks to prioritize target collections
        Returns filtered chunks with target collections first
        """
        if not target_collections:
            return chunks
        
        # Normalize target collection names
        normalized_targets = {str(col).lower().strip().strip('"\'') for col in target_collections}
        
        target_chunks = []
        other_chunks = []
        
        for chunk in chunks:
            collection_name = chunk.get('collection_name', '').lower()
            
            # Check if this chunk matches any target collection
            is_target = False
            for target in normalized_targets:
                target_normalized = target.lower().strip()
                # Exact match or contains match
                if target_normalized == collection_name or target_normalized in collection_name or collection_name in target_normalized:
                    is_target = True
                    break
            
            if is_target:
                target_chunks.append(chunk)
            else:
                other_chunks.append(chunk)
        
        # Return target chunks first, then others
        return target_chunks + other_chunks
    
    def generate_response(self, query: str, ranked_chunks: List[Dict[str, Any]]) -> str:
        """
        Phase 4: Generation - Identify which collections are needed
        Based on the final re-ranked chunks from Phase 3
        
        Args:
            query: User query
            ranked_chunks: Final chunks from Phase 3 (re-ranking)
        
        Returns:
            Python list format string with collection names
        """
        if not self.openai_client:
            return "[]"
        
        collection_id_start = time.time()
        
        # Get collection descriptions from the final re-ranked chunks (Phase 3 output)
        collections_summary = []
        seen_collections = set()
        
        for chunk in ranked_chunks:
            collection_name = chunk.get('collection_name', '')
            if collection_name and collection_name not in seen_collections:
                seen_collections.add(collection_name)
                description = chunk.get('description', chunk.get('text', ''))[:300]  # Use description or text
                collections_summary.append(f"Collection: {collection_name}\nDescription: {description}")
        
        # Create prompt to identify collections in Python list format
        system_prompt = "You are a fleet management system expert. Identify which collections are needed. Return ONLY a Python list format like [collection1, collection2]."
        user_prompt = f"""Given the following user question about a fleet management system, identify which collections from the database are needed to answer this question.

IMPORTANT: All of these are COLLECTIONS (there is no distinction between "collection" and "subcollection"). Each collection name below represents a complete collection.

CRITICAL CLASSIFICATION RULES:
- "system defined rules" / "system alert rules" / "SystemAlertRule" → For logs: Events_base (NOT AlertHistory_base)
- "AlertRule" / "alert rules" (not system) → For logs: AlertHistory_base (NOT Events_base)
- "geofence events" / "geofence triggers" → AlertHistory_base (NOT Events_base)
- "events" (driving behavior: Idling, Harsh Braking, etc.) → Events_base
- Events_base contains ONLY: Idling, Harsh Acceleration, Harsh Braking, Harsh Cornering, Sharp Turn, Sudden Stop, Over Speeding, Zigzag Driving, Frequent Start/Stop, Long Continuous Driving, Driving Without GPS Lock, driving with low battery
- AlertHistory_base contains: AlertRule notifications logs AND geofence events (NOT SystemAlertRule logs)
- Use asset_details_base to link vehicle to other collections.
- For questions about specific vehicles, include asset_details_base in the list of collections automatically even if not mentioned in the collections.
- Automatically include Driver_base and Driver_Profile for questions about specific drivers, even if not mentioned in the collections.

The following collections were identified as most relevant for this question (from re-ranking):

{chr(10).join(collections_summary)}

User Question: {query}

Based on the collection descriptions above (which are the most relevant collections from the re-ranking phase), identify which collections are needed to answer this question.

Return ONLY a Python list format with collection names. Example:

[asset_details_base, AvlRecord_base]

Do not explain, do not add any other text. Just return the Python list."""

        try:
            # Use OpenAI Chat Completions
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            resp = self.openai_client.chat.completions.create(
                model=self.openai_model_name,
                messages=messages,
                temperature=float(LLM_TEMPERATURE) if LLM_TEMPERATURE is not None else 0.0,
                max_tokens=int(LLM_MAX_TOKENS) if LLM_MAX_TOKENS is not None else 800,
                top_p=0.9
            )
            response_text = (resp.choices[0].message.content or "").strip() if getattr(resp, "choices", None) else ""
            
            collection_id_elapsed = time.time() - collection_id_start
            logger.info(f"⏱️  Collection identification completed in {collection_id_elapsed:.2f}s")
            
            # Try to parse as Python list
            import ast
            try:
                collections = ast.literal_eval(response_text)
                if isinstance(collections, list):
                    return str(collections)  # Return as string representation
            except:
                pass
            
            # Fallback: return the response as-is if it looks like a list
            import re
            if re.search(r'\[.*?\]', response_text):
                return response_text
            
            return "[]"
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "[]"
    
    def query(self, query: str, use_llm: bool = True) -> Dict[str, Any]:
        """
        Main query method: executes full RAG pipeline
        
        Args:
            query: User query
            use_llm: If True, identify collections needed. If False, return retrieved chunks only.
        
        Returns:
            Dictionary with:
            - collections: LLM-identified collection names needed to answer the question
            - chunks: Retrieved and re-ranked chunks
            - context: Context text sent to LLM
        """
        logger.info(f"Processing query: {query}")
        
        # Phase 2: High-Recall Retrieval
        candidate_chunks = self.retrieve(query)
        logger.info(f"Retrieved {len(candidate_chunks)} candidate chunks")
        
        # Phase 3: High-Precision Re-ranking
        ranked_chunks = self.rerank(query, candidate_chunks)
        logger.info(f"Re-ranked to {len(ranked_chunks)} top chunks")
        
        # Get parent chunks (Small-to-Big retrieval)
        parent_contexts = self.get_parent_chunks(ranked_chunks)
        
        result = {
            'query': query,
            'chunks': ranked_chunks,
            'context': parent_contexts,
            'collections': []
        }
        
        # Phase 4: Generation - Identify collections needed based on final re-ranked chunks
        collections_list = []
        if use_llm and self.openai_client:
            collections_needed = self.generate_response(query, ranked_chunks)
            result['collections'] = collections_needed
            result['answer'] = collections_needed  # Store as answer for backward compatibility
            
            # Parse collections from string to list
            try:
                import ast
                collections_list = ast.literal_eval(str(collections_needed))
                if not isinstance(collections_list, list):
                    collections_list = []
            except:
                # Try regex fallback
                import re
                list_match = re.search(r'\[(.*?)\]', str(collections_needed))
                if list_match:
                    list_content = list_match.group(1)
                    collections_list = [c.strip().strip("'\"") for c in list_content.split(',') if c.strip()]
        else:
            result['answer'] = None
            result['collections'] = []
            logger.info("LLM generation skipped")
        
        # Build collection JSON structure
        json_file_path = None
        if collections_list:
            try:
                collection_json = build_collection_json(
                    user_question=query,
                    selected_collections=collections_list,
                    collection_schemas_dir=COLLECTION_SCHEMAS_DIR
                )
                result['collection_json'] = collection_json
                
                # Save JSON to file (DISABLED for performance)
                json_file_path = self.save_collection_json(query, collection_json)
                result['json_file_path'] = None
            except Exception as e:
                logger.error(f"Error building collection JSON: {e}")
                result['collection_json'] = None
                result['json_file_path'] = None
        else:
            result['collection_json'] = None
            result['json_file_path'] = None
        
        return result
    
    def save_collection_json(self, query: str, collection_json: Dict[str, Any]) -> Path:
        """
        Save collection JSON to a file
        
        Args:
            query: User question (used for filename)
            collection_json: The collection JSON structure to save
        
        Returns:
            Path to the saved JSON file
        """
        import json
        import re
        from datetime import datetime
        
        # Create output directory if it doesn't exist
        JSON_OUTPUT_DIR.mkdir(exist_ok=True)
        
        # Generate filename from query (sanitize for filesystem)
        # Take first few words and sanitize
        filename = re.sub(r'[^\w\s-]', '', query[:50])  # Remove special chars
        filename = re.sub(r'[-\s]+', '_', filename)  # Replace spaces/dashes with underscores
        filename = filename.lower().strip('_')  # Lowercase and trim
        
        # Add timestamp to make unique
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{filename}.json"
        
        # Ensure filename isn't too long
        if len(safe_filename) > 150:
            safe_filename = safe_filename[:150] + ".json"
        
        file_path = JSON_OUTPUT_DIR / safe_filename
        
        # Save JSON file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(collection_json, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved collection JSON to: {file_path}")
        return file_path


def main():
    """Example usage"""
    import sys
    
    # Check if indexes should be rebuilt
    rebuild = '--rebuild' in sys.argv
    
    # Initialize pipeline
    pipeline = RAGPipeline(build_indexes=rebuild)
    
    # Example queries
    example_queries = [
        # "what is the location of the vehicle with the plate number 123 ABC?",
        # "WHAT IS THE VEHICLE TYPE OF THE VEHICLE 3688 FHD?",
        # "WHAT IS THE FLEET TYPE FOR THE VEHICLE WITH PLATE 243?",
        # "WHAT WAS THE LOCATION OF THE VEHICLE WITH THE PLATE NUMBER 3688 FHD AT 2 PM ON 1st OCT 2025?",
        # "WHAT ARE THE MANUFACTURER AND FIRMWARE/HARDWARE VERSIONS FOR THE DEVICE INSTALLED IN THE VEHICLE WITH THE PLATE NUMBER 243?"
        # "What events were triggered for the vehicle with the plate number 123 ABC?",
        # "What geofence events were triggered for the vehicle with the plate number 123 ABC?",
        # "what geofence events were triggered between 31 oct 2025 and 1 nov 2025?",
        # "who is the driver of the vehicle with the plate number 123 ABC?",
        # "WHAT WAS THE LOCATION OF THE VEHICLE WITH THE PLATE NUMBER 3688 FHD AT 2 PM ON 1st OCT 2025?",
        # "WHAT ARE THE FIRMWARE/HARDWARE VERSIONS FOR THE DEVICE INSTALLED IN THE VEHICLE WITH THE PLATE NUMBER 243?",
        # "What system defined rules are triggered for the vehicle with the plate number 123 ABC?",
        # "What system defined rules are triggered between 31 oct 2025 and 1 nov 2025?",
        # "What is the visa type of Al-Kandari?",
        # "Show me trips for vehicle 123 ABC",
        # "What is the duration of the longest trip by all the vehicles combined?",
        # "What is the duration of the longest trip by all the vehicles combined and how many hard alerts in it?"
        # "What is the location of the vehicle 5151 URA?",
        # "What alerts were triggered for the vehicle 1019 VTB?",
        # "Who is the driver of the vehicle 321 XYZ?",
        # "driver of vehicle 123 XYA",
        # "location of vehicles with teltonika installed",
        # "What is the name of driver of vehicle 5151 URA?",
        # "What is the name of driver of vehicle number 5151 URA?"
        # "tell me which events trigger on the 14 oct for the vehicle 4545 DFG?",
        # "tell me the highest speed of the vehicle 5151 UTA for today?",
        # "what is the highest speed of the vehicle 5151 URA on 15 OCT?",
        # "What is the total distance traveled by vehicle 3234 TEB on July 1, 2025?",
        # "What is the maximum speed recorded by vehicle 7458 TSA in the last 24 hours?",
        # "What is the total distance traveled by vehicle 1019 VTB from July 1st to today?",
        # "What is the last recorded GPS location of vehicle 3234 TEB?",
        "Which device is installed in 4871 SBA vehicle?",
        # "What is the idle start time for vehicle 1442 ZSA on July 9, 2025?",
        # "Is the vehicle 1993 NRA moving or IDLE?",
        # "1010 ا م ى. Give me speed violation report of this asset"
    ]

    if len(sys.argv) > 1 and not rebuild:
        # Query from command line
        query = ' '.join(sys.argv[1:])
        result = pipeline.query(query, use_llm=True)
        
        print(f"\nQuery: {query}")
        print(f"\nRetrieved {len(result['chunks'])} chunks:")
        for i, chunk in enumerate(result['chunks'][:5], 1):
            print(f"\n--- Chunk {i} ---")
            collection_name = chunk.get('collection_name') or chunk.get('collection', 'N/A')
            print(f"Collection: {collection_name}")
            print(f"Score: {chunk.get('rerank_score', 'N/A'):.4f}")
            print(f"Text preview: {chunk.get('text', '')[:200]}...")
        
        if result.get('collections'):
            print(f"\n--- Collections Needed to Answer This Question ---")
            print(result['collections'])
        elif result.get('answer'):
            print(f"\n--- Collections Needed ---")
            print(result['answer'])
        
        # Print collection JSON
        if result.get('collection_json'):
            print(f"\n{'='*60}")
            print(f"--- Collection JSON Structure ---")
            print(f"{'='*60}")
            import json
            print(json.dumps(result['collection_json'], indent=2, ensure_ascii=False))
            
            if result.get('json_file_path'):
                print(f"\n✓ JSON saved to: {result['json_file_path']}")
    else:
        # Run all example queries
        for idx, query in enumerate(example_queries, 1):
            print(f"\n\n{'#'*60}")
            print(f"# Processing Question {idx}/{len(example_queries)}")
            print(f"{'#'*60}")
            result = pipeline.query(query, use_llm=True)
            
            print(f"\n{'='*60}")
            print(f"Query: {query}")
            print(f"{'='*60}")
            print(f"\nRetrieved {len(result['chunks'])} chunks")
            
            # Show all 5 chunks
            for i, chunk in enumerate(result['chunks'], 1):
                print(f"\n--- Chunk {i} (Score: {chunk.get('rerank_score', 0):.4f}) ---")
                collection_name = chunk.get('collection_name') or chunk.get('collection', 'N/A')
                print(f"Collection: {collection_name}")
                print(f"Text preview: {chunk.get('text', '')[:300]}...")
            
            # Print collections identified
            collections_output = result.get('collections') or result.get('answer', '')
            if collections_output and collections_output != '[]':
                print(f"\n{'='*60}")
                print(f"--- Collections Needed to Answer This Question ---")
                print(f"{'='*60}")
                print(collections_output)
                
                # Also try to parse and display nicely
                try:
                    import ast
                    collections_list = ast.literal_eval(str(collections_output))
                    if isinstance(collections_list, list):
                        print(f"\nParsed as list with {len(collections_list)} collections:")
                        for i, col in enumerate(collections_list, 1):
                            print(f"  {i}. {col}")
                except:
                    pass
            else:
                print(f"\n{'='*60}")
                print("--- No Collections Identified ---")
                print("Check logs for details")
            
            # Print collection JSON
            if result.get('collection_json'):
                print(f"\n{'='*60}")
                print(f"--- Collection JSON Structure ---")
                print(f"{'='*60}")
                import json
                print(json.dumps(result['collection_json'], indent=2, ensure_ascii=False))
                
                if result.get('json_file_path'):
                    print(f"\n✓ JSON saved to: {result['json_file_path']}")


if __name__ == "__main__":
    main()

