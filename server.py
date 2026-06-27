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
  DELETE /api/books/<id>       -> 删除书籍 (软删除, 移入回收站)
  POST /api/books/upload       -> 上传书籍 (multipart/form-data)
  GET  /api/categories         -> 获取所有分类及书籍数
  POST /api/categories         -> 新建/重命名分类
  DELETE /api/categories/<name>-> 删除分类
  GET  /api/trash              -> 回收站列表 (自动清理 >30天 项)
  POST /api/trash/restore      -> 恢复书籍 {book_id}
  POST /api/trash/empty        -> 清空回收站过期项 (>30天)
  DELETE /api/trash/<book_id>  -> 永久删除回收站书籍 (删文件)
  GET  /api/ai/config          -> 获取AI配置 (key脱敏)
  POST /api/ai/config          -> 保存AI配置
  POST /api/ai/chat            -> AI Agent 对话 (流式SSE)
  GET  /api/ai/memory          -> 获取 Agent 长期记忆
  POST /api/ai/memory          -> 新增记忆事实
  DELETE /api/ai/memory/<id>   -> 删除记忆事实

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
MEMORY_FILE = os.path.join(DATA_DIR, "agent_memory.json")

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
    # 恢复到 books
    books = lib.setdefault("books", {})
    books[book_id] = {
        "progress": 0,
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
#  Agent 架构: MemoryManager / ToolRegistry / AgentLoopController /
#               ContextBuilder / 工具定义 / LLM 调用
# --------------------------------------------------------------------------- #

# ---- 标准化工具结果 ----
def make_tool_result(ok, data=None, error="", retryable=False):
    """构造统一的 ToolResult: {ok, data, error, retryable}"""
    return {"ok": bool(ok), "data": data, "error": error, "retryable": bool(retryable)}


# ---- 0. TokenEstimator ----
class TokenEstimator:
    """粗略估算 token 数 (中文≈1.5字/token, 英文≈4字/token)"""

    @staticmethod
    def estimate(text):
        if not text:
            return 0
        text = str(text)
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars / 4)

    @staticmethod
    def estimate_messages(messages):
        total = 0
        for m in messages:
            total += TokenEstimator.estimate(m.get("content", ""))
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    total += TokenEstimator.estimate(json.dumps(tc, ensure_ascii=False))
        return total


# ---- 0b. ContextCompressor ----
class ContextCompressor:
    """上下文压缩: 当消息历史超 token 预算时, 调 LLM 生成结构化摘要替换旧消息

    压缩原则: 压缩后的信息必须保证 Agent 能无缝继续下一阶段工作。
    即: 保留用户意图、已完成操作及关键结果、未完成任务、工具调用参数与返回数据。
    """

    TOKEN_BUDGET = 12000       # 总 token 预算 (留给模型回复空间)
    SUMMARY_THRESHOLD = 8000  # 超过此值触发压缩
    KEEP_RECENT = 6            # 压缩时保留最近 N 条消息 (不截断)
    TOOL_RESULT_KEEP = 800     # 工具返回结果在摘要请求中的保留长度 (字符)

    def __init__(self, config):
        self.config = config

    def should_compress(self, messages):
        """检查是否需要压缩"""
        return TokenEstimator.estimate_messages(messages) > self.SUMMARY_THRESHOLD

    def compress(self, messages):
        """压缩消息历史: 保留 system + 最近 N 条, 中间部分生成结构化摘要

        摘要包含:
        1. 用户核心意图
        2. 已调用工具及其参数
        3. 工具返回的关键数据 (不截断重要结果)
        4. Agent 已得出的结论
        5. 未完成的任务 / 下一步计划
        """
        if not self.should_compress(messages):
            return messages

        # 分离 system 消息和工具调用链
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if len(non_system) <= self.KEEP_RECENT:
            return messages

        # 智能选择保留边界: 不在 tool_calls → tool 的中间截断
        split_idx = len(non_system) - self.KEEP_RECENT
        # 向前调整, 确保不切断 tool_calls→tool 配对
        while split_idx > 0:
            msg = non_system[split_idx]
            role = msg.get("role", "")
            if role == "tool":
                # 检查前一条是否有对应的 tool_calls
                prev = non_system[split_idx - 1] if split_idx > 0 else None
                if prev and prev.get("tool_calls"):
                    split_idx -= 2
                    continue
            break
        to_compress = non_system[:split_idx]
        keep_recent = non_system[split_idx:]

        if not to_compress:
            return messages

        # 构建摘要请求
        summary_prompt = self._build_summary_prompt(to_compress)
        summary = self._generate_summary(summary_prompt)

        if summary:
            summary_msg = {
                "role": "system",
                "content": "[对话摘要 - 压缩自 {} 条历史消息]\n{}".format(
                    len(to_compress), summary),
            }
            return system_msgs + [summary_msg] + keep_recent
        else:
            # 摘要失败, 降级为简单裁剪 + 关键信息提取
            key_info = self._extract_key_info(to_compress)
            note = {"role": "system",
                    "content": "[历史已裁剪] 之前 {} 条消息已省略。\n{}".format(
                        len(to_compress), key_info)}
            return system_msgs + [note] + keep_recent

    def _build_summary_prompt(self, messages):
        """构建摘要请求: 要求 LLM 生成结构化摘要, 保留 Agent 继续工作所需的信息"""
        lines = []
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")

            if role == "tool":
                # 工具返回结果: 尝试解析 JSON, 提取关键数据
                tool_content = self._summarize_tool_result(content)
                lines.append("[工具返回] {}".format(tool_content))

            elif m.get("tool_calls"):
                # 工具调用: 保留工具名和参数
                parts = []
                for tc in m["tool_calls"]:
                    fn_name = tc.get("function", {}).get("name", "")
                    fn_args = tc.get("function", {}).get("arguments", "")
                    parts.append("{}({})".format(fn_name, fn_args))
                lines.append("[Agent调用工具] {}".format(" | ".join(parts)))

            elif role == "user":
                lines.append("用户: {}".format(content))

            elif role == "assistant":
                lines.append("Agent: {}".format(content))

            else:
                lines.append("{}: {}".format(role, content))

        return (
            "你需要将以下对话历史压缩为结构化摘要, 要求:\n"
            "1. 保留用户的原始意图和请求\n"
            "2. 列出已调用的工具名及其参数\n"
            "3. 保留工具返回的关键数据 (如书籍列表、笔记内容、分类等)\n"
            "4. 记录 Agent 已得出的结论或已完成的操作\n"
            "5. 如果有未完成的任务, 明确写出下一步该做什么\n"
            "6. 摘要长度控制在 400 字以内\n\n"
            "对话历史:\n" + "\n".join(lines))

    def _summarize_tool_result(self, content):
        """提取工具返回结果中的关键数据, 避免截断丢失信息"""
        try:
            result = json.loads(content)
            if result.get("ok"):
                data = result.get("data", {})
                # 书籍列表: 保留标题和 ID
                if "books" in data:
                    books = data["books"]
                    items = ["《{}》({})".format(
                        b.get("title", b.get("id", "")), b.get("id", ""))
                        for b in books[:20]]
                    return "找到 {} 本书: {}".format(
                        data.get("count", len(books)),
                        "; ".join(items) + ("..." if len(books) > 20 else ""))
                # 书籍内容: 保留前 500 字
                if "content" in data:
                    return "书籍文本(前500字): {}".format(data["content"][:500])
                # 分类列表
                if "categories" in data:
                    cats = data["categories"]
                    return "分类: {}".format(
                        "; ".join("{}({}本)".format(c["name"], c["count"]) for c in cats))
                # 其他数据: 保留 JSON
                return json.dumps(data, ensure_ascii=False)[:600]
            else:
                return "失败: {}".format(result.get("error", "未知错误"))
        except (json.JSONDecodeError, TypeError):
            return content[:600] if content else "(空)"

    def _extract_key_info(self, messages):
        """降级方案: 摘要失败时, 从消息中提取关键信息 (不调 LLM)"""
        user_msgs = []
        tool_calls = []
        for m in messages:
            if m.get("role") == "user" and m.get("content"):
                user_msgs.append(m["content"][:200])
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    tool_calls.append("{}({})".format(
                        tc.get("function", {}).get("name", ""),
                        tc.get("function", {}).get("arguments", "")[:100]))
        parts = []
        if user_msgs:
            parts.append("用户请求: " + " | ".join(user_msgs[:3]))
        if tool_calls:
            parts.append("已调用工具: " + " | ".join(tool_calls[:5]))
        return "\n".join(parts) if parts else "(无关键信息)"

    def _generate_summary(self, prompt):
        """调用 LLM 生成摘要"""
        try:
            resp = call_llm_api(self.config, [{"role": "user", "content": prompt}])
            if "error" not in resp:
                return resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception:
            pass
        return None


