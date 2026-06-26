// bookshelf.js — 书架视图：网格、懒加载封面、搜索/筛选/排序
import API, { humanSize } from './api.js';
import { CoverStore, makePlaceholderCover } from './store.js';

let allBooks = [];
let io = null;          // IntersectionObserver 懒加载封面
const pendingCovers = new Set();

const el = {
  shelf: document.getElementById('shelf'),
  empty: document.getElementById('empty-state'),
  search: document.getElementById('search-input'),
  format: document.getElementById('filter-format'),
  sort: document.getElementById('sort-by'),
};

function initObserver() {
  if (io) io.disconnect();
  io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        const id = e.target.dataset.id;
        const fmt = e.target.dataset.format;
        io.unobserve(e.target);
        loadCover(id, fmt, e.target);
      }
    }
  }, { rootMargin: '200px' });
}

async function load() {
  el.shelf.innerHTML = '';
  try {
    allBooks = await API.getBooks();
  } catch (err) {
    el.empty.hidden = false;
    el.shelf.hidden = true;
    return;
  }
  buildFormatFilter();
  render();
}

function buildFormatFilter() {
  const fmts = [...new Set(allBooks.map(b => b.format))].sort();
  const cur = el.format.value;
  el.format.innerHTML = '<option value="">全部格式</option>' +
    fmts.map(f => `<option value="${f}">${f.toUpperCase()}</option>`).join('');
  if (cur) el.format.value = cur;
}

function filtered() {
  let list = [...allBooks];
  const q = el.search.value.trim().toLowerCase();
  const f = el.format.value;
  if (q) list = list.filter(b => (b.title || '').toLowerCase().includes(q) || (b.author || '').toLowerCase().includes(q) || b.name.toLowerCase().includes(q));
  if (f) list = list.filter(b => b.format === f);
  const s = el.sort.value;
  if (s === 'title') list.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh'));
  else if (s === 'added') list.sort((a, b) => b.mtime - a.mtime);
  else list.sort((a, b) => (b.lastRead || 0) - (a.lastRead || 0) || b.mtime - a.mtime);
  return list;
}

function render() {
  const list = filtered();
  el.empty.hidden = list.length > 0;
  el.shelf.hidden = list.length === 0;
  if (!list.length) { el.shelf.innerHTML = ''; return; }
  initObserver();

  const frag = document.createDocumentFragment();
  for (const b of list) {
    const card = document.createElement('button');
    card.className = 'book-card';
    card.dataset.id = b.id;
    card.dataset.format = b.format;
    card.innerHTML = `
      <div class="book-cover">
        <span class="fmt-badge">${b.format.toUpperCase()}</span>
        <div class="cover-placeholder">
          <span class="cp-title"></span>
          <span class="cp-fmt">${b.format.toUpperCase()}</span>
        </div>
        ${b.progress > 0 ? `<div class="cover-progress"><i style="width:${Math.min(100, b.progress * 100)}%"></i></div>` : ''}
      </div>
      <div class="book-meta">
        <div class="book-title">${escapeHtml(b.title || b.name)}</div>
        ${b.author ? `<div class="book-author">${escapeHtml(b.author)}</div>` : ''}
      </div>`;
    card.querySelector('.cp-title').textContent = b.title || b.name;
    // 占位色板先填上，避免纯灰
    const [a, c] = palette(b.title || b.name);
    card.querySelector('.cover-placeholder').style.background = `linear-gradient(150deg, ${a} 0%, ${c} 100%)`;
    card.addEventListener('click', () => openBook(b));
    frag.appendChild(card);
    io.observe(card);
  }
  el.shelf.innerHTML = '';
  el.shelf.appendChild(frag);
}

function palette(seed) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const p = [
    ['#3a2e22', '#6b4a30'], ['#2c2a33', '#4a4358'], ['#33262a', '#6b3a3a'],
    ['#28322b', '#3f5a44'], ['#34292a', '#5e3b3e'], ['#2a2d33', '#3f5366'],
    ['#352b24', '#6b5230'], ['#2b2633', '#473a5e'],
  ];
  return p[h % p.length];
}

function setCover(card, dataUrl) {
  const ph = card.querySelector('.cover-placeholder');
  if (ph) {
    const img = document.createElement('img');
    img.src = dataUrl; img.alt = '';
    img.loading = 'lazy';
    ph.replaceWith(img);
  }
}

async function loadCover(id, fmt, card) {
  if (pendingCovers.has(id)) return;
  pendingCovers.add(id);
  try {
    const cached = await CoverStore.get(id);
    if (cached) { setCover(card, cached); return; }
    let dataUrl = null;
    if (fmt === 'pdf') dataUrl = await pdfCover(id);
    else if (fmt === 'epub') dataUrl = await epubCover(id);
    if (!dataUrl) dataUrl = makePlaceholderCover(card.querySelector('.cp-title')?.textContent || id, fmt);
    setCover(card, dataUrl);
    CoverStore.put(id, dataUrl);
  } catch (e) {
    // 失败则保留占位
  } finally {
    pendingCovers.delete(id);
  }
}

async function pdfCover(id) {
  if (!window.pdfjsLib) return null;
  const url = API.fileUrl(id);
  const pdf = await pdfjsLib.getDocument({ url }).promise;
  const page = await pdf.getPage(1);
  const base = page.getViewport({ scale: 1 });
  const scale = 260 / base.width;
  const vp = page.getViewport({ scale });
  const cv = document.createElement('canvas');
  cv.width = Math.round(vp.width); cv.height = Math.round(vp.height);
  const ctx = cv.getContext('2d');
  ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, cv.width, cv.height);
  await page.render({ canvasContext: ctx, viewport: vp }).promise;
  pdf.destroy();
  return cv.toDataURL('image/jpeg', 0.82);
}

async function epubCover(id) {
  if (!window.ePub) return null;
  const url = API.fileUrl(id);
  const book = ePub(url);
  await book.ready;
  // 顺带提取元数据
  try {
    const meta = await book.loaded.metadata;
    if (meta && (meta.title || meta.creator)) {
      API.saveMeta(id, { title: meta.title || '', author: meta.creator || '' });
    }
  } catch {}
  let dataUrl = null;
  try {
    const coverUrl = await book.coverUrl();
    if (coverUrl) {
      const blob = await (await fetch(coverUrl)).blob();
      const bmp = await createImageBitmap(blob);
      const cv = document.createElement('canvas');
      cv.width = 260; cv.height = 390;
      const ctx = cv.getContext('2d');
      ctx.fillStyle = '#1b1712'; ctx.fillRect(0, 0, 260, 390);
      // cover-fit
      const r = Math.max(260 / bmp.width, 390 / bmp.height);
      const w = bmp.width * r, h = bmp.height * r;
      ctx.drawImage(bmp, (260 - w) / 2, (390 - h) / 2, w, h);
      dataUrl = cv.toDataURL('image/jpeg', 0.82);
    }
  } catch {}
  try { book.destroy(); } catch {}
  return dataUrl;
}

function openBook(b) {
  location.hash = `#/book/${encodeURIComponent(b.id)}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function bind() {
  let t;
  el.search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(render, 160); });
  el.format.addEventListener('change', render);
  el.sort.addEventListener('change', render);
  document.getElementById('btn-refresh').addEventListener('click', load);
  document.getElementById('btn-empty-refresh').addEventListener('click', load);
}

export function initBookshelf() {
  bind();
  load();
}
export { load as refreshShelf };
