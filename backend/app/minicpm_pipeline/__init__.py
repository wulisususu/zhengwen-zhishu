"""Qwen2.5-3B document pipeline — single-section with auto-restart."""
from app.minicpm_pipeline.pipeline import (
    run_pipeline,
    run_pipeline_segmented,
    route_document,
    generate_outline,
    generate_section,
)
