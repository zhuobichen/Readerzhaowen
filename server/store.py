# -*- coding: utf-8 -*-
"""数据层: 图书馆 / 回收站 / 笔记 / 进度存储, 以及书籍文本提取等工具函数。"""
import os
import json
import time
import re
import html as html_mod
import zipfile
import urllib.parse

from .constants import *

__all__ = [
    "load_library", "save_library", "load_ai_config", "save_ai_config",
    "scan_books", "_format_size", "book_path", "get_all_categories",
    "TRASH_RETENTION_SECONDS", "clean_expired_trash", "restore_from_trash",
    "permanently_delete_from_trash", "extract_book_text",
]

# --------------------------------------------------------------------------- #
#  数据层
# --------------------------------------------------------------------------- #
def load_library():
    if not os.path.exists(LIBRARY_FILE):
        return {"books": {}, "trash": {}}
    try:
        with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"books": {}, "trash": {}}
    # 确保必要字段存在 (兼容旧版 library.json)
    if "books" not in data:
        data["books"] = {}
    # trash: {book_id: {"title": str, "deletedAt": timestamp, "originalCategory": str, "path": str}}
    if "trash" not in data:
        data["trash"] = {}
    return data


def save_library(data):
    tmp = LIBRARY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LIBRARY_FILE)


def load_ai_config():
    if not os.path.exists(AI_CONFIG_FILE):
        return {"api_key": "", "endpoint": "", "model": ""}
    try:
        with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"api_key": "", "endpoint": "", "model": ""}


def save_ai_config(cfg):
    tmp = AI_CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, AI_CONFIG_FILE)


def scan_books():
    result = []
    if not os.path.isdir(BOOKS_DIR):
        return result
    for name in sorted(os.listdir(BOOKS_DIR), key=str.lower):
        full = os.path.join(BOOKS_DIR, name)
        if os.path.isdir(full):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED_EXT:
            continue
        st = os.stat(full)
        result.append({
            "id": name, "name": name, "ext": ext,
            "format": SUPPORTED_EXT[ext], "size": st.st_size, "mtime": int(st.st_mtime),
        })
    return result


def _format_size(n):
    if n < 1024:
        return "{} B".format(n)
    elif n < 1024 * 1024:
        return "{:.1f} KB".format(n / 1024)
    else:
        return "{:.1f} MB".format(n / (1024 * 1024))


def book_path(book_id):
    """安全获取书籍路径 (沙箱验证: 防止目录遍历)"""
    name = urllib.parse.unquote(book_id)
    name = os.path.basename(name)
    if not name:
        return None
    full = os.path.join(BOOKS_DIR, name)
    full = os.path.abspath(full)
    if not validate_sandbox_path(full):
        return None
    if not os.path.isfile(full):
        return None
    return full


def get_all_categories():
    """从 library.json 收集所有分类"""
    lib = load_library()
    cats = lib.get("categories", [])
    # 也扫描书籍自定义分类
    for meta in lib.get("books", {}).values():
        c = meta.get("category")
        if c and c not in cats:
            cats.append(c)
    return sorted(cats)


# --------------------------------------------------------------------------- #
#  回收站 (trash)
# --------------------------------------------------------------------------- #
TRASH_RETENTION_SECONDS = 30 * 86400  # 回收站保留 30 天


def clean_expired_trash():
    """清理超过 30 天的回收站项目 (永久删除文件并移出 trash)"""
    lib = load_library()
    trash = lib.get("trash", {})
    if not trash:
        return []
    now = int(time.time())
    expired = []
    for bid, info in list(trash.items()):
        if now - info.get("deletedAt", 0) > TRASH_RETENTION_SECONDS:
            # 永久删除文件
            try:
                p = info.get("path", "")
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
            trash.pop(bid, None)
            expired.append(bid)
    if expired:
        save_library(lib)
    return expired


def restore_from_trash(book_id):
    """从回收站恢复一本书到书架, 返回 (info, error)"""
    lib = load_library()
    trash = lib.get("trash", {})
    if book_id not in trash:
        return None, "not in trash"
    info = trash.pop(book_id)
    # 恢复到 books (用原始文件名作 key, 与 scan_books 返回的 id 一致)
    books = lib.setdefault("books", {})
    books[book_id] = {
        "progress": info.get("progress", 0),
        "category": info.get("originalCategory", ""),
    }
    # 保留原有元数据 (标题/作者/封面等) 若存在则不覆盖
    save_library(lib)
    return info, None


def permanently_delete_from_trash(book_id):
    """永久删除回收站中的一本书 (删除文件并移出 trash), 返回 (info, error)"""
    lib = load_library()
    trash = lib.get("trash", {})
    if book_id not in trash:
        return None, "not in trash"
    info = trash.pop(book_id)
    # 永久删除文件
    try:
        p = info.get("path", "")
        if p and os.path.exists(p):
            os.remove(p)
    except Exception:
        pass
    save_library(lib)
    return info, None
def extract_book_text(path, fmt, max_chars=8000):
    """提取书籍文本用于AI总结"""
    try:
        if fmt == "txt":
            with open(path, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8", errors="replace")
            if "\ufffd" in text:
                try:
                    text = raw.decode("gbk", errors="replace")
                except Exception:
                    pass
            return text[:max_chars]
        elif fmt == "epub":
            with zipfile.ZipFile(path) as z:
                html_files = sorted([f for f in z.namelist()
                                     if f.endswith(('.html', '.xhtml', '.htm'))])
                parts = []
                for f in html_files[:30]:
                    try:
                        content = z.read(f).decode("utf-8", errors="replace")
                        clean = re.sub(r'<[^>]+>', ' ', content)
                        clean = html_mod.unescape(clean)
                        clean = re.sub(r'\s+', ' ', clean).strip()
                        if clean:
                            parts.append(clean)
                    except Exception:
                        continue
                full = "\n\n".join(parts)
                return full[:max_chars]
        elif fmt == "fb2":
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            clean = re.sub(r'<[^>]+>', ' ', content)
            clean = html_mod.unescape(clean)
            return clean[:max_chars]
    except Exception:
        pass
    return ""