# ---- 1. MemoryManager ----
class MemoryManager:
    """长期记忆 (data/agent_memory.json) + 短期记忆 (按会话 in-memory) + 会话摘要 (持久化)"""

    _DEFAULT = {
        "profile": {"language": "zh"},
        "preferences": {"summaryStyle": "detailed", "outputLanguage": "zh"},
        "readingHabits": {"favoriteTopics": [], "frequentlyReadBooks": []},
        "stableFacts": [],  # [{id, content, type, confidence, source, createdAt, updatedAt}]
        "sessionSummaries": {},  # {session_id: summary_string} 持久化
    }

    SHORT_TERM_MAX = 20   # 单个会话最大短时消息数
    SHORT_TERM_KEEP = 12  # 超限时保留最近的消息条数

    def __init__(self):
        self._memory = {}
        self._short_term = {}  # session_id -> [messages]
        self._config = None    # 由外部 set_config 注入, 供 ContextCompressor 使用
        self.load_memory()

    def set_config(self, config):
        """注入 AI 配置, 使 _summarize_old 能调用 LLM 生成摘要"""
        self._config = config

    # ---- 长期记忆 ----
    def load_memory(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    self._memory = json.load(f)
            except Exception:
                self._memory = json.loads(json.dumps(self._DEFAULT))
        else:
            self._memory = json.loads(json.dumps(self._DEFAULT))
        # 补全缺失的字段
        for k, v in self._DEFAULT.items():
            if k not in self._memory:
                self._memory[k] = json.loads(json.dumps(v))
        return self._memory

    def save_memory(self):
        tmp = MEMORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._memory, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MEMORY_FILE)

    def add_fact(self, content, type="fact", confidence=0.8, source="user"):
        now = int(time.time())
        fact = {
            "id": "fact-{}-{}".format(now, id(content) & 0xffff),
            "content": content,
            "type": type,
            "confidence": float(confidence),
            "source": source,
            "createdAt": now,
            "updatedAt": now,
        }
        self._memory.setdefault("stableFacts", []).append(fact)
        self.save_memory()
        return fact

    def remove_fact(self, fact_id):
        facts = self._memory.get("stableFacts", [])
        before = len(facts)
        self._memory["stableFacts"] = [f for f in facts if f.get("id") != fact_id]
        if len(self._memory["stableFacts"]) != before:
            self.save_memory()
            return True
        return False

    def get_relevant_memory(self, query):
        """简单的关键词匹配: 检索与 query 相关的长期事实"""
        query_lower = (query or "").lower()
        keywords = [w for w in re.split(r'[\s,，。.!！?？、；;:：()（）]+', query_lower) if w]
        facts = self._memory.get("stableFacts", [])
        relevant = []
        for fact in facts:
            content_lower = fact.get("content", "").lower()
            if any(kw in content_lower for kw in keywords):
                relevant.append(fact)
        # 若无关键词匹配, 返回全部 (帮助 Agent 在无明确线索时仍可见记忆概貌)
        if not relevant and keywords:
            relevant = list(facts)
        return relevant

    # ---- 会话摘要 (持久化到 agent_memory.json) ----
    def get_session_summary(self, session_id):
        summaries = self._memory.get("sessionSummaries", {})
        return summaries.get(session_id, "")

    def set_session_summary(self, session_id, summary):
        summaries = self._memory.setdefault("sessionSummaries", {})
        summaries[session_id] = summary
        self.save_memory()

    # ---- 短期记忆 ----
    def get_short_term(self, session_id):
        return self._short_term.get(session_id, [])

    def add_short_term(self, session_id, message):
        msgs = self._short_term.setdefault(session_id, [])
        msgs.append(message)
        if len(msgs) > self.SHORT_TERM_MAX:
            self._summarize_old(session_id)

    def _summarize_old(self, session_id):
        """超出上限时通过 ContextCompressor 生成摘要压缩较早的消息 (保留 system + 最近 N 条)"""
        msgs = self._short_term.get(session_id, [])
        if len(msgs) <= self.SHORT_TERM_MAX:
            return
        # 优先使用 LLM 摘要 (需注入 config)
        if self._config:
            try:
                compressor = ContextCompressor(self._config)
                system_msgs = [m for m in msgs if m.get("role") == "system"]
                non_system = [m for m in msgs if m.get("role") != "system"]
                if len(non_system) > self.SHORT_TERM_KEEP:
                    to_compress = non_system[:-self.SHORT_TERM_KEEP]
                    keep_recent = non_system[-self.SHORT_TERM_KEEP:]
                    prompt = compressor._build_summary_prompt(to_compress)
                    summary = compressor._generate_summary(prompt)
                    if summary:
                        summary_msg = {
                            "role": "system",
                            "content": "[对话摘要] 以下是之前对话的要点:\n" + summary,
                        }
                        self._short_term[session_id] = system_msgs + [summary_msg] + keep_recent
                        return
            except Exception:
                pass
        # 降级: 简单裁剪 (保留首条 + 最近 N 条)
        first = msgs[0] if msgs else None
        recent = msgs[-self.SHORT_TERM_KEEP:]
        dropped = len(msgs) - self.SHORT_TERM_KEEP - (1 if first else 0)
        summary = {
            "role": "system",
            "content": "[历史对话已压缩] 之前 {} 条消息已被省略, 请基于最近的上下文继续。".format(max(dropped, 0)),
        }
        new_list = ([first, summary] if first else [summary]) + recent
        self._short_term[session_id] = new_list

    def trim_short_term(self, messages):
        """对纯文本消息列表做安全裁剪 (不破坏 tool_calls 结构)"""
        if len(messages) <= self.SHORT_TERM_MAX:
            return messages
        first = messages[0]
        rest = messages[1:]
        if len(rest) <= self.SHORT_TERM_KEEP:
            return messages
        dropped = len(rest) - self.SHORT_TERM_KEEP
        note = {"role": "system",
                "content": "[历史对话已压缩] 之前 {} 条消息已省略。".format(dropped)}
        return [first, note] + rest[-self.SHORT_TERM_KEEP:]


