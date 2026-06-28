// bookshelf.js — 书架视图：网格、懒加载封面、搜索/筛选/排序
import API from './api.js';
import { CoverStore, makePlaceholderCover } from './store.js';
import { confirmModal } from './app.js';

let allBooks = [];
let categories = [];            // [{name, count}]
let currentCategory = null;    // null=全部, '__uncat__'=未分类, 其它=分类名
let catCollapsed = false;     // 分类侧栏折叠状态
let io = null;          // IntersectionObserver 懒加载封面
const pendingCovers = new Set();

const el = {
  shelf: document.getElementById('shelf'),
  empty: document.getElementById('empty-state'),
  search: document.getElementById('search-input'),
  format: document.getElementById('filter-format'),
  sort: document.getElementById('sort-by'),
  sidebar: document.getElementById('category-sidebar'),
};

// 右键菜单与分类选择器（动态创建，复用单例）
let ctxMenuEl = null;
let catPickerEl = null;

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
  refreshCategories();
  render();
}

/** 拉取分类并渲染侧栏 */
async function refreshCategories() {
  try {
    categories = await API.getCategories();
  } catch { categories = []; }
  renderSidebar();
}

/** 按当前 allBooks 计算各分类数量 */
function categoryCounts() {
  const counts = {};
  let uncat = 0;
  for (const b of allBooks) {
    if (b.category) counts[b.category] = (counts[b.category] || 0) + 1;
    else uncat++;
  }
  return { counts, uncat };
}

/** 渲染左侧分类侧栏 */
function renderSidebar() {
  if (!el.sidebar) return;
  const { counts, uncat } = categoryCounts();
  const items = [];
  // 全部
  items.push(renderCatItem('全部', 'all', allBooks.length, currentCategory === null));
  // 未分类
  items.push(renderCatItem('未分类', '__uncat__', uncat, currentCategory === '__uncat__'));
  // 各分类
  for (const c of categories) {
    const name = c.name;
    const cnt = counts[name] != null ? counts[name] : (c.count || 0);
    items.push(renderCatItem(name, name, cnt, currentCategory === name));
  }
  el.sidebar.innerHTML = `
    <div class="cat-section-title" id="cat-toggle">
      <span>分类</span>
      <svg id="cat-toggle-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="transform: ${catCollapsed ? 'rotate(-90deg)' : 'rotate(0)'}; transition: transform .2s;"><path d="M6 9l6 6 6-6"/></svg>
    </div>
    <div class="cat-list" style="${catCollapsed ? 'display:none;' : ''}">${items.join('')}</div>
    <button class="cat-add" id="cat-add-btn" title="新建分类" style="${catCollapsed ? 'display:none;' : ''}">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
      <span>新建分类</span>
    </button>`;
  // 折叠/展开
  const toggle = el.sidebar.querySelector('#cat-toggle');
  if (toggle) {
    toggle.addEventListener('click', () => {
      catCollapsed = !catCollapsed;
      renderSidebar();
    });
  }
  // 绑定点击 + 拖拽放置
  el.sidebar.querySelectorAll('.cat-item').forEach(node => {
    node.addEventListener('click', (e) => {
      if (e.target.classList.contains('cat-menu-btn')) {
        e.stopPropagation();
        const r = node.getBoundingClientRect();
        showCatContextMenu(r.right, r.bottom + 2, node.dataset.cat);
        return;
      }
      const cat = node.dataset.cat;
      currentCategory = cat === 'all' ? null : (cat === '__uncat__' ? '__uncat__' : cat);
      renderSidebar();
      render();
    });
    node.addEventListener('contextmenu', (e) => {
      const cat = node.dataset.cat;
      if (cat === 'all' || cat === '__uncat__') return;
      e.preventDefault();
      showCatContextMenu(e.clientX, e.clientY, cat);
    });
    // 拖拽放置: 书籍拖到分类项上
    if (node.dataset.drop === 'cat') {
      node.addEventListener('dragover', (e) => { e.preventDefault(); node.classList.add('drag-over'); });
      node.addEventListener('dragleave', () => { node.classList.remove('drag-over'); });
      node.addEventListener('drop', async (e) => {
        e.preventDefault();
        node.classList.remove('drag-over');
        const bookId = e.dataTransfer.getData('text/plain');
        if (!bookId) return;
        const dropCat = node.dataset.dropCat;
        try {
          await API.setCategory(bookId, dropCat);
          load();
          refreshCategories();
        } catch (err) {
          alert(err.message || '分类失败');
        }
      });
    }
  });
  // 新建分类按钮 (用 onclick 确保每次重建后只绑定一次)
  const addBtn = el.sidebar.querySelector('#cat-add-btn');
  if (addBtn) addBtn.onclick = () => addCategory();
}

