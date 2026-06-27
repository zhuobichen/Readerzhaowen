// api.js — 与本地 Python 服务器通信的薄封装
const API = {
  async getBooks() {
    const r = await fetch('/api/books');
    if (!r.ok) throw new Error('获取书架失败');
    return (await r.json()).books || [];
  },

  fileUrl(id) {
    return `/api/books/${encodeURIComponent(id)}/file`;
  },

  async saveProgress(id, payload) {
    try {
      await fetch(`/api/books/${encodeURIComponent(id)}/progress`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (e) { /* 进度保存失败不阻塞阅读 */ }
  },

  async getProgress(id) {
    try {
      const r = await fetch(`/api/books/${encodeURIComponent(id)}/progress`);
      if (!r.ok) return null;
      return await r.json();
    } catch { return null; }
  },

  async saveMeta(id, meta) {
    try {
      await fetch(`/api/books/${encodeURIComponent(id)}/meta`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(meta),
      });
    } catch { /* 元数据保存失败不阻塞 */ }
  },

  async getNotes(id) {
    try {
      const r = await fetch(`/api/books/${encodeURIComponent(id)}/notes`);
      if (!r.ok) return [];
      return (await r.json()).notes || [];
    } catch { return []; }
  },

  async saveNote(id, payload) {
    try {
      const r = await fetch(`/api/books/${encodeURIComponent(id)}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ op: 'save', ...payload }),
      });
      if (!r.ok) return [];
      return (await r.json()).notes || [];
    } catch { return []; }
  },

  async deleteNote(id, noteId) {
    try {
      const r = await fetch(`/api/books/${encodeURIComponent(id)}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ op: 'delete', id: noteId }),
      });
      if (!r.ok) return [];
      return (await r.json()).notes || [];
    } catch { return []; }
  },

  // ---- 分类 ----
  async getCategories() {
    try {
      const r = await fetch('/api/categories');
      if (!r.ok) return [];
      return (await r.json()).categories || [];
    } catch { return []; }
  },

  async createCategory(name) {
    try {
      const r = await fetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!r.ok) throw new Error('新建分类失败');
      return await r.json();
    } catch (e) { throw e; }
  },

  async renameCategory(oldName, newName) {
    try {
      const r = await fetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName, old_name: oldName }),
      });
      if (!r.ok) throw new Error('重命名分类失败');
      return await r.json();
    } catch (e) { throw e; }
  },

  async deleteCategory(name) {
    try {
      const r = await fetch(`/api/categories/${encodeURIComponent(name)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('删除分类失败');
      return await r.json();
    } catch (e) { throw e; }
  },

  async setCategory(bookId, category) {
    try {
      const r = await fetch(`/api/books/${encodeURIComponent(bookId)}/category`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category }),
      });
      if (!r.ok) throw new Error('设置分类失败');
      return await r.json();
    } catch (e) { throw e; }
  },

  async deleteBook(bookId) {
    try {
      const r = await fetch(`/api/books/${encodeURIComponent(bookId)}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('删除书籍失败');
      return await r.json();
    } catch (e) { throw e; }
  },

  async uploadBook(file) {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/books/upload', { method: 'POST', body: fd });
    if (!r.ok) throw new Error('上传书籍失败');
    return await r.json();
  },

  // ---- AI ----
  async getAIConfig() {
    try {
      const r = await fetch('/api/ai/config');
      if (!r.ok) return { endpoint: '', model: '', has_key: false };
      return await r.json();
    } catch { return { endpoint: '', model: '', has_key: false }; }
  },

  async saveAIConfig(cfg) {
    try {
      const r = await fetch('/api/ai/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: cfg.api_key, endpoint: cfg.endpoint, model: cfg.model }),
      });
      if (!r.ok) throw new Error('保存AI配置失败');
      return await r.json();
    } catch (e) { throw e; }
  },

  // AI 对话：返回 fetch Response（SSE 流），由调用方读取流
  async aiChat(messages, context = {}) {
    const r = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, context }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || 'AI请求失败');
    }
    return r;
  },
};

// 文件体积友好显示
function humanSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

export default API;
export { humanSize };