# 全局 MemoryManager 实例
MEMORY = MemoryManager()


# ---- 2. ToolRegistry ----
class ToolRegistry:
    """工具注册表: 每个 tool 返回统一 ToolResult"""

    def __init__(self):
        self._tools = {}  # name -> {"handler": fn, "schema": dict}

    def register(self, name, handler, schema):
        self._tools[name] = {"handler": handler, "schema": schema}

    def get_schemas(self):
        """返回 OpenAI function-calling 格式的工具列表"""
        return [self._tools[n]["schema"] for n in self._tools]

    def has(self, name):
        return name in self._tools

    def execute(self, name, args, context=None):
        if not self.has(name):
            return make_tool_result(False, error="未知工具: {}".format(name), retryable=False)
        handler = self._tools[name]["handler"]
        try:
            return handler(args, context)
        except Exception as e:
            return make_tool_result(False, error="工具执行出错: {}".format(e), retryable=True)


# ---- 3. AgentLoopController ----
class AgentLoopController:
    """Agent 循环控制: 步数 / 重复 / 失败 / 超时 限制 + 步骤日志"""

    MAX_STEPS = 8            # 最大思考步数 (从 6 提升至 8)
    MAX_SAME_TOOL_CALLS = 2
    MAX_FAILURES = 2
    TIMEOUT_PER_STEP = 30   # 单步超时 (秒)
    MAX_TOTAL_TIME = 120    # Agent 总执行超时 (秒)

    def __init__(self):
        self.step = 0
        self.failures = 0
        self.call_history = []  # [(name, args_key)]
        self.start_time = time.time()
        self.step_start = self.start_time
        self._log = []  # [{"step", "tool", "ok", "duration"}]

    def check_duplicate(self, name, args):
        """返回 (是否重复, 已调用次数)"""
        args_key = json.dumps(args, sort_keys=True, ensure_ascii=False)
        count = sum(1 for (n, a) in self.call_history if n == name and a == args_key)
        return count >= self.MAX_SAME_TOOL_CALLS, count

    def record_call(self, name, args):
        args_key = json.dumps(args, sort_keys=True, ensure_ascii=False)
        self.call_history.append((name, args_key))

    def record_failure(self):
        self.failures += 1

    def begin_step(self):
        """标记新一步开始, 重置单步计时"""
        self.step_start = time.time()

    def should_stop(self):
        if self.step >= self.MAX_STEPS:
            return True, "已达到最大思考步数({}步)限制。请基于已获取的信息, 直接回答用户的问题, 不要再调用工具。".format(self.MAX_STEPS)
        if self.failures >= self.MAX_FAILURES:
            return True, "工具调用连续失败次数达到上限({}次)。请基于已获取的信息, 直接回答用户的问题。".format(self.MAX_FAILURES)
        elapsed = time.time() - self.start_time
        if elapsed > self.MAX_TOTAL_TIME:
            return True, "Agent 执行总时长已超过 {} 秒上限。请基于已获取的信息, 直接回答用户的问题。".format(self.MAX_TOTAL_TIME)
        if self.step > 0:
            step_elapsed = time.time() - self.step_start
            if step_elapsed > self.TIMEOUT_PER_STEP:
                return True, "当前步骤执行超时({}秒)。请基于已获取的信息, 直接回答用户的问题。".format(self.TIMEOUT_PER_STEP)
        return False, ""

    def log_step(self, step, tool_name, result_ok):
        """记录执行日志 (便于调试)"""
        self._log.append({
            "step": step,
            "tool": tool_name,
            "ok": bool(result_ok),
            "duration": round(time.time() - self.step_start, 2),
        })

    def get_log(self):
        """返回执行日志"""
        return list(self._log)


# ---- 4. ContextBuilder ----
class ContextBuilder:
    """组装上下文: 系统提示 + 长期记忆 + 会话摘要 + 当前书籍上下文 + 短期历史 (按需压缩)"""

    def __init__(self, memory_manager, config=None):
        self.memory = memory_manager
        self.config = config
        self.compressor = ContextCompressor(config) if config else None

    def build(self, messages, context, session_id="default"):
        parts = [AI_SYSTEM_PROMPT]

        mem = self.memory.load_memory()
        # 用户偏好
        prefs = mem.get("preferences", {})
        if prefs:
            parts.append("\n\n[用户偏好]\n" + json.dumps(prefs, ensure_ascii=False, indent=2))
        # 阅读习惯
        habits = mem.get("readingHabits", {})
        if habits and (habits.get("favoriteTopics") or habits.get("frequentlyReadBooks")):
            parts.append("\n\n[阅读习惯]\n" + json.dumps(habits, ensure_ascii=False, indent=2))
        # 长期事实
        facts = mem.get("stableFacts", [])
        if facts:
            fact_lines = ["- {}".format(f.get("content", "")) for f in facts]
            parts.append("\n\n[长期记忆 - 已知事实]\n" + "\n".join(fact_lines))

        # 会话摘要 (来自之前对话, 持久化)
        session_summary = self.memory.get_session_summary(session_id)
        if session_summary:
            parts.append("\n\n[本会话历史摘要]\n" + session_summary)

        # 当前阅读上下文
        book_ctx = self._build_book_context(context)
        if book_ctx:
            parts.append("\n\n[当前阅读上下文]\n" + book_ctx)

        system_content = "".join(parts)
        built = [{"role": "system", "content": system_content}] + messages

        # 按需压缩 (token 预算超出时调 LLM 生成摘要)
        if self.compressor and self.compressor.should_compress(built):
            built = self.compressor.compress(built)

        return built

    def _build_book_context(self, context):
        if not context:
            return ""
        book_id = context.get("currentBookId")
        if not book_id:
            return "当前未打开任何书籍。"
        if not book_path(book_id):
            return "当前书籍 ID: {} (文件不存在于书架)。".format(book_id)
        lib = load_library().get("books", {})
        meta = lib.get(book_id, {})
        title = meta.get("title") or os.path.splitext(book_id)[0]
        author = meta.get("author", "")
        cat = meta.get("category", "未分类")
        progress = meta.get("progress", 0)
        page = context.get("currentPage") or meta.get("page", 0)
        lines = [
            "当前书籍: 《{}》{}".format(title, " - " + author if author else ""),
            "书籍ID: {}".format(book_id),
            "分类: {}".format(cat),
            "阅读进度: {:.0f}%".format(progress * 100),
            "当前页码: {}".format(page),
        ]
        return "\n".join(lines)


