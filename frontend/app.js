(function () {
  const screens = Array.from(document.querySelectorAll(".screen"));
  const navButtons = Array.from(document.querySelectorAll("[data-nav]"));
  const navTargetButtons = Array.from(document.querySelectorAll("[data-nav-target]"));
  const heroMicBtn = document.getElementById("heroMicBtn");
  const heroMicStatus = document.getElementById("heroMicStatus");
  const chatMicBtn = document.getElementById("chatMicBtn");
  const voiceWaveform = document.getElementById("voiceWaveform");
  const sendBtn = document.getElementById("sendBtn");
  const chatInput = document.getElementById("chatInput");
  const chatMessages = document.getElementById("chatMessages");
  const typingTemplate = document.getElementById("typingTemplate");
  const themeToggle = document.getElementById("themeToggle");

  let micActive = false;

  function showScreen(name) {
    screens.forEach((screen) => {
      screen.classList.toggle("active", screen.dataset.screen === name);
    });

    navButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.nav === name);
    });
  }

  function setMicState(active) {
    micActive = active;
    heroMicBtn.classList.toggle("listening", active);
    chatMicBtn.classList.toggle("listening", active);
    heroMicStatus.textContent = active ? "Listening..." : "Ready to listen";
    voiceWaveform.hidden = !active;
  }

  function addUserMessage(text) {
    const row = document.createElement("div");
    row.className = "message-row user";
    row.innerHTML = [
      '<div class="message-stack">',
      '<div class="message-bubble user-bubble"><p></p></div>',
      "</div>"
    ].join("");
    row.querySelector("p").textContent = text;
    chatMessages.appendChild(row);
    row.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  function addAiMessage() {
    const row = document.createElement("div");
    row.className = "message-row ai";
    row.innerHTML = [
      '<div class="message-avatar">N</div>',
      '<div class="message-stack">',
      '<div class="message-bubble ai-bubble">',
      "<p>Here is a structured legal next-step view based on what you shared.</p>",
      "</div>",
      '<div class="response-cards">',
      '<article class="step-card"><span>1</span><div><strong>Secure evidence</strong><p>Keep CCTV, timestamps, witness details, and any bills or screenshots together.</p></div></article>',
      '<article class="step-card"><span>2</span><div><strong>Prepare filing path</strong><p>Use this summary to draft an FIR or complaint with the right authority and timeline.</p></div></article>',
      '<article class="step-card"><span>3</span><div><strong>Take action</strong><p>Choose whether to file now, download the summary, or read your relevant rights first.</p></div></article>',
      "</div>",
      '<div class="response-actions">',
      '<button class="secondary-button">File FIR</button>',
      '<button class="secondary-button">Download</button>',
      '<button class="secondary-button">Learn More</button>',
      "</div>",
      "</div>"
    ].join("");
    chatMessages.appendChild(row);
    row.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  function simulateAiReply(text) {
    addUserMessage(text);

    const clone = typingTemplate.content.cloneNode(true);
    const typingNode = clone.querySelector(".typing-row");
    chatMessages.appendChild(clone);
    typingNode.scrollIntoView({ behavior: "smooth", block: "end" });

    window.setTimeout(() => {
      typingNode.remove();
      addAiMessage();
    }, 1200);
  }

  navButtons.forEach((button) => {
    button.addEventListener("click", () => showScreen(button.dataset.nav));
  });

  navTargetButtons.forEach((button) => {
    button.addEventListener("click", () => showScreen(button.dataset.navTarget));
  });

  heroMicBtn.addEventListener("click", () => {
    setMicState(!micActive);
    if (micActive) {
      showScreen("talk");
    }
  });

  chatMicBtn.addEventListener("click", () => {
    setMicState(!micActive);
  });

  sendBtn.addEventListener("click", () => {
    const text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = "";
    showScreen("talk");
    simulateAiReply(text);
  });

  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      sendBtn.click();
    }
  });

  themeToggle.addEventListener("click", () => {
    document.body.classList.toggle("light");
  });

  showScreen("home");
  setMicState(false);
})();
