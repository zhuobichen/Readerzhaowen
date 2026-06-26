// ai.js — AI 助手：悬浮按钮 + 对话面板 + 流式响应 + 设置 + Agent 上下文
import API from './api.js';

let history = [];        // 对话历史 [{role, content}]
let sending = false;     // 是否正在发送/接收
let el = {};             // DOM 元素缓存
let contextProvider = null; // 回调：获取当前阅读上下文

const SVG_SPARKLES = `<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 3l1.6 4.6L18 9l-4.4 1.4L12 15l-1.6-4.6L6 9l4.4-1.4z"/>
  <path d="M18 14l.8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8z"/>
  <path d="M6 15l.7 1.9L8.6 17.6 6.7 18.3 6 20l-.7-1.7L3.4 17.6l1.9-.7z"/>
</svg>`;

const SVG_GEAR = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
</svg>`;

const SVG_CLOSE = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`;

const SVG_SEND = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/></svg>`;
const SVG_CLEAR = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9"/><path d="M3 4v5h5"/></svg>`;

/** 构建 FAB 与对话面板 DOM */
function buildUI() {
  // ---- 悬浮按钮 ----
  const fab = document.createElement('button');
  fab.id = 'ai-fab';
  fab.className = 'ai-fab';
  fab.title = 'AI 助手';
  fab.setAttribute('aria-label', 'AI 助手');
  fab.innerHTML = SVG_SPARKLES;
  document.body.appendChild(fab);

  // ---- 对话面板 ----
  const panel = document.createElement('div');
  panel.id = 'ai-panel';
  panel.className = 'ai-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="ai-header">
      <div class="ai-title-wrap">
        <span class="ai-avatar-sm">${SVG_SPARKLES}</span>
        <span class="ai-title">AI 助手</span>
      </div>
      <div class="ai-header-tools">
        <button id="ai-clear-btn" class="ai-icon-btn" title="新对话">${SVG_CLEAR}</button>
        <button id="ai-settings-btn" class="ai-icon-btn" title="设置">${SVG_GEAR}</button>
        <button id="ai-close-btn" class="ai-icon-btn" title="关闭">${SVG_CLOSE}</button>
      </div>
    </div>
    <div class="ai-messages" id="ai-messages"></div>
    <div class="ai-input-area">
      <textarea id="ai-input" rows="1" placeholder="输入消息，Enter 发送 / Shift+Enter 换行"></textarea>
      <button id="ai-send" class="ai-send-btn" title="发送">${SVG_SEND}</button>
    </div>`;
  document.body.appendChild(panel);

  // 缓存元素
  el.fab = fab;
  el.panel = panel;
  el.messages = panel.querySelector('#ai-messages');
  el.input = panel.querySelector('#ai-input');
  el.send = panel.querySelector('#ai-send');
  el.settingsBtn = panel.querySelector('#ai-settings-btn');
  el.closeBtn = panel.querySelector('#ai-close-btn');
}

/** 设置弹窗（在 index.html 中预置） */
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

  // 打开设置
  el.settingsBtn.addEventListener('click', () => openSettings());
  if (closeBtn) closeBtn.addEventListener('click', () => { modal.hidden = true; });
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.hidden = true; });

  // 保存配置
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const cfg = {
        api_key: keyInp.value.trim(),
        endpoint: endpointInp.value.trim(),
        model: modelInp.value.trim(),
      };
      saveBtn.disabled = true;
      saveBtn.textContent = '保存中…';
      try {
        await API.saveAIConfig(cfg);
        aiConfig.has_key = true;
        modal.hidden = true;
        keyInp.value = '';
        keyInp.placeholder = '已保存（留空则不修改）';
      } catch (e) {
        alert(e.message || '保存失败');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存';
      }
    });
  }
}

let aiConfig = { has_key: false };  // 缓存配置状态

/** 加载配置并预填设置表单 */
async function loadConfig() {
  const cfg = await API.getAIConfig();
  aiConfig = cfg;
  if (el.settingsEndpoint) el.settingsEndpoint.value = cfg.endpoint || '';
  if (el.settingsModel) el.settingsModel.value = cfg.model || '';
  if (el.settingsKey) {
    if (cfg.has_key) {
      el.settingsKey.placeholder = '已配置（留空则不修改）';
    } else {
      el.settingsKey.placeholder = '输入 API Key';
    }
  }
  return cfg;
}

function openSettings() {
  loadConfig();
  el.settingsModal.hidden = false;
}

/** 打开面板 */
function openPanel() {
  el.panel.hidden = false;
  el.fab.classList.add('active');
  requestAnimationFrame(() => el.panel.classList.add('open'));
  setTimeout(() => el.input.focus(), 60);
  // 首次打开显示建议引导
  if (history.length === 0 && !el.messages.querySelector('.ai-suggestions')) {
    showSuggestions();
  }
}

/** 空状态建议 */
function showSuggestions() {
  const div = document.createElement('div');
  div.className = 'ai-suggestions';
  const tips = [
    '总结这本书的主要内容',
    '帮我找一本关于历史的书',
    '这本书的作者是谁？',
    '帮我给书架上的书分类',
  ];
  div.innerHTML = `<div class="ai-suggestion-title">试试这些：</div>` +
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

/** 关闭面板 */
function closePanel() {
  el.panel.classList.remove('open');
  el.fab.classList.remove('active');
  setTimeout(() => { el.panel.hidden = true; }, 240);
}

function togglePanel() {
  if (el.panel.hidden || !el.panel.classList.contains('open')) openPanel();
  else closePanel();
}

/** 追加一条消息气泡 */
function addMessage(role, content) {
  const wrap = document.createElement('div');
  wrap.className = 'ai-msg ' + (role === 'user' ? 'ai-msg-user' : 'ai-msg-ai');
  if (role === 'user') {
    wrap.innerHTML = `<div class="ai-bubble ai-bubble-user"></div>`;
    wrap.querySelector('.ai-bubble').textContent = content;
  } else {
    wrap.innerHTML = `
      <div class="ai-avatar">${SVG_SPARKLES}</div>
      <div class="ai-bubble ai-bubble-ai"></div>`;
    wrap.querySelector('.ai-bubble').textContent = content;
  }
  el.messages.appendChild(wrap);
  scrollToBottom();
  return wrap.querySelector('.ai-bubble');
}

/** 正在思考指示器 */
function showTyping() {
  const wrap = document.createElement('div');
  wrap.className = 'ai-msg ai-msg-ai ai-typing-wrap';
  wrap.id = 'ai-typing';
  wrap.innerHTML = `
    <div class="ai-avatar">${SVG_SPARKLES}</div>
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

/** 发送消息并流式接收回复 */
async function send() {
  if (sending) return;
  const text = el.input.value.trim();
  if (!text) return;

  // 检查 AI 是否已配置
  if (!aiConfig.has_key) {
    addMessage('assistant', '请先配置 AI API Key。点击右上角设置按钮填写。');
    openSettings();
    return;
  }

  // 移除建议引导
  el.messages.querySelector('.ai-suggestions')?.remove();
  addMessage('user', text);
  history.push({ role: 'user', content: text });
  // 历史上限：保留最近 20 条（约 10 轮对话）
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

  // 获取当前阅读上下文
  const ctx = contextProvider ? contextProvider() : {};

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

    // 收集完整 AI 回复到历史
    if (aiBubble) {
      history.push({ role: 'assistant', content: aiBubble.textContent });
    } else if (firstChunk) {
      // 未收到任何内容
      removeTyping();
      aiBubble = addMessage('assistant', '（没有收到回复，请检查 AI 配置或稍后重试）');
    }
  } catch (e) {
    removeTyping();
    if (!aiBubble) aiBubble = addMessage('assistant', '');
    aiBubble.textContent += `\n[出错] ${e.message || e}`;
  } finally {
    sending = false;
    el.send.disabled = false;
    scrollToBottom();
  }
}

/** 执行 AI 返回的动作 */
function executeActions(actions) {
  if (!Array.isArray(actions)) return;
  for (const a of actions) {
    if (a.type === 'open_book' && a.book_id) {
      location.hash = `#/book/${encodeURIComponent(a.book_id)}`;
    }
  }
}

/** textarea 自适应高度 */
function autoGrow() {
  el.input.style.height = 'auto';
  el.input.style.height = Math.min(el.input.scrollHeight, 120) + 'px';
}

/** 清空对话，开始新会话 */
function clearChat() {
  if (history.length > 0 && !confirm('清空当前对话？')) return;
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
  // Esc 关闭
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
