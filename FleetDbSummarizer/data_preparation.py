"""
Data Preparation and Indexing Module
Phase 1: Content-Aware Chunking and Dual Indexing
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
import numpy as np

from FleetDbSummarizer.config import (
    COLLECTION_CHUNKS_DIR,
    COLLECTION_INDEX_FILE,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    PARENT_CHUNK_SIZE,
    EMBEDDING_MODEL,
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
    BATCH_SIZE
)
from FleetDbSummarizer.utils import (
    load_all_collection_files,
    parse_collection_index,
    format_json_for_chunking,
    hierarchical_chunk_text,
    create_parent_chunks,
    create_collection_description_chunks
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataPreparation:
    """
    Phase 1: Data Preparation & Indexing
    - Hierarchical/Recursive Chunking
    - Small-to-Big Retrieval (Parent Document Retrieval)
    - Dual Indexing (Dense Vector + Sparse BM25)
    """
    
    def __init__(self):
        from FleetDbSummarizer.config import DEVICE
        # Load embedding model from local cache only (avoid network checks)
        try:
            self.embedding_model = SentenceTransformer(EMBEDDING_MODEL, device=DEVICE, local_files_only=True)
            logger.info(f"Loaded embedding model from local cache: {EMBEDDING_MODEL}")
        except Exception as e:
            logger.warning(f"Model not found in local cache: {e}. Attempting to download...")
            # Fallback to network download if not in cache
            self.embedding_model = SentenceTransformer(EMBEDDING_MODEL, device=DEVICE)
            logger.info(f"Downloaded and loaded embedding model: {EMBEDDING_MODEL}")
        self.chunks = []
        self.parent_chunks = {}
        self.chroma_client = None
        self.chroma_collection = None
        self.bm25_index = None
        self.bm25_tokenized_corpus = []
        
    def load_data(self) -> Dict[str, Any]:
        """Load all collection files and metadata"""
        logger.info("Loading collection files...")
        collections_data = load_all_collection_files(COLLECTION_CHUNKS_DIR)
        collections_metadata = parse_collection_index(COLLECTION_INDEX_FILE)
        
        return {
            'collections_data': collections_data,
            'collections_metadata': collections_metadata
        }
    
    def prepare_chunks_from_descriptions(self) -> List[Dict[str, Any]]:
        """
        Phase 1.1: Create chunks from collection descriptions
        - Each collection (subcollection treated as collection) gets a chunk based on its description
        - Chunks organized by collection group (base first, then others)
        """
        logger.info("Preparing chunks from collection descriptions...")
        
        # Create chunks from collection index descriptions
        description_chunks = create_collection_description_chunks(COLLECTION_INDEX_FILE)
        
        # Convert to format expected by the pipeline
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
            # Use the chunk text as parent chunk (no hierarchical chunking needed)
            self.parent_chunks[idx] = desc_chunk['text']
        
        self.chunks = all_chunks
        logger.info(f"Created {len(all_chunks)} collection description chunks")
        return all_chunks
    
    def create_dense_index(self, chunks: List[Dict[str, Any]]):
        """
        Phase 1.2: Create Dense Vector Index (ChromaDB)
        """
        logger.info("Creating dense vector index (ChromaDB)...")
        
        # Initialize ChromaDB
        CHROMA_PERSIST_DIR.mkdir(exist_ok=True)
        
        self.chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_PERSIST_DIR),
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Get or create collection
        try:
            self.chroma_collection = self.chroma_client.get_collection(CHROMA_COLLECTION_NAME)
            logger.info(f"Loaded existing collection: {CHROMA_COLLECTION_NAME}")
        except:
            self.chroma_collection = self.chroma_client.create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"description": "Fleet Management RAG Collection"}
            )
            logger.info(f"Created new collection: {CHROMA_COLLECTION_NAME}")
        
        # Extract texts and generate embeddings in batches
        texts = [chunk['text'] for chunk in chunks]
        chunk_ids = [str(chunk['global_chunk_id']) for chunk in chunks]
        
        # Generate embeddings
        logger.info("Generating embeddings...")
        embeddings = self.embedding_model.encode(
            texts,
            show_progress_bar=True,
            batch_size=BATCH_SIZE,
            convert_to_numpy=True
        )
        
        # Prepare metadata
        metadatas = []
        for chunk in chunks:
            metadatas.append({
                'collection_name': chunk.get('collection_name', ''),
                'collection_group': chunk.get('collection_group', ''),
                'is_base': chunk.get('is_base', False),
                'text_length': len(chunk.get('text', ''))
            })
        
        # Add to ChromaDB in batches
        logger.info("Adding chunks to ChromaDB...")
        batch_size = 100
        for i in range(0, len(chunk_ids), batch_size):
            batch_ids = chunk_ids[i:i+batch_size]
            batch_embeddings = embeddings[i:i+batch_size].tolist()
            batch_metadatas = metadatas[i:i+batch_size]
            batch_texts = texts[i:i+batch_size]
            
            self.chroma_collection.add(
                ids=batch_ids,
                embeddings=batch_embeddings,
                metadatas=batch_metadatas,
                documents=batch_texts
            )
        
        logger.info(f"Indexed {len(chunk_ids)} chunks in ChromaDB")
    
    def create_sparse_index(self, chunks: List[Dict[str, Any]]):
        """
        Phase 1.3: Create Sparse BM25 Index
        """
        logger.info("Creating sparse BM25 index...")
        
        # Tokenize texts for BM25
        texts = [chunk['text'] for chunk in chunks]
        tokenized_corpus = [text.lower().split() for text in texts]
        
        # Create BM25 index
        self.bm25_index = BM25Okapi(tokenized_corpus)
        self.bm25_tokenized_corpus = tokenized_corpus
        
        logger.info(f"Created BM25 index for {len(tokenized_corpus)} documents")
    
    def build_indexes(self):
        """Main method to build all indexes"""
        # Prepare chunks from descriptions (not JSON files)
        chunks = self.prepare_chunks_from_descriptions()
        
        # Create indexes
        self.create_dense_index(chunks)
        self.create_sparse_index(chunks)
        
        logger.info("Index building completed!")
        
        return {
            'chunks': chunks,
            'parent_chunks': self.parent_chunks,
            'chroma_collection': self.chroma_collection,
            'bm25_index': self.bm25_index
        }


if __name__ == "__main__":
    # Run data preparation
    prep = DataPreparation()
    indexes = prep.build_indexes()
    print(f"Indexing complete! Created {len(indexes['chunks'])} chunks.")

