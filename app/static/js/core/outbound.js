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
    </section>`;
}

function obRepaint() {
    const list = document.getElementById("ob-list");
    if (list) list.innerHTML = obListHtml();
}

function rememberOutbound() {
    if (!obDraft || !document.getElementById("ob-list")) return;
    obReadInputs();
    state.settings.outbound = obDraft.map((item) => ({ ...item }));
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