function renderCatItem(label, cat, count, active) {
  const isCustom = cat !== 'all' && cat !== '__uncat__';
  const dropTarget = cat !== 'all' ? `data-drop="cat"` : '';
  const dropCat = cat === '__uncat__' ? '' : escapeHtml(cat);
  return `<div class="cat-item${active ? ' active' : ''}" data-cat="${escapeHtml(cat)}" ${dropTarget} data-drop-cat="${dropCat}" title="${escapeHtml(label)}">
    <span class="cat-name">${escapeHtml(label)}</span>
    <span class="cat-count">${count}</span>
    ${isCustom ? '<span class="cat-menu-btn" title="右键管理">⋯</span>' : ''}
  </div>`;
}

/** 自定义输入对话框 (替代原生 prompt) */
function showInputDialog(title, placeholder, defaultValue) {
  return new Promise((resolve) => {
    document.getElementById('input-modal')?.remove();
    const modal = document.createElement('div');
    modal.id = 'input-modal';
    modal.className = 'modal-overlay';
    modal.innerHTML = `
      <div class="modal-box" style="width:360px;">
        <div class="modal-header">
          <h3>${escapeHtml(title)}</h3>
          <button class="modal-close">✕</button>
        </div>
        <div class="modal-body">
          <input type="text" id="input-modal-field" placeholder="${escapeHtml(placeholder || '')}" value="${escapeHtml(defaultValue || '')}">
        </div>
        <div class="modal-footer">
          <button class="btn-secondary" data-act="cancel">取消</button>
          <button class="btn-primary" data-act="ok">确定</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    const field = modal.querySelector('#input-modal-field');
    field.focus();
    field.select();
    const close = (val) => { modal.remove(); resolve(val); };
    modal.querySelector('.modal-close').onclick = () => close(null);
    modal.querySelector('[data-act="cancel"]').onclick = () => close(null);
    modal.querySelector('[data-act="ok"]').onclick = () => close(field.value);
    field.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') close(field.value);
      if (e.key === 'Escape') close(null);
    });
    modal.addEventListener('click', (e) => { if (e.target === modal) close(null); });
  });
}

/** 新建分类 */
async function addCategory() {
  const name = await showInputDialog('新建分类', '请输入分类名称', '');
  if (!name || !name.trim()) return;
  try {
    await API.createCategory(name.trim());
    await refreshCategories();
    if (typeof load === 'function') load();
  } catch (e) {
    console.error('新建分类失败:', e);
    alert(e.message || '新建分类失败');
  }
}

/** 分类右键菜单: 重命名 / 删除 */
function showCatContextMenu(x, y, catName) {
  closeMenus();
  const menu = document.createElement('div');
  menu.className = 'ctx-menu';
  menu.id = 'ctx-menu-active';
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.innerHTML = `
    <button data-act="rename">重命名分类</button>
    <hr>
    <button class="ctx-danger" data-act="del">删除分类</button>`;
  menu.querySelector('[data-act="rename"]').addEventListener('click', async () => {
    closeMenus();
    const newName = await showInputDialog('重命名分类', '输入新名称', catName);
    if (!newName || !newName.trim() || newName.trim() === catName) return;
    try {
      await API.renameCategory(catName, newName.trim());
      if (currentCategory === catName) currentCategory = newName.trim();
      await refreshCategories();
      render();
    } catch (e) {
      alert(e.message || '重命名失败');
    }
  });
  menu.querySelector('[data-act="del"]').addEventListener('click', async () => {
    closeMenus();
    if (!confirm(`删除分类「${catName}」？\n该分类下的书籍将归入"未分类"。`)) return;
    try {
      await API.deleteCategory(catName);
      if (currentCategory === catName) currentCategory = null;
      await refreshCategories();
      render();
    } catch (e) {
      alert(e.message || '删除失败');
    }
  });
  document.body.appendChild(menu);
  requestAnimationFrame(() => {
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = Math.max(10, window.innerWidth - rect.width - 10) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = Math.max(10, window.innerHeight - rect.height - 10) + 'px';
  });
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
  // 分类筛选
  if (currentCategory === '__uncat__') {
    list = list.filter(b => !b.category);
  } else if (currentCategory) {
    list = list.filter(b => b.category === currentCategory);
  }
  const q = el.search.value.trim().toLowerCase();
  const f = el.format.value;
  if (q) list = list.filter(b => (b.title || '').toLowerCase().includes(q) || (b.author || '').toLowerCase().includes(q) || b.name.toLowerCase().includes(q));
  if (f) list = list.filter(b => b.format === f);
  const s = el.sort.value;
  if (s === 'title') list.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh'));
  else if (s === 'added') list.sort((a, b) => b.mtime - a.mtime);
  else if (s === 'custom') list.sort((a, b) => (a.position ?? 99999) - (b.position ?? 99999) || b.mtime - a.mtime);
  else list.sort((a, b) => (b.lastRead || 0) - (a.lastRead || 0) || b.mtime - a.mtime);
  return list;
}

/** 显示/隐藏垃圾桶 */
function showTrashBin(show) {
  const bin = document.getElementById('trash-bin');
  if (!bin) return;
  if (show) {
    bin.hidden = false;
    bin.classList.add('show');
    // 绑定 drop（仅绑一次）
    if (!bin._bound) {
      bin._bound = true;
      bin.addEventListener('dragover', (e) => { e.preventDefault(); bin.classList.add('hover'); });
      bin.addEventListener('dragleave', () => { bin.classList.remove('hover'); });
      bin.addEventListener('drop', async (e) => {
        e.preventDefault();
        bin.classList.remove('hover');
        const bookId = e.dataTransfer.getData('text/plain');
        if (!bookId) return;
        closeMenus();
        const book = allBooks.find(b => b.id === bookId);
        const title = book ? (book.title || book.name) : bookId;
        if (!await confirmModal('移入回收站', `确定将《${title}》移入回收站？\n30天内可恢复，超过30天将永久删除。`, { confirmText: '移入回收站', danger: true })) return;
        try {
          await API.deleteBook(bookId);
          load();
          refreshCategories();
        } catch (err) {
          alert(err.message || '移入回收站失败');
        }
      });
    }
  } else {
    bin.classList.remove('show');
    setTimeout(() => { if (!bin.classList.contains('show')) bin.hidden = true; }, 200);
  }
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
        ${b.category ? `<div class="book-cat" data-cat="${escapeHtml(b.category)}"><span class="book-cat-tag">${escapeHtml(b.category)}</span></div>` : ''}
      </div>`;
    card.querySelector('.cp-title').textContent = b.title || b.name;
    // 占位色板先填上，避免纯灰
    const [a, c] = palette(b.title || b.name);
    card.querySelector('.cover-placeholder').style.background = `linear-gradient(150deg, ${a} 0%, ${c} 100%)`;
    card.addEventListener('click', () => openBook(b));
    card.addEventListener('contextmenu', (e) => { e.preventDefault(); showContextMenu(e.clientX, e.clientY, b); });
    // 拖拽分类: 书籍卡片可拖到左侧分类项; 自定义排序模式下可拖到另一本书上交换位置
    card.draggable = true;
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', b.id);
      e.dataTransfer.effectAllowed = 'move';
      card.classList.add('dragging');
      showTrashBin(true);
    });
    card.addEventListener('dragover', (e) => {
      // 自定义排序模式下, 允许拖到另一本书上
      if (el.sort.value === 'custom' && !card.classList.contains('dragging')) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        card.classList.add('drag-over');
      }
    });
    card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
    card.addEventListener('drop', async (e) => {
      e.preventDefault();
      card.classList.remove('drag-over');
      const draggedId = e.dataTransfer.getData('text/plain');
      if (!draggedId || draggedId === b.id) return;
      if (el.sort.value !== 'custom') return;
      // 交换位置
      try {
        await API.reorderBooks(draggedId, b.id);
        // 更新本地 position
        const a = allBooks.find(x => x.id === draggedId);
        const c = allBooks.find(x => x.id === b.id);
        if (a && c) {
          const tmp = a.position;
          a.position = c.position;
          c.position = tmp;
        }
        render();
      } catch (err) { console.error('reorder failed:', err); }
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      card.classList.remove('drag-over');
      showTrashBin(false);
    });
    // 分类标签点击 -> 弹出分类选择
    const catTag = card.querySelector('.book-cat-tag');
    if (catTag) catTag.addEventListener('click', (e) => {
      e.stopPropagation();
      const r = catTag.getBoundingClientRect();
      showCategoryPicker(r.left, r.bottom + 4, b);
    });
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

