"""PPT-master: LangGraph-based PPT generation pipeline.

注意：本包使用惰性导出（PEP 562）。app.models 会在模块末尾导入
app.PPT_master.guided_models 注册 ORM 模型；若本包在初始化时就导入
router（→ app.deps → app.models），会形成 deps → models → PPT_master →
router → deps 的循环导入，使 `import app.deps` 直接失败。
"""

__all__ = [
    "router",
    "run_pipeline_stream",
    "PipelineState",
    "initial_state",
]

_LAZY_ATTRS = {
    "router": ("app.PPT_master.router", "router"),
    "run_pipeline_stream": ("app.PPT_master.runner", "run_pipeline_stream"),
    "PipelineState": ("app.PPT_master.state", "PipelineState"),
    "initial_state": ("app.PPT_master.state", "initial_state"),
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
