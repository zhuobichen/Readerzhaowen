// ai.js 鈥?AI 鍔╂墜锛氭偓娴寜閽?+ 瀵硅瘽闈㈡澘 + 娴佸紡鍝嶅簲 + 璁剧疆 + Agent 涓婁笅鏂?import API from './api.js';

let history = [];        // 瀵硅瘽鍘嗗彶 [{role, content}]
let sending = false;     // 鏄惁姝ｅ湪鍙戦€?鎺ユ敹
let el = {};             // DOM 鍏冪礌缂撳瓨
let contextProvider = null; // 鍥炶皟锛氳幏鍙栧綋鍓嶉槄璇讳笂涓嬫枃

const SVG_ROBOT = `<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
  <rect x="4" y="7" width="16" height="12" rx="2.5"/>
  <path d="M12 7V4"/>
  <circle cx="12" cy="3" r="1.2" fill="currentColor"/>
  <circle cx="9" cy="12" r="1.5" fill="currentColor"/>
  <circle cx="15" cy="12" r="1.5" fill="currentColor"/>
  <path d="M9 16h6"/>
  <path d="M2 12v2M22 12v2"/>
</svg>`;

const SVG_GEAR = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
</svg>`;

const SVG_CLOSE = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`;

const SVG_SEND = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/></svg>`;
const SVG_CLEAR = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9"/><path d="M3 4v5h5"/></svg>`;

