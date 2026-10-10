"""pytest 全局配置：把 scripts_general 加入 sys.path，并把 CWD 固定到仓库根目录。"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts_general"))

import pytest


@pytest.fixture(autouse=True)
def _repo_cwd():
    """保证 demo 相对路径（demo/data/...）在任意 CWD 下均可解析。"""
    old = os.getcwd()
    os.chdir(REPO_ROOT)
    yield
    os.chdir(old)
