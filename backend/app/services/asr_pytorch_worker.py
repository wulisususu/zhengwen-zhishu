#!/usr/bin/env python3
"""ASR worker: full PyTorch Paraformer (VAD + Punc)."""
import os, sys, time, json, logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('asr_worker')

MODEL = None
PORT = 8003

VAD_CUSTOM_CONF = {
    'max_end_silence_time': 2000,
    'max_start_silence_time': 5000,
    'speech_to_sil_time_thres': 500,
    'sil_to_speech_time_thres': 300,
    'do_start_point_detection': True,
    'do_end_point_detection': True,
    'window_size_ms': 200,
    'do_extend': 1,
    'lookback_time_start_point': 200,
    'lookahead_time_end_point': 100,
    'max_single_segment_time': 60000,
}

def load_model():
    global MODEL
    logger.info('Loading full Paraformer (VAD + Punc)...')
    t0 = time.time()
    from funasr import AutoModel
    MODEL = AutoModel(
        model='iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        model_revision='v2.0.4',
        vad_model='fsmn-vad',
        vad_model_revision='v2.0.4',
        device='cpu',
        ncpu=4,
        disable_update=True,
    )
    if hasattr(MODEL, 'vad_kwargs') and MODEL.vad_kwargs:
        if 'model_conf' in MODEL.vad_kwargs:
            MODEL.vad_kwargs['model_conf'].update(VAD_CUSTOM_CONF)
    logger.info('Model loaded in %.1fs', time.time() - t0)

def transcribe(wav_path):
    global MODEL
    if MODEL is None:
        load_model()
    if not os.path.exists(wav_path):
        return {'error': 'File not found'}
    t0 = time.time()
    result = MODEL.generate(input=wav_path)
    elapsed = time.time() - t0
    if result and isinstance(result, list) and isinstance(result[0], dict):
        text = result[0].get('text', '')
        logger.info('Transcribed %d chars in %.1fs', len(text), elapsed)
        return {'text': text, 'time_s': round(elapsed, 2)}
    return {'error': 'No result'}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info('%s - %s', self.address_string(), fmt % args)
    def do_GET(self):
        if self.path == '/health':
            self._json({'status': 'ok', 'model_loaded': MODEL is not None})
        else:
            self._json({'error': 'Not Found'}, 404)
    def do_POST(self):
        if self.path != '/transcribe':
            self._json({'error': 'Not Found'}, 404)
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            wav_path = body.get('wav_path', '')
            self._json(transcribe(wav_path))
        except Exception as e:
            self._json({'error': str(e)}, 500)
    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    load_model()
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    logger.info('ASR worker listening on 127.0.0.1:%d', PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
