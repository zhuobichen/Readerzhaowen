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

function bind() {
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

  // 拖拽导入：全屏拖入提示
  let dragCounter = 0;
  let dropOverlay = null;
  window.addEventListener('dragenter', (e) => {
    if (!e.dataTransfer?.types?.includes('Files')) return;
    e.preventDefault();
    dragCounter++;
    if (!dropOverlay) {
      dropOverlay = document.createElement('div');
      dropOverlay.className = 'drop-overlay';
      dropOverlay.innerHTML = '<div class="drop-inner"><svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/></svg><p>松手导入书籍</p></div>';
      document.body.appendChild(dropOverlay);
    }
  });
  window.addEventListener('dragover', (e) => { if (e.dataTransfer?.types?.includes('Files')) e.preventDefault(); });
  window.addEventListener('dragleave', () => {
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      dropOverlay?.remove();
      dropOverlay = null;
    }
  });
  window.addEventListener('drop', (e) => {
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
