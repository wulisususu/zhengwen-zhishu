import threading
import time
import logging
from sentence_transformers import SentenceTransformer
from app.kb.config import EMBEDDING_MODEL_NAME, EMBEDDING_DEVICE, LOCAL_KB_MODELS, KB_EMBEDDING_IDLE_TIMEOUT

logger = logging.getLogger('app.kb.embedding')

_model = None
_last_used = 0.0
_model_lock = threading.Lock()


def get_embedding_model():
    global _model, _last_used
    with _model_lock:
        _last_used = time.time()
        if _model is None:
            logger.info('Loading embedding model: %s', EMBEDDING_MODEL_NAME)
            _model = SentenceTransformer(
                EMBEDDING_MODEL_NAME,
                device=EMBEDDING_DEVICE,
                cache_folder=str(LOCAL_KB_MODELS),
            )
            logger.info('Embedding model loaded')
    return _model


def embed_texts(texts):
    model = get_embedding_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def embed_query(query):
    prefixed = '为这个句子生成表示以用于检索相关文章：' + query
    return embed_texts([prefixed])[0]


def get_embedding_dim():
    return get_embedding_model().get_embedding_dimension()


def _evict_loop():
    global _model
    while True:
        time.sleep(60)
        with _model_lock:
            if _model and (time.time() - _last_used > KB_EMBEDDING_IDLE_TIMEOUT):
                _model = None
                logger.info('Embedding model unloaded (idle timeout %ds)', KB_EMBEDDING_IDLE_TIMEOUT)


_evict_thread = threading.Thread(target=_evict_loop, daemon=True)
_evict_thread.start()
