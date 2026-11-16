// Settings, Notifications: send Curator's events to other apps (Discord, Telegram, Pushover, ntfy, webhooks...).
// The list is edited in memory (obDraft) and handed to the settings save by rememberOutbound().

let obDraft = null;

function obCatalog() {
    return (state.settings || {}).outbound_catalog || { events: [], types: [], default_events: [] };
}

function obTypeInfo(type) {
    return obCatalog().types.find((item) => item.id === type) || { id: type, label: type, fields: [] };
}

function obStart() {
    obDraft = JSON.parse(JSON.stringify(((state.settings || {}).outbound) || []));
}

function obReadInputs() {
    if (!obDraft) return;
    document.querySelectorAll("[data-ob-card]").forEach((card) => {
        const target = obDraft.find((item) => item.id === card.dataset.obCard);
        if (!target) return;
        card.querySelectorAll("[data-ob-field]").forEach((input) => {
            const key = input.dataset.obField;
            if (input.type === "checkbox") target[key] = input.checked;
            else if (key === "secret") return;
            else target[key] = input.value;
        });
        target.events = [...card.querySelectorAll("[data-ob-event]:checked")].map((box) => box.dataset.obEvent);
    });
}

function obCardHtml(target) {
    const info = obTypeInfo(target.type);
    const typeOptions = obCatalog().types.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === target.type ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("");
    const fields = info.fields.map((field) => {
        const saved = target[`${field.key}_set`] && !target[field.key];
        const placeholder = saved ? "Saved. Type to replace." : (field.hint || "");
        return `<label class="field">${escapeHtml(field.label)}
            <input type="${field.secret ? "password" : "text"}" data-ob-field="${escapeHtml(field.key)}" value="${escapeHtml(target[field.key] || "")}" placeholder="${escapeHtml(placeholder)}" autocomplete="off" spellcheck="false"></label>`;
    }).join("");
    const events = obCatalog().events.map((event) => `<label class="choice"><input type="checkbox" data-ob-event="${escapeHtml(event.id)}" ${(target.events || []).includes(event.id) ? "checked" : ""}> ${escapeHtml(event.label)}</label>`).join("");
    return `<div class="ob-card" data-ob-card="${escapeHtml(target.id)}">
        <div class="ob-head">
            <input type="text" data-ob-field="name" value="${escapeHtml(target.name || "")}" aria-label="Name" placeholder="Name" spellcheck="false">
            <select data-ob-type aria-label="Type">${typeOptions}</select>
            <label class="choice"><input type="checkbox" data-ob-field="enabled" ${target.enabled !== false ? "checked" : ""}> On</label>
        </div>
        ${fields}
        <div class="ob-events"><span class="muted">Send when</span>${events}</div>
        <p><button type="button" class="btn-ghost" data-action="auto-ob-test" data-id="${escapeHtml(target.id)}">Send test</button>
        <button type="button" class="btn-ghost btn-remove" data-action="auto-ob-remove" data-id="${escapeHtml(target.id)}">Remove</button>
        <span class="muted ob-status" data-ob-status="${escapeHtml(target.id)}"></span></p>
    </div>`;
}

function obListHtml() {
    if (!obDraft) obStart();
    return obDraft.length ? obDraft.map(obCardHtml).join("") : `<p class="muted">No targets yet.</p>`;
}

function outboundSettingsHtml() {
    obStart();
    return `<section class="settings-section" data-tab="notifications"><h3>Send notifications to other apps</h3>
        <p class="muted">Curator can message Discord, Slack, Telegram, Pushover, ntfy, Gotify, an Apprise server or any webhook when something happens. Each target picks its own events. Addresses and tokens are hidden once saved; leave a box empty to keep the saved value. Messages are sent in the background, and a target that fails is skipped and logged.</p>
        <div id="ob-list">${obListHtml()}</div>
        <p><button type="button" class="btn-ghost" data-action="auto-ob-add">Add a target</button></p>
        ${obDigestHtml()}
    </section>`;
}

