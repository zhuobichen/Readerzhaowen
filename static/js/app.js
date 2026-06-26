// app.js — 入口与路由
import { initBookshelf } from './bookshelf.js';
import { Reader } from './reader.js';
import Notes from './notes.js';
import API from './api.js';

// 配置 PDF.js worker（本地化）
if (window.pdfjsLib) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdf.worker.min.js';
  pdfjsLib.disableWorker = false;
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
    // 取书籍信息（带元数据）
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

function bind() {
  Reader.init();
  Notes.init();
  Reader.back().addEventListener('click', () => { location.hash = '#/'; });
  window.addEventListener('hashchange', route);
}

bind();
initBookshelf();
route();
