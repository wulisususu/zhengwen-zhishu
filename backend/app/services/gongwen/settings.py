"""gongwen-kit integration settings (config.yaml `gongwen:` section)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KIT = BACKEND_ROOT / "third_party" / "gongwen-kit"
BRIDGE_SCRIPT = Path(__file__).resolve().parent / "node" / "render_notice.js"


@dataclass(frozen=True)
class GongwenSettings:
    kit_path: Path = DEFAULT_KIT
    node_bin: str = "node"
    # S1 on x86 (Xeon E5-2690 v4): check 0.45–0.71 s, render+self-check 0.9–1.0 s.
    # Board (RK3588) is unmeasured; limits leave >20x headroom.
    check_timeout_seconds: float = 20.0
    render_timeout_seconds: float = 30.0
    fix_timeout_seconds: float = 30.0
    max_upload_bytes: int = 10 * 1024 * 1024
    max_concurrent: int = 2


def load_settings() -> GongwenSettings:
    try:
        from app.config import get_config
        section = (get_config() or {}).get("gongwen") or {}
    except Exception:   # no config.yaml (tests, fresh checkout): defaults
        section = {}
    kit = Path(str(section.get("kit_path") or DEFAULT_KIT)).expanduser()
    if not kit.is_absolute():
        kit = BACKEND_ROOT / kit
    return GongwenSettings(
        kit_path=kit,
        node_bin=str(section.get("node_bin") or "node"),
        check_timeout_seconds=float(section.get("check_timeout_seconds") or 20.0),
        render_timeout_seconds=float(section.get("render_timeout_seconds") or 30.0),
        fix_timeout_seconds=float(section.get("fix_timeout_seconds") or 30.0),
        max_upload_bytes=int(float(section.get("max_upload_mb") or 10) * 1024 * 1024),
        max_concurrent=max(1, int(section.get("max_concurrent") or 2)),
    )
