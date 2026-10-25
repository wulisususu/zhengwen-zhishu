"""docs_pipeline v3 — LangGraph-based document generation pipeline.

0.6B outline + 0.6B chapter prompts + 3B per-chapter generation +
hallucination scanning + checkpoint resume + SSE streaming.

注意：本包使用惰性导出（PEP 562），不在包初始化时导入 router / runner。
原因：app.docs_pipeline.router → app.deps → app.models → app.PPT_master
（→ router → app.deps）会形成循环导入，导致 `import app.docs_pipeline`、
`import app.deps` 以及 pytest 收集测试文件时直接 ImportError。
"""

__all__ = [
    "router",
    "run_pipeline_stream",
    "run_pipeline",
    "PipelineState",
    "initial_state",
]

_LAZY_ATTRS = {
    "router": ("app.docs_pipeline.router", "router"),
    "run_pipeline_stream": ("app.docs_pipeline.runner", "run_pipeline_stream"),
    "PipelineState": ("app.docs_pipeline.state", "PipelineState"),
    "initial_state": ("app.docs_pipeline.state", "initial_state"),
    # Backward compatibility: v2 run_pipeline (used by document_tasks.py)
    "run_pipeline": ("app.docs_pipeline.core", "run_pipeline"),
}


def __getattr__(name):
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
