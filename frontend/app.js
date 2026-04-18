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

  function setupVapiEvents() {
    if (!vapiInstance) return;

    vapiInstance.on('speech-start', () => {
      lastSpeechStartAt = Date.now();
      newMicBtn.classList.add('listening');
      newMicStatus.textContent = t('vcListening');
    });
    vapiInstance.on('speech-end', () => {
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcProcessing');
    });
    vapiInstance.on('message', (msg) => {
      if (msg.type === 'status-update') {
        if (msg.status === 'active' || msg.status === 'started' || msg.status === 'in-progress') {
          vapiCallActive = true;
        }
      }
      if (msg.type === 'transcript' && msg.transcriptType === 'final') {
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
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
    });
    vapiInstance.on('error', (err) => {
      console.error('Vapi error:', err);
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      vapiCallActive = false;
      vapiSessionMode = null;
      vapiSessionLanguage = null;
      removeTypingIndicator();
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
  const sendBtn = document.getElementById('sendBtn');
  const chatMessages = document.getElementById('chatMessages');
  const offlineBanner = document.getElementById('offlineBanner');

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
    window.scrollTo({ top: 0, behavior: 'smooth' });
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

  async function speakAssistantReplyWithVapi(text) {
    if (!vapiInstance || !text || hasRecentlySpokenAssistantText(text)) return false;
    rememberSpokenAssistantText(text);
    const requestedAt = Date.now();
    if (pendingSpeechFallbackTimer) {
      clearTimeout(pendingSpeechFallbackTimer);
      pendingSpeechFallbackTimer = null;
    }
    try {
      await ensureVapiSession('chat');
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

    pendingSpeechFallbackTimer = setTimeout(() => {
      if (lastSpeechStartAt < requestedAt) {
        console.warn('Vapi speech did not start in time, falling back to browser speech');
        speakAssistantReplyInBrowser(text);
      }
    }, 4000);
    return true;
  }

  function speakAssistantReplyInBrowser(text) {
    if (!('speechSynthesis' in window) || !text) return;
    console.info('Voice output source: browser_speech_fallback');

    try {
      const cleanedText = String(text)
        .replace(/<[^>]+>/g, ' ')
        .replace(/[#*_`>-]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
      if (!cleanedText) return;
      const utterance = new SpeechSynthesisUtterance(cleanedText);
      utterance.lang = getSpeechLang();
      utterance.rate = 1;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
    } catch (err) {
      console.error('Browser speech fallback failed:', err);
    }
  }

  async function ensureVapiSession(mode = 'chat') {
    if (!vapiInstance) return false;
    const currentLang = getLang();
    const needsRestart = vapiCallActive && (vapiSessionMode !== mode || vapiSessionLanguage !== currentLang);

    if (needsRestart) {
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
      await ensureVapiSession('chat');
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
        await ensureVapiSession('chat');
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
      vapiInstance.stop();
      newMicBtn.classList.remove('listening');
      newMicStatus.textContent = t('vcReady');
      vapiCallActive = false;
      vapiSessionMode = null;
      return;
    }
    if (vapiCallActive && vapiSessionMode === 'chat') {
      newMicBtn.classList.add('listening');
      newMicStatus.textContent = t('vcListening');
      vapiSessionMode = 'voice';
      return;
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
  function startVoiceInput(targetId, btn) {
    if (!SpeechRecognition) {
      alert(getLang() === 'hi' ? 'आपका ब्राउज़र वॉइस इनपुट का समर्थन नहीं करता। कृपया Chrome उपयोग करें।' : 'Your browser does not support voice input. Please use Chrome.');
      return;
    }

    if (activeRecognition) {
      activeRecognition.stop();
      activeRecognition = null;
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = getSpeechLang();
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    activeRecognition = recognition;

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
    };

    recognition.onend = () => {
      btn.classList.remove('voice-active');
      activeRecognition = null;
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

  const predictBtn = document.getElementById('predictBtn');
  if (predictBtn) predictBtn.addEventListener('click', () => {
    const caseType = document.getElementById('predictCaseType').value;
    if (!caseType) { alert(t('alertCaseType')); return; }

    const data = CASE_DATA[caseType] || CASE_DATA.theft;
    const results = document.getElementById('predictResults');
    const lang = getLang();

    document.getElementById('meterSuccess').style.width = data.success + '%';
    document.getElementById('meterSuccessVal').textContent = data.success + '%';
    document.getElementById('predTimeVal').textContent = data.time + (lang === 'hi' ? ' माह' : ' months');
    document.getElementById('predCostVal').textContent = data.cost;
    document.getElementById('predSimilarVal').textContent = data.similar;

    document.getElementById('scWon').style.width = data.won + '%';
    document.getElementById('scWon').innerHTML = `<span>${t('predWon')}</span> ${data.won}%`;
    document.getElementById('scSettled').style.width = data.settled + '%';
    document.getElementById('scSettled').innerHTML = `<span>${t('predSettled')}</span> ${data.settled}%`;
    document.getElementById('scLost').style.width = data.lost + '%';
    document.getElementById('scLost').innerHTML = `<span>${t('predLost')}</span> ${data.lost}%`;

    const lawsDiv = document.getElementById('predLawsList');
    lawsDiv.innerHTML = data.laws.map(l => `<span class="law-tag">${l}</span>`).join('');

    const steps = lang === 'hi'
      ? ['सभी साक्ष्य और दस्तावेज़ एकत्र करें', 'निकटतम थाने में एफ़आईआर दर्ज करें या सम्बन्धित प्राधिकरण में शिकायत दर्ज करें', 'निःशुल्क कानूनी सहायता हेतु नालसा हेल्पलाइन 15100 पर सम्पर्क करें', 'किसी योग्य वकील से परामर्श करें']
      : ['Gather all evidence and documents', 'File FIR at nearest police station or lodge complaint with relevant authority', 'Contact NALSA Helpline 15100 for free legal aid', 'Consult a qualified lawyer for formal advice'];

    document.getElementById('predActionsList').innerHTML = steps.map(s => `<li>${s}</li>`).join('');

    results.style.display = 'block';
    results.scrollIntoView({ behavior: 'smooth' });
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
    const emergencyStrip = document.querySelector('.emergency-strip');
    if (emergencyStrip) emergencyStrip.style.display = '';
  }

  function openAuthModal() {
    if (authModal) authModal.classList.add('auth-modal-open');
  }
  function closeAuthModal() {
    if (authModal) authModal.classList.remove('auth-modal-open');
  }

  if (getStartedBtn) {
    getStartedBtn.addEventListener('click', () => {
      enterMainApp();
      openAuthModal();
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

  if (authLoginBtn) {
    authLoginBtn.addEventListener('click', () => {
      const email = document.getElementById('authLoginEmail');
      setUserGreetingFromAuth(email && email.value ? email.value.split('@')[0] : '');
      closeAuthModal();
    });
  }
  if (authSignupBtn) {
    authSignupBtn.addEventListener('click', () => {
      const nameEl = document.getElementById('authSignupName');
      setUserGreetingFromAuth(nameEl && nameEl.value ? nameEl.value : '');
      closeAuthModal();
    });
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
  const savedLang = getLang();
  [langSwitch, langMobile, settingsLang].forEach(sel => { if (sel) sel.value = savedLang; });
  updateStats();
  initVapi();

})();