# ---- 系统提示 ----
AI_SYSTEM_PROMPT = """你是「阅微」, 一个本地电子书书架的智能 AI 助手, 基于 Agent 架构运行。你可以通过调用工具来完成用户的请求。

## 你的能力 (可用工具)
1. list_books - 列出书架上的所有书籍 (含书名/作者/格式/分类/进度)
2. find_books - 按关键词搜索书籍
3. get_book_content - 获取一本书的文本内容, 用于总结或分析
4. get_book_metadata - 获取书籍元数据 (标题/作者/分类/进度)
5. categorize_book - 为书籍设置分类
6. list_categories - 列出所有已创建的分类
7. rename_category - 重命名分类 (该分类下所有书籍同步更新)
8. delete_category - 删除分类 (书籍归入未分类)
9. delete_book - 删除一本书 (删除文件)
10. open_book - 在阅读器中打开一本书 (前端会执行打开操作)
11. create_note - 为一本书创建笔记
12. remember_preference - 将用户偏好或重要事实保存到长期记忆
13. recall_memory - 从长期记忆中检索与查询相关的记忆
14. get_reading_context - 获取用户当前正在阅读的书籍上下文

## 行为规则
- 用简洁友好的中文回答。
- 当用户要求总结一本书时, 先调用 get_book_content 获取内容, 再进行总结。
- 当用户要打开书或删除书时, 调用相应工具; 前端会根据返回的 __ACTION__ 指令执行操作。
- 如果用户提到偏好或重要信息, 主动调用 remember_preference 保存到长期记忆。
- 回答问题前可先调用 recall_memory 检索是否有相关记忆, 也可调用 get_reading_context 了解用户当前正在读什么。
- 不要用相同参数重复调用同一个工具, 请直接使用之前返回的结果。
- 工具调用失败时不要无限重试, 基于已有信息回答即可。
- 每个工具返回统一结构 {ok, data, error, retryable}; ok 为 false 时表示失败。
- 当操作需要在浏览器执行时 (如打开书籍), 工具会返回 __ACTION__ 指令, 你也可以在最终回答中包含它。

## 记忆机制
- 你拥有长期记忆, 可以记住用户的偏好、阅读习惯和重要事实。
- 主动使用 remember_preference 保存用户告诉你的偏好或事实。
- 回答时可参考 recall_memory 检索到的相关记忆, 以及上下文中注入的长期记忆摘要。"""


# ---- 工具执行函数 (每个返回 ToolResult) ----
def _tool_list_books(args, context):
    books = scan_books()
    lib = load_library()
    trash = lib.get("trash", {})
    meta_lib = lib.get("books", {})
    data = []
    for b in books:
        # 排除回收站中的书籍
        if b["id"] in trash:
            continue
        meta = meta_lib.get(b["id"], {})
        title = meta.get("title") or os.path.splitext(b["name"])[0]
        data.append({
            "id": b["id"],
            "title": title,
            "author": meta.get("author", ""),
            "format": b["format"],
            "category": meta.get("category", "未分类"),
            "progress": meta.get("progress", 0),
        })
    return make_tool_result(True, data={"books": data, "count": len(data)})


def _tool_find_books(args, context):
    q = (args.get("query", "") or "").lower()
    books = scan_books()
    lib = load_library()
    trash = lib.get("trash", {})
    meta_lib = lib.get("books", {})
    data = []
    for b in books:
        # 排除回收站中的书籍
        if b["id"] in trash:
            continue
        meta = meta_lib.get(b["id"], {})
        title = meta.get("title") or os.path.splitext(b["name"])[0]
        author = meta.get("author", "")
        if q in title.lower() or q in author.lower() or q in b["id"].lower():
            data.append({
                "id": b["id"],
                "title": title,
                "author": author,
                "category": meta.get("category", "未分类"),
            })
    return make_tool_result(True, data={"books": data, "count": len(data)})


def _tool_get_book_content(args, context):
    bid = args.get("book_id", "")
    full = book_path(bid)
    if not full:
        return make_tool_result(False, error="找不到这本书: {}".format(bid), retryable=False)
    ext = os.path.splitext(full)[1].lower()
    fmt = SUPPORTED_EXT.get(ext, "")
    text = extract_book_text(full, fmt)
    if not text:
        return make_tool_result(False, error="无法提取 {} 格式书籍的文本内容: {}".format(fmt, bid), retryable=False)
    return make_tool_result(True, data={"content": text, "format": fmt, "bookId": bid})


def _tool_get_book_metadata(args, context):
    bid = args.get("book_id", "")
    if not book_path(bid):
        return make_tool_result(False, error="找不到这本书: {}".format(bid), retryable=False)
    lib = load_library().get("books", {})
    meta = lib.get(bid, {})
    title = meta.get("title") or os.path.splitext(bid)[0]
    return make_tool_result(True, data={
        "bookId": bid,
        "title": title,
        "author": meta.get("author", ""),
        "category": meta.get("category", "未分类"),
        "progress": meta.get("progress", 0),
        "lastRead": meta.get("lastRead", 0),
    })


def _tool_categorize_book(args, context):
    bid = args.get("book_id", "")
    cat = args.get("category", "")
    if not book_path(bid):
        return make_tool_result(False, error="找不到这本书: {}".format(bid), retryable=False)
    lib = load_library()
    meta = lib.setdefault("books", {}).setdefault(bid, {})
    meta["category"] = cat
    cats = lib.setdefault("categories", [])
    if cat and cat not in cats:
        cats.append(cat)
    save_library(lib)
    return make_tool_result(True, data={
        "bookId": bid,
        "category": cat,
        "message": "已将《{}》分类为「{}」".format(meta.get("title", bid), cat),
    })


