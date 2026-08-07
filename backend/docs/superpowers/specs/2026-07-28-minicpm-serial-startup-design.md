# MiniCPM serialized NPU lifecycle

Vision RKNN and LLM RKLLM each initialise shared NPU resources. The OCR runner now runs Vision inference first, transfers its embedding to the parent, exits Vision and releases its NPU runtime, then starts the LLM and hands it the cached embedding. The two NPU models never coexist. Stage-specific timeouts and cleanup preserve diagnosability. Existing 3B pause/resume remains unchanged.

- After Vision exits, the runner waits **5 seconds by default** for RKNN driver page and DMA cleanup before loading RKLLM. MINICPM_NPU_RELEASE_SETTLE_SECONDS tunes this from 0 to 30 seconds.
