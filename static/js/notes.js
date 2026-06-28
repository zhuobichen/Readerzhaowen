// notes.js — 笔记面板（每本书隔离）：加载/渲染/增/删/编辑/点击跳转
import API from './api.js';

let bookId = null;
let bookTitle = '';
let notes = [];
let editingId = null;
let getLocation = null;  // 回调：获取当前阅读位置 {page, progress, label}
let jumpTo = null;       // 回调：跳转到指定位置 (progress) => void

const el = {
  panel: document.getElementById('notes-panel'),
  list: document.getElementById('notes-list'),
  empty: document.getElementById('notes-empty'),
  input: document.getElementById('notes-input'),
  save: document.getElementById('notes-save'),
  close: document.getElementById('notes-close'),
  bookName: document.getElementById('notes-book-name'),
  btnNotes: document.getElementById('btn-notes'),
};

function init() {
  el.save.addEventListener('click', save);
  el.close.addEventListener('click', close);
  el.btnNotes.addEventListener('click', toggle);
  // Ctrl+Enter 快速保存
  el.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
  });
  // Esc 关闭
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !el.panel.hidden) close();
  });
}

async function load(id, title, locFn, jumpFn) {
  bookId = id;
  bookTitle = title || id;
  getLocation = locFn || (() => ({ page: 0, progress: 0, label: '' }));
  jumpTo = jumpFn || (() => {});
  el.bookName.textContent = bookTitle;
  notes = await API.getNotes(bookId);
  render();
  updateBadge();
}

function toggle() {
  if (el.panel.hidden) open();
  else close();
}

function close() {
  el.panel.hidden = true;
  el.panel.classList.remove('open');
  editingId = null;
  el.input.value = '';
  el.save.textContent = '保存笔记';
  // 记住用户关闭了笔记面板，下次不再自动展开
  localStorage.setItem('notes-auto-open', 'false');
}

function open() {
  el.panel.hidden = false;
  el.panel.classList.add('open');
  // 用户主动打开，恢复自动展开
  localStorage.setItem('notes-auto-open', 'true');
  setTimeout(() => el.input.focus(), 50);
}

async function save() {
  const content = el.input.value.trim();
  if (!content || !bookId) return;
  el.save.disabled = true;
  el.save.textContent = '保存中…';
  const loc = getLocation();
  notes = await API.saveNote(bookId, {
    id: editingId || undefined,
    content,
    page: loc.page || 0,
    progress: loc.progress || 0,
  });
  el.input.value = '';
  editingId = null;
  el.save.textContent = '保存笔记';
  el.save.disabled = false;
  render();
  updateBadge();
}

async function remove(noteId, ev) {
  ev?.stopPropagation();
  if (!bookId) return;
  notes = await API.deleteNote(bookId, noteId);
  render();
  updateBadge();
}

function edit(noteId, ev) {
  ev?.stopPropagation();
  const note = notes.find(n => n.id === noteId);
  if (!note) return;
  editingId = noteId;
  el.input.value = note.content;
  el.save.textContent = '更新笔记';
  el.input.focus();
}

function jumpToNote(note) {
  if (!note) return;
  // 优先用 page (PDF/CBZ)，否则用 progress
  if (note.progress != null && note.progress > 0) {
    jumpTo(note.progress, note.page);
  } else if (note.page) {
    // 没有 progress 信息时用 page (reader.seek 内部会处理)
    jumpTo(0, note.page);
  }
}

function render() {
  if (!notes.length) {
    el.list.innerHTML = '';
    el.empty.hidden = false;
    return;
  }
  el.empty.hidden = true;
  // 倒序：最新在上
  const sorted = [...notes].sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
  el.list.innerHTML = sorted.map(n => `
    <div class="note-card" data-id="${n.id}">
      <div class="note-meta">
        <span class="note-time">${fmtTime(n.createdAt)}</span>
        ${n.page ? `<span class="note-loc" title="点击跳转到此位置">第${n.page}页 ↗</span>` : (n.progress ? `<span class="note-loc" title="点击跳转到此位置">${Math.round(n.progress * 100)}% ↗</span>` : '')}
      </div>
      <div class="note-content">${escapeHtml(n.content)}</div>
      <div class="note-actions">
        <button class="note-edit" data-act="edit">编辑</button>
        <button data-act="del">删除</button>
      </div>
    </div>`).join('');
  // 事件委托
  el.list.querySelectorAll('.note-card').forEach(card => {
    const id = card.dataset.id;
    const note = notes.find(n => n.id === id);
    card.querySelector('[data-act="del"]').addEventListener('click', (e) => remove(id, e));
    card.querySelector('[data-act="edit"]').addEventListener('click', (e) => edit(id, e));
    // 点击位置标签或卡片内容区域跳转
    const loc = card.querySelector('.note-loc');
    const content = card.querySelector('.note-content');
    const doJump = (e) => { e.stopPropagation(); jumpToNote(note); };
    if (loc) loc.addEventListener('click', doJump);
    if (content) content.addEventListener('click', doJump);
    card.style.cursor = note?.progress || note?.page ? 'pointer' : 'default';
  });
}

function updateBadge() {
  const existing = el.btnNotes.querySelector('.note-count');
  if (notes.length > 0) {
    if (existing) {
      existing.textContent = notes.length;
    } else {
      const badge = document.createElement('span');
      badge.className = 'note-count';
      badge.textContent = notes.length;
      el.btnNotes.appendChild(badge);
    }
  } else if (existing) {
    existing.remove();
  }
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const min = String(d.getMinutes()).padStart(2, '0');
  return `${m}-${day} ${h}:${min}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export default { init, load, toggle, close, open };
