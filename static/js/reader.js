// reader.js — 阅读器：按格式分发 (PDF / EPUB / TXT / CBZ)，统一翻页/缩放/进度控制
import API from './api.js';
import Notes from './notes.js';

const UNSUPPORTED = new Set(['mobi', 'azw3', 'docx', 'fb2', 'cbr']);

const ui = {
  area: document.getElementById('reader-area'),
  stage: document.querySelector('.reader-stage'),
  title: document.getElementById('reader-title'),
  fmt: document.getElementById('reader-fmt'),
  pageInfo: document.getElementById('page-info'),
  pct: document.getElementById('progress-pct'),
  slider: document.getElementById('progress-slider'),
  prev: document.getElementById('page-prev'),
  next: document.getElementById('page-next'),
  zIn: document.getElementById('btn-zoom-in'),
  zOut: document.getElementById('btn-zoom-out'),
  fit: document.getElementById('btn-fit'),
  theme: document.getElementById('btn-theme'),
  mode: document.getElementById('btn-mode'),
  notes: document.getElementById('btn-notes'),
  zoomLvl: document.getElementById('zoom-level'),
  back: document.getElementById('reader-back'),
};

let active = null;     // 当前阅读器实例
let seeking = false;   // 用户正在拖动进度条
let saveTimer = null;
let lightTheme = false;
let scrollMode = localStorage.getItem('reader-mode') === 'vertical';

function showTool(groups) {
  // groups: {zoom, fit, theme, mode}
  ui.zIn.hidden = ui.zOut.hidden = ui.zoomLvl.hidden = !groups.zoom;
  ui.fit.hidden = !groups.fit;
  ui.theme.hidden = !groups.theme;
  ui.mode.hidden = !groups.mode;
}

function applyMode() {
  ui.stage.dataset.mode = scrollMode ? 'vertical' : 'horizontal';
  updateModeIcon();
  active?.setMode?.(scrollMode);
}

function updateModeIcon() {
  // 水平模式: 左右箭头; 垂直模式: 上下箭头
  const svg = ui.mode.querySelector('svg');
  if (scrollMode) {
    svg.innerHTML = '<path d="M12 3v18M3 12h18"/>';
    svg.setAttribute('stroke-width', '2');
    ui.mode.title = '当前: 上下滚动 | 点击切换为左右翻页';
  } else {
    svg.innerHTML = '<path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3"/>';
    ui.mode.title = '当前: 左右翻页 | 点击切换为上下滚动';
  }
}

function bindControls() {
  ui.prev.addEventListener('click', () => active?.prev());
  ui.next.addEventListener('click', () => active?.next());
  ui.zIn.addEventListener('click', () => active?.zoom?.(1));
  ui.zOut.addEventListener('click', () => active?.zoom?.(-1));
  ui.fit.addEventListener('click', () => active?.fit?.());
  ui.theme.addEventListener('click', () => { lightTheme = !lightTheme; applyTheme(); });
  ui.mode.addEventListener('click', () => {
    scrollMode = !scrollMode;
    localStorage.setItem('reader-mode', scrollMode ? 'vertical' : 'horizontal');
    applyMode();
  });
  ui.slider.addEventListener('input', () => {
    seeking = true;
    ui.pct.textContent = Math.round(ui.slider.value) + '%';
  });
  ui.slider.addEventListener('change', () => {
    const f = parseFloat(ui.slider.value) / 100;
    active?.seek?.(f);
    seeking = false;
  });
  document.addEventListener('keydown', onKey);
}

function onKey(e) {
  if (!active) return;
  if (location.hash.startsWith('#/book/')) {
    if (scrollMode) {
      if (e.key === 'ArrowDown') { e.preventDefault(); active.next(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); active.prev(); }
    } else {
      if (e.key === 'ArrowRight') { e.preventDefault(); active.next(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); active.prev(); }
    }
  }
}

function applyTheme() {
  document.documentElement.dataset.theme = lightTheme ? 'light' : 'dark';
  active?.setTheme?.(lightTheme ? 'light' : 'dark');
}

