"""
Pipeline Step 3: CodeBERT Embeddings + FAISS Vector Store
Embeds code chunks and stores/queries them via FAISS.
"""

import os
import json
import pickle
import numpy as np
from typing import List, Dict, Any, Tuple

# Lazy-loaded to avoid import errors at startup
_model = None
_tokenizer = None


def _get_model():
    global _model, _tokenizer
    if _model is None:
        from transformers import AutoTokenizer, AutoModel
        import torch
        model_name = "microsoft/codebert-base"
        print(f"[Embedder] Loading {model_name}...")
        _tokenizer = AutoTokenizer.from_pretrained(model_name)
        _model = AutoModel.from_pretrained(model_name)
        _model.eval()
        print("[Embedder] Model loaded.")
    return _tokenizer, _model


def embed_texts(texts: List[str], batch_size: int = 16) -> np.ndarray:
    """Generate CodeBERT embeddings for a list of texts."""
    import torch

    tokenizer, model = _get_model()
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with torch.no_grad():
            output = model(**encoded)
            # CLS token embedding
            embeddings = output.last_hidden_state[:, 0, :]
            # L2 normalize
            embeddings = torch.nn.functional.normalize(embeddings, dim=-1)
            all_embeddings.append(embeddings.cpu().numpy())

    return np.vstack(all_embeddings).astype("float32")


class FAISSVectorStore:
    """FAISS-backed vector store with metadata."""

    def __init__(self, index_path: str = None):
        self.index = None
        self.metadata: List[Dict] = []
        self.index_path = index_path
        self.dim = 768  # CodeBERT hidden size

    def build(self, chunks: List[Dict[str, Any]], show_progress: bool = True) -> None:
        """Embed all chunks and build FAISS index."""
        import faiss

        texts = [c["text"] for c in chunks]
        self.metadata = [
            {
                "chunk_id": c["chunk_id"],
                "file_path": c["file_path"],
                "chunk_name": c["chunk_name"],
                "node_type": c["node_type"],
                "start_line": c["start_line"],
                "end_line": c["end_line"],
                "raw_code": c["raw_code"],
                "language": c.get("language", "unknown"),
            }
            for c in chunks
        ]

        print(f"[FAISS] Embedding {len(texts)} chunks...")
        embeddings = embed_texts(texts)

        # Inner product index (works with L2-normalized vectors = cosine sim)
        self.index = faiss.IndexFlatIP(self.dim)
        self.index.add(embeddings)
        print(f"[FAISS] Index built with {self.index.ntotal} vectors.")

    def query(self, query_text: str, top_k: int = 8) -> List[Dict[str, Any]]:
        """Return top-k similar chunks for a query."""
        if self.index is None or self.index.ntotal == 0:
            return []

        q_emb = embed_texts([query_text])
        scores, indices = self.index.search(q_emb, min(top_k, self.index.ntotal))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            meta = self.metadata[idx].copy()
            meta["score"] = float(score)
            results.append(meta)

        return results

    def save(self, path: str) -> None:
        """Persist index and metadata to disk."""
        import faiss
        os.makedirs(path, exist_ok=True)
        faiss.write_index(self.index, os.path.join(path, "index.faiss"))
        with open(os.path.join(path, "metadata.pkl"), "wb") as f:
            pickle.dump(self.metadata, f)
        print(f"[FAISS] Saved to {path}")

    def load(self, path: str) -> bool:
        """Load index and metadata from disk."""
        import faiss
        idx_path = os.path.join(path, "index.faiss")
        meta_path = os.path.join(path, "metadata.pkl")
        if not (os.path.exists(idx_path) and os.path.exists(meta_path)):
            return False
        self.index = faiss.read_index(idx_path)
        with open(meta_path, "rb") as f:
            self.metadata = pickle.load(f)
        print(f"[FAISS] Loaded {self.index.ntotal} vectors from {path}")
        return True

    @property
    def is_ready(self) -> bool:
        return self.index is not None and self.index.ntotal > 0