def _tool_list_categories(args, context):
    cats = get_all_categories()
    lib = load_library().get("books", {})
    counts = {}
    for meta in lib.values():
        c = meta.get("category", "未分类")
        counts[c] = counts.get(c, 0) + 1
    data = [{"name": c, "count": counts.get(c, 0)} for c in cats]
    return make_tool_result(True, data={"categories": data, "count": len(data)})


def _tool_rename_category(args, context):
    old_name = (args.get("old_name", "") or "").strip()
    new_name = (args.get("new_name", "") or "").strip()
    if not old_name or not new_name:
        return make_tool_result(False, error="old_name 和 new_name 都不能为空", retryable=False)
    lib = load_library()
    cats = lib.setdefault("categories", [])
    if old_name not in cats:
        # 也检查书籍中是否有此分类
        has_books = any(m.get("category") == old_name for m in lib.get("books", {}).values())
        if not has_books:
            return make_tool_result(False, error="分类「{}」不存在".format(old_name), retryable=False)
    # 更新分类列表
    if old_name in cats:
        cats.remove(old_name)
    if new_name not in cats:
        cats.append(new_name)
    # 更新所有书籍的分类引用
    affected = 0
    for meta in lib.get("books", {}).values():
        if meta.get("category") == old_name:
            meta["category"] = new_name
            affected += 1
    save_library(lib)
    return make_tool_result(True, data={
        "oldName": old_name, "newName": new_name,
        "affectedBooks": affected,
        "message": "已将分类「{}」重命名为「{}」({}本书受影响)".format(old_name, new_name, affected),
    })


def _tool_delete_category(args, context):
    name = (args.get("name", "") or "").strip()
    if not name:
        return make_tool_result(False, error="分类名称不能为空", retryable=False)
    lib = load_library()
    cats = lib.get("categories", [])
    if name not in cats:
        return make_tool_result(False, error="分类「{}」不存在".format(name), retryable=False)
    cats.remove(name)
    # 该分类下的书籍归入未分类
    affected = 0
    for meta in lib.get("books", {}).values():
        if meta.get("category") == name:
            meta["category"] = ""
            affected += 1
    save_library(lib)
    return make_tool_result(True, data={
        "deletedCategory": name,
        "affectedBooks": affected,
        "message": "已删除分类「{}」, {}本书归入未分类".format(name, affected),
    })


def _tool_delete_book(args, context):
    bid = args.get("book_id", "")
    full = book_path(bid)
    if not full:
        return make_tool_result(False, error="找不到这本书: {}".format(bid), retryable=False)
    lib = load_library()
    meta = lib.get("books", {}).get(bid, {})
    title = meta.get("title", bid)
    # 软删除: 移入回收站, 不删除文件
    trash = lib.setdefault("trash", {})
    trash[bid] = {
        "title": title,
        "deletedAt": int(time.time()),
        "originalCategory": meta.get("category", ""),
        "path": full,
    }
    lib.get("books", {}).pop(bid, None)
    save_library(lib)
    return make_tool_result(True, data={
        "bookId": bid,
        "title": title,
        "message": "已将《{}》移入回收站 (30天后永久删除, 可用 restore_book 恢复)".format(title),
    })


def _tool_list_trash(args, context):
    """列出回收站中的所有书籍"""
    # 访问回收站时自动清理过期项
    expired = clean_expired_trash()
    lib = load_library()
    trash = lib.get("trash", {})
    now = int(time.time())
    data = []
    for bid, info in trash.items():
        deleted_at = info.get("deletedAt", 0)
        age = now - deleted_at
        remain = max(0, TRASH_RETENTION_SECONDS - age)
        # 剩余天数 (向上取整)
        remain_days = (remain + 86399) // 86400
        data.append({
            "bookId": bid,
            "title": info.get("title", bid),
            "deletedAt": deleted_at,
            "originalCategory": info.get("originalCategory", "未分类"),
            "remainDays": remain_days,
        })
    data.sort(key=lambda x: x.get("deletedAt", 0), reverse=True)
    return make_tool_result(True, data={
        "trash": data,
        "count": len(data),
        "expiredRemoved": len(expired),
        "message": "回收站共有 {} 本书".format(len(data)),
    })


def _tool_restore_book(args, context):
    """从回收站恢复一本书到书架"""
    bid = args.get("book_id", "")
    if not bid:
        return make_tool_result(False, error="book_id 不能为空", retryable=False)
    info, err = restore_from_trash(bid)
    if err:
        return make_tool_result(False, error="《{}》不在回收站中".format(bid), retryable=False)
    title = info.get("title", bid)
    return make_tool_result(True, data={
        "bookId": bid,
        "title": title,
        "message": "已从回收站恢复《{}》到书架".format(title),
    })


def _tool_delete_book_permanent(args, context):
    """永久删除回收站中的一本书 (删除文件, 不可恢复)"""
    bid = args.get("book_id", "")
    if not bid:
        return make_tool_result(False, error="book_id 不能为空", retryable=False)
    info, err = permanently_delete_from_trash(bid)
    if err:
        return make_tool_result(False, error="《{}》不在回收站中".format(bid), retryable=False)
    title = info.get("title", bid)
    return make_tool_result(True, data={
        "bookId": bid,
        "title": title,
        "message": "已永久删除《{}》, 文件已被移除".format(title),
    })


def _tool_open_book(args, context):
    bid = args.get("book_id", "")
    if not book_path(bid):
        return make_tool_result(False, error="找不到这本书: {}".format(bid), retryable=False)
    return make_tool_result(True, data={"action": "__ACTION__:open_book:{}".format(bid), "bookId": bid})


def _tool_create_note(args, context):
    bid = args.get("book_id", "")
    content = args.get("content", "")
    if not book_path(bid):
        return make_tool_result(False, error="找不到这本书: {}".format(bid), retryable=False)
    if not content:
        return make_tool_result(False, error="笔记内容不能为空", retryable=False)
    lib = load_library()
    meta = lib.setdefault("books", {}).setdefault(bid, {})
    notes = meta.setdefault("notes", [])
    now = int(time.time())
    note = {
        "id": "note-{}-{}".format(now, id(content) & 0xffff),
        "content": content,
        "page": meta.get("page", 0),
        "progress": meta.get("progress", 0),
        "createdAt": now,
        "updatedAt": now,
    }
    notes.append(note)
    notes.sort(key=lambda n: n.get("createdAt", 0))
    save_library(lib)
    return make_tool_result(True, data={
        "noteId": note["id"],
        "message": "已为《{}》创建笔记".format(meta.get("title", bid)),
    })


