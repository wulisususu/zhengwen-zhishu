import os
import threading
import logging
import numpy as np
import faiss

from app.kb.config import VECTOR_DIR

logger = logging.getLogger('app.kb.vector_store')

INDEX_FILE = VECTOR_DIR / 'faiss.index'


class VectorStore:
    def __init__(self):
        self.dim = self._load_dim()
        self._lock = threading.Lock()

        if INDEX_FILE.exists():
            try:
                loaded = faiss.read_index(str(INDEX_FILE))
                if isinstance(loaded, faiss.IndexIDMap):
                    self.index = loaded
                else:
                    logger.warning('Old index format, rebuilding')
                    self.index = faiss.IndexIDMap(faiss.IndexFlatIP(self.dim))
                    self._save()
            except Exception as e:
                logger.error('Failed to load FAISS index: %s, creating new', e)
                self.index = faiss.IndexIDMap(faiss.IndexFlatIP(self.dim))
        else:
            self.index = faiss.IndexIDMap(faiss.IndexFlatIP(self.dim))

    def _load_dim(self):
        from app.kb.config import EMBEDDING_DIM
        return EMBEDDING_DIM

    def _save(self):
        tmp = str(INDEX_FILE) + '.tmp'
        faiss.write_index(self.index, tmp)
        os.replace(tmp, str(INDEX_FILE))

    def add(self, vectors, chunk_ids):
        with self._lock:
            if not isinstance(vectors, np.ndarray):
                vectors = np.array(vectors, dtype=np.float32)
            ids = np.array(chunk_ids, dtype=np.int64)
            self.index.add_with_ids(vectors, ids)
            self._save()

    def search(self, query_vector, top_k=5):
        with self._lock:
            if isinstance(query_vector, np.ndarray):
                query_vector = query_vector.reshape(1, -1).astype(np.float32)
            scores, ids = self.index.search(query_vector, top_k)
        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx != -1:
                results.append({'chunk_id': int(idx), 'score': float(score)})
        return results

    def remove(self, chunk_ids):
        with self._lock:
            ids = np.array(chunk_ids, dtype=np.int64)
            id_selector = faiss.IDSelectorBatch(len(ids), faiss.swig_ptr(ids))
            self.index.remove_ids(id_selector)
            self._save()

    def get_all_ids(self):
        with self._lock:
            if self.index.ntotal == 0:
                return set()
            id_array = faiss.vector_to_array(self.index.id_map)
            return set(int(x) for x in id_array)

    def count(self):
        with self._lock:
            return self.index.ntotal

    def reset(self):
        with self._lock:
            self.index = faiss.IndexIDMap(faiss.IndexFlatIP(self.dim))
            self._save()
        if INDEX_FILE.exists():
            INDEX_FILE.unlink()