// The "Added to the library" message (curator/digest.py): how often and when. Targets tick the event as usual.
const OB_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function obDigestHtml() {
    const cfg = (state.settings || {}).outbound_digest || { every: "off", hour: 9, weekday: 0 };
    const option = (value, label, current) => `<option value="${value}" ${String(current) === String(value) ? "selected" : ""}>${label}</option>`;
    const hours = Array.from({ length: 24 }, (_, hour) => option(hour, `${String(hour).padStart(2, "0")}:00`, cfg.hour)).join("");
    const days = OB_WEEKDAYS.map((day, index) => option(index, day, cfg.weekday)).join("");
    return `<h4>Added to the library</h4>
        <p class="muted">One message listing the movies, episodes (per show), albums and music videos added since the last one. Tick <em>Added to the library</em> on the targets that should get it. When nothing was added, nothing is sent.</p>
        <div class="ob-digest">
            <label class="field">Send <select id="ob-digest-every">${option("off", "Never", cfg.every)}${option("day", "Every day", cfg.every)}${option("week", "Every week", cfg.every)}</select></label>
            <label class="field" id="ob-digest-weekday-field"${cfg.every === "week" ? "" : " hidden"}>on <select id="ob-digest-weekday">${days}</select></label>
            <label class="field">at <select id="ob-digest-hour">${hours}</select></label>
            <button type="button" class="btn-ghost" data-action="auto-ob-digest-preview">Preview</button>
            <button type="button" class="btn-ghost" data-action="auto-ob-digest-send" title="Send it now with the saved settings, to the targets that have it ticked">Send now</button>
        </div>
        <pre id="ob-digest-preview" class="ob-digest-preview" hidden></pre>`;
}

function obDigestInputs() {
    const every = document.getElementById("ob-digest-every");
    if (!every) return null;
    return {
        every: every.value,
        hour: Number((document.getElementById("ob-digest-hour") || {}).value) || 0,
        weekday: Number((document.getElementById("ob-digest-weekday") || {}).value) || 0,
    };
}

function obShowDigest(data, sent) {
    const box = document.getElementById("ob-digest-preview");
    if (!box) return;
    box.hidden = false;
    if (data.empty || (sent && !data.sent)) box.textContent = "Nothing was added since the last message, so there is nothing to send.";
    else box.textContent = `${sent ? "Sent: " : ""}${data.title}\n${data.message}`;
}

async function obDigestPreview() {
    const cfg = obDigestInputs() || { every: "day", hour: 9, weekday: 0 };
    const query = new URLSearchParams({ every: cfg.every === "off" ? "day" : cfg.every, hour: cfg.hour, weekday: cfg.weekday });
    obShowDigest(await api(`/api/v1/outbound/digest/preview?${query}`), false);
}

async function obDigestSend() {
    const data = await api("/api/v1/outbound/digest/send", { method: "POST", body: {} });
    obShowDigest(data, true);
    notify(data.sent ? "Sent to the targets that have Added to the library ticked." : "Nothing was added, so nothing was sent.", "info");
}

function obRepaint() {
    const list = document.getElementById("ob-list");
    if (list) list.innerHTML = obListHtml();
}

function rememberOutbound() {
    if (!obDraft || !document.getElementById("ob-list")) return;
    obReadInputs();
    state.settings.outbound = obDraft.map((item) => ({ ...item }));
    const digest = obDigestInputs();
    if (digest) state.settings.outbound_digest = digest;
}

function obAdd() {
    obReadInputs();
    const id = `n${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
    const first = obCatalog().types[0] || { id: "webhook" };
    obDraft.push({ id, type: first.id, name: "", enabled: true, events: (obCatalog().default_events || []).slice() });
    obRepaint();
}

function obRemove(id) {
    obReadInputs();
    obDraft = obDraft.filter((item) => item.id !== id);
    obRepaint();
}

async function obTest(id) {
    obReadInputs();
    const target = obDraft.find((item) => item.id === id);
    const status = document.querySelector(`[data-ob-status="${CSS.escape(id)}"]`);
    if (!target) return;
    if (status) status.textContent = "Sending…";
    try {
        const data = await api("/api/v1/outbound/test", { method: "POST", body: { target } });
        if (status) status.textContent = `✓ ${data.message || "Sent."}`;
    } catch (error) {
        if (status) status.textContent = `✕ ${(error && error.message) || "Could not send"}`;
    }
}

document.addEventListener("change", (event) => {
    if (event.target && event.target.id === "ob-digest-every") {
        const field = document.getElementById("ob-digest-weekday-field");
        if (field) field.hidden = event.target.value !== "week";
        return;
    }
    const select = event.target && event.target.matches && event.target.matches("[data-ob-type]") ? event.target : null;
    if (!select) return;
    obReadInputs();
    const card = select.closest("[data-ob-card]");
    const target = obDraft.find((item) => item.id === card.dataset.obCard);
    if (target) {
        target.type = select.value;
        ["url", "token", "user_key", "chat_id"].forEach((key) => { target[key] = ""; target[`${key}_set`] = false; });
    }
    obRepaint();
});
