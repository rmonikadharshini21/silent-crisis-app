"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const root = $("admin");
  const EMAIL_TEXT = {
    sent: "Email sent",
    sending: "Sending email",
    failed: "Email failed; alert is on the contact page",
    not_configured: "Email not set up; alert is on the contact page",
    no_contact: "No contact on file",
  };
  let incidents = [];
  let selected = null;

  const isOpen = (i) => i.status !== "Resolved" && i.status !== "False alarm";
  const badgeClass = (status) => `badge badge-${status.toLowerCase().replace(" ", "-")}`;

  function badge(text, className) {
    const el = document.createElement("span");
    el.className = className;
    el.textContent = text;
    return el;
  }

  function renderList() {
    const show = $("filter").value === "all" ? incidents : incidents.filter(isOpen);
    const list = $("incident-list");
    list.replaceChildren(...show.map((incident) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "admin-item";
      if (incident.id === selected) button.setAttribute("aria-current", "true");
      const text = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = incident.student;
      const meta = document.createElement("small");
      meta.textContent = `${incident.trigger === "SOS" ? "Manual SOS" : "Possible fall"} · ${SC.formatTime(incident.alerted_at)}`;
      text.append(name, meta);
      const badges = document.createElement("div");
      badges.className = "admin-badges";
      if (incident.duress) badges.append(badge("Duress", "badge badge-duress"));
      badges.append(badge(incident.status, badgeClass(incident.status)));
      button.append(text, badges);
      button.addEventListener("click", () => { selected = incident.id; render(); });
      const li = document.createElement("li");
      li.append(button);
      return li;
    }));
    $("empty").hidden = show.length > 0;
    $("stat-new").textContent = incidents.filter((i) => i.status === "New").length;
    $("stat-open").textContent = incidents.filter((i) => i.status === "Acknowledged" || i.status === "Help sent").length;
    $("stat-resolved").textContent = incidents.filter((i) => i.status === "Resolved").length;
    $("stat-false").textContent = incidents.filter((i) => i.status === "False alarm").length;
  }

  function renderDetail() {
    const incident = incidents.find((i) => i.id === selected);
    $("detail").hidden = !incident;
    if (!incident) return;
    $("d-student").textContent = incident.student;
    $("d-duress").hidden = !incident.duress;
    $("d-email").textContent = incident.student_email;
    $("d-time").textContent = SC.formatTime(incident.alerted_at);
    $("d-trigger").textContent = incident.trigger === "SOS" ? "Manual SOS" : "AI detection";
    $("d-confidence").textContent = incident.confidence === null ? "Not applicable" : `${Math.round(incident.confidence * 100)}%`;
    $("d-location").textContent = incident.location_label + (incident.location_source === "saved" ? " (saved location)" : "");
    $("d-contact").textContent = incident.contact || "None";
    $("d-email-status").textContent = (EMAIL_TEXT[incident.email_status] || "Unknown") + (incident.all_clear ? "; all clear sent" : "");
    $("d-map").hidden = !incident.map_link;
    if (incident.map_link) $("d-map").href = incident.map_link;
    $("d-page").href = incident.alert_page;
    $("d-status").value = incident.status;
  }

  function render() { renderList(); renderDetail(); }

  async function load() {
    const data = await SC.api(root.dataset.api);
    incidents = data.incidents;
    render();
  }

  $("filter").addEventListener("change", renderList);
  $("d-close").addEventListener("click", () => { selected = null; render(); });

  $("status-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = $("d-status").value;
    if (status === "New") return;
    try {
      await SC.api(`/admin/api/incidents/${selected}/status`, { status });
      SC.toast(`Status updated to ${status}.`, "ok");
      await load();
    } catch (error) {
      SC.toast(error.message, "alert");
    }
  });

  SC.connect("/events", {
    incident: ({ kind, name }) => {
      if (kind === "new") {
        SC.toast(`New alert: ${name}`, "alert");
        SC.beep(980, 300);
      }
      load().catch(() => {});
    },
  }, () => load().catch(() => {}));

  load().catch((error) => SC.toast(error.message, "alert"));
})();
