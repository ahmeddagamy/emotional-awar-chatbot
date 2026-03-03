/* webcam.js v3.0 – Emotion-aware chat via /chat proxy */
(() => {
  'use strict';

  // ── Config ──────────────────────────────────────────────────────────
  const VISION_BASE = window.VISION_API_BASE || window.location.origin || 'http://localhost:8081';
  const CHAT_URL = `${VISION_BASE}/chat`;
  const INGEST_URL = `${VISION_BASE}/ingest-frame`;
  const SIGNALS_URL = `${VISION_BASE}/latest-signals`;
  const HEALTH_URL = `${VISION_BASE}/health`;

  const FRAME_INTERVAL = 200;   // 5 fps
  const POLL_INTERVAL = 1000;
  const HEARTBEAT_INTERVAL = 3000;
  const TARGET_W = 224;
  const TARGET_H = 224;
  const JPEG_Q = 0.6;

  // Emotion colors
  const EMOTION_COLORS = {
    happy: '#21c185', sad: '#6b8dd6', angry: '#e94b35',
    fear: '#c084fc', surprise: '#ffb347', disgust: '#a78bfa',
    neutral: '#9fb1d9',
  };

  // ── DOM refs ────────────────────────────────────────────────────────
  const $ = id => document.getElementById(id);
  const els = {
    video: $('video'), camStatus: $('cam-status'),
    msgs: $('msgs'), input: $('input'), composer: $('composer'),
    consent: $('consent-modal'), allow: $('consent-allow'), deny: $('consent-deny'),
    chk: $('chk-send-frames'), visionBadge: $('vision-badge'),
    btnStart: $('btn-start'), btnStop: $('btn-stop'),
    emoExpr: $('emo-expr'), emoDot: $('emo-dot'), emoLabel: $('emo-label'),
    emoGaze: $('emo-gaze'), gazeVal: $('gaze-val'),
    emoFps: $('emo-fps'), fpsVal: $('fps-val'),
    engageDot: $('engage-dot'), engagePct: $('engage-pct'),
    quickReplies: $('quick-replies'),
  };

  // Validate critical elements
  if (!els.video || !els.msgs || !els.input || !els.composer) {
    console.error('Missing critical DOM elements'); return;
  }

  // ── State ───────────────────────────────────────────────────────────
  const senderId = getSenderId();
  let mediaStream = null, capturing = false, isVisible = true;
  let pushTimer = null, pollTimer = null, heartbeatTimer = null;
  let framesThisSec = 0, lastFpsAt = performance.now();

  // ── Init ────────────────────────────────────────────────────────────
  document.addEventListener('visibilitychange', () => {
    isVisible = !document.hidden;
    if (!isVisible && capturing) stopFramePush();
    else if (isVisible && capturing && localStorage.getItem('dental_consent') === 'send') startFramePush();
  });
  window.addEventListener('beforeunload', cleanup);

  boot();

  function boot() {
    if (!localStorage.getItem('dental_consent')) showConsent();
    bindChat();
    bindCamera();
    bindQuickReplies();
    appendBot('Hi! I adapt to your comfort in real time. Start the camera and ask me anything!');
    heartbeat();
  }

  // ── Chat (routed through /chat proxy) ───────────────────────────────
  function bindChat() {
    els.composer.addEventListener('submit', async e => {
      e.preventDefault();
      const text = els.input.value.trim();
      if (!text || text.length > 1000) return;
      appendYou(text);
      els.input.value = '';
      setInputEnabled(false);

      try {
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), 30000);
        const res = await fetch(CHAT_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sender: senderId, message: text }),
          signal: ctrl.signal,
        });
        clearTimeout(tid);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Enriched response: { responses: [...], emotion: {...}, intent }
        const responses = data.responses || [];
        const emotion = data.emotion || {};
        if (responses.length === 0) {
          appendBot("I received your message but didn't get a response.");
        } else {
          responses.forEach(r => {
            if (r && r.text) appendBot(r.text, emotion);
          });
        }

        // Update emotion overlay from chat response
        if (emotion.expression) updateEmotionOverlay(emotion);
      } catch (err) {
        if (err.name === 'AbortError') appendBot('Request timed out. Please try again.');
        else appendBot("Sorry, I couldn't reach the assistant. Please try again.");
        console.error('Chat error:', err);
      } finally {
        setInputEnabled(true);
      }
    });
  }

  function bindQuickReplies() {
    if (!els.quickReplies) return;
    els.quickReplies.addEventListener('click', e => {
      const chip = e.target.closest('.qr-chip');
      if (!chip) return;
      const msg = chip.dataset.msg;
      if (msg) {
        els.input.value = msg;
        els.composer.dispatchEvent(new Event('submit'));
      }
    });
  }

  function setInputEnabled(on) {
    els.input.disabled = !on;
    const btn = els.composer.querySelector('button[type="submit"]');
    if (btn) btn.disabled = !on;
    if (on) els.input.focus();
  }

  // ── Camera ──────────────────────────────────────────────────────────
  function bindCamera() {
    if (els.btnStart) els.btnStart.addEventListener('click', () => startCamera());
    if (els.btnStop) els.btnStop.addEventListener('click', stopCamera);
    if (els.allow) els.allow.addEventListener('click', async () => {
      localStorage.setItem('dental_consent', els.chk?.checked ? 'send' : 'local');
      hideConsent(); await startCamera();
    });
    if (els.deny) els.deny.addEventListener('click', () => {
      localStorage.setItem('dental_consent', 'deny');
      hideConsent();
      appendBot('Camera disabled. I\'ll proceed without vision signals.');
    });
  }

  async function startCamera() {
    if (capturing) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setText(els.camStatus, 'not supported'); return;
    }
    try {
      setText(els.camStatus, 'requesting...');
      mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false
      });
      els.video.srcObject = mediaStream;
      await new Promise((ok, fail) => {
        const done = () => { els.video.removeEventListener('loadedmetadata', done); ok(); };
        els.video.addEventListener('loadedmetadata', done);
        setTimeout(() => fail(new Error('timeout')), 5000);
      });
      capturing = true;
      setText(els.camStatus, 'live');
      if (els.btnStart) els.btnStart.disabled = true;
      if (els.btnStop) els.btnStop.disabled = false;
      startSignalPolling();
      if (localStorage.getItem('dental_consent') === 'send' && isVisible) startFramePush();
    } catch (err) {
      capturing = false;
      setText(els.camStatus, 'error');
      appendBot("Couldn't access camera. You can still chat without it.");
      console.error('Camera error:', err);
      if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
      els.video.srcObject = null;
    }
  }

  function stopCamera() {
    capturing = false;
    stopFramePush(); stopSignalPolling();
    if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
    els.video.srcObject = null;
    setText(els.camStatus, 'stopped');
    if (els.btnStart) els.btnStart.disabled = false;
    if (els.btnStop) els.btnStop.disabled = true;
  }

  // ── Frame push ──────────────────────────────────────────────────────
  function startFramePush() {
    if (pushTimer) return;
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    canvas.width = TARGET_W; canvas.height = TARGET_H;
    let errs = 0;

    pushTimer = setInterval(async () => {
      if (!capturing || !mediaStream || !isVisible) { stopFramePush(); return; }
      if (!els.video || els.video.readyState < 2) return;
      try {
        ctx.drawImage(els.video, 0, 0, TARGET_W, TARGET_H);
        const blob = await new Promise((ok, fail) => {
          canvas.toBlob(b => b ? ok(b) : fail('blob'), 'image/jpeg', JPEG_Q);
        });
        const fd = new FormData();
        fd.append('file', blob, 'frame.jpg');
        const res = await fetch(INGEST_URL, {
          method: 'POST', body: fd,
          headers: { 'X-Sender': senderId },
        });
        if (res.ok) { errs = 0; framesThisSec++; updateFps(); }
        else { errs++; if (errs > 5) stopFramePush(); }
      } catch { errs++; if (errs > 5) stopFramePush(); }
    }, FRAME_INTERVAL);
  }

  function stopFramePush() { if (pushTimer) { clearInterval(pushTimer); pushTimer = null; } }

  // ── Signal polling ──────────────────────────────────────────────────
  function startSignalPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      if (!capturing) return;
      try {
        const res = await fetch(SIGNALS_URL, { headers: { 'X-Sender': senderId } });
        if (!res.ok) return;
        const js = await res.json();
        updateEmotionOverlay({
          expression: js.micro_expression || 'neutral',
          confidence: js.expression_confidence || 0.5,
          intensity: js.expression_intensity || 0,
          engagement: js.engagement_level || 0.5,
        });
      } catch {}
    }, POLL_INTERVAL);
  }

  function stopSignalPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

  // ── Emotion overlay ─────────────────────────────────────────────────
  function updateEmotionOverlay(emotion) {
    const expr = emotion.expression || 'neutral';
    const conf = emotion.confidence || 0.5;
    const intensity = emotion.intensity || 0;
    const engagement = emotion.engagement || 0.5;
    const color = EMOTION_COLORS[expr] || EMOTION_COLORS.neutral;

    // Expression badge
    if (els.emoExpr) { els.emoExpr.classList.add('active'); }
    if (els.emoDot) { els.emoDot.style.background = color; }
    if (els.emoLabel) { els.emoLabel.textContent = `${expr} ${Math.round(conf * 100)}%`; }

    // Gaze badge
    if (els.emoGaze) els.emoGaze.classList.add('active');

    // Engagement
    const engColor = engagement > 0.6 ? '#21c185' : engagement > 0.35 ? '#ffb347' : '#e94b35';
    if (els.engageDot) els.engageDot.style.background = engColor;
    if (els.engagePct) els.engagePct.textContent = `${Math.round(engagement * 100)}%`;
  }

  // ── Heartbeat ───────────────────────────────────────────────────────
  function heartbeat() {
    const ping = async () => {
      if (!isVisible) { heartbeatTimer = setTimeout(ping, HEARTBEAT_INTERVAL); return; }
      const t0 = performance.now();
      try {
        const res = await fetch(HEALTH_URL);
        const ms = Math.round(performance.now() - t0);
        if (els.visionBadge) {
          els.visionBadge.textContent = res.ok ? `online ${ms}ms` : 'offline';
          els.visionBadge.style.color = res.ok ? 'var(--success)' : 'var(--danger)';
          els.visionBadge.classList.toggle('pulse', !res.ok);
        }
      } catch {
        if (els.visionBadge) {
          els.visionBadge.textContent = 'offline';
          els.visionBadge.style.color = 'var(--danger)';
          els.visionBadge.classList.add('pulse');
        }
      }
      heartbeatTimer = setTimeout(ping, HEARTBEAT_INTERVAL);
    };
    ping();
  }

  // ── Chat UI ─────────────────────────────────────────────────────────
  function appendYou(text) { append(text, 'you'); }
  function appendBot(text, emotion) { append(text, 'bot', emotion); }

  function append(text, who, emotion) {
    if (!els.msgs || !text) return;
    const div = document.createElement('div');
    div.className = `msg ${who === 'you' ? 'you' : ''}`;

    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = who === 'you' ? 'You' : 'Assistant';
    div.appendChild(meta);

    const body = document.createElement('div');
    body.className = 'text';
    body.textContent = String(text).substring(0, 5000);
    div.appendChild(body);

    // Emotion tag on bot messages
    if (who !== 'you' && emotion && emotion.expression && emotion.expression !== 'neutral') {
      const tag = document.createElement('div');
      tag.className = 'emo-tag';
      const dot = document.createElement('span');
      dot.className = 'dot';
      dot.style.background = EMOTION_COLORS[emotion.expression] || EMOTION_COLORS.neutral;
      tag.appendChild(dot);
      tag.appendChild(document.createTextNode(
        ` ${emotion.expression} ${Math.round((emotion.confidence || 0.5) * 100)}%`
      ));
      div.appendChild(tag);
    }

    els.msgs.appendChild(div);
    els.msgs.scrollTop = els.msgs.scrollHeight;
  }

  // ── Utilities ───────────────────────────────────────────────────────
  function getSenderId() {
    const key = 'dental_sender';
    try {
      let id = localStorage.getItem(key);
      if (!id) { id = 'web_' + Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem(key, id); }
      return id;
    } catch { return 'session_' + Math.random().toString(36).slice(2); }
  }

  function setText(el, t) { if (el) el.textContent = t; }
  function showConsent() { if (els.consent) els.consent.classList.remove('hidden'); }
  function hideConsent() { if (els.consent) els.consent.classList.add('hidden'); }

  function updateFps() {
    const now = performance.now();
    if (now - lastFpsAt >= 1000) {
      if (els.fpsVal) els.fpsVal.textContent = framesThisSec;
      if (els.emoFps) els.emoFps.classList.add('active');
      framesThisSec = 0; lastFpsAt = now;
    }
  }

  function cleanup() {
    stopCamera();
    if (heartbeatTimer) { clearTimeout(heartbeatTimer); heartbeatTimer = null; }
  }
})();