def _tool_remember_preference(args, context):
    content = args.get("content", "")
    type_ = args.get("type", "preference")
    confidence = args.get("confidence", 0.8)
    if not content:
        return make_tool_result(False, error="记忆内容不能为空", retryable=False)
    fact = MEMORY.add_fact(content, type_, confidence, source="agent")
    return make_tool_result(True, data={"factId": fact["id"], "message": "已保存到长期记忆"})


def _tool_recall_memory(args, context):
    query = args.get("query", "")
    facts = MEMORY.get_relevant_memory(query)
    prefs = MEMORY.load_memory().get("preferences", {})
    return make_tool_result(True, data={"facts": facts, "preferences": prefs, "count": len(facts)})


def _tool_get_reading_context(args, context):
    if not context:
        return make_tool_result(True, data={"message": "当前没有阅读上下文"})
    bid = context.get("currentBookId")
    if not bid:
        return make_tool_result(True, data={"message": "当前没有打开的书籍"})
    if not book_path(bid):
        return make_tool_result(False, error="当前书籍文件不存在: {}".format(bid), retryable=False)
    lib = load_library().get("books", {})
    meta = lib.get(bid, {})
    title = meta.get("title") or os.path.splitext(bid)[0]
    return make_tool_result(True, data={
        "bookId": bid,
        "title": title,
        "author": meta.get("author", ""),
        "category": meta.get("category", "未分类"),
        "progress": meta.get("progress", 0),
        "currentPage": context.get("currentPage", 0),
        "currentProgress": context.get("currentProgress", 0),
        "currentLabel": context.get("currentLabel", ""),
    })


# ---- 工具定义 (schema + handler) ----
TOOL_DEFS = [
    {
        "name": "list_books",
        "description": "列出书架上的所有书籍, 包括书名、作者、格式、分类和阅读进度",
        "parameters": {"type": "object", "properties": {}},
        "handler": _tool_list_books,
    },
    {
        "name": "find_books",
        "description": "按关键词搜索书籍 (匹配书名、作者或文件名)",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索关键词"}},
            "required": ["query"],
        },
        "handler": _tool_find_books,
    },
    {
        "name": "get_book_content",
        "description": "获取一本书的文本内容, 用于总结或分析",
        "parameters": {
            "type": "object",
            "properties": {"book_id": {"type": "string", "description": "书籍ID (文件名)"}},
            "required": ["book_id"],
        },
        "handler": _tool_get_book_content,
    },
    {
        "name": "get_book_metadata",
        "description": "获取书籍的元数据: 标题、作者、分类、阅读进度",
        "parameters": {
            "type": "object",
            "properties": {"book_id": {"type": "string", "description": "书籍ID"}},
            "required": ["book_id"],
        },
        "handler": _tool_get_book_metadata,
    },
    {
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
        "handler": _tool_categorize_book,
    },
    {
        "name": "list_categories",
        "description": "列出所有已创建的分类及每个分类的书籍数量",
        "parameters": {"type": "object", "properties": {}},
        "handler": _tool_list_categories,
    },
    {
        "name": "rename_category",
        "description": "重命名一个分类, 该分类下所有书籍的分类引用会同步更新",
        "parameters": {
            "type": "object",
            "properties": {
                "old_name": {"type": "string", "description": "当前分类名称"},
                "new_name": {"type": "string", "description": "新的分类名称"},
            },
            "required": ["old_name", "new_name"],
        },
        "handler": _tool_rename_category,
    },
    {
        "name": "delete_category",
        "description": "删除一个分类, 该分类下的书籍将归入未分类",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "要删除的分类名称"}},
            "required": ["name"],
        },
        "handler": _tool_delete_category,
    },
    {
        "name": "delete_book",
        "description": "从书架移除一本书 (移入回收站, 30天后永久删除, 可用 restore_book 恢复)",
        "parameters": {
            "type": "object",
            "properties": {"book_id": {"type": "string", "description": "书籍ID"}},
            "required": ["book_id"],
        },
        "handler": _tool_delete_book,
    },
    {
        "name": "list_trash",
        "description": "列出回收站中的所有书籍 (含删除时间、原分类、剩余保留天数)",
        "parameters": {"type": "object", "properties": {}},
        "handler": _tool_list_trash,
    },
    {
        "name": "restore_book",
        "description": "从回收站恢复一本书到书架 (放回原分类)",
        "parameters": {
            "type": "object",
            "properties": {"book_id": {"type": "string", "description": "回收站中的书籍ID"}},
            "required": ["book_id"],
        },
        "handler": _tool_restore_book,
    },
    {
        "name": "delete_book_permanent",
        "description": "永久删除回收站中的一本书 (删除文件, 不可恢复)",
        "parameters": {
            "type": "object",
            "properties": {"book_id": {"type": "string", "description": "回收站中的书籍ID"}},
            "required": ["book_id"],
        },
        "handler": _tool_delete_book_permanent,
    },
    {
        "name": "open_book",
        "description": "在阅读器中打开一本书 (前端会执行打开操作)",
        "parameters": {
            "type": "object",
            "properties": {"book_id": {"type": "string", "description": "书籍ID"}},
            "required": ["book_id"],
        },
        "handler": _tool_open_book,
    },
    {
        "name": "create_note",
        "description": "为书籍创建一条笔记",
        "parameters": {
            "type": "object",
            "properties": {
                "book_id": {"type": "string", "description": "书籍ID"},
                "content": {"type": "string", "description": "笔记内容"},
            },
            "required": ["book_id", "content"],
        },
        "handler": _tool_create_note,
    },
    {
        "name": "remember_preference",
        "description": "将用户偏好或重要事实保存到长期记忆, 以便以后回忆",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容"},
                "type": {"type": "string", "description": "类型: preference/fact/habit", "default": "preference"},
                "confidence": {"type": "number", "description": "置信度 0-1", "default": 0.8},
            },
            "required": ["content"],
        },
        "handler": _tool_remember_preference,
    },
    {
        "name": "recall_memory",
        "description": "从长期记忆中检索与查询相关的记忆",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "检索关键词"}},
            "required": ["query"],
        },
        "handler": _tool_recall_memory,
    },
    {
        "name": "get_reading_context",
        "description": "获取用户当前正在阅读的书籍上下文 (当前书、页码、进度)",
        "parameters": {"type": "object", "properties": {}},
        "handler": _tool_get_reading_context,
    },
]

# OpenAI function-calling 格式
AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": d["name"],
            "description": d["description"],
            "parameters": d["parameters"],
        },
    }
    for d in TOOL_DEFS
]


def register_default_tools(registry):
    """将所有内置工具注册到 ToolRegistry"""
    for d in TOOL_DEFS:
        schema = {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": d["parameters"],
            },
        }
        registry.register(d["name"], d["handler"], schema)


def extract_actions(text):
    """从文本中提取 __ACTION__:open_book:<id> 动作指令"""
    actions = []
    for m in re.finditer(r'__ACTION__:open_book:([^\s"\'\\]+)', text or ""):
        book_id = m.group(1).strip()
        if book_id:
            actions.append({"type": "open_book", "book_id": book_id})
    return actions


