"use strict";
(() => {
  const root = document.getElementById("help-map");
  const status = document.getElementById("map-status");
  const places = document.getElementById("places");
  const RADIUS_METRES = 5000;

  function message(text) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = text;
    places.replaceChildren(li);
  }

  function distanceKm(a, b) {
    const rad = Math.PI / 180;
    const dLat = (b[0] - a[0]) * rad;
    const dLng = (b[1] - a[1]) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLng / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(h));
  }

  async function search(point, map) {
    const [lat, lng] = point;
    const query = `[out:json][timeout:20];(` +
      `nwr["amenity"="police"](around:${RADIUS_METRES},${lat},${lng});` +
      `nwr["amenity"="hospital"](around:${RADIUS_METRES},${lat},${lng}););out center 40;`;
    const response = await fetch("https://overpass-api.de/api/interpreter", {
      method: "POST",
      body: new URLSearchParams({ data: query }),
    });
    if (!response.ok) throw new Error("search failed");
    const data = await response.json();
    const found = data.elements
      .map((el) => ({
        name: el.tags?.name || (el.tags?.amenity === "police" ? "Police station" : "Hospital"),
        kind: el.tags?.amenity === "police" ? "Police" : "Hospital",
        point: [el.lat ?? el.center?.lat, el.lon ?? el.center?.lon],
      }))
      .filter((p) => p.point[0] !== undefined)
      .map((p) => ({ ...p, km: distanceKm(point, p.point) }))
      .sort((a, b) => a.km - b.km);
    if (!found.length) {
      message("Nothing found within 5 km in the map data.");
      return;
    }
    places.replaceChildren(...found.map((place) => {
      const marker = L.marker(place.point).addTo(map);
      marker.bindPopup(() => {
        const el = document.createElement("span");
        el.textContent = place.name;
        return el;
      });
      const li = document.createElement("li");
      const name = document.createElement("strong");
      name.textContent = place.name;
      const meta = document.createElement("small");
      meta.textContent = `${place.kind} · ${place.km.toFixed(1)} km`;
      li.append(name, meta);
      return li;
    }));
  }

  function show(point, description) {
    status.textContent = description;
    const map = L.map("map").setView(point, 14);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    L.circleMarker(point, { radius: 9, color: "#c1341f", fillOpacity: 0.8 }).addTo(map);
    search(point, map).catch(() => message("The place search is unavailable right now. Try again later."));
  }

  function useSaved() {
    if (root.dataset.lat && root.dataset.lng) {
      show([Number(root.dataset.lat), Number(root.dataset.lng)], `Using your saved location: ${root.dataset.label}`);
    } else {
      status.textContent = "Your location isn't available, and your saved location has no map position. Add one in Setup.";
      message("No position to search from.");
    }
  }

  if (!window.L) {
    status.textContent = "The map could not load. Check your internet connection.";
    message("Map unavailable.");
  } else if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (p) => show([p.coords.latitude, p.coords.longitude], "Using your current location."),
      useSaved,
      { enableHighAccuracy: true, timeout: 8000 },
    );
  } else {
    useSaved();
  }
})();
