/* file: web_integration/static/webcam.js */
(() => {
    'use strict';
    
    // ======= CONFIG (auto-detect from current host or use defaults) ============
    // For production, these can be set via window globals or detected from current URL
    const getBaseUrl = () => {
        if (window.VISION_API_BASE) return window.VISION_API_BASE;
        if (window.location.protocol === 'https:') {
            return `${window.location.protocol}//${window.location.host}`;
        }
        return window.location.origin || "http://localhost:8081";
    };
    
    const getRasaUrl = () => {
        if (window.RASA_REST_URL) return window.RASA_REST_URL;
        const base = getBaseUrl();
        // Try to infer Rasa URL from vision API URL
        if (base.includes(':8081')) {
            return base.replace(':8081', ':5005') + '/webhooks/rest/webhook';
        }
        return "http://localhost:5005/webhooks/rest/webhook";
    };
    
    const RASA_REST_URL = getRasaUrl();
    const VISION_API_BASE = getBaseUrl();
    const VISION_PUSH_ENDPOINT = `${VISION_API_BASE}/ingest-frame`;      // POST image
    const VISION_LATEST_ENDPOINT = `${VISION_API_BASE}/latest-signals`;  // GET signals
    
    // Configuration constants
    const CONFIG = {
        FRAME_INTERVAL: 200,        // 5 fps target
        POLL_INTERVAL: 1000,        // 1 second polling
        HEARTBEAT_INTERVAL: 3000,    // 3 seconds heartbeat
        MAX_RETRIES: 3,             // Max retry attempts
        RETRY_DELAY: 1000,          // Retry delay in ms
        TARGET_WIDTH: 224,          // Frame width
        TARGET_HEIGHT: 224,         // Frame height
        JPEG_QUALITY: 0.6           // JPEG compression quality
    };
  
    // ======= STATE =============================================================
    const els = {
      video: document.getElementById("video"),
      camStatus: document.getElementById("cam-status"),
      gazeVal: document.getElementById("gaze-val"),
      exprVal: document.getElementById("expr-val"),
      fpsVal: document.getElementById("fps-val"),
      msgs: document.getElementById("msgs"),
      input: document.getElementById("input"),
      composer: document.getElementById("composer"),
      consent: document.getElementById("consent-modal"),
      allow: document.getElementById("consent-allow"),
      deny: document.getElementById("consent-deny"),
      chkSendFrames: document.getElementById("chk-send-frames"),
      visionBadge: document.getElementById("vision-badge"),
      btnStart: document.getElementById("btn-start"),
      btnStop: document.getElementById("btn-stop"),
      rasaLabel: document.getElementById("rasa-endpoint-label"),
      visionLabel: document.getElementById("vision-endpoint-label"),
      senderLabel: document.getElementById("sender-label"),
    };
    
    // Validate critical DOM elements
    const requiredElements = ['video', 'camStatus', 'gazeVal', 'exprVal', 'msgs', 'input', 'composer'];
    const missingElements = requiredElements.filter(id => !els[id]);
    if (missingElements.length > 0) {
        console.error('Missing required DOM elements:', missingElements);
        return; // Exit early if critical elements are missing
    }
  
    const senderId = getSenderId();
    let mediaStream = null;
    let capturing = false;
    let lastFpsAt = performance.now();
    let framesInWindow = 0;
    let pollTimer = null;
    let pushTimer = null;
    let heartbeatTimer = null;
    let abortController = null; // For fetch request cancellation
    let connectionState = 'disconnected'; // 'connected', 'disconnected', 'error'
    let consecutiveErrors = 0;
    let isPageVisible = true;
  
    // Safe element access helper
    const safeSetText = (element, text, fallback = '—') => {
        if (element) {
            try {
                element.textContent = text || fallback;
            } catch (e) {
                console.warn('Failed to set text on element:', e);
            }
        }
    };
    
    // Safe class manipulation
    const safeClassToggle = (element, className, add) => {
        if (element) {
            try {
                if (add) {
                    element.classList.add(className);
                } else {
                    element.classList.remove(className);
                }
            } catch (e) {
                console.warn('Failed to toggle class on element:', e);
            }
        }
    };
  
    // Initialize labels safely
    try {
        if (els.rasaLabel) {
            try {
                els.rasaLabel.textContent = new URL(RASA_REST_URL).pathname;
            } catch (e) {
                els.rasaLabel.textContent = '/webhooks/rest/webhook';
            }
        }
        if (els.visionLabel) els.visionLabel.textContent = "/ingest-frame";
        if (els.senderLabel) els.senderLabel.textContent = senderId;
    } catch (e) {
        console.warn('Failed to initialize labels:', e);
    }
  
    // ======= INIT ==============================================================
    // Page visibility API to pause/resume when tab is hidden
    document.addEventListener('visibilitychange', () => {
        isPageVisible = !document.hidden;
        if (!isPageVisible && capturing) {
            // Pause frame pushing when tab is hidden (privacy + performance)
            stopFramePush();
        } else if (isPageVisible && capturing) {
            const consent = localStorage.getItem("dental_consent");
            if (consent === "send") startFramePush();
        }
    });
    
    // Cleanup on page unload
    window.addEventListener('beforeunload', cleanup);
    window.addEventListener('pagehide', cleanup);
    
    function cleanup() {
        stopCamera();
        if (heartbeatTimer) {
            clearTimeout(heartbeatTimer);
            heartbeatTimer = null;
        }
        if (abortController) {
            abortController.abort();
            abortController = null;
        }
    }
    
    boot();
  
    function boot() {
      try {
        // show consent modal on first visit
        const consent = localStorage.getItem("dental_consent");
        if (!consent) showConsent();
        bindChat();
        bindCameraButtons();
        appendBot("Hi! I can explain treatments or book an appointment. I also adapt to your comfort in real time.");
        heartbeatVision();
      } catch (e) {
        console.error('Boot error:', e);
        appendBot("Initialization error. Please refresh the page.");
      }
    }
  
    function bindChat() {
      if (!els.composer) return;
      
      els.composer.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = (els.input?.value || "").trim();
        if (!text) return;
        
        // Input validation
        if (text.length > 1000) {
          appendBot("Message too long. Please keep it under 1000 characters.");
          return;
        }
        
        appendYou(text);
        if (els.input) els.input.value = "";
        
        // Disable input while processing
        if (els.input) els.input.disabled = true;
        if (els.composer) {
          const submitBtn = els.composer.querySelector('button[type="submit"]');
          if (submitBtn) submitBtn.disabled = true;
        }

        try {
          // Create abort controller for this request
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout
          
          const res = await fetch(RASA_REST_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sender: senderId, message: text }),
            signal: controller.signal
          });
          
          clearTimeout(timeoutId);
          
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
          }
          
          const data = await res.json();
          if (Array.isArray(data)) {
            data.forEach((m) => {
              if (m && m.text) appendBot(m.text);
            });
            if (data.length === 0) {
              appendBot("I received your message but didn't get a response. Please try again.");
            }
          } else if (data && data.text) {
            appendBot(data.text);
          } else {
            appendBot("I received your message but the response format was unexpected.");
          }
        } catch (err) {
          if (err.name === 'AbortError') {
            appendBot("Request timed out. Please try again.");
          } else if (err.name === 'TypeError' && err.message.includes('fetch')) {
            appendBot("Sorry, I couldn't reach the assistant API. Please check your connection.");
          } else {
            appendBot("Sorry, I encountered an error. Please try again.");
          }
          console.error('Chat error:', err);
        } finally {
          // Re-enable input
          if (els.input) els.input.disabled = false;
          if (els.composer) {
            const submitBtn = els.composer.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.disabled = false;
          }
        }
      });
    }
  
    function bindCameraButtons() {
      if (els.btnStart) {
        els.btnStart.addEventListener("click", () => {
          startCamera().catch(err => {
            console.error('Camera start error:', err);
            safeSetText(els.camStatus, "error");
          });
        });
      }
      if (els.btnStop) {
        els.btnStop.addEventListener("click", stopCamera);
      }

      if (els.allow) {
        els.allow.addEventListener("click", async () => {
          try {
            const sendFrames = els.chkSendFrames?.checked ?? true;
            localStorage.setItem("dental_consent", sendFrames ? "send" : "local");
            hideConsent();
            await startCamera();
          } catch (err) {
            console.error('Consent allow error:', err);
            hideConsent();
          }
        });
      }
      if (els.deny) {
        els.deny.addEventListener("click", () => {
          try {
            localStorage.setItem("dental_consent", "deny");
            hideConsent();
            // you can still chat without camera
            appendBot("Camera disabled. I'll proceed without vision signals.");
          } catch (err) {
            console.error('Consent deny error:', err);
          }
        });
      }
    }
  
    // ======= CAMERA / CAPTURE ==================================================
    async function startCamera() {
      if (capturing) {
        console.log('Camera already capturing');
        return;
      }
      
      // Check if getUserMedia is available
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        const errorMsg = "Camera access is not supported in this browser.";
        safeSetText(els.camStatus, "not supported");
        appendBot(errorMsg);
        console.error(errorMsg);
        return;
      }
      
      try {
        safeSetText(els.camStatus, "requesting permission…");
        
        // Request camera with constraints
        const constraints = {
          video: {
            width: { ideal: 640 },
            height: { ideal: 480 },
            facingMode: 'user'
          },
          audio: false
        };
        
        mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
        
        // Verify stream is valid
        if (!mediaStream || !mediaStream.getVideoTracks().length) {
          throw new Error('No video tracks in stream');
        }
        
        // Set up video element
        if (els.video) {
          els.video.srcObject = mediaStream;
          
          // Wait for video to be ready
          await new Promise((resolve, reject) => {
            if (!els.video) {
              reject(new Error('Video element not found'));
              return;
            }
            
            const onLoadedMetadata = () => {
              els.video.removeEventListener('loadedmetadata', onLoadedMetadata);
              els.video.removeEventListener('error', onError);
              resolve();
            };
            
            const onError = (e) => {
              els.video.removeEventListener('loadedmetadata', onLoadedMetadata);
              els.video.removeEventListener('error', onError);
              reject(new Error('Video element error'));
            };
            
            els.video.addEventListener('loadedmetadata', onLoadedMetadata);
            els.video.addEventListener('error', onError);
            
            // Timeout after 5 seconds
            setTimeout(() => {
              els.video.removeEventListener('loadedmetadata', onLoadedMetadata);
              els.video.removeEventListener('error', onError);
              reject(new Error('Video load timeout'));
            }, 5000);
          });
        }
        
        safeSetText(els.camStatus, "live");
        capturing = true;
        consecutiveErrors = 0;

        // Start polling latest signals (whether we send frames or not)
        startSignalPolling();

        // Optionally push frames (depends on consent mode)
        const consent = localStorage.getItem("dental_consent");
        if (consent === "send" && isPageVisible) {
          startFramePush();
        } else {
          stopFramePush();
        }
      } catch (err) {
        capturing = false;
        let errorMsg = "I couldn't access the camera. You can continue chatting without it.";
        
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          safeSetText(els.camStatus, "permission denied");
          errorMsg = "Camera permission was denied. You can continue chatting without it.";
        } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
          safeSetText(els.camStatus, "no camera");
          errorMsg = "No camera found. You can continue chatting without it.";
        } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
          safeSetText(els.camStatus, "camera busy");
          errorMsg = "Camera is being used by another application. You can continue chatting without it.";
        } else if (err.name === 'OverconstrainedError' || err.name === 'ConstraintNotSatisfiedError') {
          safeSetText(els.camStatus, "unsupported");
          errorMsg = "Camera doesn't support the required settings. You can continue chatting without it.";
        } else {
          safeSetText(els.camStatus, "error");
          errorMsg = "Camera error occurred. You can continue chatting without it.";
        }
        
        appendBot(errorMsg);
        console.error('Camera error:', err);
        
        // Clean up on error
        if (mediaStream) {
          mediaStream.getTracks().forEach(track => track.stop());
          mediaStream = null;
        }
        if (els.video) {
          els.video.srcObject = null;
        }
      }
    }
  
    function stopCamera() {
      capturing = false;
      stopSignalPolling();
      stopFramePush();
      
      try {
        if (mediaStream) {
          mediaStream.getTracks().forEach((t) => {
            try {
              t.stop();
            } catch (e) {
              console.warn('Error stopping track:', e);
            }
          });
          mediaStream = null;
        }
        if (els.video) {
          els.video.srcObject = null;
        }
        safeSetText(els.camStatus, "stopped");
      } catch (err) {
        console.error('Error stopping camera:', err);
        safeSetText(els.camStatus, "error");
      }
    }
  
    function startFramePush() {
      if (pushTimer || !capturing || !isPageVisible) return;
      
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      canvas.width = CONFIG.TARGET_W;
      canvas.height = CONFIG.TARGET_H;
      
      let framePushErrors = 0;
      const MAX_FRAME_ERRORS = 5;

      pushTimer = setInterval(async () => {
        if (!capturing || !mediaStream || !isPageVisible) {
          stopFramePush();
          return;
        }
        
        // Check if video is ready
        if (!els.video || els.video.readyState !== HTMLMediaElement.HAVE_ENOUGH_DATA) {
          return;
        }
        
        try {
          // Draw frame to canvas
          ctx.drawImage(els.video, 0, 0, CONFIG.TARGET_W, CONFIG.TARGET_H);
          
          // Convert to blob
          const blob = await new Promise((resolve, reject) => {
            canvas.toBlob(
              (blob) => {
                if (blob) {
                  resolve(blob);
                } else {
                  reject(new Error('Failed to create blob'));
                }
              },
              "image/jpeg",
              CONFIG.JPEG_QUALITY
            );
          });
          
          // Send frame with timeout
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 5000); // 5s timeout
          
          try {
            const res = await fetch(VISION_PUSH_ENDPOINT, {
              method: "POST",
              body: blob,
              headers: { 
                "Content-Type": "image/jpeg", 
                "X-Sender": senderId 
              },
              signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            if (res.ok) {
              framePushErrors = 0; // Reset error counter on success
              framesInWindow++;
              updateFps();
            } else {
              framePushErrors++;
              if (framePushErrors >= MAX_FRAME_ERRORS) {
                console.warn('Too many frame push errors, stopping');
                stopFramePush();
              }
            }
          } catch (fetchErr) {
            clearTimeout(timeoutId);
            if (fetchErr.name !== 'AbortError') {
              framePushErrors++;
              if (framePushErrors >= MAX_FRAME_ERRORS) {
                console.warn('Too many frame push errors, stopping');
                stopFramePush();
              }
            }
          }
        } catch (e) {
          console.warn("Frame push error:", e);
          framePushErrors++;
          if (framePushErrors >= MAX_FRAME_ERRORS) {
            console.warn('Too many frame push errors, stopping');
            stopFramePush();
          }
        }
      }, CONFIG.FRAME_INTERVAL);
    }
  
    function stopFramePush() {
      if (pushTimer) {
        clearInterval(pushTimer);
        pushTimer = null;
      }
    }
  
    function startSignalPolling() {
      if (pollTimer) return;
      
      let pollErrors = 0;
      const MAX_POLL_ERRORS = 3;
      
      pollTimer = setInterval(async () => {
        if (!capturing) return;
        
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 5000); // 5s timeout
          
          const res = await fetch(VISION_LATEST_ENDPOINT, {
            headers: { "X-Sender": senderId },
            signal: controller.signal
          });
          
          clearTimeout(timeoutId);
          
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
          }
          
          const js = await res.json();
          
          // Validate response structure
          if (js && typeof js === 'object') {
            const gaze = js.gaze_state || "neutral";
            const expr = js.micro_expression || "neutral";
            safeSetText(els.gazeVal, gaze);
            safeSetText(els.exprVal, expr);
            pollErrors = 0; // Reset error counter on success
            connectionState = 'connected';
            consecutiveErrors = 0;
          } else {
            throw new Error('Invalid response format');
          }
        } catch (e) {
          pollErrors++;
          consecutiveErrors++;
          
          // If your vision server is down, keep UI responsive
          safeSetText(els.gazeVal, "—");
          safeSetText(els.exprVal, "—");
          
          if (pollErrors >= MAX_POLL_ERRORS) {
            connectionState = 'error';
            console.warn('Signal polling failed multiple times, connection may be down');
          }
          
          // Don't log every error to avoid console spam
          if (pollErrors === 1 || pollErrors % 10 === 0) {
            console.warn('Signal polling error:', e.message || e);
          }
        }
      }, CONFIG.POLL_INTERVAL);
    }
  
    function stopSignalPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      // Reset display values
      safeSetText(els.gazeVal, "—");
      safeSetText(els.exprVal, "—");
    }
  
    // ======= VISION HEARTBEAT ===================================================
    async function heartbeatVision() {
      const ping = async () => {
        if (!isPageVisible) {
          // Skip heartbeat when page is hidden
          heartbeatTimer = setTimeout(ping, CONFIG.HEARTBEAT_INTERVAL);
          return;
        }
        
        const start = performance.now();
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 5000); // 5s timeout
          
          const res = await fetch(`${VISION_API_BASE}/health`, {
            signal: controller.signal
          });
          
          clearTimeout(timeoutId);
          
          const ok = res.ok;
          const t = Math.max(1, Math.round(performance.now() - start));
          
          if (els.visionBadge) {
            els.visionBadge.textContent = ok ? `online • ${t}ms` : "offline";
            els.visionBadge.style.color = ok ? "var(--success)" : "var(--danger)";
            safeClassToggle(els.visionBadge, "pulse", !ok);
          }
          
          connectionState = ok ? 'connected' : 'error';
          if (ok) consecutiveErrors = 0;
        } catch (err) {
          if (els.visionBadge) {
            els.visionBadge.textContent = "offline";
            els.visionBadge.style.color = "var(--danger)";
            safeClassToggle(els.visionBadge, "pulse", true);
          }
          connectionState = 'error';
          consecutiveErrors++;
          
          // Don't log every error
          if (consecutiveErrors === 1 || consecutiveErrors % 10 === 0) {
            console.warn('Heartbeat error:', err.message || err);
          }
        }
        
        heartbeatTimer = setTimeout(ping, CONFIG.HEARTBEAT_INTERVAL);
      };
      ping();
    }
  
    // ======= CHAT UI HELPERS ====================================================
    function append(msg, who = "bot") {
      if (!els.msgs || !msg) return;
      
      try {
        const item = document.createElement("div");
        item.className = `msg ${who === "you" ? "you" : ""}`;
        
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = who === "you" ? "You" : "Assistant";
        
        const text = document.createElement("div");
        text.className = "text";
        // Sanitize text to prevent XSS (basic)
        text.textContent = String(msg).substring(0, 5000); // Limit length
        
        item.appendChild(meta);
        item.appendChild(text);
        els.msgs.appendChild(item);
        
        // Smooth scroll to bottom
        els.msgs.scrollTop = els.msgs.scrollHeight;
      } catch (e) {
        console.error('Error appending message:', e);
      }
    }
    const appendYou = (t) => append(t, "you");
    const appendBot = (t) => append(t, "bot");
  
    // ======= UTILITIES ==========================================================
    function getSenderId() {
      const key = "dental_sender";
      try {
        let id = localStorage.getItem(key);
        if (!id || id.length < 5) {
          // Generate a unique ID
          id = "web_" + Math.random().toString(36).slice(2) + Date.now().toString(36) + Math.random().toString(36).slice(2);
          localStorage.setItem(key, id);
        }
        return id;
      } catch (e) {
        // Fallback if localStorage is not available
        console.warn('localStorage not available, using session ID');
        return "session_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      }
    }
  
    function showConsent() {
      if (els.consent) {
        safeClassToggle(els.consent, "hidden", false);
      }
    }
    
    function hideConsent() {
      if (els.consent) {
        safeClassToggle(els.consent, "hidden", true);
      }
    }
  
    function updateFps() {
      const now = performance.now();
      if (now - lastFpsAt >= 1000) {
        safeSetText(els.fpsVal, String(framesInWindow), "0");
        framesInWindow = 0;
        lastFpsAt = now;
      }
    }
  
  })();
  