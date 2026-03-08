/* webcam.js v4.0 – Advanced emotion-aware chat with trajectory tracking */
(() => {
  'use strict';

  // ── Config ──────────────────────────────────────────────────────────
  const VISION_BASE = window.VISION_API_BASE || window.location.origin || 'http://localhost:8081';
  const CHAT_URL = `${VISION_BASE}/chat`;
  const INGEST_URL = `${VISION_BASE}/ingest-frame`;
  const SIGNALS_URL = `${VISION_BASE}/latest-signals`;
  const HEALTH_URL = `${VISION_BASE}/health`;
  const HISTORY_URL = `${VISION_BASE}/emotion-history`;

  const FRAME_INTERVAL = 200;   // 5 fps baseline
  const POLL_INTERVAL = 800;
  const HEARTBEAT_INTERVAL = 3000;
  const HISTORY_INTERVAL = 2000;
  const TARGET_W = 320;
  const TARGET_H = 240;
  const JPEG_Q = 0.65;

  // Emotion colors
  const EMOTION_COLORS = {
    happy: '#21c185', sad: '#6b8dd6', angry: '#e94b35',
    fear: '#c084fc', surprise: '#ffb347', disgust: '#a78bfa',
    contempt: '#f472b6', neutral: '#9fb1d9',
    anxious: '#c084fc', frustrated: '#e94b35',
    happily_surprised: '#21c185', bittersweet: '#6b8dd6',
    nervous_disgust: '#a78bfa',
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
    // New v4 elements
    emoCompound: $('emo-compound'), compoundLabel: $('compound-label'),
    emoSpike: $('emo-spike'), spikeLabel: $('spike-label'),
    valenceBar: $('valence-bar'), arousalBar: $('arousal-bar'),
    valenceVal: $('valence-val'), arousalVal: $('arousal-val'),
    momentumBadge: $('momentum-badge'), momentumLabel: $('momentum-label'),
    trajectoryCanvas: $('trajectory-canvas'),
  };

  if (!els.video || !els.msgs || !els.input || !els.composer) {
    console.error('Missing critical DOM elements'); return;
  }

  // ── State ───────────────────────────────────────────────────────────
  const senderId = getSenderId();
  let mediaStream = null, capturing = false, isVisible = true;
  let pushTimer = null, pollTimer = null, heartbeatTimer = null, historyTimer = null;
  let framesThisSec = 0, lastFpsAt = performance.now();
  let lastSpike = null, spikeTimeout = null;
  let trajectoryData = [];

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

        const responses = data.responses || [];
        const emotion = data.emotion || {};
        if (responses.length === 0) {
          appendBot("I received your message but didn't get a response.");
        } else {
          responses.forEach(r => {
            if (r && r.text) appendBot(r.text, emotion);
          });
        }

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
      startHistoryPolling();
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
    stopFramePush(); stopSignalPolling(); stopHistoryPolling();
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
          compound_emotion: js.compound_emotion || null,
          compound_confidence: js.compound_confidence || 0,
          micro_expression_spike: js.micro_expression_spike || null,
          spike_intensity: js.spike_intensity || 0,
          valence: js.valence || 0,
          arousal: js.arousal || 0,
        });
        // Update gaze
        if (els.gazeVal) els.gazeVal.textContent = js.gaze_state || '--';
        if (els.emoGaze) els.emoGaze.classList.add('active');
      } catch {}
    }, POLL_INTERVAL);
  }

  function stopSignalPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

  // ── Emotion history polling ─────────────────────────────────────────
  function startHistoryPolling() {
    if (historyTimer) return;
    historyTimer = setInterval(async () => {
      if (!capturing) return;
      try {
        const res = await fetch(HISTORY_URL, { headers: { 'X-Sender': senderId } });
        if (!res.ok) return;
        const data = await res.json();
        trajectoryData = data.trajectory || [];
        updateMomentumBadge(data.momentum || {});
        drawTrajectory();
      } catch {}
    }, HISTORY_INTERVAL);
  }

  function stopHistoryPolling() { if (historyTimer) { clearInterval(historyTimer); historyTimer = null; } }

  // ── Emotion overlay ─────────────────────────────────────────────────
  function updateEmotionOverlay(emotion) {
    const expr = emotion.expression || 'neutral';
    const conf = emotion.confidence || 0.5;
    const intensity = emotion.intensity || 0;
    const engagement = emotion.engagement || 0.5;
    const compound = emotion.compound_emotion;
    const compoundConf = emotion.compound_confidence || 0;
    const spike = emotion.micro_expression_spike;
    const spikeInt = emotion.spike_intensity || 0;
    const valence = emotion.valence || 0;
    const arousal = emotion.arousal || 0;
    const color = EMOTION_COLORS[expr] || EMOTION_COLORS.neutral;

    // Expression badge
    if (els.emoExpr) els.emoExpr.classList.add('active');
    if (els.emoDot) els.emoDot.style.background = color;
    if (els.emoLabel) els.emoLabel.textContent = `${expr} ${Math.round(conf * 100)}%`;

    // Gaze badge
    if (els.emoGaze) els.emoGaze.classList.add('active');

    // Engagement
    const engColor = engagement > 0.6 ? '#21c185' : engagement > 0.35 ? '#ffb347' : '#e94b35';
    if (els.engageDot) els.engageDot.style.background = engColor;
    if (els.engagePct) els.engagePct.textContent = `${Math.round(engagement * 100)}%`;

    // Compound emotion badge
    if (els.emoCompound && compound) {
      els.emoCompound.classList.add('active');
      const compColor = EMOTION_COLORS[compound] || EMOTION_COLORS.neutral;
      if (els.compoundLabel) {
        els.compoundLabel.textContent = `${compound} ${Math.round(compoundConf * 100)}%`;
        els.compoundLabel.style.color = compColor;
      }
    } else if (els.emoCompound) {
      els.emoCompound.classList.remove('active');
    }

    // Micro-expression spike (flash briefly)
    if (spike && spikeInt > 0.1 && spike !== lastSpike) {
      lastSpike = spike;
      if (els.emoSpike) {
        els.emoSpike.classList.add('active', 'spike-flash');
        const spikeColor = EMOTION_COLORS[spike] || '#fff';
        if (els.spikeLabel) {
          els.spikeLabel.textContent = `SPIKE: ${spike}`;
          els.spikeLabel.style.color = spikeColor;
        }
        if (spikeTimeout) clearTimeout(spikeTimeout);
        spikeTimeout = setTimeout(() => {
          if (els.emoSpike) els.emoSpike.classList.remove('active', 'spike-flash');
          lastSpike = null;
        }, 2000);
      }
    }

    // Valence bar (-1 to +1)
    if (els.valenceBar) {
      const pct = ((valence + 1) / 2) * 100; // map -1..1 to 0..100
      els.valenceBar.style.width = `${pct}%`;
      els.valenceBar.style.background = valence > 0 ? '#21c185' : valence < -0.2 ? '#e94b35' : '#ffb347';
    }
    if (els.valenceVal) els.valenceVal.textContent = valence > 0 ? `+${valence.toFixed(2)}` : valence.toFixed(2);

    // Arousal bar (0 to 1)
    if (els.arousalBar) {
      els.arousalBar.style.width = `${Math.round(arousal * 100)}%`;
      els.arousalBar.style.background = arousal > 0.6 ? '#e94b35' : arousal > 0.3 ? '#ffb347' : '#6b8dd6';
    }
    if (els.arousalVal) els.arousalVal.textContent = arousal.toFixed(2);
  }

  function updateMomentumBadge(momentum) {
    if (!els.momentumBadge) return;
    const dir = momentum.direction || 'stable';
    const anxiety = momentum.anxiety_trend || 'stable';

    els.momentumBadge.classList.add('active');

    let label = dir;
    let color = '#9fb1d9';
    if (dir === 'improving') { color = '#21c185'; }
    else if (dir === 'declining') { color = '#e94b35'; }
    if (anxiety === 'increasing') { label += ' (anxiety up)'; color = '#c084fc'; }
    else if (anxiety === 'decreasing') { label += ' (calming)'; color = '#21c185'; }

    if (els.momentumLabel) {
      els.momentumLabel.textContent = label;
      els.momentumLabel.style.color = color;
    }
  }

  // ── Trajectory chart (mini sparkline) ───────────────────────────────
  function drawTrajectory() {
    const canvas = els.trajectoryCanvas;
    if (!canvas || trajectoryData.length < 2) return;

    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.offsetWidth * (window.devicePixelRatio || 1);
    const h = canvas.height = canvas.offsetHeight * (window.devicePixelRatio || 1);
    ctx.clearRect(0, 0, w, h);

    const data = trajectoryData;
    const n = data.length;
    const stepX = w / (n - 1);

    // Draw valence line
    ctx.beginPath();
    ctx.strokeStyle = '#21c185';
    ctx.lineWidth = 2;
    for (let i = 0; i < n; i++) {
      const x = i * stepX;
      const y = h / 2 - (data[i].valence || 0) * (h / 2) * 0.8;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Draw arousal line
    ctx.beginPath();
    ctx.strokeStyle = '#ffb347';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    for (let i = 0; i < n; i++) {
      const x = i * stepX;
      const y = h - (data[i].arousal || 0) * h * 0.8;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw engagement line
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(107,176,221,0.5)';
    ctx.lineWidth = 1;
    for (let i = 0; i < n; i++) {
      const x = i * stepX;
      const y = h - (data[i].engagement || 0.5) * h * 0.8;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Center line
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.lineWidth = 1;
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
    ctx.stroke();
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
          els.visionBadge.textContent = res.ok ? `v3 ${ms}ms` : 'offline';
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
    if (who !== 'you' && emotion) {
      const expr = emotion.expression;
      const compound = emotion.compound_emotion;
      const displayEmotion = compound || expr;

      if (displayEmotion && displayEmotion !== 'neutral') {
        const tag = document.createElement('div');
        tag.className = 'emo-tag';
        const dot = document.createElement('span');
        dot.className = 'dot';
        dot.style.background = EMOTION_COLORS[displayEmotion] || EMOTION_COLORS.neutral;
        tag.appendChild(dot);
        const conf = emotion.compound_confidence || emotion.confidence || 0.5;
        tag.appendChild(document.createTextNode(
          ` ${displayEmotion} ${Math.round(conf * 100)}%`
        ));

        // Momentum indicator
        const momentum = emotion.momentum;
        if (momentum && momentum.direction && momentum.direction !== 'stable') {
          const arrow = momentum.direction === 'improving' ? ' \u2191' : ' \u2193';
          tag.appendChild(document.createTextNode(arrow));
        }

        div.appendChild(tag);
      }
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