// ---- 右键上下文菜单 ----
function showContextMenu(x, y, book) {
  closeMenus();
  const menu = document.createElement('div');
  menu.className = 'ctx-menu';
  menu.id = 'ctx-menu-active';
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.innerHTML = `
    <button data-act="cat">设置分类</button>
    <hr>
    <button class="ctx-danger" data-act="del">移出书架</button>`;
  menu.querySelector('[data-act="cat"]').addEventListener('click', () => {
    closeMenus();
    showCategoryPicker(x, y, book);
  });
  menu.querySelector('[data-act="del"]').addEventListener('click', async () => {
    closeMenus();
    if (!await confirmModal('移出书架', `确定将《${book.title || book.name}》移出书架？\n30天内可在回收站恢复。`, { confirmText: '移出书架', danger: true })) return;
    try {
      await API.deleteBook(book.id);
      load();
      refreshCategories();
    } catch (e) {
      alert(e.message || '移出书架失败');
    }
  });
  document.body.appendChild(menu);
  // 越界修正 (下一帧确保布局已完成)
  requestAnimationFrame(() => {
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = Math.max(10, window.innerWidth - rect.width - 10) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = Math.max(10, window.innerHeight - rect.height - 10) + 'px';
  });
}

// ---- 分类选择器 ----
async function showCategoryPicker(x, y, book) {
  closeMenus();
  let cats = [];
  try { cats = await API.getCategories(); } catch {}
  const picker = document.createElement('div');
  picker.className = 'cat-picker';
  picker.id = 'ctx-menu-active';
  picker.style.left = x + 'px';
  picker.style.top = y + 'px';
  let html = cats.map(c => `<button data-cat="${escapeHtml(c.name)}">${escapeHtml(c.name)}</button>`).join('');
  html += '<hr style="border:none;border-top:1px solid var(--line);margin:4px 0;">';
  html += '<button data-cat="" style="color:var(--text-mute);">移除分类</button>';
  picker.innerHTML = html;
  picker.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', async () => {
      const cat = btn.dataset.cat;
      closeMenus();
      try {
        await API.setCategory(book.id, cat);
        load();
      } catch (e) {
        alert(e.message || '设置分类失败');
      }
    });
  });
  document.body.appendChild(picker);
  // 越界修正 (下一帧确保布局已完成)
  requestAnimationFrame(() => {
    const rect = picker.getBoundingClientRect();
    if (rect.right > window.innerWidth) picker.style.left = Math.max(10, window.innerWidth - rect.width - 10) + 'px';
    if (rect.bottom > window.innerHeight) picker.style.top = Math.max(10, window.innerHeight - rect.height - 10) + 'px';
  });
}

function closeMenus() {
  document.querySelectorAll('#ctx-menu-active').forEach(el => el.remove());
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
  // 点击空白关闭菜单
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#ctx-menu-active')) closeMenus();
  });
}

export function initBookshelf() {
  bind();
  load();
}
export { load as refreshShelf, refreshCategories };
