# -*- coding: utf-8 -*-
"""
书架 + 阅读器 本地服务 (零第三方依赖, 仅使用 Python 标准库)

路由:
  GET  /                       -> 书架首页 (static/index.html)
  GET  /static/<path>          -> 静态资源 (css/js/vendor/...)
  GET  /api/books              -> 书籍列表 (含分类信息)
  GET  /api/library            -> 完整 library.json
  POST /api/library            -> 保存完整 library.json
  GET  /api/books/<id>/file    -> 书籍原文件 (支持 HTTP Range)
  POST /api/books/<id>/progress-> 保存阅读进度
  GET  /api/books/<id>/progress-> 读取阅读进度
  POST /api/books/<id>/meta    -> 保存书籍元数据
  GET  /api/books/<id>/notes   -> 读取笔记列表
  POST /api/books/<id>/notes   -> 增/改/删笔记
  POST /api/books/<id>/category-> 设置书籍分类 {category}
  DELETE /api/books/<id>       -> 删除书籍文件
  POST /api/books/upload       -> 上传书籍 (multipart/form-data)
  GET  /api/categories         -> 获取所有分类及书籍数
  POST /api/categories         -> 新建/重命名分类
  DELETE /api/categories/<name>-> 删除分类
  GET  /api/ai/config          -> 获取AI配置 (key脱敏)
  POST /api/ai/config          -> 保存AI配置
  POST /api/ai/chat            -> AI对话代理 (流式SSE)

启动:  python server.py
默认端口 8769, 也可: python server.py 9000
"""
import os
import sys
import json
import time
import re
import html as html_mod
import mimetypes
import urllib.parse
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
BOOKS_DIR = os.path.join(ROOT, "books")
STATIC_DIR = os.path.join(ROOT, "static")
DATA_DIR = os.path.join(ROOT, "data")
LIBRARY_FILE = os.path.join(DATA_DIR, "library.json")
AI_CONFIG_FILE = os.path.join(DATA_DIR, "ai_config.json")

SUPPORTED_EXT = {
    ".pdf": "pdf", ".epub": "epub", ".txt": "txt",
    ".mobi": "mobi", ".azw3": "azw3", ".fb2": "fb2",
    ".cbz": "cbz", ".cbr": "cbr", ".docx": "docx",
}

for d in (BOOKS_DIR, STATIC_DIR, DATA_DIR):
    os.makedirs(d, exist_ok=True)


# --------------------------------------------------------------------------- #
#  数据层
# --------------------------------------------------------------------------- #
def load_library():
    if not os.path.exists(LIBRARY_FILE):
        return {"books": {}}
    try:
        with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"books": {}}


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


def book_path(book_id):
    name = urllib.parse.unquote(book_id)
    name = os.path.basename(name)
    if not name:
        return None
    full = os.path.join(BOOKS_DIR, name)
    full = os.path.abspath(full)
    if not full.startswith(os.path.abspath(BOOKS_DIR) + os.sep):
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


