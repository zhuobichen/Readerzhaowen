// app.js — 入口与路由
import { initBookshelf, refreshShelf, refreshCategories } from './bookshelf.js';
import { Reader } from './reader.js';
import Notes from './notes.js';
import AI from './ai.js';
import API from './api.js';

// 配置 PDF.js worker（本地化）
if (window.pdfjsLib) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdf.worker.min.js';
  pdfjsLib.disableWorker = false;
}

// 为 AI 提供当前阅读上下文
function getReaderContext() {
  const hash = location.hash;
  const m = hash.match(/^#\/book\/(.+)$/);
  const bookId = m ? decodeURIComponent(m[1]) : '';
  const loc = Reader.getLocation ? Reader.getLocation() : {};
  return {
    currentBookId: bookId,
    currentPage: loc.page || 0,
    currentProgress: loc.progress || 0,
    currentLabel: loc.label || '',
  };
}

const viewShelf = document.getElementById('view-shelf');
const viewReader = document.getElementById('view-reader');

function showView(name) {
  viewShelf.hidden = name !== 'shelf';
  viewReader.hidden = name !== 'reader';
  document.body.dataset.view = name;
}

async function route() {
  const hash = location.hash.replace(/^#/, '');
  const m = hash.match(/^\/book\/(.+)$/);
  if (m) {
    const id = decodeURIComponent(m[1]);
    showView('reader');
    try {
      const books = await API.getBooks();
      const book = books.find(b => b.id === id);
      if (!book) { throw new Error('找不到这本书，可能已被移出 books 文件夹'); }
      await Reader.open(book);
    } catch (err) {
      Reader.cleanup();
      document.getElementById('reader-area').innerHTML =
        `<div class="unsupported"><h3>无法打开</h3><p class="unsupported-tip">${escapeHtml(err.message)}</p></div>`;
    }
  } else {
    Reader.cleanup();
    showView('shelf');
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// 文件上传处理
async function handleUpload(files) {
  if (!files || !files.length) return;
  let ok = 0, fail = 0;
  for (const file of files) {
    try {
      await API.uploadBook(file);
      ok++;
    } catch { fail++; }
  }
  if (ok > 0) {
    refreshShelf();
    refreshCategories();
  }
  if (fail > 0) {
    alert(`导入完成：成功 ${ok} 本，失败 ${fail} 本`);
  }
}

// ---- 主题切换 ----
function initTheme() {
  const saved = localStorage.getItem('reader-theme') || 'dark';
  applyTheme(saved);
  const btn = document.getElementById('btn-theme-toggle');
  if (btn) {
    btn.addEventListener('click', () => {
      const current = document.body.dataset.theme === 'light' ? 'light' : 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      localStorage.setItem('reader-theme', next);
    });
  }
}

function applyTheme(theme) {
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
    document.body.dataset.theme = 'light';
  } else {
    document.documentElement.removeAttribute('data-theme');
    document.body.dataset.theme = 'dark';
  }
  const darkIcon = document.getElementById('theme-icon-dark');
  const lightIcon = document.getElementById('theme-icon-light');
  if (darkIcon && lightIcon) {
    darkIcon.style.display = theme === 'dark' ? '' : 'none';
    lightIcon.style.display = theme === 'light' ? '' : 'none';
  }
}

// ---- 回收站 ----
function initTrash() {
  const btn = document.getElementById('btn-trash');
  if (btn) btn.addEventListener('click', openTrashModal);
}

async function openTrashModal() {
  // 关闭已有
  document.getElementById('trash-modal')?.remove();
  const modal = document.createElement('div');
  modal.id = 'trash-modal';
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-box trash-modal-box">
      <div class="modal-header">
        <h3>回收站</h3>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">✕</button>
      </div>
      <div class="trash-list" id="trash-list"><p style="text-align:center;color:var(--text-mute);padding:40px 0;">加载中...</p></div>
      <div class="trash-footer" id="trash-footer" style="display:none;">
        <button class="btn-text" id="btn-empty-trash">清空过期项</button>
      </div>
    </div>`;
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
  document.body.appendChild(modal);
  await loadTrashList();
}

async function loadTrashList() {
  const listEl = document.getElementById('trash-list');
  const footerEl = document.getElementById('trash-footer');
  try {
    const data = await API.getTrash();
    const items = data.trash || [];
    if (!items.length) {
      listEl.innerHTML = '<p style="text-align:center;color:var(--text-mute);padding:40px 0;">回收站为空</p>';
      return;
    }
    listEl.innerHTML = items.map(item => {
      const title = decodeURIComponent(item.title || item.bookId || '');
      const days = Math.ceil(item.remainSeconds / 86400);
      const date = new Date(item.deletedAt * 1000).toLocaleDateString('zh-CN');
      return `<div class="trash-item">
        <div class="trash-item-info">
          <span class="trash-item-title">${escapeHtmlSafe(title)}</span>
          <span class="trash-item-meta">${date} · 剩余 ${days} 天</span>
        </div>
        <div class="trash-item-actions">
          <button class="btn-sm" data-act="restore" data-id="${escapeHtmlSafe(item.bookId)}">恢复</button>
          <button class="btn-sm btn-danger" data-act="permanent" data-id="${escapeHtmlSafe(item.bookId)}">永久删除</button>
        </div>
      </div>`;
    }).join('');
    footerEl.style.display = 'flex';
    // 绑定按钮
    listEl.querySelectorAll('[data-act="restore"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        try {
          await API.restoreBook(id);
          loadTrashList();
          refreshShelf();
          refreshCategories();
        } catch (e) { alert(e.message || '恢复失败'); }
      });
    });
    listEl.querySelectorAll('[data-act="permanent"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        if (!confirm('永久删除后无法恢复，确定吗？')) return;
        try {
          await API.deleteBookPermanent(id);
          loadTrashList();
        } catch (e) { alert(e.message || '永久删除失败'); }
      });
    });
    const emptyBtn = document.getElementById('btn-empty-trash');
    if (emptyBtn) emptyBtn.onclick = async () => {
      try {
        await API.emptyTrash();
        loadTrashList();
      } catch (e) { alert(e.message || '清空失败'); }
    };
  } catch (e) {
    listEl.innerHTML = `<p style="text-align:center;color:var(--danger);">加载失败: ${e.message}</p>`;
  }
}

function escapeHtmlSafe(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

function bind() {
  initTheme();
  initTrash();
  Reader.init();
  Notes.init();
  AI.init();
  AI.setContextProvider(getReaderContext);
  Reader.back().addEventListener('click', () => { location.hash = '#/'; });
  window.addEventListener('hashchange', route);

  // 文件上传
  const fileInput = document.getElementById('file-input');
  const btnUpload = document.getElementById('btn-upload');
  if (btnUpload && fileInput) {
    btnUpload.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      handleUpload(e.target.files);
      e.target.value = '';
    });
  }

  // 拖拽导入：仅书架视图+仅文件类型才触发
  let dragCounter = 0;
  let dropOverlay = null;
  function isFileDrag(e) {
    return e.dataTransfer && e.dataTransfer.types && Array.from(e.dataTransfer.types).includes('Files');
  }
  function isShelfView() {
    const shelf = document.getElementById('view-shelf');
    return shelf && !shelf.hidden;
  }
  window.addEventListener('dragenter', (e) => {
    if (!isFileDrag(e) || !isShelfView()) return;
    e.preventDefault();
    dragCounter++;
    if (!dropOverlay) {
      dropOverlay = document.createElement('div');
      dropOverlay.className = 'drop-overlay';
      dropOverlay.innerHTML = '<div class="drop-inner"><svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/></svg><p>松手导入书籍</p></div>';
      document.body.appendChild(dropOverlay);
    }
  });
  window.addEventListener('dragover', (e) => { if (isFileDrag(e) && isShelfView()) e.preventDefault(); });
  window.addEventListener('dragleave', () => {
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      dropOverlay?.remove();
      dropOverlay = null;
    }
  });
  window.addEventListener('drop', (e) => {
    if (!isFileDrag(e) || !isShelfView()) return;
    e.preventDefault();
    dragCounter = 0;
    dropOverlay?.remove();
    dropOverlay = null;
    const files = [...(e.dataTransfer?.files || [])];
    const valid = files.filter(f => /\.(pdf|epub|txt|mobi|azw3|fb2|cbz|cbr|docx)$/i.test(f.name));
    if (valid.length) handleUpload(valid);
  });
}

bind();
initBookshelf();
route();
