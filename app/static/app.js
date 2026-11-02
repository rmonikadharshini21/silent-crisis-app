"use strict";
const SC = (() => {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;

  async function api(url, body) {
    const response = await fetch(url, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || "Something went wrong. Please try again.");
      error.data = data;
      throw error;
    }
    return data;
  }

  function toast(message, kind = "") {
    const box = document.getElementById("toasts");
    const item = document.createElement("div");
    item.className = "toast" + (kind ? ` toast-${kind}` : "");
    item.textContent = message;
    box.append(item);
    setTimeout(() => item.remove(), kind === "alert" ? 9000 : 5000);
  }

  function formatTime(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
  }

  function localizeTimes(root = document) {
    root.querySelectorAll("time[data-local]").forEach((el) => {
      el.textContent = formatTime(el.getAttribute("datetime"));
    });
  }

  let audio;
  function beep(frequency = 880, ms = 160) {
    try {
      audio = audio || new AudioContext();
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.frequency.value = frequency;
      gain.gain.value = 0.15;
      osc.connect(gain).connect(audio.destination);
      osc.start();
      osc.stop(audio.currentTime + ms / 1000);
    } catch (_) { /* Sound is a bonus; the screen still shows the warning. */ }
  }

  // EventSource reconnects by itself; onReconnect reloads state missed while offline.
  function connect(url, handlers, onReconnect) {
    const label = document.getElementById("live-state");
    const source = new EventSource(url);
    let wasLost = false;
    source.onopen = () => {
      if (label) { label.dataset.state = "live"; label.textContent = "Live"; }
      if (wasLost && onReconnect) onReconnect();
      wasLost = false;
    };
    source.onerror = () => {
      wasLost = true;
      if (label) { label.dataset.state = "lost"; label.textContent = "Reconnecting"; }
    };
    Object.entries(handlers).forEach(([event, handler]) => {
      source.addEventListener(event, (e) => handler(JSON.parse(e.data)));
    });
    return source;
  }

  localizeTimes();
  return { api, toast, beep, connect, formatTime, localizeTimes };
})();
