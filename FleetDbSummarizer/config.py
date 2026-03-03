"""
Configuration settings for the RAG pipeline
"""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent
COLLECTION_CHUNKS_DIR = BASE_DIR / "collection_chunks"
COLLECTION_SCHEMAS_DIR = BASE_DIR / "collection_schemas"
DOCS_DIR = BASE_DIR / "docs"
COLLECTION_INDEX_FILE = DOCS_DIR / "collection_index_rag.md"

# Chunking Configuration
CHUNK_SIZE = 512  # Base chunk size for small chunks
CHUNK_OVERLAP = 50  # Overlap between chunks
PARENT_CHUNK_SIZE = 2048  # Size for parent chunks (Small-to-Big retrieval)

# Retrieval Configuration
K_DENSE = 12  # Top K for dense vector search
K_SPARSE = 12  # Top K for sparse BM25 search
RRF_K = 60  # Reciprocal Rank Fusion parameter
TOP_N_RERANK = 14  # Top N documents for re-ranking
TOP_K_FINAL = 5  # Final top K chunks to send to LLM

# Model Configuration
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # Fast, good quality
# For better quality: "sentence-transformers/all-mpnet-base-v2" or "BAAI/bge-base-en-v1.5"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"  # Fast cross-encoder
# For better quality: "cross-encoder/ms-marco-MiniLM-L-12-v2"

# LLM Configuration
# LLM_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"  # HuggingFace model
#LLM_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 1000
DEVICE = "cpu"  # Use CPU (CUDA not available)

# Vector Database Configuration
CHROMA_PERSIST_DIR = BASE_DIR / "chroma_db"
CHROMA_COLLECTION_NAME = "fleet_management_rag"

# Indexing Configuration
BATCH_SIZE = 100  # Batch size for indexing

# JSON Output Configuration
JSON_OUTPUT_DIR = BASE_DIR / "output_json"  # Directory to save collection JSON files

# Logging
LOG_LEVEL = "INFO"
LLM_MODEL = '4o'