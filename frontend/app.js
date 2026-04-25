/* ── NyayaVoice — Frontend UI Logic (Backend-Connected) ──── */

(function () {
  'use strict';

  // Prefer same-origin backend so local frontend talks to the local server.
  const SAME_ORIGIN_BASE =
    window.location && /^https?:$/i.test(window.location.protocol)
      ? window.location.origin
      : '';
  const API_BASE = window.NYAYAVOICE_BACKEND_URL || SAME_ORIGIN_BASE || 'https://aivoice.up.railway.app';

  /* ── State ───────────────────────────────────────────────── */
  let userId = localStorage.getItem('nyayavoice_user_id') || ('user_' + Math.random().toString(36).slice(2, 10));
  localStorage.setItem('nyayavoice_user_id', userId);

  let conversationHistory = [];
  let generatedDocs = JSON.parse(localStorage.getItem('nyayavoice_docs') || '[]');
  let messageCount = parseInt(localStorage.getItem('nyayavoice_msg_count') || '0', 10);

  /* ── Vapi ────────────────────────────────────────────────── */
  let vapiInstance = null;
  let vapiPublicKey = '';
  let vapiCallActive = false;
  let vapiSessionMode = null;
  let vapiSessionLanguage = null;
  let pendingTypedMessages = [];
  let recentSpokenAssistantTexts = [];
  let lastSpeechStartAt = 0;
  let pendingSpeechFallbackTimer = null;
  let pendingSpeechRequestId = 0;
  let activeSpeechRequestId = 0;
  let browserSpeechActive = false;
  let browserSpeechPaused = false;
  let currentBrowserUtterance = null;
  let currentAssistantSpeechText = '';
  let resumableAssistantSpeech = null;
  let pendingVapiSpeech = null;
  let pendingVapiReadyResolvers = [];
  let vapiUnavailableReason = null;
  let browserVoiceFallbackEnabled = true;

  async function waitForVapiSdk(timeoutMs = 5000) {
    const start = Date.now();
    while (!window.Vapi && Date.now() - start < timeoutMs) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    return window.Vapi || null;
  }

  async function initVapi() {
    // Use public key directly (Vapi public key is safe to embed in frontend)
    vapiPublicKey = '79d4aa17-ee30-45af-8aa4-6d769a1b794e';
    const VapiSdk = await waitForVapiSdk();
    if (vapiPublicKey && VapiSdk) {
      vapiInstance = new VapiSdk(vapiPublicKey);
      console.info('Vapi initialized successfully');
      setupVapiEvents();
    } else {
      console.warn('Vapi not initialized', { hasPublicKey: !!vapiPublicKey, hasSdk: !!VapiSdk });
    }
  }

  function resolvePendingVapiReady() {
    if (!pendingVapiReadyResolvers.length) return;
    const resolvers = pendingVapiReadyResolvers.slice();
    pendingVapiReadyResolvers = [];
    resolvers.forEach(resolve => resolve(true));
  }

  function rejectPendingVapiReady() {
    if (!pendingVapiReadyResolvers.length) return;
    const resolvers = pendingVapiReadyResolvers.slice();
    pendingVapiReadyResolvers = [];
    resolvers.forEach(resolve => resolve(false));
  }

  function waitForVapiReady(timeoutMs = 4000) {
    if (vapiCallActive) return Promise.resolve(true);
    return new Promise(resolve => {
      const timer = setTimeout(() => {
        pendingVapiReadyResolvers = pendingVapiReadyResolvers.filter(item => item !== finish);
        resolve(false);
      }, timeoutMs);

      const finish = (ready) => {
        clearTimeout(timer);
        resolve(ready);
      };

      pendingVapiReadyResolvers.push(finish);
    });
  }

  function setupVapiEvents() {
    if (!vapiInstance) return;

    vapiInstance.on('speech-start', () => {
      lastSpeechStartAt = Date.now();
      if (browserSpeechActive) {
        console.info('Browser fallback is still speaking, postponing Vapi speech');
        try {
          vapiInstance.stop();
        } catch (err) {
          console.error('Vapi stop while waiting for browser speech failed:', err);
        }
        vapiCallActive = false;
        vapiSessionMode = null;
        vapiSessionLanguage = null;
        return;
      }
      clearPendingSpeechFallback();
      stopBrowserSpeech();
      newMicBtn.classList.add('listening');
      newMicStatus.textContent = t('vcListening');
    });
    vapiInstance.on('speech-end', () => {
      clearPendingSpeechFallback();
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcProcessing');
    });
    vapiInstance.on('message', (msg) => {
      if (msg.type === 'status-update') {
        if (msg.status === 'active' || msg.status === 'started' || msg.status === 'in-progress') {
          vapiCallActive = true;
          resolvePendingVapiReady();
        }
      }
      if (msg.type === 'transcript' && msg.transcriptType === 'final') {
        if (vapiSessionMode === 'chat') {
          return;
        }
        if (msg.role === 'user') {
          if (consumePendingTypedMessage(msg.transcript)) return;
          showPage('chat');
          if (!isDuplicateConversationTurn('user', msg.transcript)) {
            addMessage(msg.transcript, true, 'text');
            conversationHistory.push({ role: 'user', text: msg.transcript });
          }
        } else if (msg.role === 'assistant') {
          removeTypingIndicator();
          console.info('Vapi assistant transcript received:', { sessionMode: vapiSessionMode, transcriptType: msg.transcriptType });
          if (!isDuplicateConversationTurn('assistant', msg.transcript)) {
            addMessage(msg.transcript, false, 'markdown');
            conversationHistory.push({ role: 'assistant', text: msg.transcript });
            messageCount++;
            localStorage.setItem('nyayavoice_msg_count', messageCount);
            updateStats();
          }
        }
      }
    });
    vapiInstance.on('call-end', () => {
      const shouldFallbackToBrowser = !!pendingSpeechFallbackTimer && !browserSpeechActive;
      rejectPendingVapiReady();
      clearPendingSpeechFallback();
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
      if (shouldFallbackToBrowser && conversationHistory.length) {
        const lastAssistantMessage = [...conversationHistory].reverse().find(msg => msg.role === 'assistant' && msg.text);
        if (lastAssistantMessage) {
          console.warn('Vapi call ended before speaking completed, using browser speech fallback');
          startBrowserSpeechFallback(lastAssistantMessage.text, activeSpeechRequestId);
        }
      }
    });
    vapiInstance.on('error', (err) => {
      console.error('Vapi error:', err);
      const shouldFallbackToBrowser = !!pendingSpeechFallbackTimer && !browserSpeechActive;
      rejectPendingVapiReady();
      if (err && err.type === 'daily-error') {
        vapiUnavailableReason = 'daily_limit_reached';
        console.warn('Vapi unavailable for this session: daily limit reached or account quota exhausted');
      }
      clearPendingSpeechFallback();
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
      removeTypingIndicator();
      if (shouldFallbackToBrowser && conversationHistory.length) {
        const lastAssistantMessage = [...conversationHistory].reverse().find(msg => msg.role === 'assistant' && msg.text);
        if (lastAssistantMessage) {
          console.warn('Vapi errored before speech playback, using browser speech fallback');
          startBrowserSpeechFallback(lastAssistantMessage.text, activeSpeechRequestId);
        }
      }
    });
  }

  /* ── DOM refs ──────────────────────────────────────────── */
  const sidebar = document.getElementById('sidebar');
  const mainContent = document.getElementById('mainContent');
  const mobileHeader = document.getElementById('mobileHeader');
  const hamburgerBtn = document.getElementById('hamburgerBtn');
  const langSwitch = document.getElementById('langSwitch');
  const langMobile = document.getElementById('langSwitchMobile');
  const settingsLang = document.getElementById('settingsLang');
  const themeToggle = document.getElementById('themeToggle');
  const micBtn = document.getElementById('micBtn');
  const micStatus = document.getElementById('micStatus');
  const chatInput = document.getElementById('chatInput');
  const stopAudioBtn = document.getElementById('stopAudioBtn');
  const sendBtn = document.getElementById('sendBtn');
  const chatMessages = document.getElementById('chatMessages');
  const offlineBanner = document.getElementById('offlineBanner');
  const emergencyContactsInput = document.getElementById('emergencyContacts');
  const emergencyTypeSelect = document.getElementById('emergencyType');
  const emergencyModeSelect = document.getElementById('emergencyMode');
  const emergencyCustomMessageInput = document.getElementById('emergencyCustomMessage');
  const emergencyLocationStatus = document.getElementById('emergencyLocationStatus');
  const emergencyAlertStatus = document.getElementById('emergencyAlertStatus');
  const fetchEmergencyLocationBtn = document.getElementById('fetchEmergencyLocationBtn');
  const sendEmergencyAlertBtn = document.getElementById('sendEmergencyAlertBtn');
  let emergencyLocation = null;

  function on(el, eventName, handler) {
    if (el) el.addEventListener(eventName, handler);
  }

  let overlay = document.createElement('div');
  overlay.className = 'sidebar-overlay';
  document.body.appendChild(overlay);

  /* ── NAVIGATION ────────────────────────────────────────── */
  const navBtns = document.querySelectorAll('.nav-btn[data-page]');
  const pages = document.querySelectorAll('.page');

  function showPage(pageId) {
    pages.forEach(p => p.classList.remove('active'));
    navBtns.forEach(b => b.classList.remove('active'));
    const target = document.getElementById('page-' + pageId);
    if (target) target.classList.add('active');
    navBtns.forEach(b => { if (b.dataset.page === pageId) b.classList.add('active'); });
    closeSidebar();
    if (mainContent) {
      mainContent.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    if (pageId === 'docs') renderDocsList();
  }

  navBtns.forEach(btn => btn.addEventListener('click', () => showPage(btn.dataset.page)));

  document.querySelectorAll('.quick-action-card[data-page]').forEach(card => {
    card.addEventListener('click', () => showPage(card.dataset.page));
  });

  /* ── SIDEBAR MOBILE ────────────────────────────────────── */
  function openSidebar() {
    if (!sidebar) return;
    sidebar.classList.add('open');
    overlay.classList.add('active');
  }
  function closeSidebar() {
    if (sidebar) sidebar.classList.remove('open');
    overlay.classList.remove('active');
  }
  on(hamburgerBtn, 'click', () => sidebar && sidebar.classList.contains('open') ? closeSidebar() : openSidebar());
  on(overlay, 'click', closeSidebar);

  /* ── LANGUAGE SWITCHING ────────────────────────────────── */
  function switchLang(code) {
    applyLang(code);
    [langSwitch, langMobile, settingsLang].forEach(sel => { if (sel) sel.value = code; });
    updateStopAudioButtonLabel();
    clearPendingSpeechFallback();
    stopBrowserSpeech();
    if (vapiInstance && vapiCallActive) {
      try {
        vapiInstance.stop();
      } catch (err) {
        console.error('Vapi stop on language switch failed:', err);
      }
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
    }
  }
  on(langSwitch, 'change', e => switchLang(e.target.value));
  on(langMobile, 'change', e => switchLang(e.target.value));
  on(settingsLang, 'change', e => switchLang(e.target.value));

  /* ── THEME TOGGLE ──────────────────────────────────────── */
  function initTheme() {
    const savedTheme = localStorage.getItem('nyayavoice_theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    if (themeToggle) {
      themeToggle.addEventListener('click', toggleTheme);
    }
  }

  function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('nyayavoice_theme', newTheme);
  }

  /* ── HELPER: API call ──────────────────────────────────── */
  async function apiCall(endpoint, body) {
    const res = await fetch(API_BASE + endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `API error ${res.status}`);
    }
    return res.json();
  }

  /* ── CHAT ──────────────────────────────────────────────── */
  function parseEmergencyContacts(value) {
    return String(value || '')
      .split(/[\n,]+/)
      .map(item => item.trim())
      .filter(Boolean)
      .slice(0, 5);
  }

  function persistEmergencyDraft() {
    try {
      localStorage.setItem('nyayavoice_emergency_contacts', emergencyContactsInput ? emergencyContactsInput.value : '');
      localStorage.setItem('nyayavoice_emergency_type', emergencyTypeSelect ? emergencyTypeSelect.value : 'general');
      localStorage.setItem('nyayavoice_emergency_mode', emergencyModeSelect ? emergencyModeSelect.value : 'sms');
      localStorage.setItem('nyayavoice_emergency_message', emergencyCustomMessageInput ? emergencyCustomMessageInput.value : '');
    } catch (_) {}
  }

  function setEmergencyStatus(message, type = '') {
    if (!emergencyAlertStatus) return;
    emergencyAlertStatus.textContent = message;
    emergencyAlertStatus.classList.remove('is-error', 'is-success');
    if (type) emergencyAlertStatus.classList.add(type === 'error' ? 'is-error' : 'is-success');
  }

  function setEmergencyLocationText(message) {
    if (emergencyLocationStatus) emergencyLocationStatus.textContent = message;
  }

  async function fetchEmergencyLocation() {
    if (!navigator.geolocation) {
      setEmergencyLocationText(t('emergencyStatusLocationFailed'));
      setEmergencyStatus(t('emergencyStatusLocationFailed'), 'error');
      return null;
    }

    setEmergencyLocationText(t('emergencyLocationFetching'));
    setEmergencyStatus('', '');

    try {
      const position = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 15000,
          maximumAge: 0,
        });
      });

      emergencyLocation = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
      };

      setEmergencyLocationText(
        `${t('emergencyLocationReady')} ${emergencyLocation.latitude.toFixed(5)}, ${emergencyLocation.longitude.toFixed(5)}`
      );
      return emergencyLocation;
    } catch (err) {
      const denied = err && err.code === 1;
      setEmergencyLocationText(denied ? t('emergencyStatusLocationDenied') : t('emergencyStatusLocationFailed'));
      setEmergencyStatus(denied ? t('emergencyStatusLocationDenied') : t('emergencyStatusLocationFailed'), 'error');
      return null;
    }
  }

  async function sendEmergencyAlert() {
    const contacts = parseEmergencyContacts(emergencyContactsInput ? emergencyContactsInput.value : '');
    if (!contacts.length) {
      setEmergencyStatus(t('emergencyStatusNeedContacts'), 'error');
      return;
    }

    if (!emergencyLocation) {
      const fetched = await fetchEmergencyLocation();
      if (!fetched) return;
    }

    persistEmergencyDraft();
    setEmergencyStatus(t('emergencyStatusSending'));
    if (sendEmergencyAlertBtn) sendEmergencyAlertBtn.disabled = true;
    if (fetchEmergencyLocationBtn) fetchEmergencyLocationBtn.disabled = true;

    try {
      const result = await apiCall('/api/emergency-alert', {
        user_id: userId,
        language: getLang(),
        message_mode: emergencyModeSelect ? emergencyModeSelect.value : 'sms',
        emergency_type: emergencyTypeSelect ? emergencyTypeSelect.value : 'general',
        custom_message: emergencyCustomMessageInput ? emergencyCustomMessageInput.value.trim() : '',
        contacts,
        latitude: emergencyLocation.latitude,
        longitude: emergencyLocation.longitude,
      });

      const deliveryLabel = result.delivery_mode === 'call' ? 'call(s)' : 'message(s)';
      setEmergencyStatus(`${t('emergencyStatusSent')} ${result.deliveries.length} ${deliveryLabel} sent.`, 'success');
      if (result.location_label) setEmergencyLocationText(result.location_label);
    } catch (err) {
      setEmergencyStatus(err.message || 'Emergency alert failed.', 'error');
    } finally {
      if (sendEmergencyAlertBtn) sendEmergencyAlertBtn.disabled = false;
      if (fetchEmergencyLocationBtn) fetchEmergencyLocationBtn.disabled = false;
    }
  }

  function initEmergencyAlertForm() {
    if (!emergencyContactsInput) return;
    try {
      emergencyContactsInput.value = localStorage.getItem('nyayavoice_emergency_contacts') || '';
      if (emergencyTypeSelect) emergencyTypeSelect.value = localStorage.getItem('nyayavoice_emergency_type') || 'general';
      if (emergencyModeSelect) emergencyModeSelect.value = localStorage.getItem('nyayavoice_emergency_mode') || 'sms';
      if (emergencyCustomMessageInput) emergencyCustomMessageInput.value = localStorage.getItem('nyayavoice_emergency_message') || '';
    } catch (_) {}

    on(emergencyContactsInput, 'input', persistEmergencyDraft);
    on(emergencyTypeSelect, 'change', persistEmergencyDraft);
    on(emergencyModeSelect, 'change', persistEmergencyDraft);
    on(emergencyCustomMessageInput, 'input', persistEmergencyDraft);
    on(fetchEmergencyLocationBtn, 'click', fetchEmergencyLocation);
    on(sendEmergencyAlertBtn, 'click', sendEmergencyAlert);
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatInlineMarkdown(text) {
    return text
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>');
  }

  function formatMarkdownBlock(block) {
    const lines = block.split('\n').map(line => line.trim()).filter(Boolean);
    if (!lines.length) return '';

    if (lines.every(line => /^[-*]\s+/.test(line))) {
      return '<ul class="msg-list">' + lines
        .map(line => `<li>${formatInlineMarkdown(line.replace(/^[-*]\s+/, ''))}</li>`)
        .join('') + '</ul>';
    }

    return '<p>' + lines.map(formatInlineMarkdown).join('<br>') + '</p>';
  }

  function formatMessageContent(text) {
    const escaped = escapeHtml(text).replace(/\r\n/g, '\n');
    return escaped
      .split(/\n{2,}/)
      .map(part => part.trim())
      .filter(Boolean)
      .map(formatMarkdownBlock)
      .join('');
  }

  function addMessage(text, isUser, mode = 'text') {
    const wrapper = document.createElement('div');
    wrapper.className = 'msg ' + (isUser ? 'msg-user' : 'msg-bot');
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    if (mode === 'html') {
      bubble.innerHTML = text;
    } else if (mode === 'markdown') {
      bubble.innerHTML = formatMessageContent(text);
    } else {
      bubble.innerHTML = escapeHtml(text).replace(/\n/g, '<br>');
    }
    wrapper.appendChild(bubble);
    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function addTypingIndicator() {
    const wrapper = document.createElement('div');
    wrapper.className = 'msg msg-bot typing-indicator';
    wrapper.id = 'typingIndicator';
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.innerHTML = '<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>';
    wrapper.appendChild(bubble);
    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function removeTypingIndicator() {
    const el = document.getElementById('typingIndicator');
    if (el) el.remove();
  }

  function isDuplicateConversationTurn(role, text) {
    const normalized = normalizeText(text);
    const lastMessage = conversationHistory[conversationHistory.length - 1];
    return !!lastMessage && lastMessage.role === role && normalizeText(lastMessage.text) === normalized;
  }

  function normalizeText(text) {
    return String(text || '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function queueTypedMessage(text) {
    pendingTypedMessages.push(normalizeText(text));
  }

  function consumePendingTypedMessage(text) {
    const normalized = normalizeText(text);
    const index = pendingTypedMessages.indexOf(normalized);
    if (index >= 0) {
      pendingTypedMessages.splice(index, 1);
      return true;
    }
    return false;
  }

  function hasRecentlySpokenAssistantText(text) {
    const normalized = normalizeText(text);
    const now = Date.now();
    recentSpokenAssistantTexts = recentSpokenAssistantTexts.filter(item => now - item.ts < 15000);
    return recentSpokenAssistantTexts.some(item => item.text === normalized);
  }

  function rememberSpokenAssistantText(text) {
    recentSpokenAssistantTexts.push({ text: normalizeText(text), ts: Date.now() });
  }

  function clearPendingSpeechFallback() {
    if (pendingSpeechFallbackTimer) {
      clearTimeout(pendingSpeechFallbackTimer);
      pendingSpeechFallbackTimer = null;
    }
  }

  function setStopAudioButtonIcon(mode = 'stop') {
    if (!stopAudioBtn) return;
    if (mode === 'resume') {
      stopAudioBtn.innerHTML = `
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
          <path d="M8 6.5v11l9-5.5z"></path>
        </svg>
      `;
      return;
    }
    stopAudioBtn.innerHTML = `
      <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true">
        <rect x="7" y="7" width="10" height="10" rx="2"></rect>
      </svg>
    `;
  }

  function setResumableAssistantSpeech(text) {
    const cleanedText = String(text || '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/[#*_`>-]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    resumableAssistantSpeech = cleanedText ? cleanedText : null;
    updateStopAudioButtonLabel();
  }

  function pauseBrowserSpeech() {
    if (!('speechSynthesis' in window) || !currentBrowserUtterance || window.speechSynthesis.paused) return false;
    window.speechSynthesis.pause();
    browserSpeechActive = false;
    browserSpeechPaused = true;
    setResumableAssistantSpeech(currentAssistantSpeechText);
    return true;
  }

  function resumeBrowserSpeech() {
    if (!('speechSynthesis' in window) || !window.speechSynthesis.paused) return false;
    window.speechSynthesis.resume();
    browserSpeechActive = true;
    browserSpeechPaused = false;
    resumableAssistantSpeech = null;
    updateStopAudioButtonLabel();
    return true;
  }

  function stopBrowserSpeech(clearResumeState = true) {
    if (!('speechSynthesis' in window)) return;
    browserSpeechActive = false;
    browserSpeechPaused = false;
    currentBrowserUtterance = null;
    if (clearResumeState) resumableAssistantSpeech = null;
    window.speechSynthesis.cancel();
    updateStopAudioButtonLabel();
  }

  async function resumeAssistantReplyWithVapi(text) {
    if (!vapiInstance || !text || vapiUnavailableReason) return false;
    const requestId = ++pendingSpeechRequestId;
    activeSpeechRequestId = requestId;
    currentAssistantSpeechText = text;
    browserSpeechPaused = false;
    resumableAssistantSpeech = null;
    updateStopAudioButtonLabel();
    const requestedAt = Date.now();
    clearPendingSpeechFallback();

    try {
      const sessionReady = await ensureVapiSession('chat');
      if (!sessionReady) return false;
      vapiSessionMode = 'chat';
      console.info('Resuming voice output source: vapi');
      vapiInstance.send({
        type: 'say',
        content: text,
        endCallAfterSpoken: false,
      });
    } catch (err) {
      console.error('Vapi resume say failed:', err);
      return false;
    }

    if (!browserVoiceFallbackEnabled) return true;

    pendingSpeechFallbackTimer = setTimeout(() => {
      if (requestId !== activeSpeechRequestId || browserSpeechActive) return;
      if (lastSpeechStartAt < requestedAt) {
        console.warn('Resumed Vapi speech did not start in time, falling back to browser speech');
        startBrowserSpeechFallback(text, requestId);
      }
    }, 3500);
    return true;
  }

  async function resumeResponseAudio() {
    if (resumeBrowserSpeech()) return;
    if (!resumableAssistantSpeech) return;
    const textToResume = resumableAssistantSpeech;
    const resumedWithVapi = await resumeAssistantReplyWithVapi(textToResume);
    if (resumedWithVapi) return;
    resumableAssistantSpeech = null;
    updateStopAudioButtonLabel();
    speakAssistantReplyInBrowser(textToResume);
  }

  function stopResponseAudio() {
    if (browserSpeechPaused || resumableAssistantSpeech) {
      resumeResponseAudio();
      return;
    }
    if (pauseBrowserSpeech()) return;

    activeSpeechRequestId += 1;
    setResumableAssistantSpeech(currentAssistantSpeechText);
    pendingVapiSpeech = null;
    clearPendingSpeechFallback();
    stopBrowserSpeech(false);
    if (vapiInstance && vapiCallActive && vapiSessionMode === 'chat') {
      try {
        vapiInstance.stop();
      } catch (err) {
        console.error('Vapi stop for response audio failed:', err);
      }
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
    }
  }

  function updateStopAudioButtonLabel() {
    if (!stopAudioBtn) return;
    const label = (browserSpeechPaused || resumableAssistantSpeech)
      ? t('resumeVoice')
      : (browserSpeechActive ? t('pauseVoice') : t('stopVoice'));
    stopAudioBtn.setAttribute('aria-label', label);
    stopAudioBtn.setAttribute('title', label);
    setStopAudioButtonIcon((browserSpeechPaused || resumableAssistantSpeech) ? 'resume' : 'stop');
  }

  function startBrowserSpeechFallback(text, requestId) {
    if (!browserVoiceFallbackEnabled) return false;
    if (requestId && requestId !== activeSpeechRequestId) return false;
    pendingVapiSpeech = text ? { text, requestId: requestId || activeSpeechRequestId } : null;
    speakAssistantReplyInBrowser(text, requestId);
    return true;
  }

  async function replayPendingVapiSpeech() {
    if (!pendingVapiSpeech || browserSpeechActive || !vapiInstance || vapiUnavailableReason) return;
    const queuedSpeech = pendingVapiSpeech;
    pendingVapiSpeech = null;
    if (queuedSpeech.requestId !== activeSpeechRequestId) return;
    try {
      await ensureVapiSession('chat');
      vapiSessionMode = 'chat';
      console.info('Replaying deferred Vapi speech after browser fallback finished');
      vapiInstance.send({
        type: 'say',
        content: queuedSpeech.text,
        endCallAfterSpoken: false,
      });
    } catch (err) {
      console.error('Deferred Vapi speech replay failed:', err);
    }
  }

  async function speakAssistantReplyWithVapi(text) {
    if (!vapiInstance || !text || hasRecentlySpokenAssistantText(text) || vapiUnavailableReason) return false;
    rememberSpokenAssistantText(text);
    const requestId = ++pendingSpeechRequestId;
    activeSpeechRequestId = requestId;
    currentAssistantSpeechText = text;
    browserSpeechPaused = false;
    resumableAssistantSpeech = null;
    updateStopAudioButtonLabel();
    const requestedAt = Date.now();
    clearPendingSpeechFallback();
    try {
      const sessionReady = await ensureVapiSession('chat');
      if (!sessionReady) return false;
      vapiSessionMode = 'chat';
      console.info('Voice output source: vapi');
      vapiInstance.send({
        type: 'say',
        content: text,
        endCallAfterSpoken: false,
      });
    } catch (err) {
      console.error('Vapi say failed:', err);
      return false;
    }

    if (!browserVoiceFallbackEnabled) return true;

    pendingSpeechFallbackTimer = setTimeout(() => {
      if (requestId !== activeSpeechRequestId || browserSpeechActive) return;
      if (lastSpeechStartAt < requestedAt) {
        console.warn('Vapi speech did not start in time, falling back to browser speech');
        startBrowserSpeechFallback(text, requestId);
      }
    }, 3500);
    return true;
  }

  function speakAssistantReplyInBrowser(text, requestId = null) {
    if (!('speechSynthesis' in window) || !text) return;
    if (requestId && requestId !== activeSpeechRequestId) return;
    console.info('Voice output source: browser_speech_fallback');

    try {
      const cleanedText = String(text)
        .replace(/<[^>]+>/g, ' ')
        .replace(/[#*_`>-]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
      if (!cleanedText) return;
      currentAssistantSpeechText = cleanedText;
      browserSpeechPaused = false;
      resumableAssistantSpeech = null;
      clearPendingSpeechFallback();
      browserSpeechActive = true;
      updateStopAudioButtonLabel();
      const utterance = new SpeechSynthesisUtterance(cleanedText);
      currentBrowserUtterance = utterance;
      utterance.lang = getSpeechLang();
      utterance.rate = 1;
      utterance.onend = () => {
        if (currentBrowserUtterance === utterance) {
          browserSpeechActive = false;
          browserSpeechPaused = false;
          currentBrowserUtterance = null;
          resumableAssistantSpeech = null;
          updateStopAudioButtonLabel();
          replayPendingVapiSpeech();
        }
      };
      utterance.onerror = () => {
        if (currentBrowserUtterance === utterance) {
          browserSpeechActive = false;
          browserSpeechPaused = false;
          currentBrowserUtterance = null;
          resumableAssistantSpeech = null;
          pendingVapiSpeech = null;
          updateStopAudioButtonLabel();
        }
      };
      stopBrowserSpeech();
      browserSpeechActive = true;
      browserSpeechPaused = false;
      currentBrowserUtterance = utterance;
      window.speechSynthesis.speak(utterance);
      updateStopAudioButtonLabel();
    } catch (err) {
      browserSpeechActive = false;
      browserSpeechPaused = false;
      currentBrowserUtterance = null;
      updateStopAudioButtonLabel();
      console.error('Browser speech fallback failed:', err);
    }
  }

  async function ensureVapiSession(mode = 'chat') {
    if (!vapiInstance) return false;
    const currentLang = getLang();
    const needsRestart = vapiCallActive && (vapiSessionMode !== mode || vapiSessionLanguage !== currentLang);

    if (needsRestart) {
      clearPendingSpeechFallback();
      stopBrowserSpeech();
      try {
        vapiInstance.stop();
      } catch (err) {
        console.error('Vapi stop before restart failed:', err);
      }
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
    }

    if (vapiCallActive) return true;

    vapiSessionMode = mode;
    vapiSessionLanguage = currentLang;
    console.info('Starting Vapi session', { mode, language: currentLang, serverUrl: API_BASE + '/vapi-webhook' });
    await vapiInstance.start({
      serverUrl: API_BASE + '/vapi-webhook',
      serverUrlSecret: '',
      metadata: { user_id: userId, language: currentLang, mode },
    });
    const isReady = await waitForVapiReady();
    if (!isReady) {
      console.warn('Vapi session did not become ready in time after start');
      try {
        vapiInstance.stop();
      } catch (err) {
        console.error('Vapi stop after readiness timeout failed:', err);
      }
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
      return false;
    }
    vapiCallActive = true;
    console.info('Vapi session started', { mode, language: currentLang });
    return true;
  }

  async function sendToVapiChat(userText) {
    if (!vapiInstance) return false;

    addTypingIndicator();
    queueTypedMessage(userText);
    conversationHistory.push({ role: 'user', text: userText });

    try {
      const sessionReady = await ensureVapiSession('chat');
      if (!sessionReady) throw new Error('vapi_session_not_ready');
      vapiSessionMode = 'chat';
      vapiInstance.send({
        type: 'add-message',
        message: {
          role: 'user',
          content: userText,
        },
        triggerResponseEnabled: true,
      });
      return true;
    } catch (err) {
      console.error('Vapi chat send failed:', err);
      try {
        if (vapiInstance) vapiInstance.stop();
      } catch (stopErr) {
        console.error('Vapi stop after send failure failed:', stopErr);
      }
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;

      try {
        const sessionReady = await ensureVapiSession('chat');
        if (!sessionReady) throw new Error('vapi_session_not_ready');
        vapiSessionMode = 'chat';
        vapiInstance.send({
          type: 'add-message',
          message: {
            role: 'user',
            content: userText,
          },
          triggerResponseEnabled: true,
        });
        return true;
      } catch (retryErr) {
        console.error('Vapi chat retry failed:', retryErr);
        removeTypingIndicator();
        const normalized = normalizeText(userText);
        pendingTypedMessages = pendingTypedMessages.filter(item => item !== normalized);
        conversationHistory = conversationHistory.filter((msg, index) => !(index === conversationHistory.length - 1 && msg.role === 'user' && msg.text === userText));
        return false;
      }
    }
  }

  async function speakAssistantReply(text) {
    if (!text) return;
    if (vapiInstance) {
      const spokeWithVapi = await speakAssistantReplyWithVapi(text);
      if (spokeWithVapi) return;
    }
    speakAssistantReplyInBrowser(text);
  }

  async function sendToBackendChat(userText) {
    const previousConversation = conversationHistory.slice(0, -1);
    addTypingIndicator();

    try {
      const result = await apiCall('/api/query', {
        user_id: userId,
        text: userText,
        language: getLang(),
        conversation: previousConversation,
      });
      console.info('Chat response source:', result.source);
      console.info('Chat response detail:', result.source_detail);

      removeTypingIndicator();

      if (result.source === 'backend_fallback' && result.source_detail === 'insufficient_quota') {
        addMessage(
          'OpenAI is temporarily unavailable because the API quota is exhausted. Showing the backend fallback response below.',
          false,
          'text'
        );
      }

      if (!isDuplicateConversationTurn('assistant', result.response)) {
        addMessage(result.response, false, 'markdown');
        conversationHistory.push({ role: 'assistant', text: result.response });
        messageCount++;
        localStorage.setItem('nyayavoice_msg_count', messageCount);
        updateStats();
      }

      await speakAssistantReply(result.response);
      return true;
    } catch (err) {
      console.error('Backend chat request failed:', err);
      removeTypingIndicator();
      return false;
    }
  }

  /* ── FALLBACK (offline / no backend) ───────────────────── */
  const LEGAL_RESPONSES = {
    en: {
      theft: '<strong>Theft — Your Legal Rights:</strong><br><br>IPC Section 378/379: Theft is a cognizable offence. Police MUST register your FIR — free of cost.<br><br>Zero FIR: You can file at ANY police station regardless of where the crime happened.<br><br><em>Would you like me to help you draft an FIR? Go to the <strong>FIR Wizard</strong> section.</em>',
      violence: '<strong>Domestic Violence — Your Legal Protection:</strong><br><br>Protection of Women from Domestic Violence Act 2005 covers physical, emotional, verbal, sexual, and economic abuse.<br><br>Immediate help: Women Helpline <strong>181</strong> (24/7) | Police <strong>100</strong><br><br><em>You are not alone. Help is available right now.</em>',
      default: 'I\'m currently unable to reach the server. Please check if the backend is running. In the meantime, here are emergency numbers:<br><br>Police: <strong>100</strong> | Women Helpline: <strong>181</strong> | Emergency: <strong>112</strong> | NALSA Legal Aid: <strong>15100</strong>'
    },
    hi: {
      theft: '<strong>चोरी — आपके कानूनी अधिकार:</strong><br><br>भारतीय दण्ड संहिता धारा 378/379: चोरी संज्ञेय अपराध है। पुलिस को आपकी एफ़आईआर निःशुल्क दर्ज करनी होगी।<br><br><em>एफ़आईआर विज़ार्ड में जाकर प्रारूप तैयार करें।</em>',
      violence: '<strong>घरेलू हिंसा — आपकी कानूनी सुरक्षा:</strong><br><br>घरेलू हिंसा से महिलाओं की सुरक्षा अधिनियम 2005 के तहत शिकायत दर्ज कराएँ।<br><br>तुरन्त सहायता: महिला हेल्पलाइन <strong>181</strong> | पुलिस <strong>100</strong>',
      default: 'सर्वर से कनेक्ट नहीं हो पा रहा। कृपया जाँचें कि बैकएंड चल रहा है।<br><br>आपातकालीन नम्बर: पुलिस <strong>100</strong> | महिला हेल्पलाइन <strong>181</strong> | आपातकाल <strong>112</strong>'
    }
  };

  function fallbackReplyLegacy(userText) {
    const lang = getLang();
    const lower = userText.toLowerCase();
    const r = LEGAL_RESPONSES[lang] || LEGAL_RESPONSES.en;
    let reply = r.default;
    if (/chori|theft|stolen|चोरी|phone|फ़ोन|snatch/.test(lower)) reply = r.theft;
    else if (/violen|hinsa|हिंसा|domestic|abuse|beat|पीट/.test(lower)) reply = r.violence;
    addMessage(reply, false, 'html');
    speakAssistantReplyInBrowser(reply);
  }

  function fallbackReplyBasic(userText) {
    const lang = getLang();
    const lower = String(userText || '').toLowerCase();
    const fallbackTopics = {
      en: {
        default: 'I\'m unable to complete the Vapi chat session right now. Please try again in a moment.<br><br>Emergency numbers: Police <strong>100</strong> | Women Helpline <strong>181</strong> | Emergency <strong>112</strong> | NALSA <strong>15100</strong>',
        theft: '<strong>Theft — Your Legal Rights:</strong><br><br>For theft, you can file an FIR or Zero FIR at the nearest police station free of cost.<br><br><em>You can also use the FIR Wizard to prepare a draft.</em>',
        violence: '<strong>Domestic Violence — Your Legal Protection:</strong><br><br>Protection of Women from Domestic Violence Act 2005 covers physical, emotional, verbal, sexual, and economic abuse.<br><br>Immediate help: Women Helpline <strong>181</strong> | Police <strong>100</strong>.',
        wage: '<strong>Wage Theft — What to do:</strong><br><br>Ask your employer for payment in writing, keep a record of missed salary, and file a complaint with the Labour Department if payment is still withheld.',
        legalAid: '<strong>Free Legal Aid — What to do:</strong><br><br>Apply for free legal aid through the District Legal Services Authority and explain your issue clearly so they can assign legal help.',
        land: '<strong>Land Dispute — What to do:</strong><br><br>Secure your ownership records, record the interference or encroachment, and send a written complaint or legal notice as the next step.',
        cyber: '<strong>Cyber Crime — What to do:</strong><br><br>Block the compromised account if possible, save the transaction details and screenshots, and report the incident immediately.',
        consumer: '<strong>Consumer Rights — What to do:</strong><br><br>Ask the seller or service provider for a refund or repair in writing, keep the complaint record, and escalate the complaint if they do not respond.',
        rti: '<strong>RTI — What to do:</strong><br><br>Write a clear RTI application, ask for specific information from the public authority, and follow up if no reply is received within the time limit.'
      },
      hi: {
        default: 'अभी Vapi chat session पूरा नहीं हो पा रहा है। कृपया थोड़ी देर बाद फिर कोशिश करें।<br><br>आपातकालीन नंबर: पुलिस <strong>100</strong> | महिला हेल्पलाइन <strong>181</strong> | आपातकाल <strong>112</strong> | नालसा <strong>15100</strong>',
        theft: '<strong>चोरी — आपके कानूनी अधिकार:</strong><br><br>चोरी के मामले में आप निकटतम पुलिस स्टेशन में एफ़आईआर या ज़ीरो एफ़आईआर निःशुल्क दर्ज करा सकते हैं।<br><br><em>आप FIR Wizard से ड्राफ्ट भी तैयार कर सकते हैं।</em>',
        violence: '<strong>घरेलू हिंसा — आपकी कानूनी सुरक्षा:</strong><br><br>घरेलू हिंसा से महिलाओं की सुरक्षा अधिनियम 2005 शारीरिक, मानसिक, यौन और आर्थिक शोषण को कवर करता है।<br><br>तुरन्त सहायता: महिला हेल्पलाइन <strong>181</strong> | पुलिस <strong>100</strong>।',
        wage: '<strong>वेतन चोरी — बुनियादी सहायता:</strong><br><br>अगर आपका वेतन रोका गया है, तो अपने जिले के श्रम आयुक्त या Labour Department में शिकायत कर सकते हैं।<br><br>वेतन स्लिप, बैंक स्टेटमेंट, हाजिरी रिकॉर्ड और चैट/ईमेल सुरक्षित रखें।',
        legalAid: '<strong>निःशुल्क कानूनी सहायता — बुनियादी सहायता:</strong><br><br>अगर आप वकील का खर्च नहीं उठा सकते, तो जिला विधिक सेवा प्राधिकरण (DLSA) से संपर्क करें।<br><br>नालसा हेल्पलाइन: <strong>15100</strong>।',
        land: '<strong>भूमि विवाद — बुनियादी सहायता:</strong><br><br>यदि किसी ने आपकी भूमि पर अवैध कब्जा किया है, तो बिक्री विलेख, कर रसीदें और भूमि रिकॉर्ड सुरक्षित रखें।<br><br>मामले के अनुसार स्थानीय पुलिस स्टेशन, तहसीलदार या राजस्व न्यायालय से संपर्क किया जा सकता है।',
        cyber: '<strong>साइबर अपराध — बुनियादी सहायता:</strong><br><br>स्क्रीनशॉट, ट्रांजैक्शन आईडी, फोन नंबर और लिंक सुरक्षित रखें।<br><br>जल्दी से <strong>cybercrime.gov.in</strong> पर शिकायत करें या <strong>1930</strong> पर कॉल करें।',
        consumer: '<strong>उपभोक्ता अधिकार — बुनियादी सहायता:</strong><br><br>बिल, वारंटी और विक्रेता से हुई बातचीत सुरक्षित रखें।<br><br><strong>edaakhil.nic.in</strong> पर या जिला उपभोक्ता फोरम में शिकायत की जा सकती है।',
        rti: '<strong>आरटीआई — बुनियादी सहायता:</strong><br><br>आरटीआई अधिनियम 2005 के तहत आप सरकारी कार्यालय से जानकारी मांग सकते हैं।<br><br>विभाग को सामान्यतः <strong>30 दिनों</strong> के भीतर जवाब देना होता है।'
      }
    };

    const topics = fallbackTopics[lang] || fallbackTopics.en;
    let reply = topics.default;
    if (/chori|theft|stolen|चोरी|phone|फ़ोन|snatch|fir|एफ़आईआर/.test(lower)) reply = topics.theft;
    else if (/violen|hinsa|हिंसा|domestic|abuse|beat|पीट/.test(lower)) reply = topics.violence;
    else if (/wage|salary|vetan|वेतन|labour|labor|श्रम/.test(lower)) reply = topics.wage;
    else if (/legal aid|free legal|निःशुल्क कानूनी सहायता|कानूनी सहायता|dlsa|nalsa|15100/.test(lower)) reply = topics.legalAid;
    else if (/land|property|bhumi|भूमि|ज़मीन|zameen|encroach/.test(lower)) reply = topics.land;
    else if (/cyber|साइबर|online|ऑनलाइन|fraud|धोखा|धोखाधड़ी|phishing|1930/.test(lower)) reply = topics.cyber;
    else if (/consumer|उपभोक्ता|refund|warranty|edaakhil|product|defect/.test(lower)) reply = topics.consumer;
    else if (/\brti\b|आरटीआई|सूचना का अधिकार|right to info/.test(lower)) reply = topics.rti;

    addMessage(reply, false, 'html');
    speakAssistantReplyInBrowser(reply);
  }

  function fallbackReply(userText) {
    const lang = getLang();
    const lower = String(userText || '').toLowerCase();
    const fallbackTopics = {
      en: {
        default: 'I\'m unable to complete the Vapi chat session right now. Please try again in a moment.<br><br>Emergency numbers: Police <strong>100</strong> | Women Helpline <strong>181</strong> | Emergency <strong>112</strong> | NALSA <strong>15100</strong>',
        theft: '<strong>Theft â€” Your Legal Rights:</strong><br><br>For theft, you can file an FIR or Zero FIR at the nearest police station free of cost.<br><br><em>You can also use the FIR Wizard to prepare a draft.</em>',
        violence: '<strong>Domestic Violence â€” Your Legal Protection:</strong><br><br>Protection of Women from Domestic Violence Act 2005 covers physical, emotional, verbal, sexual, and economic abuse.<br><br>Immediate help: Women Helpline <strong>181</strong> | Police <strong>100</strong>.',
        wage: '<strong>Wage Theft â€” Basic Help:</strong><br><br>If your salary is withheld, complain to the Labour Commissioner or Labour Department in your district.<br><br>Keep salary slips, bank statements, attendance records, and chats/emails safely.',
        legalAid: '<strong>Free Legal Aid â€” Basic Help:</strong><br><br>If you cannot afford a lawyer, contact the District Legal Services Authority (DLSA).<br><br>NALSA helpline: <strong>15100</strong>.',
        land: '<strong>Land Dispute â€” Basic Help:</strong><br><br>Keep sale deed, tax receipts, and land records safely.<br><br>You may need the local police station, Tehsildar, or Revenue Court depending on the issue.',
        cyber: '<strong>Cyber Crime â€” Basic Help:</strong><br><br>Save screenshots, transaction IDs, phone numbers, and links.<br><br>Report at <strong>cybercrime.gov.in</strong> or call <strong>1930</strong> quickly.',
        consumer: '<strong>Consumer Rights â€” Basic Help:</strong><br><br>Keep the bill, warranty, and seller communication safely.<br><br>You can complain on <strong>edaakhil.nic.in</strong> or before the District Consumer Forum.',
        property: '<strong>Property & Rent Issues:</strong><br><br>Landlord not returning deposit, illegal eviction, rent agreement disputes, builder delay, and property fraud.<br><br><strong>What to do:</strong> collect your agreement and payment proof, ask for the refund in writing, and send a legal notice if the landlord still refuses.',
        family: '<strong>Family Issues:</strong><br><br>Divorce, domestic violence, child custody, and dowry harassment.<br><br><strong>What to do:</strong> seek immediate protection if needed, record the abuse or dispute details, and make a written complaint to the relevant authority.',
        employment: '<strong>Employment Issues:</strong><br><br>Salary not paid, wrongful termination, and workplace harassment.<br><br><strong>What to do:</strong> keep your job records, raise a written complaint with your employer, and escalate if the issue is not resolved.',
        traffic: '<strong>Traffic Issues:</strong><br><br>Accidents, vehicle theft, and insurance claim issues.<br><br><strong>What to do:</strong> record the incident details, take photos if possible, and report the matter promptly.',
        finance: '<strong>Financial Issues:</strong><br><br>Bank fraud, cheque bounce, and loan harassment.<br><br><strong>What to do:</strong> inform the bank or lender immediately, keep a written record of the issue, and file a formal complaint if the problem continues.',
        quick: '<strong>General Steps:</strong><br><br>Collect evidence, send legal notice, file complaint/FIR, hire lawyer, attend hearings.<br><br><strong>Quick Rule:</strong> Criminal -> Police, Property/Money -> Civil Court, Service/Product -> Consumer Court, Job -> Labour Court, Family -> Family Court.',
        rti: '<strong>RTI â€” Basic Help:</strong><br><br>Under the RTI Act, you can seek information from a government office.<br><br>The authority should generally reply within <strong>30 days</strong>.'
      },
      hi: {
        default: 'अभी Vapi chat session पूरा नहीं हो पा रहा है। कृपया थोड़ी देर बाद फिर कोशिश करें।<br><br>आपातकालीन नंबर: पुलिस <strong>100</strong> | महिला हेल्पलाइन <strong>181</strong> | आपातकाल <strong>112</strong> | नालसा <strong>15100</strong>',
        theft: '<strong>चोरी — आपके कानूनी अधिकार:</strong><br><br>चोरी के मामले में आप निकटतम पुलिस स्टेशन में एफआईआर या ज़ीरो एफआईआर निःशुल्क दर्ज करा सकते हैं।<br><br><em>आप FIR Wizard से ड्राफ्ट भी तैयार कर सकते हैं।</em>',
        violence: '<strong>घरेलू हिंसा — आपकी कानूनी सुरक्षा:</strong><br><br>घरेलू हिंसा से महिलाओं की सुरक्षा अधिनियम 2005 शारीरिक, मानसिक, यौन और आर्थिक शोषण को कवर करता है।<br><br>तुरन्त सहायता: महिला हेल्पलाइन <strong>181</strong> | पुलिस <strong>100</strong>।',
        wage: '<strong>वेतन चोरी — बुनियादी सहायता:</strong><br><br>अगर आपका वेतन रोका गया है, तो अपने जिले के श्रम आयुक्त या Labour Department में शिकायत कर सकते हैं।<br><br>वेतन स्लिप, बैंक स्टेटमेंट, हाजिरी रिकॉर्ड और चैट/ईमेल सुरक्षित रखें।',
        legalAid: '<strong>निःशुल्क कानूनी सहायता — बुनियादी सहायता:</strong><br><br>अगर आप वकील का खर्च नहीं उठा सकते, तो जिला विधिक सेवा प्राधिकरण (DLSA) से संपर्क करें।<br><br>नालसा हेल्पलाइन: <strong>15100</strong>।',
        land: '<strong>भूमि विवाद — बुनियादी सहायता:</strong><br><br>यदि किसी ने आपकी भूमि पर अवैध कब्जा किया है, तो बिक्री विलेख, कर रसीदें और भूमि रिकॉर्ड सुरक्षित रखें।<br><br>मामले के अनुसार स्थानीय पुलिस स्टेशन, तहसीलदार या राजस्व न्यायालय से संपर्क किया जा सकता है।',
        cyber: '<strong>साइबर अपराध — बुनियादी सहायता:</strong><br><br>स्क्रीनशॉट, ट्रांजैक्शन आईडी, फोन नंबर और लिंक सुरक्षित रखें।<br><br>जल्दी से <strong>cybercrime.gov.in</strong> पर शिकायत करें या <strong>1930</strong> पर कॉल करें।',
        consumer: '<strong>उपभोक्ता अधिकार — बुनियादी सहायता:</strong><br><br>बिल, वारंटी और विक्रेता से हुई बातचीत सुरक्षित रखें।<br><br><strong>edaakhil.nic.in</strong> पर या जिला उपभोक्ता फोरम में शिकायत की जा सकती है।',
        property: '<strong>संपत्ति और किराया विवाद:</strong><br><br><strong>आम समस्याएं:</strong> मकान मालिक डिपॉज़िट वापस नहीं कर रहा, अवैध बेदखली, किराया एग्रीमेंट विवाद, बिल्डर द्वारा देरी, प्रॉपर्टी में धोखाधड़ी।<br><br><strong>क्या करें:</strong> अपना एग्रीमेंट और पेमेंट का सबूत इकट्ठा करें, लिखित में रिफंड मांगें, और मकान मालिक के मना करने पर लीगल नोटिस भेजें।',
        family: '<strong>पारिवारिक मामले:</strong><br><br><strong>आम समस्याएं:</strong> तलाक, घरेलू हिंसा, बच्चे की कस्टडी, दहेज उत्पीड़न।<br><br><strong>क्या करें:</strong> ज़रूरत हो तो तुरंत सुरक्षा लें, घटना या विवाद का रिकॉर्ड रखें, और संबंधित प्राधिकरण को लिखित शिकायत दें।',
        employment: '<strong>नौकरी से जुड़ी समस्याएं:</strong><br><br><strong>आम समस्याएं:</strong> सैलरी नहीं मिली, गलत तरीके से नौकरी से निकाला, कार्यस्थल पर उत्पीड़न।<br><br><strong>क्या करें:</strong> नौकरी से जुड़े रिकॉर्ड सुरक्षित रखें, कंपनी को लिखित शिकायत दें, और समाधान न मिलने पर मामला आगे बढ़ाएं।',
        traffic: '<strong>ट्रैफिक मामले:</strong><br><br><strong>आम समस्याएं:</strong> एक्सीडेंट, वाहन चोरी, इंश्योरेंस समस्या।<br><br><strong>क्या करें:</strong> घटना का रिकॉर्ड बनाएं, संभव हो तो फोटो लें, और मामले की तुरंत रिपोर्ट करें।',
        finance: '<strong>बैंकिंग और वित्तीय मामले:</strong><br><br><strong>आम समस्याएं:</strong> बैंक फ्रॉड, चेक बाउंस, लोन परेशानियां।<br><br><strong>क्या करें:</strong> तुरंत बैंक या लोन देने वाले को बताएं, समस्या का लिखित रिकॉर्ड रखें, और मामला जारी रहने पर औपचारिक शिकायत करें।',
        quick: '<strong>सामान्य प्रक्रिया:</strong><br><br>सबूत इकट्ठा करें, लीगल नोटिस भेजें, शिकायत / FIR दर्ज करें, वकील रखें, सुनवाई में जाएं।<br><br><strong>आसान नियम:</strong> अपराध -> पुलिस, जमीन/पैसा -> सिविल कोर्ट, सर्विस/प्रोडक्ट -> कंज्यूमर कोर्ट, नौकरी -> लेबर कोर्ट, परिवार -> फैमिली कोर्ट।',
        rti: '<strong>आरटीआई — बुनियादी सहायता:</strong><br><br>आरटीआई अधिनियम 2005 के तहत आप सरकारी कार्यालय से जानकारी मांग सकते हैं।<br><br>विभाग को सामान्यतः <strong>30 दिनों</strong> के भीतर जवाब देना होता है।'
      }
    };

    const topics = fallbackTopics[lang] || fallbackTopics.en;
    let reply = topics.default;
    if (/chori|theft|stolen|चोरी|phone|फ़ोन|snatch|fir|एफआईआर/.test(lower)) reply = topics.theft;
    else if (/violen|hinsa|हिंसा|domestic|abuse|beat|पीट/.test(lower)) reply = topics.violence;
    else if (/wage|salary|vetan|वेतन|labour|labor|श्रम/.test(lower)) reply = topics.wage;
    else if (/legal aid|free legal|निःशुल्क कानूनी सहायता|कानूनी सहायता|dlsa|nalsa|15100/.test(lower)) reply = topics.legalAid;
    else if (/landlord|tenant|rent|deposit|evict|eviction|lease|builder|property fraud|property|land|भूमि|ज़मीन|जमीन|मकान मालिक|किराया|डिपॉज़िट|बेदखली|बिल्डर|प्रॉपर्टी|encroach/.test(lower)) reply = topics.property || topics.land;
    else if (/divorce|custody|dowry|family court|domestic violence|तलाक|कस्टडी|दहेज|फैमिली कोर्ट|पारिवारिक/.test(lower)) reply = topics.family || topics.violence;
    else if (/salary not paid|wrongful termination|workplace harassment|offer letter|labour court|सैलरी नहीं मिली|नौकरी से निकाला|कार्यस्थल पर उत्पीड़न|लेबर कोर्ट/.test(lower)) reply = topics.employment || topics.wage;
    else if (/cyber|साइबर|online|ऑनलाइन|fraud|धोखा|धोखाधड़ी|phishing|1930/.test(lower)) reply = topics.cyber;
    else if (/accident|vehicle theft|insurance claim|traffic police|mact|एक्सीडेंट|वाहन चोरी|इंश्योरेंस|ट्रैफिक पुलिस/.test(lower)) reply = topics.traffic;
    else if (/consumer|उपभोक्ता|refund|warranty|edaakhil|product|defect/.test(lower)) reply = topics.consumer;
    else if (/bank fraud|cheque bounce|loan harassment|rbi ombudsman|banking|financial|बैंक फ्रॉड|चेक बाउंस|लोन परेशानियां|ओम्बड्समैन|वित्तीय/.test(lower)) reply = topics.finance;
    else if (/civil court|consumer court|labour court|family court|property\/money|job|criminal|general steps|quick rule|सिविल कोर्ट|कंज्यूमर कोर्ट|लेबर कोर्ट|फैमिली कोर्ट|अपराध|पैसा|नौकरी|सामान्य प्रक्रिया|आसान नियम/.test(lower)) reply = topics.quick;
    else if (/\brti\b|आरटीआई|सूचना का अधिकार|right to info/.test(lower)) reply = topics.rti;

    addMessage(reply, false, 'html');
    speakAssistantReplyInBrowser(reply);
  }

  function contextualFallbackReply(userText) {
    const lower = String(userText || '').toLowerCase();
    const recentText = conversationHistory
      .slice(-6)
      .map(msg => String(msg && msg.text ? msg.text : '').toLowerCase())
      .join(' ');

    function detectScope(text) {
      if (/where to file|where can i file|where should i file|which court|tribunal|forum|कहाँ|किस कोर्ट|कहाँ शिकायत/.test(text)) return 'where';
      if (/documents|document needed|documents needed|what documents|proof|papers|receipt|agreement|दस्तावेज|सबूत|कागज/.test(text)) return 'documents';
      if (/what to do|what can i do|what should i do|next step|next steps|how to proceed|क्या करें|क्या करूँ|अगला कदम/.test(text)) return 'what';
      return 'general';
    }

    function detectTopic(text) {
      if (/landlord|tenant|rent|deposit|evict|eviction|lease|builder|property fraud|property|land|भूमि|ज़मीन|जमीन|मकान मालिक|किराया|डिपॉज़िट|बेदखली|बिल्डर|प्रॉपर्टी|encroach/.test(text)) return 'property';
      if (/divorce|custody|dowry|family court|domestic violence|तलाक|कस्टडी|दहेज|फैमिली कोर्ट|पारिवारिक/.test(text)) return 'family';
      if (/salary|wage|vetan|वेतन|labour|labor|श्रम|wrongful termination|offer letter|लेबर कोर्ट|कार्यस्थल पर उत्पीड़न/.test(text)) return 'employment';
      if (/cyber|साइबर|online|ऑनलाइन|fraud|धोखा|धोखाधड़ी|phishing|1930/.test(text)) return 'cyber';
      if (/consumer|उपभोक्ता|refund|warranty|edaakhil|product|defect/.test(text)) return 'consumer';
      if (/bank fraud|cheque bounce|loan harassment|rbi ombudsman|banking|financial|बैंक फ्रॉड|चेक बाउंस|लोन परेशानियां|ओम्बड्समैन|वित्तीय/.test(text)) return 'finance';
      if (/accident|vehicle theft|insurance claim|traffic police|mact|एक्सीडेंट|वाहन चोरी|इंश्योरेंस|ट्रैफिक पुलिस/.test(text)) return 'traffic';
      if (/legal aid|free legal|कानूनी सहायता|dlsa|nalsa|15100/.test(text)) return 'legalAid';
      if (/\brti\b|आरटीआई|सूचना का अधिकार|right to info/.test(text)) return 'rti';
      if (/chori|theft|stolen|phone|snatch|fir|एफआईआर/.test(text)) return 'theft';
      return '';
    }

    const topic = detectTopic(lower) || detectTopic(recentText);
    const scope = detectScope(lower);
    const answers = {
      property: {
        title: 'Property & Rent Issues',
        what: 'Collect your agreement and payment proof, ask for the refund in writing, and send a legal notice if the landlord still refuses.',
        where: 'Civil Court or Rent Tribunal. For builder matters, Consumer Court may also apply.',
        documents: 'Rent agreement, payment receipts, bank statement, chats/emails, and photos/videos.',
      },
      family: {
        title: 'Family Issues',
        what: 'Seek immediate protection if needed, record the abuse or dispute details, and make a written complaint to the relevant authority.',
        where: 'Family Court or Police Station, depending on the issue.',
        documents: 'Marriage certificate, medical reports, chats/recordings, and income proof.',
      },
      employment: {
        title: 'Employment Issues',
        what: 'Keep your job records, raise a written complaint with your employer, and escalate if the issue is not resolved.',
        where: 'Labour Court or the relevant complaints authority, depending on the issue.',
        documents: 'Offer letter, salary slips, bank statement, emails, and complaint records.',
      },
      cyber: {
        title: 'Cyber Crime',
        what: 'Block the compromised account if possible, save the transaction details and screenshots, and report the incident immediately.',
        where: 'Cybercrime portal, helpline 1930, or police.',
        documents: 'Screenshots, transaction IDs, account details, phone numbers, and links.',
      },
      consumer: {
        title: 'Consumer Rights',
        what: 'Ask the seller or service provider for a refund or repair in writing, keep the complaint record, and escalate the complaint if they do not respond.',
        where: 'Consumer Commission or eDaakhil.',
        documents: 'Bill, warranty, complaint messages, photos, and product or service details.',
      },
      finance: {
        title: 'Financial Issues',
        what: 'Inform the bank or lender immediately, keep a written record of the issue, and file a formal complaint if the problem continues.',
        where: 'Bank grievance cell, RBI Ombudsman, or police depending on the issue.',
        documents: 'Bank statement, complaint reference, cheque memo, loan records, and transaction proof.',
      },
      traffic: {
        title: 'Traffic Issues',
        what: 'Record the incident details, take photos if possible, and report the matter promptly.',
        where: 'Traffic Police, police station, insurer, or MACT depending on the issue.',
        documents: 'Driving license, RC, insurance papers, photos, and any police report.',
      },
      legalAid: {
        title: 'Free Legal Aid',
        what: 'Apply for free legal aid through the District Legal Services Authority and explain your issue clearly.',
        where: 'District Legal Services Authority.',
        documents: 'Identity proof, eligibility proof, and a short summary of the issue.',
      },
      rti: {
        title: 'RTI',
        what: 'Write a clear RTI application, ask for specific information, and follow up if no reply is received in time.',
        where: 'The concerned public authority.',
        documents: 'RTI application, fee receipt if applicable, and previous correspondence.',
      },
      theft: {
        title: 'Theft / FIR',
        what: 'Write down what was stolen, when and where it happened, and ask the police to register an FIR or Zero FIR.',
        where: 'Nearest police station.',
        documents: 'ID proof, incident details, bills, photos, and any available evidence.',
      },
    };

    if (!topic || !answers[topic]) {
      fallbackReply(userText);
      return;
    }

    const answer = answers[topic];
    let reply = `<strong>${answer.title}:</strong><br><br><strong>What to do:</strong> ${answer.what}<br><br><strong>Where to file:</strong> ${answer.where}<br><br><strong>Documents needed:</strong> ${answer.documents}`;
    if (scope === 'what') reply = `<strong>${answer.title}:</strong><br><br><strong>What to do:</strong> ${answer.what}`;
    else if (scope === 'where') reply = `<strong>${answer.title}:</strong><br><br><strong>Where to file:</strong> ${answer.where}`;
    else if (scope === 'documents') reply = `<strong>${answer.title}:</strong><br><br><strong>Documents needed:</strong> ${answer.documents}`;

    addMessage(reply, false, 'html');
    speakAssistantReplyInBrowser(reply);
  }

  function contextualFallbackReply(userText) {
    const lang = getLang();
    const lower = String(userText || '').toLowerCase();
    const recentText = conversationHistory
      .slice(-6)
      .map(msg => String(msg && msg.text ? msg.text : '').toLowerCase())
      .join(' ');

    function detectScope(text) {
      if (/where to file|where can i file|where should i file|which court|tribunal|forum|कहाँ|किस कोर्ट|कहाँ शिकायत|कहाँ रिपोर्ट|कहां/.test(text)) return 'where';
      if (/documents|document needed|documents needed|what documents|proof|papers|receipt|agreement|दस्तावेज|सबूत|कागज|कागज़|प्रमाण/.test(text)) return 'documents';
      if (/what to do|what can i do|what should i do|next step|next steps|how to proceed|क्या करें|क्या करूं|क्या करूँ|अगला कदम|अब क्या/.test(text)) return 'what';
      return 'general';
    }

    function detectTopic(text) {
      if (/landlord|tenant|rent|deposit|evict|eviction|lease|builder|property fraud|property|land|भूमि|ज़मीन|जमीन|मकान मालिक|किराया|डिपॉजिट|बेदखली|बिल्डर|प्रॉपर्टी|encroach/.test(text)) return 'property';
      if (/divorce|custody|dowry|family court|domestic violence|तलाक|कस्टडी|दहेज|फैमिली कोर्ट|पारिवारिक|घरेलू हिंसा/.test(text)) return 'family';
      if (/salary|wage|vetan|वेतन|labour|labor|श्रम|wrongful termination|offer letter|लेबर कोर्ट|कार्यस्थल पर उत्पीड़न/.test(text)) return 'employment';
      if (/cyber|साइबर|online|ऑनलाइन|fraud|धोखा|धोखाधड़ी|phishing|1930/.test(text)) return 'cyber';
      if (/consumer|उपभोक्ता|refund|warranty|edaakhil|product|defect/.test(text)) return 'consumer';
      if (/bank fraud|cheque bounce|loan harassment|rbi ombudsman|banking|financial|बैंक फ्रॉड|चेक बाउंस|लोन परेशानियां|ओम्बड्समैन|वित्तीय/.test(text)) return 'finance';
      if (/accident|vehicle theft|insurance claim|traffic police|mact|एक्सीडेंट|वाहन चोरी|इंश्योरेंस|ट्रैफिक पुलिस/.test(text)) return 'traffic';
      if (/legal aid|free legal|कानूनी सहायता|dlsa|nalsa|15100/.test(text)) return 'legalAid';
      if (/\brti\b|आरटीआई|सूचना का अधिकार|right to info/.test(text)) return 'rti';
      if (/chori|theft|stolen|phone|mobile|snatch|fir|फोन|फ़ोन|मोबाइल|चोरी|एफआईआर|एफ़आईआर/.test(text)) return 'theft';
      return '';
    }

    const fallbackCatalog = {
      en: {
        default: {
          title: 'Legal Help',
          what: 'Please describe what happened, when it happened, and where it happened so I can guide you more clearly.',
          where: 'The correct authority depends on the issue. If it is a crime, start with the police. For civil disputes, the relevant court or tribunal may apply.',
          documents: 'Keep identity proof, incident details, photos, screenshots, bills, and any written communication.',
        },
        property: {
          title: 'Property & Rent Issues',
          what: 'Collect your agreement and payment proof, ask for the refund in writing, and send a legal notice if the landlord still refuses.',
          where: 'Civil Court or Rent Tribunal. For builder matters, Consumer Commission may also apply.',
          documents: 'Rent agreement, payment receipts, bank statement, chats/emails, and photos/videos.',
        },
        family: {
          title: 'Family Issues',
          what: 'Seek immediate protection if needed, record the abuse or dispute details, and make a written complaint to the relevant authority.',
          where: 'Family Court or Police Station, depending on the issue.',
          documents: 'Marriage certificate, medical reports, chats/recordings, and income proof.',
        },
        employment: {
          title: 'Employment Issues',
          what: 'Keep your job records, raise a written complaint with your employer, and escalate if the issue is not resolved.',
          where: 'Labour Court, Labour Commissioner, or the relevant complaints authority.',
          documents: 'Offer letter, salary slips, bank statement, emails, and complaint records.',
        },
        cyber: {
          title: 'Cyber Crime',
          what: 'Block the compromised account if possible, save the transaction details and screenshots, and report the incident immediately.',
          where: 'Cybercrime portal, helpline 1930, or police.',
          documents: 'Screenshots, transaction IDs, account details, phone numbers, and links.',
        },
        consumer: {
          title: 'Consumer Rights',
          what: 'Ask the seller or service provider for a refund or repair in writing, keep the complaint record, and escalate the complaint if they do not respond.',
          where: 'Consumer Commission or eDaakhil.',
          documents: 'Bill, warranty, complaint messages, photos, and product or service details.',
        },
        finance: {
          title: 'Financial Issues',
          what: 'Inform the bank or lender immediately, keep a written record of the issue, and file a formal complaint if the problem continues.',
          where: 'Bank grievance cell, RBI Ombudsman, or police depending on the issue.',
          documents: 'Bank statement, complaint reference, cheque memo, loan records, and transaction proof.',
        },
        traffic: {
          title: 'Traffic Issues',
          what: 'Record the incident details, take photos if possible, and report the matter promptly.',
          where: 'Traffic Police, police station, insurer, or MACT depending on the issue.',
          documents: 'Driving license, RC, insurance papers, photos, and any police report.',
        },
        legalAid: {
          title: 'Free Legal Aid',
          what: 'Apply for free legal aid through the District Legal Services Authority and explain your issue clearly.',
          where: 'District Legal Services Authority.',
          documents: 'Identity proof, eligibility proof, and a short summary of the issue.',
        },
        rti: {
          title: 'RTI',
          what: 'Write a clear RTI application, ask for specific information, and follow up if no reply is received in time.',
          where: 'The concerned public authority.',
          documents: 'RTI application, fee receipt if applicable, and previous correspondence.',
        },
        theft: {
          title: 'Theft / FIR',
          what: 'Write down what was stolen, when and where it happened. Block your SIM if a phone was stolen, keep the IMEI number, and ask the police to register an FIR or Zero FIR.',
          where: 'Nearest police station. You can also ask for a Zero FIR at any police station.',
          documents: 'ID proof, incident details, phone bill or IMEI, photos, and any available evidence.',
        },
      },
      hi: {
        default: {
          title: 'कानूनी सहायता',
          what: 'कृपया बताइए क्या हुआ, कब हुआ और कहाँ हुआ, ताकि मैं आपको अधिक सही सलाह दे सकूँ।',
          where: 'सही प्राधिकरण मामले पर निर्भर करता है। अपराध होने पर पहले पुलिस से संपर्क करें। सिविल विवाद में सम्बन्धित न्यायालय या प्राधिकरण लागू हो सकता है।',
          documents: 'पहचान पत्र, घटना का विवरण, फ़ोटो, स्क्रीनशॉट, बिल और लिखित बातचीत सुरक्षित रखें।',
        },
        property: {
          title: 'सम्पत्ति और किराया विवाद',
          what: 'एग्रीमेंट और भुगतान के सबूत सुरक्षित रखें, लिखित में रिफंड या राहत माँगें, और ज़रूरत हो तो लीगल नोटिस भेजें।',
          where: 'सिविल कोर्ट, रेंट ट्रिब्यूनल, या बिल्डर मामले में कंज्यूमर कमीशन उपयुक्त हो सकता है।',
          documents: 'रेंट एग्रीमेंट, भुगतान रसीदें, बैंक स्टेटमेंट, चैट/ईमेल और फ़ोटो/वीडियो।',
        },
        family: {
          title: 'पारिवारिक मामले',
          what: 'जरूरत हो तो तुरंत सुरक्षा लें, घटना या विवाद का रिकॉर्ड रखें, और सम्बन्धित प्राधिकरण को लिखित शिकायत दें।',
          where: 'मामले के अनुसार फैमिली कोर्ट या पुलिस स्टेशन।',
          documents: 'विवाह प्रमाणपत्र, मेडिकल रिपोर्ट, चैट/रिकॉर्डिंग और आय सम्बन्धी दस्तावेज़।',
        },
        employment: {
          title: 'नौकरी और वेतन सम्बन्धी मामले',
          what: 'नौकरी से जुड़े रिकॉर्ड सुरक्षित रखें, नियोक्ता को लिखित शिकायत दें, और समाधान न मिलने पर मामला आगे बढ़ाएँ।',
          where: 'लेबर कमिश्नर, लेबर कोर्ट, या सम्बन्धित शिकायत प्राधिकरण।',
          documents: 'ऑफ़र लेटर, वेतन स्लिप, बैंक स्टेटमेंट, ईमेल और शिकायत की कॉपी।',
        },
        cyber: {
          title: 'साइबर अपराध',
          what: 'अकाउंट या सिम सुरक्षित करें, स्क्रीनशॉट और ट्रांजैक्शन डिटेल्स सेव करें, और तुरंत शिकायत दर्ज करें।',
          where: 'cybercrime.gov.in, हेल्पलाइन 1930, या पुलिस स्टेशन।',
          documents: 'स्क्रीनशॉट, ट्रांजैक्शन आईडी, अकाउंट डिटेल्स, फोन नंबर और लिंक।',
        },
        consumer: {
          title: 'उपभोक्ता अधिकार',
          what: 'विक्रेता या सेवा प्रदाता से लिखित में रिफंड या रिपेयर माँगें, शिकायत का रिकॉर्ड रखें, और जवाब न मिलने पर शिकायत आगे बढ़ाएँ।',
          where: 'कंज्यूमर कमीशन या eDaakhil पोर्टल।',
          documents: 'बिल, वारंटी, शिकायत संदेश, फ़ोटो और प्रोडक्ट/सेवा का विवरण।',
        },
        finance: {
          title: 'बैंकिंग और वित्तीय मामले',
          what: 'तुरंत बैंक या ऋणदाता को सूचित करें, समस्या का लिखित रिकॉर्ड रखें, और जरूरत होने पर औपचारिक शिकायत करें।',
          where: 'बैंक grievance cell, RBI Ombudsman, या पुलिस स्टेशन।',
          documents: 'बैंक स्टेटमेंट, शिकायत संख्या, चेक मेमो, लोन रिकॉर्ड और ट्रांजैक्शन प्रूफ।',
        },
        traffic: {
          title: 'ट्रैफिक और वाहन मामले',
          what: 'घटना का रिकॉर्ड बनाएं, संभव हो तो फ़ोटो लें, और मामले की तुरंत रिपोर्ट करें।',
          where: 'ट्रैफिक पुलिस, पुलिस स्टेशन, बीमा कंपनी, या MACT।',
          documents: 'ड्राइविंग लाइसेंस, RC, इंश्योरेंस पेपर, फ़ोटो और पुलिस रिपोर्ट।',
        },
        legalAid: {
          title: 'निःशुल्क कानूनी सहायता',
          what: 'जिला विधिक सेवा प्राधिकरण से निःशुल्क कानूनी सहायता के लिए आवेदन करें और अपनी समस्या साफ़ लिखें।',
          where: 'जिला विधिक सेवा प्राधिकरण (DLSA)।',
          documents: 'पहचान पत्र, पात्रता से जुड़े दस्तावेज़ और समस्या का संक्षिप्त विवरण।',
        },
        rti: {
          title: 'आरटीआई',
          what: 'स्पष्ट आरटीआई आवेदन लिखें, माँगी गई जानकारी साफ़ बताएं, और समय पर जवाब न मिले तो फॉलो-अप करें।',
          where: 'सम्बन्धित सरकारी कार्यालय या लोक सूचना अधिकारी।',
          documents: 'आरटीआई आवेदन, फीस रसीद (यदि लागू हो), और पूर्व पत्राचार।',
        },
        theft: {
          title: 'फोन चोरी / एफ़आईआर',
          what: 'तुरंत सिम ब्लॉक कराएं, फोन का IMEI नंबर सुरक्षित रखें, घटना का समय और स्थान लिखें, और नज़दीकी थाने में एफ़आईआर या ज़ीरो एफ़आईआर दर्ज कराने को कहें।',
          where: 'नज़दीकी पुलिस स्टेशन। जरूरत हो तो किसी भी थाने में ज़ीरो एफ़आईआर दर्ज कराई जा सकती है।',
          documents: 'पहचान पत्र, घटना का विवरण, मोबाइल बिल या IMEI नंबर, फ़ोटो और उपलब्ध सबूत।',
        },
      }
    };

    const topic = detectTopic(lower) || detectTopic(recentText);
    const scope = detectScope(lower);
    const answers = fallbackCatalog[lang] || fallbackCatalog.en;
    const answer = answers[topic] || answers.default;
    const labels = lang === 'hi'
      ? { what: 'क्या करें', where: 'कहाँ शिकायत करें', documents: 'कौन से दस्तावेज़ रखें' }
      : { what: 'What to do', where: 'Where to file', documents: 'Documents needed' };

    let reply = `<strong>${answer.title}:</strong><br><br><strong>${labels.what}:</strong> ${answer.what}<br><br><strong>${labels.where}:</strong> ${answer.where}<br><br><strong>${labels.documents}:</strong> ${answer.documents}`;
    if (scope === 'what') reply = `<strong>${answer.title}:</strong><br><br><strong>${labels.what}:</strong> ${answer.what}`;
    else if (scope === 'where') reply = `<strong>${answer.title}:</strong><br><br><strong>${labels.where}:</strong> ${answer.where}`;
    else if (scope === 'documents') reply = `<strong>${answer.title}:</strong><br><br><strong>${labels.documents}:</strong> ${answer.documents}`;

    addMessage(reply, false, 'html');
    speakAssistantReplyInBrowser(reply);
  }

  function handleOutgoingChatMessage(text) {
    if (!text) return;
    addMessage(text, true, 'text');
    conversationHistory.push({ role: 'user', text });
    sendToBackendChat(text).then(sent => {
      if (!sent) contextualFallbackReply(text);
    });
  }

  on(sendBtn, 'click', () => {
    if (!chatInput) return;
    const text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = '';
    handleOutgoingChatMessage(text);
  });

  on(chatInput, 'keydown', e => { if (e.key === 'Enter' && sendBtn) sendBtn.click(); });
  on(stopAudioBtn, 'click', stopResponseAudio);

  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      showPage('chat');
      const text = chip.textContent.trim();
      handleOutgoingChatMessage(text);
    });
  });

  /* ── STATS ─────────────────────────────────────────────── */
  function updateStats() {
    const statNums = document.querySelectorAll('.stat-card .stat-num');
    if (statNums.length >= 2) {
      statNums[0].textContent = messageCount;
      statNums[1].textContent = generatedDocs.length;
    }
  }

  /* ── MIC BUTTON — Vapi Voice Call OR Web Speech API ────── */
  let newMicBtn = micBtn;
  let newMicStatus = micStatus;
  if (micBtn) {
    micBtn.replaceWith(micBtn.cloneNode(true));
    newMicBtn = document.getElementById('micBtn');
    newMicStatus = document.getElementById('micStatus');
  }

  on(newMicBtn, 'click', () => {
    if (vapiInstance) {
      startVapiCall();
    } else {
      startWebSpeechDashboard();
    }
  });

  function startVapiCall() {
    if (newMicBtn.classList.contains('listening') || (vapiCallActive && vapiSessionMode === 'voice')) {
      clearPendingSpeechFallback();
      stopBrowserSpeech();
      vapiInstance.stop();
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      vapiCallActive = false;
      vapiSessionMode = null;
      return;
    }
    if (vapiCallActive && vapiSessionMode === 'chat') {
      clearPendingSpeechFallback();
      stopBrowserSpeech();
      try {
        vapiInstance.stop();
      } catch (err) {
        console.error('Vapi stop before switching from chat to voice failed:', err);
      }
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
    }
    newMicBtn.classList.add('listening');
    newMicStatus.textContent = t('vcListening');

    vapiInstance.start({
      serverUrl: API_BASE + '/vapi-webhook',
      serverUrlSecret: '',
      metadata: { user_id: userId, language: getLang(), mode: 'voice' },
    }).catch(err => {
      console.error('Vapi call failed:', err);
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      startWebSpeechDashboard();
    });
    vapiCallActive = true;
    vapiSessionMode = 'voice';
  }

  /* ── WEB SPEECH API — Fallback Voice Input ─────────────── */
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let activeRecognition = null;
  let activeVoiceInputBtn = null;

  function getSpeechLang() {
    return getLang() === 'hi' ? 'hi-IN' : 'en-IN';
  }

  function startWebSpeechDashboard() {
    if (!SpeechRecognition) {
      alert(getLang() === 'hi' ? 'आपका ब्राउज़र वॉइस इनपुट का समर्थन नहीं करता।' : 'Your browser does not support voice input.');
      return;
    }

    if (newMicBtn.classList.contains('listening')) {
      if (activeRecognition) activeRecognition.stop();
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = getSpeechLang();
    recognition.interimResults = false;
    recognition.continuous = false;
    activeRecognition = recognition;

    newMicBtn.classList.add('listening');
    newMicStatus.textContent = t('vcListening');

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      activeRecognition = null;
      showPage('chat');
      handleOutgoingChatMessage(transcript);
    };

    recognition.onerror = () => {
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      activeRecognition = null;
    };

    recognition.onend = () => {
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      activeRecognition = null;
    };

    recognition.start();
  }

  /* ── Voice input for form fields ───────────────────────── */
  function stopActiveVoiceInput() {
    if (activeRecognition) {
      activeRecognition.stop();
      activeRecognition = null;
    }
    if (activeVoiceInputBtn) {
      activeVoiceInputBtn.classList.remove('voice-active');
      activeVoiceInputBtn = null;
    }
  }

  function startVoiceInput(targetId, btn) {
    if (!SpeechRecognition) {
      alert(getLang() === 'hi' ? 'आपका ब्राउज़र वॉइस इनपुट का समर्थन नहीं करता। कृपया Chrome उपयोग करें।' : 'Your browser does not support voice input. Please use Chrome.');
      return;
    }

    if (activeRecognition && activeVoiceInputBtn === btn) {
      stopActiveVoiceInput();
      return;
    }

    stopActiveVoiceInput();

    const recognition = new SpeechRecognition();
    recognition.lang = getSpeechLang();
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    activeRecognition = recognition;
    activeVoiceInputBtn = btn;

    btn.classList.add('voice-active');

    const target = document.getElementById(targetId);
    let finalTranscript = target.value || '';

    recognition.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          finalTranscript += (finalTranscript ? ' ' : '') + event.results[i][0].transcript;
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      target.value = finalTranscript + (interim ? ' ' + interim : '');
    };

    recognition.onerror = () => {
      btn.classList.remove('voice-active');
      activeRecognition = null;
      if (activeVoiceInputBtn === btn) activeVoiceInputBtn = null;
    };

    recognition.onend = () => {
      btn.classList.remove('voice-active');
      activeRecognition = null;
      if (activeVoiceInputBtn === btn) activeVoiceInputBtn = null;
      target.value = finalTranscript;
    };

    recognition.start();
  }

  document.querySelectorAll('.voice-input-btn[data-voice-target]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      startVoiceInput(btn.dataset.voiceTarget, btn);
    });
  });

  /* ── CHAT MIC — Real Speech Recognition ────────────────── */
  const chatMicBtn = document.getElementById('chatMicBtn');
  let chatRecognition = null;

  if (chatMicBtn) {
    chatMicBtn.addEventListener('click', () => {
      if (!SpeechRecognition) {
        alert(getLang() === 'hi' ? 'आपका ब्राउज़र वॉइस इनपुट का समर्थन नहीं करता।' : 'Your browser does not support voice input.');
        return;
      }

      if (chatRecognition) {
        chatRecognition.stop();
        chatRecognition = null;
        chatMicBtn.classList.remove('voice-active');
        return;
      }

      const recognition = new SpeechRecognition();
      recognition.lang = getSpeechLang();
      recognition.interimResults = false;
      recognition.continuous = false;
      chatRecognition = recognition;

      chatMicBtn.classList.add('voice-active');

      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        chatInput.value = transcript;
        chatMicBtn.classList.remove('voice-active');
        chatRecognition = null;
        sendBtn.click();
      };

      recognition.onerror = () => {
        chatMicBtn.classList.remove('voice-active');
        chatRecognition = null;
      };

      recognition.onend = () => {
        chatMicBtn.classList.remove('voice-active');
        chatRecognition = null;
      };

      recognition.start();
    });
  }

  /* ── FIR WIZARD ────────────────────────────────────────── */
  const firWizard = document.getElementById('firWizard');
  let firStep = 1;

  function showFirStep(n) {
    firStep = n;
    firWizard.querySelectorAll('.wizard-step').forEach(s => { s.classList.remove('active'); s.style.display = 'none'; });
    const target = firWizard.querySelector(`[data-step="${n}"]`);
    if (target) { target.style.display = ''; target.classList.add('active'); }
  }

  if (firWizard) {
    firWizard.addEventListener('click', e => {
      if (e.target.classList.contains('wizard-next')) {
        if (firStep === 1 && !document.getElementById('firIncident').value.trim()) {
          alert(t('alertIncident')); return;
        }
        if (firStep === 2 && !document.getElementById('firDate').value) {
          alert(t('alertDate')); return;
        }
        if (firStep === 3 && !document.getElementById('firLocation').value.trim()) {
          alert(t('alertLocation')); return;
        }
        if (firStep < 5) showFirStep(firStep + 1);
        if (firStep === 5) buildFirReview();
      }
      if (e.target.classList.contains('wizard-back')) {
        if (firStep > 1) showFirStep(firStep - 1);
      }
    });
  }

  function buildFirReview() {
    const lang = getLang();
    const labels = lang === 'hi'
      ? { what: 'क्या हुआ', when: 'कब हुआ', where: 'कहाँ हुआ', suspect: 'आरोपी', witness: 'गवाह' }
      : { what: 'What happened', when: 'When', where: 'Where', suspect: 'Suspect', witness: 'Witness' };

    document.getElementById('firReview').innerHTML = `
      <p><strong>${labels.what}:</strong> ${document.getElementById('firIncident').value || '—'}</p>
      <p><strong>${labels.when}:</strong> ${document.getElementById('firDate').value || '—'}</p>
      <p><strong>${labels.where}:</strong> ${document.getElementById('firLocation').value || '—'}</p>
      <p><strong>${labels.suspect}:</strong> ${document.getElementById('firSuspect').value || '—'}</p>
      <p><strong>${labels.witness}:</strong> ${document.getElementById('firWitness').value || '—'}</p>
    `;
  }

  /* ── FIR Generate — calls backend /generate-document ───── */
  const firGenerateBtn = document.getElementById('firGenerateBtn');
  if (firGenerateBtn) firGenerateBtn.addEventListener('click', async () => {
    const incident = document.getElementById('firIncident').value;
    const date = document.getElementById('firDate').value;
    const location = document.getElementById('firLocation').value;
    const suspect = document.getElementById('firSuspect').value;
    const witness = document.getElementById('firWitness').value;

    const generateBtn = document.getElementById('firGenerateBtn');
    generateBtn.disabled = true;
    generateBtn.textContent = getLang() === 'hi' ? 'तैयार हो रहा है...' : 'Generating...';

    try {
      const result = await apiCall('/api/generate-document', {
        user_id: userId,
        doc_type: 'FIR',
        details: {
          incident_description: incident,
          date_time: date,
          location: location,
          suspect_description: suspect || 'Unknown',
          witness: witness || 'None',
          language: getLang(),
          complainant_id: userId,
        },
      });

      generatedDocs.push({
        name: result.filename,
        url: result.document_url,
        type: 'FIR',
        date: new Date().toLocaleDateString(),
      });
      localStorage.setItem('nyayavoice_docs', JSON.stringify(generatedDocs));
      updateStats();

      showFirStep('done');

      const downloadBtn = firWizard.querySelector('[data-step="done"] .btn-primary');
      if (downloadBtn) {
        downloadBtn.onclick = () => window.open(result.document_url, '_blank');
      }

    } catch (err) {
      console.error('FIR generation failed:', err);
      alert((getLang() === 'hi' ? 'एफ़आईआर बनाने में त्रुटि: ' : 'FIR generation failed: ') + err.message);
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = t('firGenerate');
    }
  });

  const firNewBtn = document.getElementById('firNewBtn');
  if (firNewBtn) firNewBtn.addEventListener('click', () => {
    ['firIncident', 'firDate', 'firLocation', 'firSuspect', 'firWitness'].forEach(id => document.getElementById(id).value = '');
    showFirStep(1);
  });

  const detectBtn = document.getElementById('detectLocationBtn');
  if (detectBtn) detectBtn.addEventListener('click', () => {
    detectBtn.querySelector('span').textContent = t('firDetecting');
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          document.getElementById('firLocation').value =
            `Lat: ${pos.coords.latitude.toFixed(4)}, Lon: ${pos.coords.longitude.toFixed(4)}`;
          detectBtn.querySelector('span').textContent = t('firDetected');
          setTimeout(() => detectBtn.querySelector('span').textContent = t('firDetect'), 2000);
        },
        () => {
          document.getElementById('firLocation').value =
            getLang() === 'hi' ? 'मुख्य बाज़ार, सेक्टर 12, दिल्ली' : 'Main Bazaar, Sector 12, Delhi';
          detectBtn.querySelector('span').textContent = t('firDetected');
          setTimeout(() => detectBtn.querySelector('span').textContent = t('firDetect'), 2000);
        }
      );
    } else {
      document.getElementById('firLocation').value =
        getLang() === 'hi' ? 'मुख्य बाज़ार, सेक्टर 12, दिल्ली' : 'Main Bazaar, Sector 12, Delhi';
      detectBtn.querySelector('span').textContent = t('firDetected');
      setTimeout(() => detectBtn.querySelector('span').textContent = t('firDetect'), 2000);
    }
  });

  const CASE_DATA = {
    theft: { success: 68, time: '3-6', cost: '₹2-5K', similar: 24, won: 55, settled: 20, lost: 25, laws: ['IPC 378', 'IPC 379', 'IPC 411', 'CrPC 154'] },
    dv: { success: 75, time: '6-12', cost: '₹5-15K', similar: 32, won: 60, settled: 25, lost: 15, laws: ['DV Act 2005', 'IPC 498A', 'CrPC 125', 'HMA 1955'] },
    wage: { success: 80, time: '3-9', cost: '₹1-3K', similar: 28, won: 65, settled: 25, lost: 10, laws: ['Payment of Wages Act', 'Min. Wages Act', 'ID Act 1947'] },
    harass: { success: 70, time: '6-18', cost: '₹10-30K', similar: 18, won: 50, settled: 30, lost: 20, laws: ['POSH Act 2013', 'IPC 354A', 'IPC 509'] },
    land: { success: 55, time: '12-36', cost: '₹20-80K', similar: 20, won: 45, settled: 30, lost: 25, laws: ['TPA 1882', 'Registration Act', 'Specific Relief Act'] },
    cyber: { success: 62, time: '6-12', cost: '₹5-15K', similar: 15, won: 50, settled: 25, lost: 25, laws: ['IT Act 2000', 'IT Amdt. 2008', 'IPC 420', 'IPC 468'] },
    consumer: { success: 78, time: '3-12', cost: '₹1-5K', similar: 35, won: 65, settled: 20, lost: 15, laws: ['CPA 2019', 'Legal Metrology Act', 'FSSAI Act'] }
  };

  const CASE_TRAINING_DATA = {
    theft: {
      baseConfidence: 64,
      laws: ['IPC 378', 'IPC 379', 'IPC 411', 'CrPC 154'],
      judgeQuestions: {
        en: ['When did the theft happen, and can you show the timeline clearly?', 'What specific property was taken, and how will you prove ownership?', 'Did you report the incident promptly to police or any authority?'],
        hi: ['चोरी कब हुई, और क्या आप समय-क्रम साफ़ बता सकते हैं?', 'कौन सी वस्तु चोरी हुई, और उसके मालिक होने का सबूत कैसे देंगे?', 'क्या आपने घटना की रिपोर्ट तुरंत पुलिस या किसी प्राधिकरण को दी थी?']
      },
      opponentQuestions: {
        en: ['Do you have proof that the accused had access to the property?', 'If there is no CCTV or witness, why should your version be believed?', 'Can the other side say the property was misplaced and not stolen?'],
        hi: ['क्या आपके पास यह साबित करने का सबूत है कि आरोपी को उस संपत्ति तक पहुंच थी?', 'अगर CCTV या गवाह नहीं है, तो आपकी बात पर भरोसा क्यों किया जाए?', 'क्या सामने वाला यह कह सकता है कि सामान खो गया था, चोरी नहीं हुआ?']
      },
      weaknessHints: {
        missingEvidence: { en: 'Ownership or theft proof is thin right now.', hi: 'इस समय मालिकाना हक या चोरी का सबूत कमज़ोर है।' },
        missingTimeline: { en: 'Your timeline may be too vague for police or court follow-up.', hi: 'आपकी समय-रेखा पुलिस या अदालत के लिए बहुत अस्पष्ट लग सकती है।' },
        generic: { en: 'Be ready to explain access, motive, and immediate reporting.', hi: 'पहुँच, कारण और तुरंत रिपोर्ट करने की बात साफ़ रखने की तैयारी करें।' }
      },
      actionSteps: {
        en: ['Collect ownership proof, bills, photos, or item identifiers.', 'Write a clean timeline from last possession to discovery of loss.', 'File or update the complaint/FIR and keep the acknowledgement copy.', 'Ask witnesses or nearby shops for CCTV before footage is deleted.'],
        hi: ['मालिकाना हक के सबूत, बिल, फोटो या वस्तु की पहचान से जुड़े दस्तावेज़ जुटाएँ।', 'सामान आखिरी बार कब आपके पास था से लेकर गुम होने तक की साफ़ समय-रेखा लिखें।', 'शिकायत या एफ़आईआर दर्ज करें या अपडेट करें और उसकी प्रति सुरक्षित रखें।', 'फुटेज मिटने से पहले गवाहों या आसपास की दुकानों से CCTV के बारे में पूछें।']
      }
    },
    dv: {
      baseConfidence: 70,
      laws: ['DV Act 2005', 'IPC 498A', 'CrPC 125', 'HMA 1955'],
      judgeQuestions: {
        en: ['What specific incidents happened, and on what dates?', 'Do you have medical records, messages, or prior complaints?', 'Is there an immediate safety concern for you or any children?'],
        hi: ['कौन-कौन सी घटनाएँ हुईं, और वे किन तारीखों पर हुईं?', 'क्या आपके पास मेडिकल रिकॉर्ड, संदेश या पुरानी शिकायतें हैं?', 'क्या आपके या किसी बच्चे के लिए अभी तत्काल सुरक्षा का खतरा है?']
      },
      opponentQuestions: {
        en: ['Why was there no complaint earlier if the abuse was repeated?', 'Can the other side say this is a family dispute and not violence?', 'Do your messages or witnesses support repeated abuse or control?'],
        hi: ['अगर हिंसा बार-बार हुई, तो पहले शिकायत क्यों नहीं की गई?', 'क्या दूसरी तरफ़ इसे सिर्फ़ पारिवारिक विवाद कह सकती है, हिंसा नहीं?', 'क्या आपके संदेश या गवाह लगातार हिंसा या नियंत्रण को साबित करते हैं?']
      },
      weaknessHints: {
        missingEvidence: { en: 'Independent proof of abuse or injury looks limited.', hi: 'हिंसा या चोट का स्वतंत्र सबूत सीमित दिख रहा है।' },
        missingTimeline: { en: 'Repeated incidents need a clearer sequence.', hi: 'बार-बार हुई घटनाओं का क्रम और साफ़ होना चाहिए।' },
        generic: { en: 'Consistency across incidents, injuries, and witnesses will matter a lot.', hi: 'घटनाओं, चोटों और गवाहों में एकरूपता बहुत महत्वपूर्ण होगी।' }
      },
      actionSteps: {
        en: ['Write each incident separately with date, place, and who saw it.', 'Preserve medical papers, photos, chats, calls, and prior complaints.', 'If safety is urgent, contact police, a protection officer, or a trusted shelter immediately.', 'Seek legal aid or a support organization for protection, residence, and maintenance options.'],
        hi: ['हर घटना को तारीख, स्थान और गवाहों के साथ अलग-अलग लिखें।', 'मेडिकल कागज़, फोटो, चैट, कॉल और पुरानी शिकायतें सुरक्षित रखें।', 'अगर सुरक्षा का खतरा है, तो तुरंत पुलिस, प्रोटेक्शन ऑफिसर या सुरक्षित आश्रय से संपर्क करें।', 'सुरक्षा, निवास और भरण-पोषण के विकल्पों के लिए कानूनी सहायता या सहायता संगठन से जुड़ें।']
      }
    },
    wage: {
      baseConfidence: 76,
      laws: ['Payment of Wages Act', 'Minimum Wages Act', 'ID Act 1947'],
      judgeQuestions: {
        en: ['What work did you do, and what amount is unpaid?', 'Do you have salary slips, attendance, bank records, or chats from the employer?', 'Have you already made a written demand for pending wages?'],
        hi: ['आपने कौन सा काम किया, और कितना वेतन बकाया है?', 'क्या आपके पास सैलरी स्लिप, उपस्थिति, बैंक रिकॉर्ड या नियोक्ता की चैट है?', 'क्या आपने बकाया वेतन के लिए पहले लिखित मांग की है?']
      },
      opponentQuestions: {
        en: ['Can the employer say you were absent or left without notice?', 'If there is no written contract, how will you prove the pay rate?', 'Do your records show the exact period of unpaid work?'],
        hi: ['क्या नियोक्ता कह सकता है कि आप अनुपस्थित थे या बिना सूचना चले गए?', 'अगर लिखित अनुबंध नहीं है, तो वेतन दर कैसे साबित करेंगे?', 'क्या आपके रिकॉर्ड में बकाया काम की पूरी अवधि साफ़ दिखती है?']
      },
      weaknessHints: {
        missingEvidence: { en: 'Employment records and payment proof need strengthening.', hi: 'रोज़गार रिकॉर्ड और भुगतान का सबूत और मजबूत करना होगा।' },
        missingTimeline: { en: 'The unpaid work period is not yet mapped clearly.', hi: 'बकाया काम की अवधि अभी साफ़ तरह से दर्ज नहीं है।' },
        generic: { en: 'Your strongest path is precise wage math backed by work records.', hi: 'काम के रिकॉर्ड के साथ सटीक वेतन गणना आपका सबसे मजबूत आधार होगा।' }
      },
      actionSteps: {
        en: ['Prepare a month-by-month unpaid wage calculation.', 'Collect attendance proof, bank entries, chats, ID cards, and coworker support.', 'Send a written demand to the employer and keep a copy.', 'Approach the Labour Commissioner or legal aid if the employer still refuses.'],
        hi: ['महीने-दर-महीने बकाया वेतन की गणना तैयार करें।', 'उपस्थिति, बैंक एंट्री, चैट, आईडी कार्ड और सहकर्मियों के समर्थन के सबूत रखें।', 'नियोक्ता को लिखित मांग भेजें और उसकी प्रति सुरक्षित रखें।', 'अगर नियोक्ता फिर भी मना करे तो श्रम आयुक्त या कानूनी सहायता से संपर्क करें।']
      }
    },
    harass: {
      baseConfidence: 66,
      laws: ['POSH Act 2013', 'IPC 354A', 'IPC 509'],
      judgeQuestions: {
        en: ['What exactly was said or done, and where did it happen?', 'Did you report it internally or to any authority?', 'Are there messages, emails, CCTV clips, or coworkers who noticed the conduct?'],
        hi: ['ठीक-ठीक क्या कहा गया या किया गया, और यह कहाँ हुआ?', 'क्या आपने इसकी शिकायत संस्था के अंदर या किसी प्राधिकरण को दी?', 'क्या संदेश, ईमेल, CCTV या सहकर्मी हैं जिन्होंने यह व्यवहार देखा?']
      },
      opponentQuestions: {
        en: ['Can the other side say your interpretation is exaggerated or mistaken?', 'If others were present, who will support your version?', 'Did you preserve the original chats or screenshots with dates?'],
        hi: ['क्या दूसरी तरफ़ कह सकती है कि आपने बात को बढ़ा-चढ़ाकर समझा?', 'अगर दूसरे लोग मौजूद थे, तो कौन आपकी बात का समर्थन करेगा?', 'क्या आपने तारीख सहित मूल चैट या स्क्रीनशॉट सुरक्षित रखे हैं?']
      },
      weaknessHints: {
        missingEvidence: { en: 'Harassment claims are often attacked when records are missing.', hi: 'जब रिकॉर्ड नहीं होते, तो उत्पीड़न के दावों पर जल्दी हमला होता है।' },
        missingTimeline: { en: 'You may need a clearer sequence of incidents and complaints.', hi: 'घटनाओं और शिकायतों का क्रम और साफ़ चाहिए।' },
        generic: { en: 'Precision about words, context, and witnesses will improve credibility.', hi: 'शब्दों, संदर्भ और गवाहों की सटीकता विश्वसनीयता बढ़ाएगी।' }
      },
      actionSteps: {
        en: ['Record each incident with date, place, and exact conduct.', 'Keep original chats, mails, screenshots, and reporting history.', 'Use the POSH/Internal Committee route where applicable and preserve acknowledgement.', 'Seek support from a trusted colleague, legal aid, or counselor if pressure is escalating.'],
        hi: ['हर घटना को तारीख, स्थान और सटीक व्यवहार के साथ दर्ज करें।', 'मूल चैट, मेल, स्क्रीनशॉट और शिकायत इतिहास सुरक्षित रखें।', 'जहाँ लागू हो, POSH/आंतरिक समिति की प्रक्रिया अपनाएँ और रसीद सुरक्षित रखें।', 'अगर दबाव बढ़ रहा है, तो भरोसेमंद सहकर्मी, कानूनी सहायता या काउंसलर से मदद लें।']
      }
    },
    land: {
      baseConfidence: 58,
      laws: ['TPA 1882', 'Registration Act', 'Specific Relief Act', 'Limitation Act'],
      judgeQuestions: {
        en: ['Which property is involved, and what title or possession documents do you hold?', 'When did the dispute begin, and what happened after that?', 'Have you sent a notice or made any complaint about encroachment or interference?'],
        hi: ['कौन सी संपत्ति विवाद में है, और आपके पास मालिकाना या कब्जे के कौन से कागज़ हैं?', 'विवाद कब शुरू हुआ, और उसके बाद क्या हुआ?', 'क्या आपने अतिक्रमण या दखल के बारे में कोई नोटिस या शिकायत दी है?']
      },
      opponentQuestions: {
        en: ['Can the other side show stronger title papers or longer possession?', 'If boundaries are disputed, do you have maps, mutation, or survey support?', 'Is there any delay that can be used against your claim?'],
        hi: ['क्या दूसरी तरफ़ मजबूत मालिकाना कागज़ या लंबे कब्जे का दावा दिखा सकती है?', 'अगर सीमा विवाद है, तो क्या आपके पास नक्शा, म्यूटेशन या सर्वे का सहारा है?', 'क्या कोई देरी है जिसे आपके खिलाफ़ इस्तेमाल किया जा सकता है?']
      },
      weaknessHints: {
        missingEvidence: { en: 'Property papers and possession proof may not yet be enough.', hi: 'संपत्ति के कागज़ और कब्जे का सबूत अभी पर्याप्त नहीं लग रहा।' },
        missingTimeline: { en: 'Land disputes get weaker when delay and sequence are unclear.', hi: 'भूमि विवाद तब कमजोर पड़ते हैं जब देरी और घटनाओं का क्रम अस्पष्ट हो।' },
        generic: { en: 'Boundary details, title chain, and prompt objection will be critical.', hi: 'सीमा विवरण, मालिकाना श्रृंखला और समय पर आपत्ति बहुत महत्वपूर्ण होगी।' }
      },
      actionSteps: {
        en: ['Assemble title deeds, tax receipts, mutation entries, and survey records.', 'Make a clear chronology of ownership, possession, and interference.', 'Send a written objection or legal notice and preserve proof of service.', 'Consult a property lawyer or legal aid before the dispute hardens further.'],
        hi: ['टाइटल डीड, टैक्स रसीद, म्यूटेशन एंट्री और सर्वे रिकॉर्ड इकट्ठा करें।', 'मालिकाना, कब्जे और दखल की साफ़ समय-रेखा बनाएँ।', 'लिखित आपत्ति या कानूनी नोटिस भेजें और उसकी सेवा का सबूत रखें।', 'विवाद और बढ़ने से पहले संपत्ति वकील या कानूनी सहायता से सलाह लें।']
      }
    },
    cyber: {
      baseConfidence: 61,
      laws: ['IT Act 2000', 'IT Amendment 2008', 'IPC 420', 'IPC 468'],
      judgeQuestions: {
        en: ['What exactly happened online, and through which platform or account?', 'Do you have transaction IDs, screenshots, emails, or device logs?', 'How quickly did you report the fraud or preserve the digital trail?'],
        hi: ['ऑनलाइन क्या हुआ, और किस प्लेटफ़ॉर्म या अकाउंट पर हुआ?', 'क्या आपके पास ट्रांजैक्शन आईडी, स्क्रीनशॉट, ईमेल या डिवाइस लॉग हैं?', 'आपने धोखाधड़ी की रिपोर्ट कितनी जल्दी की या डिजिटल रिकॉर्ड कितनी जल्दी सुरक्षित किया?']
      },
      opponentQuestions: {
        en: ['Can the other side say the screenshots are incomplete or altered?', 'Do you know who controlled the account or number involved?', 'If money moved fast, do you have bank or wallet records tying it to the fraud?'],
        hi: ['क्या दूसरी तरफ़ कह सकती है कि स्क्रीनशॉट अधूरे या बदले गए हैं?', 'क्या आपको पता है कि संबंधित अकाउंट या नंबर किसके नियंत्रण में था?', 'अगर पैसा जल्दी ट्रांसफर हुआ, तो क्या आपके पास बैंक या वॉलेट रिकॉर्ड हैं जो धोखाधड़ी से जुड़ते हों?']
      },
      weaknessHints: {
        missingEvidence: { en: 'Digital evidence may disappear quickly if not preserved fully.', hi: 'अगर डिजिटल सबूत पूरी तरह सुरक्षित नहीं किए गए, तो वे जल्दी गायब हो सकते हैं।' },
        missingTimeline: { en: 'Cyber cases need minute-by-minute reporting detail where possible.', hi: 'साइबर मामलों में जहाँ संभव हो, मिनट-दर-मिनट रिपोर्टिंग विवरण मदद करता है।' },
        generic: { en: 'Source account details and rapid reporting will shape your case strength.', hi: 'स्रोत अकाउंट का विवरण और तेज़ रिपोर्टिंग केस की ताकत तय करेंगे।' }
      },
      actionSteps: {
        en: ['Preserve screenshots, transaction IDs, phone numbers, emails, and URLs in one place.', 'Report quickly to the cyber portal, bank, wallet provider, and police.', 'Write the exact sequence from first contact to money loss or account misuse.', 'Do not delete devices or chats that may contain logs.'],
        hi: ['स्क्रीनशॉट, ट्रांजैक्शन आईडी, फोन नंबर, ईमेल और URL एक जगह सुरक्षित रखें।', 'साइबर पोर्टल, बैंक, वॉलेट प्रदाता और पुलिस को तुरंत रिपोर्ट करें।', 'पहले संपर्क से लेकर पैसे के नुकसान या अकाउंट दुरुपयोग तक पूरा क्रम लिखें।', 'ऐसे डिवाइस या चैट डिलीट न करें जिनमें लॉग हो सकते हैं।']
      }
    },
    consumer: {
      baseConfidence: 74,
      laws: ['CPA 2019', 'Legal Metrology Act', 'FSSAI Act'],
      judgeQuestions: {
        en: ['What product or service failed, and what loss did you suffer?', 'Do you have bills, warranty, chats, or complaint numbers?', 'Did you first ask the seller or platform to fix, refund, or replace the issue?'],
        hi: ['कौन सा उत्पाद या सेवा खराब निकला, और आपको क्या नुकसान हुआ?', 'क्या आपके पास बिल, वारंटी, चैट या शिकायत नंबर हैं?', 'क्या आपने पहले विक्रेता या प्लेटफ़ॉर्म से सुधार, रिफंड या रिप्लेसमेंट माँगा था?']
      },
      opponentQuestions: {
        en: ['Can the seller say the product was misused or outside warranty?', 'If you want compensation, how will you prove the amount of loss?', 'Do your records show you gave the business a fair chance to respond?'],
        hi: ['क्या विक्रेता कह सकता है कि उत्पाद का गलत उपयोग हुआ या वारंटी से बाहर था?', 'अगर आप मुआवज़ा चाहते हैं, तो नुकसान की राशि कैसे साबित करेंगे?', 'क्या आपके रिकॉर्ड दिखाते हैं कि आपने व्यवसाय को जवाब देने का उचित मौका दिया था?']
      },
      weaknessHints: {
        missingEvidence: { en: 'Purchase proof and complaint trail must be stronger.', hi: 'खरीद का सबूत और शिकायत का रिकॉर्ड और मजबूत होना चाहिए।' },
        missingTimeline: { en: 'Your complaint and response timeline needs tightening.', hi: 'शिकायत और जवाब की समय-रेखा और साफ़ होनी चाहिए।' },
        generic: { en: 'Consumer matters become stronger with receipts, notices, and quantified loss.', hi: 'उपभोक्ता मामलों में रसीद, नोटिस और स्पष्ट नुकसान गणना से ताकत बढ़ती है।' }
      },
      actionSteps: {
        en: ['Keep invoice, warranty, screenshots, and product photos together.', 'Document every complaint, response, and promised resolution.', 'Send one final written demand for refund, replacement, or repair.', 'Quantify your financial loss before filing a consumer complaint.'],
        hi: ['इनवॉइस, वारंटी, स्क्रीनशॉट और उत्पाद की फोटो एक साथ रखें।', 'हर शिकायत, जवाब और वादे की गई कार्रवाई दर्ज करें।', 'रिफंड, रिप्लेसमेंट या रिपेयर के लिए एक अंतिम लिखित मांग भेजें।', 'उपभोक्ता शिकायत दाखिल करने से पहले अपने आर्थिक नुकसान की गणना करें।']
      }
    }
  };

  function hasTimelineSignal(text) {
    return /(today|yesterday|last|before|after|date|dated|month|week|year|day|timeline|when|\b\d{1,2}[\/-]\d{1,2}|\b20\d{2}\b|आज|कल|पहले|बाद|तारीख|महीना|साल|दिन|समय)/i.test(text);
  }

  function hasReportSignal(text) {
    return /(police|fir|complaint|reported|report|notice|email|helpline|station|portal|शिकायत|रिपोर्ट|एफ़आईआर|एफआईआर|नोटिस|थाना|पोर्टल)/i.test(text);
  }

  function hasEvidenceNarrative(text) {
    return /(screenshot|bill|invoice|record|document|photo|video|medical|witness|chat|email|receipt|proof|cctv|message|सबूत|दस्तावेज|फोटो|वीडियो|गवाह|रसीद|चैट|ईमेल|रिकॉर्ड)/i.test(text);
  }

  function renderPracticeList(items) {
    return items.map(item => `<li>${item}</li>`).join('');
  }

  function renderWeaknessList(items) {
    return items.map(item => `<div class="weakness-item">${item}</div>`).join('');
  }

  const predictSession = {
    active: false,
    caseType: '',
    facts: '',
    lang: 'en',
    selectedEvidence: [],
    questions: [],
    answers: [],
    summary: '',
    questionTarget: 6,
  };

  async function requestCasePredictor() {
    return apiCall('/api/case-predictor', {
      case_type: predictSession.caseType,
      facts: predictSession.facts,
      evidence: predictSession.selectedEvidence,
      language: predictSession.lang,
      answers: predictSession.answers,
      question_target: predictSession.questionTarget,
    });
  }

  function showPredictQuestion(questionData) {
    const flow = document.getElementById('predInteractiveFlow');
    const legacy = document.getElementById('predLegacyReport');
    const counter = document.getElementById('predQuestionCounter');
    const role = document.getElementById('predQuestionRole');
    const question = document.getElementById('predCurrentQuestion');
    const answerInput = document.getElementById('predAnswerInput');
    const answerBtn = document.getElementById('predAnswerBtn');
    flow.style.display = 'block';
    legacy.style.display = 'none';
    stopActiveVoiceInput();
    document.getElementById('predCaseSummaryText').textContent = predictSession.summary;
    counter.textContent = `Question ${predictSession.answers.length + 1} of ${predictSession.questionTarget}`;
    role.textContent = questionData.role;
    question.textContent = questionData.text;
    answerInput.value = '';
    answerInput.focus();
    answerBtn.disabled = false;
    answerBtn.textContent = predictSession.answers.length + 1 === predictSession.questionTarget ? 'Finish Cross-Examination' : 'Submit Answer';
  }

  function finalizePredictSession(report) {
    const strengths = report.strengths || [];
    const weaknesses = report.weaknesses || [];
    const missingEvidence = report.missing_evidence || [];
    const legalRisks = report.legal_risks || [];
    const suggestions = report.suggestions || [];
    const winProbability = Math.max(0, Math.min(100, Number(report.win_probability) || 0));
    const confidenceScore = report.confidence_score || 'Low';
    const pressureLabel = winProbability < 45 ? t('predPressureHigh') : (winProbability < 70 ? t('predPressureMedium') : t('predPressureLow'));
    const readinessLabel = winProbability >= 75 ? t('predReadyStrong') : (winProbability >= 55 ? t('predReadyModerate') : t('predReadyFragile'));

    stopActiveVoiceInput();
    document.getElementById('predStructuredReport').innerHTML = `
      <h4>Final Case Prediction Report</h4>
      <ol class="how-list">
        <li><strong>Estimated Win Probability:</strong> ${winProbability}%</li>
        <li><strong>Confidence Score:</strong> ${escapeHtml(confidenceScore)}</li>
        <li><strong>Case Summary:</strong> ${escapeHtml(report.case_summary || predictSession.summary)}</li>
        <li><strong>Strengths of the Case:</strong> ${escapeHtml(strengths.join(' '))}</li>
        <li><strong>Weaknesses of the Case:</strong> ${escapeHtml(weaknesses.join(' '))}</li>
        <li><strong>Missing Evidence:</strong> ${escapeHtml(missingEvidence.join(' '))}</li>
        <li><strong>Legal Risks:</strong> ${escapeHtml(legalRisks.join(' '))}</li>
        <li><strong>Suggestions to Improve Case:</strong> ${escapeHtml(suggestions.join(' '))}</li>
      </ol>
    `;

    document.getElementById('meterSuccess').style.width = winProbability + '%';
    document.getElementById('meterSuccessVal').textContent = winProbability + '%';
    document.getElementById('predTimeVal').textContent = readinessLabel;
    document.getElementById('predCostVal').textContent = pressureLabel;
    document.getElementById('predSimilarVal').textContent = String(weaknesses.length);
    document.getElementById('predLawsList').innerHTML = (CASE_TRAINING_DATA[predictSession.caseType] || CASE_TRAINING_DATA.theft).laws
      .map(law => `<span class="law-tag">${law}</span>`).join('');
    document.getElementById('predJudgeList').innerHTML = renderPracticeList(
      predictSession.answers.filter(item => item.role === 'Judge').map(item => item.question)
    );
    document.getElementById('predOpponentList').innerHTML = renderPracticeList(
      predictSession.answers.filter(item => item.role === 'Opposing Lawyer').map(item => item.question)
    );
    document.getElementById('predWeaknessList').innerHTML = renderWeaknessList(
      weaknesses.concat(missingEvidence).concat(legalRisks).slice(0, 8)
    );
    document.getElementById('predActionsList').innerHTML = suggestions.map(step => `<li>${escapeHtml(step)}</li>`).join('');

    document.getElementById('predInteractiveFlow').style.display = 'none';
    document.getElementById('predLegacyReport').style.display = 'block';
    document.getElementById('predictResults').scrollIntoView({ behavior: 'smooth' });
    predictSession.active = false;
  }

  const predictBtn = document.getElementById('predictBtn');
  if (predictBtn) predictBtn.addEventListener('click', async () => {
    const caseType = document.getElementById('predictCaseType').value;
    if (!caseType) { alert(t('alertCaseType')); return; }
    const facts = document.getElementById('predictFacts').value.trim();
    if (!facts) { alert(t('alertCaseFacts')); return; }

    const results = document.getElementById('predictResults');
    const lang = getLang();
    const selectedEvidence = Array.from(document.querySelectorAll('#page-predict input[type="checkbox"]:checked'))
      .map(input => input.value)
      .filter(value => value !== 'none');
    const hasNoEvidence = document.querySelector('#page-predict input[value="none"]')?.checked;
    predictSession.active = true;
    predictSession.caseType = caseType;
    predictSession.facts = facts;
    predictSession.lang = lang;
    predictSession.selectedEvidence = hasNoEvidence ? [] : selectedEvidence;
    predictSession.answers = [];
    stopActiveVoiceInput();
    results.style.display = 'block';
    document.getElementById('predInteractiveFlow').style.display = 'block';
    document.getElementById('predLegacyReport').style.display = 'none';
    document.getElementById('predCaseSummaryText').textContent = 'Analyzing your case...';
    document.getElementById('predCurrentQuestion').textContent = '';
    document.getElementById('predAnswerBtn').disabled = true;
    try {
      const response = await requestCasePredictor();
      predictSession.summary = response.case_summary || '';
      if (response.next_step === 'final_report' && response.report) {
        finalizePredictSession(response.report);
      } else if (response.question) {
        showPredictQuestion(response.question);
      } else {
        throw new Error('Case predictor did not return a usable question.');
      }
      results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
      predictSession.active = false;
      alert('Case predictor failed: ' + err.message);
    }
  });

  const predAnswerBtn = document.getElementById('predAnswerBtn');
  if (predAnswerBtn) predAnswerBtn.addEventListener('click', async () => {
    if (!predictSession.active) return;
    const answerInput = document.getElementById('predAnswerInput');
    const answer = answerInput.value.trim();
    if (!answer) {
      alert('Please answer the current cross-question before proceeding.');
      return;
    }
    const currentRole = document.getElementById('predQuestionRole').textContent.trim();
    const currentQuestion = document.getElementById('predCurrentQuestion').textContent.trim();
    predAnswerBtn.disabled = true;
    predAnswerBtn.textContent = 'Analyzing...';
    predictSession.answers.push({
      role: currentRole,
      question: currentQuestion,
      answer: answer,
    });
    try {
      const response = await requestCasePredictor();
      predictSession.summary = response.case_summary || predictSession.summary;
      if (response.next_step === 'final_report' && response.report) {
        finalizePredictSession(response.report);
        return;
      }
      if (!response.question) {
        throw new Error('Case predictor did not return the next question.');
      }
      showPredictQuestion(response.question);
    } catch (err) {
      predAnswerBtn.disabled = false;
      predAnswerBtn.textContent = 'Submit Answer';
      predictSession.answers.pop();
      alert('Case predictor failed: ' + err.message);
    }
  });

  /* ── RISK SCORE ────────────────────────────────────────── */
  const RISK_DATA = {
    theft: { base: 35, laws: ['IPC 378/379', 'CrPC 154', 'IPC 166A'] },
    dv: { base: 55, laws: ['DV Act 2005', 'IPC 498A', 'CrPC 125'] },
    wage: { base: 30, laws: ['Payment of Wages Act', 'Min. Wages Act'] },
    harass: { base: 50, laws: ['POSH Act 2013', 'IPC 354A'] },
    land: { base: 60, laws: ['TPA 1882', 'Registration Act', 'Limitation Act'] },
    cyber: { base: 45, laws: ['IT Act 2000', 'IPC 420', 'IPC 468'] },
    consumer: { base: 25, laws: ['CPA 2019', 'Legal Metrology Act'] }
  };

  const riskCalcBtn = document.getElementById('riskCalcBtn');
  if (riskCalcBtn) riskCalcBtn.addEventListener('click', () => {
    const category = document.getElementById('riskCategory').value;
    if (!document.getElementById('riskSituation').value.trim()) { alert(t('alertSituation')); return; }

    const rd = RISK_DATA[category] || { base: 40, laws: ['IPC', 'CrPC'] };
    const factors = document.querySelectorAll('input[name="rf"]:checked');
    let score = rd.base + (factors.length * 10);
    score = Math.min(score, 95);

    const lang = getLang();
    const result = document.getElementById('riskResult');
    const circle = document.getElementById('gaugeCircle');

    document.getElementById('gaugeNum').textContent = score;
    circle.classList.remove('low', 'medium', 'high');

    if (score <= 35) {
      circle.classList.add('low');
      document.getElementById('gaugeLabel').textContent = t('riskLow');
    } else if (score <= 65) {
      circle.classList.add('medium');
      document.getElementById('gaugeLabel').textContent = t('riskMedium');
    } else {
      circle.classList.add('high');
      document.getElementById('gaugeLabel').textContent = t('riskHigh');
    }

    document.getElementById('urgencyFill').style.width = Math.min(score + 15, 100) + '%';
    document.getElementById('complexityFill').style.width = Math.min(score, 100) + '%';
    document.getElementById('evidenceFill').style.width = Math.max(100 - score, 10) + '%';

    document.getElementById('riskLawsList').innerHTML = rd.laws.map(l => `<span class="law-tag">${l}</span>`).join('');

    const actions = lang === 'hi'
      ? [
        { title: 'साक्ष्य सुरक्षित करें', desc: 'सभी दस्तावेज़, फ़ोटो, वीडियो, स्क्रीनशॉट और गवाहों के विवरण एकत्र करें।' },
        { title: 'शिकायत दर्ज करें', desc: 'निकटतम थाने में एफ़आईआर दर्ज करें या सम्बन्धित प्राधिकरण में शिकायत करें।' },
        { title: 'कानूनी सहायता लें', desc: 'निःशुल्क कानूनी सहायता हेतु नालसा हेल्पलाइन 15100 या जिला विधिक सेवा प्राधिकरण से सम्पर्क करें।' },
        { title: 'समय सीमा का ध्यान रखें', desc: 'प्रत्येक कानूनी कार्यवाही की एक परिसीमा अवधि होती है। जितना जल्दी हो सके कार्यवाही करें।' }
      ]
      : [
        { title: 'Secure Your Evidence', desc: 'Gather all documents, photos, videos, screenshots, and witness details.' },
        { title: 'File Your Complaint', desc: 'File FIR at nearest police station or lodge complaint with the relevant authority.' },
        { title: 'Get Legal Aid', desc: 'Contact NALSA Helpline 15100 or DLSA for free legal assistance if you cannot afford a lawyer.' },
        { title: 'Mind the Deadline', desc: 'Every legal action has a limitation period. Act as soon as possible to preserve your rights.' }
      ];

    document.getElementById('riskActionsList').innerHTML = actions.map((a, i) =>
      `<li class="action-step"><span class="action-step-num">${i + 1}</span><div class="action-step-text"><strong>${a.title}</strong>${a.desc}</div></li>`
    ).join('');

    const phases = lang === 'hi'
      ? [['शिकायत', '1-2 सप्ताह'], ['जाँच', '1-3 माह'], ['कानूनी कार्यवाही', '3-12 माह'], ['निर्णय', '1-6 माह']]
      : [['File Complaint', '1-2 weeks'], ['Investigation', '1-3 months'], ['Legal Proceedings', '3-12 months'], ['Resolution', '1-6 months']];

    document.getElementById('riskTimelineBar').innerHTML = phases.map((p, i) =>
      `<div class="timeline-phase ${i === 0 ? 'tl-active' : 'tl-pending'}"><div class="timeline-phase-label">${p[0]}</div><div class="timeline-phase-dur">${p[1]}</div></div>`
    ).join('');

    result.style.display = 'block';
    result.scrollIntoView({ behavior: 'smooth' });
  });

  /* ── MY DOCUMENTS (dynamic from backend) ───────────────── */
  function renderDocsList() {
    const docsList = document.querySelector('#page-docs .docs-list');
    if (!docsList) return;

    if (generatedDocs.length === 0) {
      docsList.innerHTML = `<div style="text-align:center;padding:2rem;color:#64748b;">
        ${getLang() === 'hi' ? 'अभी तक कोई दस्तावेज़ नहीं बना। एफ़आईआर विज़ार्ड या चैट से दस्तावेज़ बनाएँ।' :
          'No documents generated yet. Use the FIR Wizard or Chat to generate documents.'}
      </div>`;
      return;
    }

    docsList.innerHTML = generatedDocs.map(doc => `
      <div class="doc-card">
        <div class="doc-icon">&#128196;</div>
        <div class="doc-info">
          <div class="doc-name">${doc.name}</div>
          <div class="doc-meta">${doc.type} &bull; ${doc.date}</div>
        </div>
        <button class="btn btn-outline btn-sm" onclick="window.open('${doc.url}', '_blank')">${t('firDownload')}</button>
      </div>
    `).join('');
  }

  /* ── NEW DOCUMENT BUTTON ────────────────────────────────– */
  const newDocBtn = document.querySelector('[data-i18n="newDoc"]');
  if (newDocBtn) {
    newDocBtn.addEventListener('click', () => showPage('fir'));
  }

  /* ── FILTER BUTTONS ────────────────────────────────────── */
  document.querySelectorAll('.filter-row').forEach(row => {
    row.addEventListener('click', e => {
      if (e.target.classList.contains('filter-btn')) {
        row.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
      }
    });
  });

  /* ── CLEAR DATA ────────────────────────────────────────── */
  const clearDataBtn = document.getElementById('clearDataBtn');
  if (clearDataBtn) clearDataBtn.addEventListener('click', () => {
    const msg = getLang() === 'hi' ? 'क्या आप वाकई सारा डेटा मिटाना चाहते हैं?' : 'Are you sure you want to clear all data?';
    if (confirm(msg)) { try { localStorage.clear(); } catch (_) { } location.reload(); }
  });

  /* ── OFFLINE DETECTION ─────────────────────────────────── */
  function updateOnline() { offlineBanner.style.display = navigator.onLine ? 'none' : 'block'; }
  window.addEventListener('online', updateOnline);
  window.addEventListener('offline', updateOnline);
  updateOnline();

  /* ── LANDING, AUTH, DEMO TOUR ─────────────────────────── */
  const landingScreen = document.getElementById('landingScreen');
  const getStartedBtn = document.getElementById('getStartedBtn');
  const liveDemoBtn = document.getElementById('liveDemoBtn');
  const landingLangToggle = document.getElementById('landingLangToggle');
  const authModal = document.getElementById('authModal');
  const authCloseBtn = document.getElementById('authCloseBtn');
  const authLoginTab = document.getElementById('authLoginTab');
  const authSignupTab = document.getElementById('authSignupTab');
  const authLoginForm = document.getElementById('authLoginForm');
  const authSignupForm = document.getElementById('authSignupForm');
  const authLoginBtn = document.getElementById('authLoginBtn');
  const authSignupBtn = document.getElementById('authSignupBtn');
  const userNameDisplay = document.getElementById('userNameDisplay');
  const demoTour = document.getElementById('demoTour');
  const demoTourStepIndicator = document.getElementById('demoTourStepIndicator');
  const demoTourNext = document.getElementById('demoTourNext');
  const demoTourSkip = document.getElementById('demoTourSkip');
  const demoTourFinish = document.getElementById('demoTourFinish');
  const demoStepPanels = document.querySelectorAll('.demo-step-panel');

  function enterMainApp() {
    if (landingScreen) landingScreen.style.display = 'none';
    if (sidebar) sidebar.style.display = '';
    if (mainContent) mainContent.style.display = '';
    if (mobileHeader) mobileHeader.style.display = '';
  }

  function openAuthModal() {
    if (authModal) authModal.classList.add('auth-modal-open');
    if (landingScreen) landingScreen.classList.add('auth-active');
  }
  function closeAuthModal() {
    if (authModal) authModal.classList.remove('auth-modal-open');
    if (landingScreen) landingScreen.classList.remove('auth-active');
  }

  if (getStartedBtn) {
    getStartedBtn.addEventListener('click', () => {
      openAuthModal();
      const emailInput = document.getElementById('authLoginEmail');
      if (emailInput) emailInput.focus();
    });
  }

  let demoStep = 1;
  function showDemoStep(n) {
    demoStep = n;
    demoStepPanels.forEach(p => {
      p.style.display = p.getAttribute('data-demo-step') === String(n) ? 'block' : 'none';
    });
    if (demoTourStepIndicator) demoTourStepIndicator.textContent = n + ' / 5';
    const last = n >= 5;
    if (demoTourNext) demoTourNext.style.display = last ? 'none' : '';
    if (demoTourFinish) demoTourFinish.style.display = last ? '' : 'none';
  }

  function openDemoTour() {
    enterMainApp();
    demoStep = 1;
    showDemoStep(1);
    if (demoTour) demoTour.style.display = 'flex';
  }

  function closeDemoTour() {
    if (demoTour) demoTour.style.display = 'none';
  }

  if (liveDemoBtn) liveDemoBtn.addEventListener('click', () => openDemoTour());

  if (landingLangToggle) {
    landingLangToggle.querySelectorAll('button[data-landing-lang]').forEach(btn => {
      btn.addEventListener('click', () => switchLang(btn.getAttribute('data-landing-lang')));
    });
  }

  if (authCloseBtn) authCloseBtn.addEventListener('click', closeAuthModal);

  if (authLoginTab && authSignupTab && authLoginForm && authSignupForm) {
    authLoginTab.addEventListener('click', () => {
      authLoginTab.classList.add('active');
      authSignupTab.classList.remove('active');
      authLoginForm.style.display = '';
      authSignupForm.style.display = 'none';
    });
    authSignupTab.addEventListener('click', () => {
      authSignupTab.classList.add('active');
      authLoginTab.classList.remove('active');
      authSignupForm.style.display = '';
      authLoginForm.style.display = 'none';
    });
  }

  function setUserGreetingFromAuth(nameOrEmail) {
    const v = (nameOrEmail || '').trim();
    if (!userNameDisplay) return;
    if (v) {
      userNameDisplay.removeAttribute('data-i18n');
      userNameDisplay.textContent = v;
      userId = v.replace(/[^a-zA-Z0-9_]/g, '_').substring(0, 20);
      localStorage.setItem('nyayavoice_user_id', userId);
    } else {
      userNameDisplay.setAttribute('data-i18n', 'anonUser');
      userNameDisplay.textContent = t('anonUser');
    }
  }

  function finishAuth(nameOrEmail) {
    setUserGreetingFromAuth(nameOrEmail);
    closeAuthModal();
    enterMainApp();
  }

  if (authLoginForm) {
    authLoginForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const email = document.getElementById('authLoginEmail');
      const password = document.getElementById('authLoginPassword');

      if (!authLoginForm.reportValidity()) return;
      if (!password || !password.value.trim()) return;

      finishAuth(email && email.value ? email.value.split('@')[0] : '');
    });
  }

  if (authSignupForm) {
    authSignupForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const nameEl = document.getElementById('authSignupName');
      const passwordEl = document.getElementById('authSignupPassword');
      const confirmEl = document.getElementById('authSignupConfirm');

      if (confirmEl && passwordEl) {
        confirmEl.setCustomValidity(
          confirmEl.value && passwordEl.value && confirmEl.value !== passwordEl.value
            ? 'Passwords do not match.'
            : ''
        );
      }

      if (!authSignupForm.reportValidity()) return;

      finishAuth(nameEl && nameEl.value ? nameEl.value : '');
    });
  }

  if (authSignupBtn) {
    const syncSignupValidity = () => {
      const passwordEl = document.getElementById('authSignupPassword');
      const confirmEl = document.getElementById('authSignupConfirm');
      if (!passwordEl || !confirmEl) return;
      confirmEl.setCustomValidity(
        confirmEl.value && passwordEl.value && confirmEl.value !== passwordEl.value
          ? 'Passwords do not match.'
          : ''
      );
    };

    const passwordEl = document.getElementById('authSignupPassword');
    const confirmEl = document.getElementById('authSignupConfirm');
    if (passwordEl) passwordEl.addEventListener('input', syncSignupValidity);
    if (confirmEl) confirmEl.addEventListener('input', syncSignupValidity);
  }

  document.querySelectorAll('.auth-forgot').forEach(a => {
    a.addEventListener('click', e => e.preventDefault());
  });

  if (demoTourNext) {
    demoTourNext.addEventListener('click', () => {
      if (demoStep < 5) showDemoStep(demoStep + 1);
    });
  }
  if (demoTourSkip) demoTourSkip.addEventListener('click', closeDemoTour);
  if (demoTourFinish) demoTourFinish.addEventListener('click', closeDemoTour);

  /* ── INTERACTIVE UI ENHANCEMENTS ────────────────────────── */
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('animate-in');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1 });

  document.querySelectorAll('.card, .stat-card, .accord-item, .helpline-card, .doc-card, .quick-action-card').forEach(el => {
    el.classList.add('animate-target');
    observer.observe(el);
  });

  document.querySelectorAll('.btn-primary, .btn-outline, .send-btn, .landing-btn').forEach(btn => {
    btn.addEventListener('click', function (e) {
      const ripple = document.createElement('span');
      ripple.className = 'btn-ripple';
      const rect = this.getBoundingClientRect();
      ripple.style.left = (e.clientX - rect.left) + 'px';
      ripple.style.top = (e.clientY - rect.top) + 'px';
      this.appendChild(ripple);
      setTimeout(() => ripple.remove(), 600);
    });
  });

  /* ── User ID display in settings ───────────────────────── */
  const userIdDisplay = document.getElementById('userIdDisplay');
  if (userIdDisplay) userIdDisplay.textContent = userId;

  /* ── INIT ──────────────────────────────────────────────── */
  initTheme();
  initLang();
  initEmergencyAlertForm();
  updateStopAudioButtonLabel();
  const savedLang = getLang();
  [langSwitch, langMobile, settingsLang].forEach(sel => { if (sel) sel.value = savedLang; });
  updateStats();
  initVapi();

})();