function updateProgress(frac, info) {
  lastFrac = frac;
  if (!seeking) {
    ui.slider.value = Math.max(0, Math.min(100, frac * 100));
    ui.pct.textContent = Math.round(frac * 100) + '%';
  }
  if (info != null) ui.pageInfo.textContent = info;
  scheduleSave(frac);
}

function scheduleSave(frac) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => active?.save(frac), 900);
}

// 即时保存：页面关闭/切换标签时，不再等防抖，直接保存
let lastFrac = 0;
function flushSave() {
  if (!active) return;
  clearTimeout(saveTimer);
  active?.save(lastFrac);
}
window.addEventListener('beforeunload', flushSave);
document.addEventListener('visibilitychange', () => { if (document.hidden) flushSave(); });

// ----------------------------- 入口 -----------------------------
async function open(book) {
  cleanup();
  ui.title.textContent = book.title || book.name;
  ui.fmt.textContent = book.format.toUpperCase();
  ui.area.innerHTML = '';
  ui.pageInfo.textContent = '加载中…';
  ui.slider.value = 0;
  ui.pct.textContent = '0%';

  const saved = await API.getProgress(book.id);
  const resume = saved?.progress ? saved : null;

  // 加载笔记（每本书隔离）
  Notes.load(
    book.id,
    book.title || book.name,
    () => active?.getLocation?.() || { page: 0, progress: 0 },
    (progress, page) => {
      if (progress > 0) active?.seek?.(progress);
      else if (page) active?.seekByPage?.(page);
    },
  );

  try {
    if (book.format === 'pdf') active = new PDFReader(book, resume);
    else if (book.format === 'epub') active = await EPUBReader.create(book, resume);
    else if (book.format === 'txt') active = new TxtReader(book, resume);
    else if (book.format === 'cbz') active = await CBZReader.create(book, resume);
    else active = new UnsupportedReader(book);
    await active.start();
    // 应用阅读模式（水平/垂直）
    applyMode();
  } catch (err) {
    showError(err);
  }
}

function showError(err) {
  ui.area.innerHTML = `<div class="unsupported"><h3>无法打开此书</h3><p class="unsupported-tip">${escapeHtml(err.message || String(err))}</p></div>`;
  showTool({});
}