def extract_book_text(path, fmt, max_chars=8000):
    """提取书籍文本用于AI总结"""
    try:
        if fmt == "txt":
            with open(path, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8", errors="replace")
            if "\ufffd" in text * 10:
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


# --------------------------------------------------------------------------- #
#  AI 工具定义 (OpenAI function calling 格式)
# --------------------------------------------------------------------------- #
AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_books",
            "description": "列出书架上的所有书籍，包括书名、格式、分类和阅读进度",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_books",
            "description": "按关键词搜索书籍（匹配书名或作者）",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_book_content",
            "description": "获取一本书的文本内容用于总结或分析",
            "parameters": {
                "type": "object",
                "properties": {"book_id": {"type": "string", "description": "书籍ID（文件名）"}},
                "required": ["book_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "categorize_book",
            "description": "为书籍设置分类",
            "parameters": {
                "type": "object",
                "properties": {
                    "book_id": {"type": "string", "description": "书籍ID"},
                    "category": {"type": "string", "description": "分类名称"},
                },
                "required": ["book_id", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "列出所有已创建的分类",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_book",
            "description": "从书架删除一本书（删除文件）",
            "parameters": {
                "type": "object",
                "properties": {"book_id": {"type": "string", "description": "书籍ID"}},
                "required": ["book_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_book",
            "description": "在阅读器中打开一本书",
            "parameters": {
                "type": "object",
                "properties": {"book_id": {"type": "string", "description": "书籍ID"}},
                "required": ["book_id"],
            },
        },
    },
]

AI_SYSTEM_PROMPT = """你是「阅微」，一个本地电子书书架的AI助手。你可以帮助用户：
1. 总结书籍内容
2. 查找和推荐书籍
3. 管理书籍分类
4. 打开书籍
5. 删除书籍
6. 回答关于书籍的问题

请用简洁友好的中文回答。当用户要求总结一本书时，先调用get_book_content获取内容，再进行总结。
当用户要打开书或删除书时，调用相应工具，前端会执行操作。"""


def execute_ai_tool(name, args):
    """执行AI工具调用，返回结果字符串"""
    try:
        if name == "list_books":
            books = scan_books()
            lib = load_library().get("books", {})
            lines = []
            for b in books:
                meta = lib.get(b["id"], {})
                title = meta.get("title") or os.path.splitext(b["name"])[0]
                cat = meta.get("category", "未分类")
                prog = meta.get("progress", 0)
                lines.append(f"- {title} | 格式:{b['format']} | 分类:{cat} | 进度:{prog*100:.0f}% | ID:{b['id']}")
            return "\n".join(lines) if lines else "书架为空"

        elif name == "find_books":
            q = args.get("query", "").lower()
            books = scan_books()
            lib = load_library().get("books", {})
            results = []
            for b in books:
                meta = lib.get(b["id"], {})
                title = meta.get("title") or os.path.splitext(b["name"])[0]
                author = meta.get("author", "")
                if q in title.lower() or q in author.lower() or q in b["id"].lower():
                    cat = meta.get("category", "未分类")
                    results.append(f"- {title}" + (f" - {author}" if author else "") + f" | 分类:{cat} | ID:{b['id']}")
            return "\n".join(results) if results else "未找到匹配的书籍"

        elif name == "get_book_content":
            bid = args.get("book_id", "")
            full = book_path(bid)
            if not full:
                return "找不到这本书"
            ext = os.path.splitext(full)[1].lower()
            fmt = SUPPORTED_EXT.get(ext, "")
            text = extract_book_text(full, fmt)
            if text:
                return text
            return f"无法提取{fmt}格式书籍的文本内容。书籍: {bid}"

        elif name == "categorize_book":
            bid = args.get("book_id", "")
            cat = args.get("category", "")
            if not book_path(bid):
                return "找不到这本书"
            lib = load_library()
            meta = lib.setdefault("books", {}).setdefault(bid, {})
            meta["category"] = cat
            cats = lib.setdefault("categories", [])
            if cat not in cats:
                cats.append(cat)
            save_library(lib)
            return f"已将《{meta.get('title', bid)}》分类为「{cat}」"

        elif name == "list_categories":
            cats = get_all_categories()
            lib = load_library().get("books", {})
            counts = {}
            for meta in lib.values():
                c = meta.get("category", "未分类")
                counts[c] = counts.get(c, 0) + 1
            lines = [f"- {c} ({counts.get(c, 0)}本)" for c in cats]
            return "\n".join(lines) if lines else "还没有分类"

        elif name == "delete_book":
            bid = args.get("book_id", "")
            full = book_path(bid)
            if not full:
                return "找不到这本书"
            lib = load_library()
            title = lib.get("books", {}).get(bid, {}).get("title", bid)
            os.remove(full)
            lib.get("books", {}).pop(bid, None)
            save_library(lib)
            return f"已删除《{title}》"

        elif name == "open_book":
            bid = args.get("book_id", "")
            full = book_path(bid)
            if not full:
                return "找不到这本书"
            return f"__ACTION__:open_book:{bid}"

        return f"未知工具: {name}"
    except Exception as e:
        return f"工具执行出错: {e}"


def call_llm_api(config, messages, tools=None):
    """调用 OpenAI 兼容 API (非流式)"""
    endpoint = config.get("endpoint", "").rstrip("/")
    if not endpoint:
        endpoint = "https://api.openai.com/v1"
    url = f"{endpoint}/chat/completions"
    api_key = config.get("api_key", "")
    model = config.get("model", "gpt-4o-mini")

    body = {"model": model, "messages": messages, "max_tokens": 4096}
    if tools:
        body["tools"] = tools

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": f"API错误 {e.code}: {err_body[:500]}"}
    except Exception as e:
        return {"error": str(e)}


def call_llm_stream(config, messages, tools=None):
    """调用 OpenAI 兼容 API (流式, 返回生成器)"""
    endpoint = config.get("endpoint", "").rstrip("/")
    if not endpoint:
        endpoint = "https://api.openai.com/v1"
    url = f"{endpoint}/chat/completions"
    api_key = config.get("api_key", "")
    model = config.get("model", "gpt-4o-mini")

    body = {"model": model, "messages": messages, "stream": True, "max_tokens": 4096}
    if tools:
        body["tools"] = tools

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    resp = urllib.request.urlopen(req, timeout=120)
    buf = b""
    for line in resp:
        buf += line
        while b"\n" in buf:
            line_bytes, buf = buf.split(b"\n", 1)
            line_str = line_bytes.decode("utf-8", errors="replace").strip()
            if not line_str or not line_str.startswith("data:"):
                continue
            payload = line_str[5:].strip()
            if payload == "[DONE]":
                return
            try:
                chunk = json.loads(payload)
                yield chunk
            except json.JSONDecodeError:
                continue
    # 处理剩余
    line_str = buf.decode("utf-8", errors="replace").strip()
    if line_str.startswith("data:") and line_str[5:].strip() != "[DONE]":
        try:
            yield json.loads(line_str[5:].strip())
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  HTTP 处理器
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "ShelfReader/2.0"

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if isinstance(body, (bytes, bytearray)):
            self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        if body and isinstance(body, (bytes, bytearray)):
            self.wfile.write(body)

    def _json(self, code, obj, extra_headers=None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), headers=extra_headers)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return b""
        return self.rfile.read(length)

    # ---- GET ----
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        parts = [p for p in path.split("/") if p != ""]

        if path in ("", "/"):
            return self._serve_static_file("index.html", "/")
        if parts and parts[0] == "api":
            return self._api_get(parts, parsed)
        if parts and parts[0] == "static":
            rel = os.path.join(*parts[1:]) if len(parts) > 1 else ""
            return self._serve_static_file(rel, path)
        if parts and parts[0] in ("css", "js", "vendor", "assets"):
            return self._serve_static_file(os.path.join(*parts), path)
        self._send(404, b"not found", "text/plain; charset=utf-8")

    # ---- POST ----
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p != ""]

        # /api/books/upload
        if parts == ["api", "books", "upload"]:
            return self._api_upload_book()

        # /api/books/<id>/<action>
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "books":
            book_id = parts[2]
            action = parts[3]
            if action == "progress":
                return self._api_save_progress(book_id)
            if action == "meta":
                return self._api_save_meta(book_id)
            if action == "notes":
                return self._api_notes(book_id)
            if action == "category":
                return self._api_set_category(book_id)

        # /api/categories
        if parts == ["api", "categories"]:
            return self._api_create_category()

        # /api/ai/config
        if parts == ["api", "ai", "config"]:
            return self._api_save_ai_config()

        # /api/ai/chat
        if parts == ["api", "ai", "chat"]:
            return self._api_ai_chat()

        if len(parts) == 2 and parts[0] == "api" and parts[1] == "library":
            return self._api_save_library()

        self._json(404, {"error": "unknown endpoint"})

    # ---- DELETE ----
    def do_DELETE(self):
        parts = [p for p in urllib.parse.urlparse(self.path).path.split("/") if p != ""]

        # /api/books/<id>
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "books":
            return self._api_delete_book(parts[2])

        # /api/categories/<name>
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "categories":
            return self._api_delete_category(urllib.parse.unquote(parts[2]))

        self._json(404, {"error": "unknown endpoint"})

    # ---- 静态文件 ----
    def _serve_static_file(self, rel, original_path):
        rel = rel.replace("\\", "/").lstrip("/")
        full = os.path.join(STATIC_DIR, rel)
        full = os.path.abspath(full)
        if not full.startswith(os.path.abspath(STATIC_DIR) + os.sep) and full != os.path.abspath(STATIC_DIR):
            return self._send(403, b"forbidden", "text/plain; charset=utf-8")
        if not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif full.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif full.endswith(".mjs"):
            ctype = "application/javascript; charset=utf-8"
        return self._stream_file(full, ctype)

    def _stream_file(self, full, ctype):
        size = os.path.getsize(full)
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        partial = False
        if range_header and range_header.startswith("bytes="):
            try:
                r = range_header[6:].split("-")
                start = int(r[0]) if r[0] else 0
                end = int(r[1]) if len(r[1]) and r[1] else size - 1
                if end >= size:
                    end = size - 1
                partial = True
            except ValueError:
                pass
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(full, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    # ---- API GET ----
    def _api_get(self, parts, parsed):
        # /api/books
        if parts == ["api", "books"]:
            books = scan_books()
            lib = load_library().get("books", {})
            for b in books:
                meta = lib.get(b["id"], {})
                b["title"] = meta.get("title") or os.path.splitext(b["name"])[0]
                b["author"] = meta.get("author", "")
                b["progress"] = meta.get("progress", 0)
                b["lastRead"] = meta.get("lastRead", 0)
                b["hasCover"] = bool(meta.get("cover"))
                b["category"] = meta.get("category", "")
            return self._json(200, {"books": books})

        # /api/library
        if parts == ["api", "library"]:
            return self._json(200, load_library())

        # /api/categories
        if parts == ["api", "categories"]:
            cats = get_all_categories()
            lib = load_library().get("books", {})
            counts = {}
            for meta in lib.values():
                c = meta.get("category", "")
                if c:
                    counts[c] = counts.get(c, 0) + 1
            result = [{"name": c, "count": counts.get(c, 0)} for c in cats]
            return self._json(200, {"categories": result})

        # /api/ai/config
        if parts == ["api", "ai", "config"]:
            cfg = load_ai_config()
            # 脱敏
            safe = {
                "endpoint": cfg.get("endpoint", ""),
                "model": cfg.get("model", ""),
                "has_key": bool(cfg.get("api_key")),
            }
            return self._json(200, safe)

        # /api/books/<id>/file
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "books" and parts[3] == "file":
            full = book_path(parts[2])
            if not full:
                return self._json(404, {"error": "book not found"})
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if full.lower().endswith(".epub"):
                ctype = "application/epub+zip"
            elif full.lower().endswith(".pdf"):
                ctype = "application/pdf"
            return self._stream_file(full, ctype)

        # /api/books/<id>/progress
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "books" and parts[3] == "progress":
            lib = load_library().get("books", {})
            meta = lib.get(parts[2], {})
            return self._json(200, {
                "progress": meta.get("progress", 0),
                "cfi": meta.get("cfi"),
                "page": meta.get("page", 0),
                "total": meta.get("total", 0),
            })

        # /api/books/<id>/notes
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "books" and parts[3] == "notes":
            lib = load_library().get("books", {})
            meta = lib.get(parts[2], {})
            notes = meta.get("notes", [])
            notes.sort(key=lambda n: n.get("createdAt", 0))
            return self._json(200, {"notes": notes})

        return self._json(404, {"error": "unknown endpoint"})

    # ---- 分类 API ----
    def _api_create_category(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        name = payload.get("name", "").strip()
        old_name = payload.get("old_name", "").strip()
        if not name:
            return self._json(400, {"error": "name required"})
        lib = load_library()
        cats = lib.setdefault("categories", [])
        if old_name:
            # 重命名
            if old_name in cats:
                cats.remove(old_name)
            if name not in cats:
                cats.append(name)
            for meta in lib.get("books", {}).values():
                if meta.get("category") == old_name:
                    meta["category"] = name
        else:
            if name not in cats:
                cats.append(name)
        save_library(lib)
        self._json(200, {"ok": True})

    def _api_delete_category(self, name):
        lib = load_library()
        cats = lib.get("categories", [])
        if name in cats:
            cats.remove(name)
        # 清除书籍的分类引用
        for meta in lib.get("books", {}).values():
            if meta.get("category") == name:
                meta["category"] = ""
        save_library(lib)
        self._json(200, {"ok": True})

    def _api_set_category(self, book_id):
        if not book_path(book_id):
            return self._json(404, {"error": "book not found"})
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        cat = payload.get("category", "").strip()
        lib = load_library()
        meta = lib.setdefault("books", {}).setdefault(book_id, {})
        meta["category"] = cat
        cats = lib.setdefault("categories", [])
        if cat and cat not in cats:
            cats.append(cat)
        save_library(lib)
        self._json(200, {"ok": True})

    # ---- 书籍删除 ----
    def _api_delete_book(self, book_id):
        full = book_path(book_id)
        if not full:
            return self._json(404, {"error": "book not found"})
        lib = load_library()
        title = lib.get("books", {}).get(book_id, {}).get("title", book_id)
        try:
            os.remove(full)
        except Exception as e:
            return self._json(500, {"error": str(e)})
        lib.get("books", {}).pop(book_id, None)
        save_library(lib)
        self._json(200, {"ok": True, "title": title})

    # ---- 书籍上传 ----
    def _api_upload_book(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._json(400, {"error": "expected multipart/form-data"})
        body = self._read_body()
        # 解析 multipart
        boundary = None
        for part in ctype.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
                break
        if not boundary:
            return self._json(400, {"error": "no boundary"})
        boundary_bytes = ("--" + boundary).encode()
        sections = body.split(boundary_bytes)
        saved = []
        for section in sections:
            if not section or section == b"--\r\n" or section == b"--":
                continue
            # 去掉 \r\n 前缀
            section = section.strip(b"\r\n")
            if not section:
                continue
            header_end = section.find(b"\r\n\r\n")
            if header_end < 0:
                continue
            header_str = section[:header_end].decode("utf-8", errors="replace")
            file_data = section[header_end + 4:]
            # 去掉结尾 \r\n
            if file_data.endswith(b"\r\n"):
                file_data = file_data[:-2]
            # 提取文件名
            fname = None
            for line in header_str.split("\r\n"):
                m = re.search(r'filename="(.+?)"', line)
                if m:
                    fname = m.group(1)
                    break
            if not fname:
                continue
            fname = os.path.basename(fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXT:
                continue
            dest = os.path.join(BOOKS_DIR, fname)
            # 避免覆盖
            if os.path.exists(dest):
                base, e = os.path.splitext(fname)
                fname = f"{base}_{int(time.time())}{e}"
                dest = os.path.join(BOOKS_DIR, fname)
            with open(dest, "wb") as f:
                f.write(file_data)
            saved.append(fname)
        self._json(200, {"ok": True, "saved": saved})

    # ---- AI 配置 ----
    def _api_save_ai_config(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        cfg = load_ai_config()
        if "api_key" in payload:
            cfg["api_key"] = payload["api_key"]
        if "endpoint" in payload:
            cfg["endpoint"] = payload["endpoint"]
        if "model" in payload:
            cfg["model"] = payload["model"]
        save_ai_config(cfg)
        self._json(200, {"ok": True})

    # ---- AI 对话 (流式 SSE) ----
    def _api_ai_chat(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})

        config = load_ai_config()
        if not config.get("api_key"):
            return self._json(400, {"error": "请先在设置中配置 AI API Key"})

        messages = payload.get("messages", [])
        if not messages:
            return self._json(400, {"error": "messages required"})

        # 注入系统提示
        sys_msg = {"role": "system", "content": AI_SYSTEM_PROMPT}
        messages = [sys_msg] + messages

        # 第一轮：带工具调用
        first_response = call_llm_api(config, messages, AI_TOOLS)
        if "error" in first_response:
            return self._json(500, {"error": first_response["error"]})

        choice = first_response.get("choices", [{}])[0]
        msg = choice.get("message", {})

        # 如果有工具调用，执行并继续对话
        max_rounds = 5
        while msg.get("tool_calls") and max_rounds > 0:
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = json.loads(tc["function"]["args"]) if tc["function"].get("args") else {}
                tool_result = execute_ai_tool(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })
            max_rounds -= 1
            # 继续调用 (不带流式, 直到没有更多工具调用)
            first_response = call_llm_api(config, messages, AI_TOOLS)
            if "error" in first_response:
                break
            choice = first_response.get("choices", [{}])[0]
            msg = choice.get("message", {})

        # 最终回复：流式输出
        final_content = msg.get("content", "")
        if final_content:
            # 检查是否有动作指令
            actions = []
            clean_content = final_content
            if "__ACTION__:" in final_content:
                for m in re.finditer(r'__ACTION__:open_book:(.+?)(?:\n|$)', final_content):
                    actions.append({"type": "open_book", "book_id": m.group(1).strip()})
                clean_content = re.sub(r'__ACTION__:open_book:.+?(?:\n|$)', '', final_content).strip()

            # SSE 流式输出
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            # 逐字发送
            chunk_size = 4
            for i in range(0, len(clean_content), chunk_size):
                chunk = clean_content[i:i + chunk_size]
                data = json.dumps({"content": chunk}, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()

            # 发送动作
            if actions:
                data = json.dumps({"actions": actions}, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()

            # 结束标记
            self.wfile.write(b"data: {\"done\": true}\n\n")
            self.wfile.flush()
        else:
            self._json(200, {"content": "", "error": "AI未返回内容"})

    # ---- 原有 API ----
    def _api_save_progress(self, book_id):
        if not book_path(book_id):
            return self._json(404, {"error": "book not found"})
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        lib = load_library()
        meta = lib.setdefault("books", {}).setdefault(book_id, {})
        meta["progress"] = float(payload.get("progress", 0))
        if payload.get("cfi") is not None:
            meta["cfi"] = payload["cfi"]
        if payload.get("page") is not None:
            meta["page"] = int(payload["page"])
        if payload.get("total") is not None:
            meta["total"] = int(payload["total"])
        meta["lastRead"] = int(time.time())
        save_library(lib)
        self._json(200, {"ok": True})

    def _api_save_meta(self, book_id):
        if not book_path(book_id):
            return self._json(404, {"error": "book not found"})
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        lib = load_library()
        meta = lib.setdefault("books", {}).setdefault(book_id, {})
        for k in ("title", "author", "cover", "category"):
            if k in payload:
                meta[k] = payload[k]
        save_library(lib)
        self._json(200, {"ok": True})

    def _api_save_library(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        save_library(payload)
        self._json(200, {"ok": True})

    def _api_notes(self, book_id):
        if not book_path(book_id):
            return self._json(404, {"error": "book not found"})
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        lib = load_library()
        meta = lib.setdefault("books", {}).setdefault(book_id, {})
        notes = meta.setdefault("notes", [])
        now = int(time.time())
        op = payload.get("op", "save")
        if op == "delete":
            note_id = payload.get("id")
            meta["notes"] = [n for n in notes if n.get("id") != note_id]
        else:
            note_id = payload.get("id") or f"note-{now}-{id(payload) & 0xffff}"
            existing = None
            for n in notes:
                if n.get("id") == note_id:
                    existing = n
                    break
            if existing:
                existing["content"] = payload.get("content", existing.get("content", ""))
                existing["page"] = payload.get("page", existing.get("page", 0))
                existing["progress"] = payload.get("progress", existing.get("progress", 0))
                existing["updatedAt"] = now
            else:
                notes.append({
                    "id": note_id, "content": payload.get("content", ""),
                    "page": payload.get("page", 0), "progress": payload.get("progress", 0),
                    "createdAt": now, "updatedAt": now,
                })
        meta["notes"].sort(key=lambda n: n.get("createdAt", 0))
        save_library(lib)
        self._json(200, {"ok": True, "notes": meta.get("notes", [])})

    def log_message(self, *args):
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    port = 8769
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    srv = Server(("0.0.0.0", port), Handler)
    print(f"书架阅读器已启动:  http://localhost:{port}")
    print(f"书籍目录: {BOOKS_DIR}")
    print("按 Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()


if __name__ == "__main__":
    main()
