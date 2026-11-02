"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const root = $("dashboard");
  const feed = $("feed");
  const END_REASONS = {
    video_finished: "The recorded video finished.",
    camera_lost: "The webcam stopped sending video, so monitoring has stopped.",
  };

  // Monitoring
  let watchId = null;
  let lastSent = 0;

  function sendPosition(position) {
    const now = Date.now();
    if (now - lastSent < 20000) return;
    lastSent = now;
    SC.api("/api/location", { lat: position.coords.latitude, lng: position.coords.longitude }).catch(() => {});
  }

  function startLocation() {
    if (!navigator.geolocation || watchId !== null) return;
    watchId = navigator.geolocation.watchPosition(sendPosition, () => {}, { enableHighAccuracy: true, maximumAge: 30000 });
  }

  function stopLocation() {
    if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    watchId = null;
    lastSent = 0;
  }

  function showMonitoring(running) {
    const indicator = $("indicator");
    indicator.dataset.on = String(running);
    indicator.textContent = running ? "On" : "Off";
    $("start").hidden = running;
    $("stop").hidden = !running;
    $("source").disabled = running;
    $("consent").disabled = running;
    $("video-empty").hidden = running;
    feed.hidden = !running;
    $("person-note").hidden = !running;
    if (running) {
      feed.src = `${root.dataset.feed}?t=${Date.now()}`;
      startLocation();
    } else {
      feed.removeAttribute("src");
      $("consent").checked = false;
      stopLocation();
    }
  }

  $("monitor-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!$("consent").checked) {
      SC.toast("Please accept the consent notice first.", "alert");
      $("consent").focus();
      return;
    }
    SC.beep(660, 1); // Browsers only allow sound after a click, so unlock it now.
    $("start").disabled = true;
    try {
      await SC.api("/api/monitor/start", { consent: true, source: $("source").value });
      showMonitoring(true);
      SC.toast("Monitoring is on.", "ok");
    } catch (error) {
      SC.toast(error.message, "alert");
    } finally {
      $("start").disabled = false;
    }
  });

  $("stop").addEventListener("click", async () => {
    try {
      await SC.api("/api/monitor/stop", {});
      showMonitoring(false);
      SC.toast("Monitoring is off. The webcam has stopped.");
    } catch (error) {
      SC.toast(error.message, "alert");
    }
  });

  // Countdown
  let activeId = null;
  let endsAt = 0;
  let total = 10;
  let tick = null;
  let lastSecond = null;

  function render() {
    const remaining = Math.max(0, (endsAt - performance.now()) / 1000);
    const second = Math.ceil(remaining);
    $("count-number").textContent = second;
    $("ring-fill").style.strokeDashoffset = String(100 * (1 - remaining / total));
    if (second !== lastSecond && second > 0) SC.beep(second <= 3 ? 1040 : 820);
    lastSecond = second;
  }

  function showCountdown(info) {
    if (activeId === info.id) return;
    activeId = info.id;
    total = Math.max(info.remaining, 1);
    endsAt = performance.now() + info.remaining * 1000;
    $("count-trigger").textContent = info.trigger === "SOS" ? "SOS pressed" : "Possible fall detected";
    $("pin").value = "";
    $("pin-message").textContent = "";
    $("countdown").hidden = false;
    $("pin").focus();
    clearInterval(tick);
    tick = setInterval(render, 100);
    render();
  }

  function hideCountdown() {
    clearInterval(tick);
    activeId = null;
    lastSecond = null;
    $("countdown").hidden = true;
  }

  $("pin-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (activeId === null) return;
    const id = activeId;
    const pin = $("pin").value;
    $("pin").value = "";
    try {
      const { result } = await SC.api(`/api/incidents/${id}/cancel`, { pin });
      if (result === "cancelled") {
        // The live event may already have closed the countdown and shown this message.
        if (activeId === id) {
          hideCountdown();
          SC.toast("Alert cancelled. Nobody was told.", "ok");
        }
      } else if (result === "wrong_pin") {
        $("pin-message").textContent = "That PIN is not right. The countdown continues.";
        $("pin").focus();
      } else if (result === "locked") {
        $("pin-message").textContent = "Too many wrong PINs. The alert will go out.";
      }
    } catch (error) {
      $("pin-message").textContent = error.message;
    }
  });

  $("sos").addEventListener("click", async () => {
    SC.beep(660, 1);
    startLocation();
    try {
      showCountdown(await SC.api("/api/sos", {}));
    } catch (error) {
      SC.toast(error.message, "alert");
    }
  });

  // Live events
  async function refreshRecent() {
    const box = $("recent");
    const response = await fetch(box.dataset.url);
    if (!response.ok) return;
    // Rendered and escaped by the server's template.
    box.innerHTML = await response.text();
    SC.localizeTimes(box);
  }

  async function syncState() {
    const state = await SC.api("/api/state");
    showMonitoring(state.monitoring);
    if (state.countdown) showCountdown(state.countdown);
    else if (activeId !== null) hideCountdown();
    await refreshRecent();
  }

  SC.connect("/events", {
    countdown: showCountdown,
    countdown_end: ({ id, outcome }) => {
      if (id !== activeId && activeId !== null) return;
      const wasShowing = activeId !== null;
      hideCountdown();
      if (outcome === "alerted") SC.toast("Alert sent to your trusted contact and campus staff.", "alert");
      else if (wasShowing) SC.toast("Alert cancelled. Nobody was told.", "ok");
      refreshRecent().catch(() => {});
    },
    monitor: ({ running, reason }) => {
      showMonitoring(running);
      if (running || !reason || reason === "stopped") return;
      SC.toast(END_REASONS[reason] || "Monitoring stopped because of an error.", "alert");
    },
    status: ({ status }) => {
      SC.toast(`Campus staff updated your incident: ${status}.`);
      refreshRecent().catch(() => {});
    },
  }, syncState);

  setInterval(async () => {
    if ($("indicator").dataset.on !== "true") return;
    const state = await SC.api("/api/state").catch(() => null);
    if (state && state.monitoring) {
      $("person-note").textContent = state.person_visible
        ? "You're in view."
        : "No person in view. A fall can't be detected unless you're in the frame.";
    }
  }, 3000);

  syncState().catch(() => {});
})();
