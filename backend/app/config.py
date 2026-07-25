import os
from pathlib import Path

import yaml

_config = None
_ENV_LOADED = False


def _runtime_file(env_name: str, filename: str) -> Path:
    explicit = str(os.getenv(env_name) or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    external_dir = str(os.getenv("AI_BOX_CONFIG_DIR") or "").strip()
    if external_dir:
        return Path(external_dir).expanduser() / filename
    external_default = Path.home() / ".config" / "ai-box" / "backend" / filename
    if external_default.exists():
        return external_default
    return Path(__file__).parent.parent / filename


def _load_dotenv_if_present() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = _runtime_file("BACKEND_ENV_FILE", ".env")
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_key = key.strip()
            if not normalized_key:
                continue
            normalized_value = value.strip().strip('"').strip("'")
            os.environ.setdefault(normalized_key, normalized_value)
    _ENV_LOADED = True


_load_dotenv_if_present()

def get_config() -> dict:
    global _config
    if _config is None:
        cfg_path = _runtime_file("BACKEND_CONFIG_FILE", "config.yaml")
        with open(cfg_path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f)
    return _config