function cleanup() {
  flushSave();
  clearTimeout(saveTimer);
  if (active?.destroy) { try { active.destroy(); } catch {} }
  active = null;
  ui.area.innerHTML = '';
  Notes.close();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// =====================================================================
//  PDF 阅读器
// =====================================================================
class PDFReader {
  constructor(book, resume) { this.book = book; this.resume = resume; this.page = 1; this.scale = 1.2; this.pdf = null; this.rendering = false; this.pending = null; }
  async start() {
    showTool({ zoom: true, fit: true, theme: false, mode: true });
    this.canvas = document.createElement('canvas');
    this.canvas.id = 'pdf-canvas';
    ui.area.appendChild(this.canvas);
    this.pdf = await pdfjsLib.getDocument({ url: API.fileUrl(this.book.id) }).promise;
    this.total = this.pdf.numPages;
    if (this.resume?.page) this.page = Math.min(this.resume.page, this.total);
    await this.fit();
    window.addEventListener('resize', this._onResize = () => this.fit());
  }
  async render() {
    if (this.rendering) { this.pending = this.page; return; }
    this.rendering = true;
    try {
      const page = await this.pdf.getPage(this.page);
      const vp = page.getViewport({ scale: this.scale * (window.devicePixelRatio || 1) });
      const ctx = this.canvas.getContext('2d');
      this.canvas.width = vp.width; this.canvas.height = vp.height;
      this.canvas.style.width = (vp.width / (window.devicePixelRatio || 1)) + 'px';
      this.canvas.style.height = (vp.height / (window.devicePixelRatio || 1)) + 'px';
      await page.render({ canvasContext: ctx, viewport: vp }).promise;
      this.updateZoomLabel();
      ui.area.scrollTop = 0;  // 翻页后回到顶部
      updateProgress((this.page - 1) / Math.max(1, this.total - 1), `${this.page} / ${this.total}`);
    } finally {
      this.rendering = false;
      if (this.pending) { const p = this.pending; this.pending = null; this.page = p; this.render(); }
    }
  }
  async fit() {
    const page = await this.pdf.getPage(this.page);
    const base = page.getViewport({ scale: 1 });
    const avail = ui.area.clientWidth - 48;
    this.scale = avail / base.width;
    await this.render();
  }
  zoom(dir) {
    this.scale *= dir > 0 ? 1.15 : 1 / 1.15;
    this.scale = Math.max(0.4, Math.min(6, this.scale));
    this.render();
  }
  updateZoomLabel() { ui.zoomLvl.textContent = Math.round(this.scale * 100) + '%'; }
  next() { if (this.page < this.total) { this.page++; this.render(); } }
  prev() { if (this.page > 1) { this.page--; this.render(); } }
  seek(f) { this.page = Math.max(1, Math.min(this.total, Math.round(f * (this.total - 1)) + 1)); this.render(); }
  seekByPage(page) { this.page = Math.max(1, Math.min(this.total, page)); this.render(); }
  getLocation() { return { page: this.page, progress: (this.page - 1) / Math.max(1, this.total - 1), label: `第${this.page}页` }; }
  setMode(vertical) {
    // 清理旧的 wheel 监听
    if (this._onWheel) { ui.area.removeEventListener('wheel', this._onWheel); this._onWheel = null; }
    if (this._wheelLock) { clearTimeout(this._wheelLock); this._wheelLock = null; }
    if (vertical) {
      // 垂直模式：滚轮在页面边界时翻页
      this._onWheel = (e) => {
        if (this.rendering) return;
        const area = ui.area;
        const atBottom = area.scrollTop + area.clientHeight >= area.scrollHeight - 3;
        const atTop = area.scrollTop <= 3;
        if (e.deltaY > 0 && atBottom) {
          e.preventDefault();
          if (this._wheelLock) return;
          this.next();
          this._wheelLock = setTimeout(() => { this._wheelLock = null; }, 350);
        } else if (e.deltaY < 0 && atTop) {
          e.preventDefault();
          if (this._wheelLock) return;
          this.prev();
          this._wheelLock = setTimeout(() => { this._wheelLock = null; }, 350);
        }
      };
      ui.area.addEventListener('wheel', this._onWheel, { passive: false });
    }
  }
  save(frac) { API.saveProgress(this.book.id, { progress: frac, page: this.page, total: this.total }); }
  destroy() { window.removeEventListener('resize', this._onResize); if (this._onWheel) ui.area.removeEventListener('wheel', this._onWheel); if (this._wheelLock) clearTimeout(this._wheelLock); try { this.pdf?.destroy(); } catch {} }
}

// =====================================================================
//  EPUB 阅读器
// =====================================================================
class EPUBReader {
  static async create(book, resume) { return new EPUBReader(book, resume); }
  constructor(book, resume) { this.book = book; this.resume = resume; this.cfi = resume?.cfi || null; this.currentProgress = 0; }
  async start() {
    showTool({ zoom: false, fit: false, theme: true, mode: true });
    this.host = document.createElement('div');
    this.host.id = 'epub-viewer';
    this.host.style.cssText = 'position:absolute;inset:0;';
    ui.area.appendChild(this.host);
    this.bookObj = ePub(API.fileUrl(this.book.id));
    await this.bookObj.ready;
    this.rendition = this.bookObj.renderTo(this.host, {
      width: '100%', height: '100%', flow: scrollMode ? 'scrolled' : 'paginated', spread: 'none', allowScriptedContent: false,
    });
    this.registerThemes();
    this.rendition.themes.select(lightTheme ? 'light' : 'dark');
    await this.rendition.display(this.cfi || undefined);
    this.rendition.on('relocated', (loc) => this.onRelocate(loc));
    await this.bookObj.locations.generate(1024);
    window.addEventListener('resize', this._onResize = () => this.rendition?.resize?.());
  }
  registerThemes() {
    this.rendition.themes.register('dark', {
      body: { background: 'transparent !important', color: '#e8e0d4' },
      p: { color: '#e8e0d4', 'line-height': '1.8' },
      a: { color: '#d8a65a' },
      'h1,h2,h3': { color: '#ece4d6' },
    });
    this.rendition.themes.register('light', {
      body: { background: 'transparent !important', color: '#2a2118' },
      p: { color: '#2a2118', 'line-height': '1.8' },
      a: { color: '#a9702f' },
    });
  }
  onRelocate(loc) {
    const start = loc?.start || loc;
    this.cfi = start.cfi;
    let frac = start.percentage;
    if (frac == null && this.bookObj.locations.length()) {
      frac = this.bookObj.locations.percentageFromCfi(this.cfi);
    }
    frac = frac || 0;
    this.currentProgress = frac;
    const pct = Math.round(frac * 100);
    updateProgress(frac, `${pct}% · 第 ${Math.max(1, start.location || 1)} 处`);
  }
  next() { this.rendition.next(); }
  prev() { this.rendition.prev(); }
  seek(f) {
    if (!this.bookObj.locations.length()) return;
    const cfi = this.bookObj.locations.cfiFromPercentage(Math.min(0.999, Math.max(0, f)));
    this.cfi = cfi; this.rendition.display(cfi);
  }
  seekByPage(page) { /* EPUB 用 CFI 定位，走 seek(progress) 路径 */ }
  setTheme(t) { this.rendition?.themes.select(t); }
  getLocation() { return { page: 0, progress: this.currentProgress, label: `${Math.round(this.currentProgress * 100)}%` }; }
  setMode(vertical) {
    if (!this.rendition) return;
    // epub.js 原生支持 flow 切换
    this.rendition.flow(vertical ? 'scrolled' : 'paginated');
  }
  save(frac) { API.saveProgress(this.book.id, { progress: frac, cfi: this.cfi }); }
  destroy() {
    window.removeEventListener('resize', this._onResize);
    try { this.rendition?.destroy(); } catch {}
    try { this.bookObj?.destroy(); } catch {}
  }
}

// =====================================================================
//  TXT 阅读器（按视口分页滚动）
// =====================================================================
class TxtReader {
  constructor(book, resume) { this.book = book; this.resume = resume; this._frac = 0; }
  async start() {
    showTool({ zoom: true, fit: false, theme: true, mode: true });
    this.box = document.createElement('div');
    this.box.className = 'txt-reader';
    ui.area.appendChild(this.box);
    const buf = await (await fetch(API.fileUrl(this.book.id))).arrayBuffer();
    this.text = decodeText(buf);
    this.box.textContent = this.text;
    await new Promise(r => requestAnimationFrame(r));
    this.box.fontSize = 17; this._scale = 1;
    this.box.addEventListener('scroll', () => this.onScroll(), { passive: true });
    window.addEventListener('resize', this._onResize = () => this.onScroll());
    if (this.resume?.progress) {
      this.box.scrollTop = this.resume.progress * (this.box.scrollHeight - this.box.clientHeight);
    }
    this.onScroll();
  }
  onScroll() {
    const max = this.box.scrollHeight - this.box.clientHeight;
    const frac = max > 0 ? this.box.scrollTop / max : 0;
    this._frac = frac;
    const pct = Math.round(frac * 100);
    updateProgress(frac, `${pct}%`);
  }
  zoom(dir) {
    this._scale *= dir > 0 ? 1.1 : 1 / 1.1;
    this._scale = Math.max(0.6, Math.min(2.4, this._scale));
    this.box.style.fontSize = (17 * this._scale) + 'px';
    ui.zoomLvl.textContent = Math.round(this._scale * 100) + '%';
  }
  next() { this.box.scrollBy({ top: this.box.clientHeight * 0.92, behavior: 'smooth' }); }
  prev() { this.box.scrollBy({ top: -this.box.clientHeight * 0.92, behavior: 'smooth' }); }
  seek(f) { const max = this.box.scrollHeight - this.box.clientHeight; this.box.scrollTop = f * max; }
  seekByPage(page) { /* TXT 无分页概念，忽略 */ }
  getLocation() { return { page: 0, progress: this._frac, label: `${Math.round(this._frac * 100)}%` }; }
  setMode(vertical) { /* TXT 始终滚动；CSS 控制导航按钮显隐 */ }
  setTheme() {}
  save(frac) { API.saveProgress(this.book.id, { progress: frac }); }
  destroy() { window.removeEventListener('resize', this._onResize); }
}

// =====================================================================
//  CBZ 漫画阅读器
// =====================================================================
class CBZReader {
  static async create(book, resume) {
    const r = new CBZReader(book, resume);
    await r.load();
    return r;
  }
  constructor(book, resume) { this.book = book; this.resume = resume; this.idx = 0; }
  async load() {
    const buf = await (await fetch(API.fileUrl(this.book.id))).arrayBuffer();
    const zip = await JSZip.loadAsync(buf);
    this.entries = Object.values(zip.files)
      .filter(f => !f.dir && /\.(jpe?g|png|webp|gif|bmp)$/i.test(f.name))
      .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
    this.total = this.entries.length;
  }
  async start() {
    showTool({ zoom: false, fit: false, theme: false, mode: true });
    this.wrap = document.createElement('div');
    this.wrap.className = 'cbz-reader';
    this.img = document.createElement('img');
    this.wrap.appendChild(this.img);
    ui.area.appendChild(this.wrap);
    if (this.resume?.page) this.idx = Math.min(this.resume.page, this.total - 1);
    await this.render();
  }
  async render() {
    if (!this.total) return;
    const blob = await this.entries[this.idx].async('blob');
    if (this._url) URL.revokeObjectURL(this._url);
    this._url = URL.createObjectURL(blob);
    this.img.src = this._url;
    updateProgress(this.total > 1 ? this.idx / (this.total - 1) : 0, `${this.idx + 1} / ${this.total}`);
  }
  next() { if (this.idx < this.total - 1) { this.idx++; this.render(); } }
  prev() { if (this.idx > 0) { this.idx--; this.render(); } }
  seek(f) { this.idx = Math.max(0, Math.min(this.total - 1, Math.round(f * (this.total - 1)))); this.render(); }
  seekByPage(page) { this.idx = Math.max(0, Math.min(this.total - 1, page - 1)); this.render(); }
  getLocation() { return { page: this.idx + 1, progress: this.total > 1 ? this.idx / (this.total - 1) : 0, label: `${this.idx + 1}/${this.total}` }; }
  setMode(vertical) {
    if (this._onWheel) { ui.area.removeEventListener('wheel', this._onWheel); this._onWheel = null; }
    if (this._wheelLock) { clearTimeout(this._wheelLock); this._wheelLock = null; }
    if (vertical) {
      this._onWheel = (e) => {
        if (Math.abs(e.deltaY) < 10) return;
        if (this._wheelLock) return;
        this._wheelLock = setTimeout(() => { this._wheelLock = null; }, 400);
        if (e.deltaY > 0) this.next();
        else this.prev();
      };
      ui.area.addEventListener('wheel', this._onWheel, { passive: true });
    }
  }
  save(frac) { API.saveProgress(this.book.id, { progress: frac, page: this.idx, total: this.total }); }
  destroy() { if (this._url) URL.revokeObjectURL(this._url); if (this._onWheel) ui.area.removeEventListener('wheel', this._onWheel); if (this._wheelLock) clearTimeout(this._wheelLock); }
}

// =====================================================================
//  不支持格式
// =====================================================================
class UnsupportedReader {
  constructor(book) { this.book = book; }
  async start() {
    showTool({});
    const tpl = document.getElementById('tpl-unsupported');
    const node = tpl.content.cloneNode(true);
    node.querySelector('.unsupported-fmt').textContent = `.${this.book.format}`;
    ui.area.innerHTML = '';
    ui.area.appendChild(node);
    ui.pageInfo.textContent = '—';
    updateProgress(0, '—');
  }
  getLocation() { return { page: 0, progress: 0, label: '' }; }
  next() {} prev() {} seek() {} save() {} setMode() {} destroy() {}
}

function decodeText(buf) {
  const utf8 = new TextDecoder('utf-8', { fatal: false }).decode(buf);
  // 简单启发：大量替换符则尝试 GBK
  const repl = (utf8.match(/\uFFFD/g) || []).length;
  if (repl > utf8.length * 0.02) {
    try { return new TextDecoder('gbk').decode(buf); } catch { return utf8; }
  }
  return utf8;
}

export const Reader = { open, cleanup, init: bindControls, applyTheme, back: () => ui.back, getLocation: () => active?.getLocation?.() || { page: 0, progress: 0, label: '' } };
