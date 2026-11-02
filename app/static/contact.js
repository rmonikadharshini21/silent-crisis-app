"use strict";
(() => {
  const live = document.getElementById("contact-live");
  if (live.dataset.events) {
    SC.connect(live.dataset.events, { alert: () => location.reload() }, () => location.reload());
  }
  const mapEl = document.getElementById("map");
  if (mapEl && window.L) {
    const point = [Number(mapEl.dataset.lat), Number(mapEl.dataset.lng)];
    const map = L.map(mapEl).setView(point, 16);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    L.marker(point).addTo(map);
  }
})();
