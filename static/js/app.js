// app.js — 入口与路由
import { initBookshelf, refreshShelf } from './bookshelf.js';
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
      e.target.value = ''; // 清空，允许重复选同一文件
    });
  }
}

bind();
initBookshelf();
route();
