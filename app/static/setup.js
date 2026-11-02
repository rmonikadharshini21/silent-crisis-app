"use strict";
(() => {
  const form = document.getElementById("location-form");
  const note = document.getElementById("coords-note");
  document.getElementById("use-location").addEventListener("click", () => {
    if (!navigator.geolocation) {
      note.textContent = "This browser can't share a position. The description will still be saved.";
      return;
    }
    note.textContent = "Finding your position…";
    navigator.geolocation.getCurrentPosition(
      (position) => {
        form.elements.lat.value = position.coords.latitude.toFixed(6);
        form.elements.lng.value = position.coords.longitude.toFixed(6);
        note.textContent = "Position found. Click Save location to keep it.";
      },
      () => { note.textContent = "Couldn't get your position. The description will still be saved."; },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  });
  document.querySelectorAll("[data-select-on-focus]").forEach((input) => {
    input.addEventListener("focus", () => input.select());
  });
})();
