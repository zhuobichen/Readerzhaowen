// store.js — IndexedDB 封面缓存（避免重复提取，提速二次进入）
const DB_NAME = 'yuewei-reader';
const STORE = 'covers';
const VERSION = 1;

let dbp = null;
function db() {
  if (dbp) return dbp;
  dbp = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, VERSION);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}

const CoverStore = {
  async get(id) {
    try {
      const d = await db();
      return await new Promise((res) => {
        const tx = d.transaction(STORE, 'readonly').objectStore(STORE).get(id);
        tx.onsuccess = () => res(tx.result || null);
        tx.onerror = () => res(null);
      });
    } catch { return null; }
  },
  async put(id, dataUrl) {
    try {
      const d = await db();
      return await new Promise((res) => {
        const tx = d.transaction(STORE, 'readwrite').objectStore(STORE).put(dataUrl, id);
        tx.onsuccess = () => res(true);
        tx.onerror = () => res(false);
      });
    } catch { return false; }
  },
};

// 由书名生成稳定的占位色板（暖色系，避免突兀）
function paletteFor(seed) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const palettes = [
    ['#3a2e22', '#6b4a30'],
    ['#2c2a33', '#4a4358'],
    ['#33262a', '#6b3a3a'],
    ['#28322b', '#3f5a44'],
    ['#34292a', '#5e3b3e'],
    ['#2a2d33', '#3f5366'],
    ['#352b24', '#6b5230'],
    ['#2b2633', '#473a5e'],
  ];
  return palettes[h % palettes.length];
}

// 生成文字封面 dataURL（无封面文件时的兜底）
function makePlaceholderCover(title, fmt) {
  const W = 240, H = 360;
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  const [a, b] = paletteFor(title + fmt);
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, a); g.addColorStop(1, b);
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  // 书脊
  ctx.fillStyle = 'rgba(0,0,0,0.28)'; ctx.fillRect(12, 0, 3, H);
  // 标题
  ctx.fillStyle = 'rgba(255,255,255,0.92)';
  ctx.font = '600 19px Georgia, serif';
  ctx.textBaseline = 'top';
  wrapText(ctx, title, 26, 34, W - 48, 24, 6);
  // 格式角标
  ctx.fillStyle = 'rgba(255,255,255,0.45)';
  ctx.font = '500 11px monospace';
  ctx.fillText((fmt || '').toUpperCase(), 26, H - 28);
  return cv.toDataURL('image/jpeg', 0.82);
}

function wrapText(ctx, text, x, y, maxW, lh, maxLines) {
  const chars = [...text];
  let line = '', lineNo = 0;
  for (let i = 0; i < chars.length; i++) {
    const test = line + chars[i];
    if (ctx.measureText(test).width > maxW && line) {
      ctx.fillText(line, x, y + lineNo * lh);
      line = chars[i]; lineNo++;
      if (lineNo >= maxLines) { return; }
    } else { line = test; }
  }
  if (line && lineNo < maxLines) ctx.fillText(line, x, y + lineNo * lh);
}

export { CoverStore, paletteFor, makePlaceholderCover };
