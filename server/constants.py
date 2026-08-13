# -*- coding: utf-8 -*-
"""路径常量与沙箱工具 (零第三方依赖)。"""
import os

__all__ = [
    "ROOT", "BOOKS_DIR", "STATIC_DIR", "DATA_DIR",
    "LIBRARY_FILE", "AI_CONFIG_FILE", "MEMORY_FILE",
    "SANDBOX_DIRS", "validate_sandbox_path", "SUPPORTED_EXT",
]

# constants.py 位于 <root>/server/ 下, 向上两级才是仓库根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(ROOT, "books")
STATIC_DIR = os.path.join(ROOT, "static")
DATA_DIR = os.path.join(ROOT, "data")
LIBRARY_FILE = os.path.join(DATA_DIR, "library.json")
AI_CONFIG_FILE = os.path.join(DATA_DIR, "ai_config.json")
MEMORY_FILE = os.path.join(DATA_DIR, "agent_memory.json")

# ---- Agent 沙箱: 所有文件操作限制在这些目录内 ----
SANDBOX_DIRS = [os.path.abspath(BOOKS_DIR), os.path.abspath(DATA_DIR)]

def validate_sandbox_path(path):
    """验证路径在沙箱目录内, 防止目录遍历攻击"""
    if not path:
        return False
    abs_path = os.path.abspath(path)
    for sandbox_dir in SANDBOX_DIRS:
        if abs_path.startswith(sandbox_dir + os.sep) or abs_path == sandbox_dir:
            return True
    return False

SUPPORTED_EXT = {
    ".pdf": "pdf", ".epub": "epub", ".txt": "txt",
    ".mobi": "mobi", ".azw3": "azw3", ".fb2": "fb2",
    ".cbz": "cbz", ".cbr": "cbr", ".docx": "docx",
}

for d in (BOOKS_DIR, STATIC_DIR, DATA_DIR):
    os.makedirs(d, exist_ok=True)