# ---- LLM API 调用 ----
def call_llm_api(config, messages, tools=None):
    """调用 OpenAI 兼容 API (非流式), 用于工具调用轮次"""
    endpoint = config.get("endpoint", "").rstrip("/")
    if not endpoint:
        endpoint = "https://api.openai.com/v1"
    url = "{}/chat/completions".format(endpoint)
    api_key = config.get("api_key", "")
    model = config.get("model", "gpt-4o-mini")

    body = {"model": model, "messages": messages, "max_tokens": 4096}
    if tools:
        body["tools"] = tools

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer {}".format(api_key))

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": "API错误 {}: {}".format(e.code, err_body[:500])}
    except Exception as e:
        return {"error": str(e)}


def call_llm_stream(config, messages, tools=None):
    """调用 OpenAI 兼容 API (流式, 返回生成器)"""
    endpoint = config.get("endpoint", "").rstrip("/")
    if not endpoint:
        endpoint = "https://api.openai.com/v1"
    url = "{}/chat/completions".format(endpoint)
    api_key = config.get("api_key", "")
    model = config.get("model", "gpt-4o-mini")

    body = {"model": model, "messages": messages, "stream": True, "max_tokens": 4096}
    if tools:
        body["tools"] = tools

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer {}".format(api_key))

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

        # /api/ai/memory
        if parts == ["api", "ai", "memory"]:
            return self._api_memory_add()

        # /api/ai/chat
        if parts == ["api", "ai", "chat"]:
            return self._api_ai_chat()

        # /api/trash/restore  -> 从回收站恢复书籍
        if parts == ["api", "trash", "restore"]:
            return self._api_trash_restore()

        # /api/trash/empty  -> 清空回收站过期项 (>30天)
        if parts == ["api", "trash", "empty"]:
            return self._api_trash_empty()

        if len(parts) == 2 and parts[0] == "api" and parts[1] == "library":
            return self._api_save_library()

        self._json(404, {"error": "unknown endpoint"})

    # ---- DELETE ----
    def do_DELETE(self):
        parts = [p for p in urllib.parse.urlparse(self.path).path.split("/") if p != ""]

        # /api/books/<id>
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "books":
            return self._api_delete_book(parts[2])

        # /api/trash/<book_id>  -> 永久删除回收站中的书籍
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "trash":
            return self._api_trash_delete_permanent(urllib.parse.unquote(parts[2]))

        # /api/categories/<name>
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "categories":
            return self._api_delete_category(urllib.parse.unquote(parts[2]))

        # /api/ai/memory/<id>
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "ai" and parts[2] == "memory":
            return self._api_memory_delete(urllib.parse.unquote(parts[3]))

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
            lib = load_library()
            trash = lib.get("trash", {})
            books = scan_books()
            meta_lib = lib.get("books", {})
            # 过滤掉回收站中的书籍 (文件仍在磁盘, 但不应出现在书架)
            books = [b for b in books if b["id"] not in trash]
            for b in books:
                meta = meta_lib.get(b["id"], {})
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

        # /api/ai/memory
        if parts == ["api", "ai", "memory"]:
            return self._api_memory_get()

        # /api/trash  -> 回收站列表
        if parts == ["api", "trash"]:
            return self._api_trash_list()

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

    # ---- 书籍删除 (软删除: 移入回收站, 不删除文件) ----
    def _api_delete_book(self, book_id):
        full = book_path(book_id)
        if not full:
            return self._json(404, {"error": "book not found"})
        lib = load_library()
        meta = lib.get("books", {}).get(book_id, {})
        title = meta.get("title", book_id)
        # 移入回收站, 不删除文件
        trash = lib.setdefault("trash", {})
        trash[book_id] = {
            "title": title,
            "deletedAt": int(time.time()),
            "originalCategory": meta.get("category", ""),
            "path": full,
        }
        lib.get("books", {}).pop(book_id, None)
        save_library(lib)
        self._json(200, {"ok": True, "title": title, "message": "已移入回收站"})

    # ---- 回收站 API ----
    def _api_trash_list(self):
        # 访问回收站时自动清理过期项
        expired = clean_expired_trash()
        lib = load_library()
        trash = lib.get("trash", {})
        now = int(time.time())
        items = []
        for bid, info in trash.items():
            deleted_at = info.get("deletedAt", 0)
            age = now - deleted_at
            # 剩余保留时间 (秒), 不少于 0
            remain = max(0, TRASH_RETENTION_SECONDS - age)
            items.append({
                "bookId": bid,
                "title": info.get("title", bid),
                "deletedAt": deleted_at,
                "originalCategory": info.get("originalCategory", ""),
                "path": info.get("path", ""),
                "ageSeconds": age,
                "remainSeconds": remain,
            })
        # 按删除时间倒序 (最新删除在前)
        items.sort(key=lambda x: x.get("deletedAt", 0), reverse=True)
        return self._json(200, {
            "trash": items,
            "count": len(items),
            "expiredRemoved": len(expired),
        })

    def _api_trash_restore(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        book_id = payload.get("book_id", "")
        if not book_id:
            return self._json(400, {"error": "book_id required"})
        info, err = restore_from_trash(book_id)
        if err:
            return self._json(404, {"error": "该书不在回收站中"})
        return self._json(200, {
            "ok": True,
            "bookId": book_id,
            "title": info.get("title", book_id),
            "message": "已从回收站恢复《{}》".format(info.get("title", book_id)),
        })

    def _api_trash_empty(self):
        """清空回收站中所有过期项 (>30天), 并返回被清理的数量"""
        expired = clean_expired_trash()
        return self._json(200, {
            "ok": True,
            "expiredRemoved": len(expired),
            "removed": expired,
            "message": "已清理 {} 本过期书籍".format(len(expired)),
        })

    def _api_trash_delete_permanent(self, book_id):
        """永久删除回收站中的一本书 (删除文件 + 移出 trash)"""
        info, err = permanently_delete_from_trash(book_id)
        if err:
            return self._json(404, {"error": "该书不在回收站中"})
        return self._json(200, {
            "ok": True,
            "bookId": book_id,
            "title": info.get("title", book_id),
            "message": "已永久删除《{}》".format(info.get("title", book_id)),
        })

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

    # ---- Agent 记忆 API ----
    def _api_memory_get(self):
        mem = MEMORY.load_memory()
        return self._json(200, mem)

    def _api_memory_add(self):
        try:
            payload = json.loads(self._read_body().decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "bad json"})
        content = (payload.get("content", "") or "").strip()
        if not content:
            return self._json(400, {"error": "content required"})
        type_ = payload.get("type", "fact")
        confidence = payload.get("confidence", 0.8)
        source = payload.get("source", "user")
        fact = MEMORY.add_fact(content, type_, confidence, source)
        return self._json(200, {"ok": True, "fact": fact})

    def _api_memory_delete(self, fact_id):
        if not fact_id:
            return self._json(400, {"error": "id required"})
        ok = MEMORY.remove_fact(fact_id)
        if not ok:
            return self._json(404, {"error": "fact not found"})
        return self._json(200, {"ok": True})

    # ---- AI Agent 对话 (流式 SSE) ----
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

        context = payload.get("context", {}) or {}
        session_id = payload.get("session_id", "default")

        # 注入配置, 使记忆 / 上下文压缩模块可调用 LLM
        MEMORY.set_config(config)

        # 安全裁剪前端传入的纯文本历史 (不破坏 tool_calls 结构)
        messages = MEMORY.trim_short_term(messages)

        # 组装上下文 (注入会话摘要 + 长期记忆 + 书籍上下文, 按需压缩)
        ctx_builder = ContextBuilder(MEMORY, config)
        registry = ToolRegistry()
        register_default_tools(registry)
        controller = AgentLoopController()

        llm_messages = ctx_builder.build(messages, context, session_id)
        collected_actions = []
        final_content = ""

        # ---- Agent 循环 ----
        while True:
            stop, reason = controller.should_stop()
            if stop:
                final_content = reason
                break

            controller.step += 1
            controller.begin_step()

            response = call_llm_api(config, llm_messages, registry.get_schemas())
            if "error" in response:
                final_content = "AI 调用失败: {}".format(response["error"])
                break

            choices = response.get("choices", [])
            if not choices:
                final_content = "AI 返回了空响应, 请稍后重试。"
                break
            msg = choices[0].get("message", {})
            tool_calls = msg.get("tool_calls")

            # 没有工具调用 -> 最终回答
            if not tool_calls:
                final_content = msg.get("content", "") or ""
                break

            # 追加带 tool_calls 的 assistant 消息
            llm_messages.append(msg)

            # 执行每个工具调用
            for tc in tool_calls:
                fn_name = tc.get("function", {}).get("name", "")
                try:
                    fn_args = json.loads(tc.get("function", {}).get("arguments") or "{}")
                except Exception:
                    fn_args = {}

                # 重复调用检测
                is_dup, dup_count = controller.check_duplicate(fn_name, fn_args)
                if is_dup:
                    result = make_tool_result(
                        False,
                        error="已重复调用工具 {} (相同参数 {} 次)。请直接使用之前该工具返回的结果, 不要再次调用。".format(fn_name, dup_count),
                        retryable=False,
                    )
                else:
                    controller.record_call(fn_name, fn_args)
                    result = registry.execute(fn_name, fn_args, context)

                # 失败计数
                result_ok = bool(result.get("ok"))
                if not result_ok:
                    controller.record_failure()

                # 记录步骤日志 (便于调试)
                controller.log_step(controller.step, fn_name, result_ok)

                # 序列化为工具结果内容
                result_str = json.dumps(result, ensure_ascii=False)

                # 从工具结果中收集动作指令
                for act in extract_actions(result_str):
                    if act not in collected_actions:
                        collected_actions.append(act)

                llm_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result_str,
                })

            # 上下文增长后按需压缩 (避免 token 超限)
            if ctx_builder.compressor and ctx_builder.compressor.should_compress(llm_messages):
                llm_messages = ctx_builder.compressor.compress(llm_messages)
                # 清理可能因压缩产生的孤立 tool 消息 (其 tool_call_id 已不在上下文中)
                llm_messages = self._sanitize_messages(llm_messages)

            # 循环继续: 检查步数/失败/超时上限 (should_stop 在下一轮开头判断)

        # ---- 流式输出最终回答 ----
        # 从最终回答中提取动作指令
        for act in extract_actions(final_content):
            if act not in collected_actions:
                collected_actions.append(act)

        # 清除最终回答中的动作指令行
        clean_content = re.sub(r'__ACTION__:open_book:[^\s"\'\\]+', '', final_content).strip()

        if not clean_content and not collected_actions:
            clean_content = "(AI 未返回内容, 请检查 AI 配置或稍后重试。)"

        # SSE 流式
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # 逐字发送内容
        chunk_size = 4
        for i in range(0, len(clean_content), chunk_size):
            chunk = clean_content[i:i + chunk_size]
            data = json.dumps({"content": chunk}, ensure_ascii=False)
            self.wfile.write("data: {}\n\n".format(data).encode("utf-8"))
            self.wfile.flush()

        # 发送动作
        if collected_actions:
            data = json.dumps({"actions": collected_actions}, ensure_ascii=False)
            self.wfile.write("data: {}\n\n".format(data).encode("utf-8"))
            self.wfile.flush()

        # 结束标记
        self.wfile.write(b"data: {\"done\": true}\n\n")
        self.wfile.flush()

        # ---- 保存会话摘要 (best-effort, 在响应发送后执行, 不影响用户体验) ----
        self._save_session_summary(session_id, llm_messages, config)

    @staticmethod
    def _sanitize_messages(messages):
        """移除孤立的 tool 消息 (其 tool_call_id 在前序 assistant 消息中不存在)"""
        valid_call_ids = set()
        for m in messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m.get("tool_calls", []):
                    cid = tc.get("id")
                    if cid:
                        valid_call_ids.add(cid)
        return [m for m in messages
                if m.get("role") != "tool" or m.get("tool_call_id") in valid_call_ids]

    def _save_session_summary(self, session_id, messages, config):
        """生成并保存会话摘要 (best-effort), 与已有摘要合并后持久化"""
        try:
            # 提取本轮最后一条用户消息与最终回答
            last_user = ""
            last_assistant = ""
            tool_names = []
            for m in messages:
                role = m.get("role", "")
                if role == "user":
                    last_user = (m.get("content", "") or "")[:300]
                if role == "assistant":
                    c = m.get("content", "") or ""
                    if c:
                        last_assistant = c[:300]
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        tool_names.append(tc.get("function", {}).get("name", ""))
            if not last_user and not last_assistant:
                return
            prompt = ("请用中文将以下本轮对话摘要为 100 字以内的要点, 保留关键信息:\n"
                      "用户: {}\n助手: {}\n工具调用: {}").format(
                last_user, last_assistant, ", ".join(tool_names) or "无")
            compressor = ContextCompressor(config)
            summary = compressor._generate_summary(prompt)
            if summary:
                existing = MEMORY.get_session_summary(session_id)
                if existing:
                    combined = existing + "\n" + summary[:200]
                else:
                    combined = summary[:300]
                MEMORY.set_session_summary(session_id, combined[:800])
        except Exception:
            pass

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
