import os
from pathlib import Path
import pytest
from app.services.gongwen.runner import run_node
from app.services.gongwen.settings import load_settings
from app.services.gongwen.runner import GongwenToolError


@pytest.mark.skipif(os.name != "nt", reason="Windows Node crypto environment regression")
def test_real_node_crypto_initializes_in_minimal_environment():
    result = run_node(load_settings(), ["-e", "console.log(require('node:crypto').randomBytes(8).length)"], timeout=10, cwd=Path.cwd())
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "8"


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree termination regression")
def test_timeout_terminates_real_node_process():
    with pytest.raises(GongwenToolError, match="TIMEOUT"):
        run_node(load_settings(), ["-e", "setTimeout(()=>{}, 10000)"], timeout=0.2, cwd=Path.cwd())