/** 鏋勫缓 FAB 涓庡璇濋潰鏉?DOM */
function buildUI() {
  // ---- 鎮诞鎸夐挳 ----
  const fab = document.createElement('button');
  fab.id = 'ai-fab';
  fab.className = 'ai-fab';
  fab.title = 'AI 鍔╂墜';
  fab.setAttribute('aria-label', 'AI 鍔╂墜');
  fab.innerHTML = SVG_ROBOT;
  document.body.appendChild(fab);

  // ---- 瀵硅瘽闈㈡澘 ----
  const panel = document.createElement('div');
  panel.id = 'ai-panel';
  panel.className = 'ai-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="ai-header">
      <div class="ai-title-wrap">
        <span class="ai-avatar-sm">${SVG_ROBOT}</span>
        <span class="ai-title">AI 鍔╂墜</span>
      </div>
      <div class="ai-header-tools">
        <button id="ai-clear-btn" class="ai-icon-btn" title="鏂板璇?>${SVG_CLEAR}</button>
        <button id="ai-settings-btn" class="ai-icon-btn" title="璁剧疆">${SVG_GEAR}</button>
        <button id="ai-close-btn" class="ai-icon-btn" title="鍏抽棴">${SVG_CLOSE}</button>
      </div>
    </div>
    <div class="ai-messages" id="ai-messages"></div>
    <div class="ai-input-area">
      <textarea id="ai-input" rows="1" placeholder="杈撳叆娑堟伅锛孍nter 鍙戦€?/ Shift+Enter 鎹㈣"></textarea>
      <button id="ai-send" class="ai-send-btn" title="鍙戦€?>${SVG_SEND}</button>
    </div>`;
  document.body.appendChild(panel);

  // 缂撳瓨鍏冪礌
  el.fab = fab;
  el.panel = panel;
  el.messages = panel.querySelector('#ai-messages');
  el.input = panel.querySelector('#ai-input');
  el.send = panel.querySelector('#ai-send');
  el.settingsBtn = panel.querySelector('#ai-settings-btn');
  el.closeBtn = panel.querySelector('#ai-close-btn');
}

/** 璁剧疆寮圭獥锛堝湪 index.html 涓缃級 */
function bindSettings() {
  const modal = document.getElementById('ai-settings');
  if (!modal) return;
  const endpointInp = modal.querySelector('#ai-set-endpoint');
  const keyInp = modal.querySelector('#ai-set-key');
  const modelInp = modal.querySelector('#ai-set-model');
  const saveBtn = modal.querySelector('#ai-set-save');
  const closeBtn = modal.querySelector('#ai-set-close');

  el.settingsModal = modal;
  el.settingsEndpoint = endpointInp;
  el.settingsKey = keyInp;
  el.settingsModel = modelInp;

  // 鎵撳紑璁剧疆
  el.settingsBtn.addEventListener('click', () => openSettings());
  if (closeBtn) closeBtn.addEventListener('click', () => { modal.hidden = true; });
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.hidden = true; });

  // 淇濆瓨閰嶇疆
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const cfg = {
        api_key: keyInp.value.trim(),
        endpoint: endpointInp.value.trim(),
        model: modelInp.value.trim(),
      };
      saveBtn.disabled = true;
      saveBtn.textContent = '淇濆瓨涓€?;
      try {
        await API.saveAIConfig(cfg);
        aiConfig.has_key = true;
        modal.hidden = true;
        keyInp.value = '';
        keyInp.placeholder = '宸蹭繚瀛橈紙鐣欑┖鍒欎笉淇敼锛?;
      } catch (e) {
        alert(e.message || '淇濆瓨澶辫触');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '淇濆瓨';
      }
    });
  }
}

let aiConfig = { has_key: false };  // 缂撳瓨閰嶇疆鐘舵€?
/** 鍔犺浇閰嶇疆骞堕濉缃〃鍗?*/
async function loadConfig() {
  const cfg = await API.getAIConfig();
  aiConfig = cfg;
  if (el.settingsEndpoint) el.settingsEndpoint.value = cfg.endpoint || '';
  if (el.settingsModel) el.settingsModel.value = cfg.model || '';
  if (el.settingsKey) {
    if (cfg.has_key) {
      el.settingsKey.placeholder = '宸查厤缃紙鐣欑┖鍒欎笉淇敼锛?;
    } else {
      el.settingsKey.placeholder = '杈撳叆 API Key';
    }
  }
  return cfg;
}

function openSettings() {
  loadConfig();
  el.settingsModal.hidden = false;
}

/** 鎵撳紑闈㈡澘 */
function openPanel() {
  el.panel.hidden = false;
  el.fab.classList.add('active');
  requestAnimationFrame(() => el.panel.classList.add('open'));
  setTimeout(() => el.input.focus(), 60);
  // 棣栨鎵撳紑鏄剧ず寤鸿寮曞
  if (history.length === 0 && !el.messages.querySelector('.ai-suggestions')) {
    showSuggestions();
  }
}

/** 绌虹姸鎬佸缓璁?*/
function showSuggestions() {
  const div = document.createElement('div');
  div.className = 'ai-suggestions';
  const tips = [
    '鎬荤粨杩欐湰涔︾殑涓昏鍐呭',
    '甯垜鎵句竴鏈叧浜庡巻鍙茬殑涔?,
    '杩欐湰涔︾殑浣滆€呮槸璋侊紵',
    '甯垜缁欎功鏋朵笂鐨勪功鍒嗙被',
  ];
  div.innerHTML = `<div class="ai-suggestion-title">璇曡瘯杩欎簺锛?/div>` +
    tips.map(t => `<button class="ai-suggestion-chip">${t}</button>`).join('');
  div.querySelectorAll('.ai-suggestion-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      el.input.value = btn.textContent;
      el.input.focus();
      div.remove();
    });
  });
  el.messages.appendChild(div);
}

/** 鍏抽棴闈㈡澘 */
function closePanel() {
  el.panel.classList.remove('open');
  el.fab.classList.remove('active');
  setTimeout(() => { el.panel.hidden = true; }, 240);
}

function togglePanel() {
  if (el.panel.hidden || !el.panel.classList.contains('open')) openPanel();
  else closePanel();
}

/** 杩藉姞涓€鏉℃秷鎭皵娉?*/
function addMessage(role, content) {
  const wrap = document.createElement('div');
  wrap.className = 'ai-msg ' + (role === 'user' ? 'ai-msg-user' : 'ai-msg-ai');
  if (role === 'user') {
    wrap.innerHTML = `<div class="ai-bubble ai-bubble-user"></div>`;
    wrap.querySelector('.ai-bubble').textContent = content;
  } else {
    wrap.innerHTML = `
      <div class="ai-avatar">${SVG_ROBOT}</div>
      <div class="ai-bubble ai-bubble-ai"></div>`;
    wrap.querySelector('.ai-bubble').textContent = content;
  }
  el.messages.appendChild(wrap);
  scrollToBottom();
  return wrap.querySelector('.ai-bubble');
}

/** 姝ｅ湪鎬濊€冩寚绀哄櫒 */
function showTyping() {
  const wrap = document.createElement('div');
  wrap.className = 'ai-msg ai-msg-ai ai-typing-wrap';
  wrap.id = 'ai-typing';
  wrap.innerHTML = `
    <div class="ai-avatar">${SVG_ROBOT}</div>
    <div class="ai-bubble ai-bubble-ai ai-typing"><span></span><span></span><span></span></div>`;
  el.messages.appendChild(wrap);
  scrollToBottom();
}

function removeTyping() {
  const t = document.getElementById('ai-typing');
  if (t) t.remove();
}

function scrollToBottom() {
  el.messages.scrollTop = el.messages.scrollHeight;
}

/** 鍙戦€佹秷鎭苟娴佸紡鎺ユ敹鍥炲 */
async function send() {
  if (sending) return;
  const text = el.input.value.trim();
  if (!text) return;

  // 妫€鏌?AI 鏄惁宸查厤缃?  if (!aiConfig.has_key) {
    addMessage('assistant', '璇峰厛閰嶇疆 AI API Key銆傜偣鍑诲彸涓婅璁剧疆鎸夐挳濉啓銆?);
    openSettings();
    return;
  }

  // 绉婚櫎寤鸿寮曞
  el.messages.querySelector('.ai-suggestions')?.remove();
  addMessage('user', text);
  history.push({ role: 'user', content: text });
  // 鍘嗗彶涓婇檺锛氫繚鐣欐渶杩?20 鏉★紙绾?10 杞璇濓級
  if (history.length > 20) {
    history = history.slice(-20);
  }
  el.input.value = '';
  autoGrow();
  sending = true;
  el.send.disabled = true;

  showTyping();
  let aiBubble = null;
  let firstChunk = true;

  // 鑾峰彇褰撳墠闃呰涓婁笅鏂?  const ctx = contextProvider ? contextProvider() : {};

  try {
    const resp = await API.aiChat(history, ctx);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n');
      buffer = parts.pop();
      for (const line of parts) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const payload = trimmed.slice(5).trim();
        if (!payload) continue;
        let data;
        try { data = JSON.parse(payload); } catch { continue; }

        if (data.content) {
          if (firstChunk) { removeTyping(); firstChunk = false; }
          if (!aiBubble) aiBubble = addMessage('assistant', '');
          aiBubble.textContent += data.content;
          scrollToBottom();
        }
        if (data.actions) {
          executeActions(data.actions);
        }
        if (data.done) {
          removeTyping();
        }
      }
    }
    removeTyping();

    // 鏀堕泦瀹屾暣 AI 鍥炲鍒板巻鍙?    if (aiBubble) {
      history.push({ role: 'assistant', content: aiBubble.textContent });
    } else if (firstChunk) {
      // 鏈敹鍒颁换浣曞唴瀹?      removeTyping();
      aiBubble = addMessage('assistant', '锛堟病鏈夋敹鍒板洖澶嶏紝璇锋鏌?AI 閰嶇疆鎴栫◢鍚庨噸璇曪級');
    }
  } catch (e) {
    removeTyping();
    if (!aiBubble) aiBubble = addMessage('assistant', '');
    aiBubble.textContent += `\n[鍑洪敊] ${e.message || e}`;
  } finally {
    sending = false;
    el.send.disabled = false;
    scrollToBottom();
  }
}

/** 鎵ц AI 杩斿洖鐨勫姩浣?*/
function executeActions(actions) {
  if (!Array.isArray(actions)) return;
  for (const a of actions) {
    if (a.type === 'open_book' && a.book_id) {
      location.hash = `#/book/${encodeURIComponent(a.book_id)}`;
    }
  }
}

/** textarea 鑷€傚簲楂樺害 */
function autoGrow() {
  el.input.style.height = 'auto';
  el.input.style.height = Math.min(el.input.scrollHeight, 120) + 'px';
}

/** 娓呯┖瀵硅瘽锛屽紑濮嬫柊浼氳瘽 */
function clearChat() {
  if (history.length > 0 && !confirm('娓呯┖褰撳墠瀵硅瘽锛?)) return;
  history = [];
  el.messages.innerHTML = '';
  showSuggestions();
}

function bind() {
  el.fab.addEventListener('click', togglePanel);
  el.closeBtn.addEventListener('click', closePanel);
  el.send.addEventListener('click', send);
  const clearBtn = document.getElementById('ai-clear-btn');
  if (clearBtn) clearBtn.addEventListener('click', clearChat);
  el.input.addEventListener('input', autoGrow);
  el.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  // Esc 鍏抽棴
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !el.panel.hidden) closePanel();
  });
}

function init() {
  buildUI();
  bindSettings();
  bind();
  loadConfig();
}

function setContextProvider(fn) {
  contextProvider = fn;
}

export { init, openPanel, closePanel, setContextProvider };
export default { init, openPanel, closePanel, setContextProvider };

