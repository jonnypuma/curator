// Bulk duplicate cleanup: a warning, a preview of what stays and what goes, and a separate confirm button.

state.cleanup = { data: null, timer: 0, skip: new Set() };

async function openCleanup() {
    state.cleanup.skip = new Set();
    document.getElementById("cleanup-modal").classList.remove("hidden");
    state.cleanup.data = await api("/api/v1/cleanup");
    renderCleanup();
    if (["planning", "running"].includes(state.cleanup.data.status)) pollCleanup();
}

async function previewCleanup() {
    const media = [...document.querySelectorAll("[data-cleanup-media]")].filter((box) => box.checked).map((box) => box.dataset.cleanupMedia);
    const include = !!(document.getElementById("cleanup-upgrades") || {}).checked;
    state.cleanup.skip = new Set();
    state.cleanup.data = await api("/api/v1/cleanup/preview", { method: "POST", body: { media, include_upgrades: include } });
    renderCleanup();
    pollCleanup();
}

async function pollCleanup() {
    clearTimeout(state.cleanup.timer);
    const data = await api("/api/v1/cleanup");
    const wasRunning = state.cleanup.data && state.cleanup.data.status === "running";
    state.cleanup.data = data;
    renderCleanup();
    if (["planning", "running"].includes(data.status)) {
        state.cleanup.timer = setTimeout(() => pollCleanup().catch(() => {}), 1500);
    } else if (wasRunning) {
        notify(data.message || "Cleanup finished.", data.status === "failed" ? "error" : "success");
    }
}

function cleanupCount() {
    const plan = (state.cleanup.data || {}).plan;
    if (!plan) return { copies: 0, bytes: 0 };
    const groups = plan.groups.filter((group) => !state.cleanup.skip.has(group.id));
    const items = groups.flatMap((group) => group.remove);
    return { copies: items.length, bytes: items.reduce((sum, item) => sum + (Number(item.size_bytes) || 0), 0) };
}

function cleanupCopyLine(item, tag) {
    const uses = item.in_use ? ` <span class="tag-pill" title="${escapeHtml(item.arr)} uses this copy">${escapeHtml(item.arr)} uses this</span>` : "";
    const size = item.size_bytes ? ` · ${escapeHtml(fmtSize(item.size_bytes))}` : "";
    const why = item.reason ? ` · ${escapeHtml(item.reason)}` : "";
    return `<div class="cleanup-copy"><b>${escapeHtml(tag)}</b>${uses}<small class="muted">${size}${why}</small><br><small class="mono muted">${escapeHtml(item.path || "")}</small></div>`;
}

function cleanupGroupHtml(group) {
    const box = group.remove.length
        ? `<input type="checkbox" data-cleanup-group="${escapeHtml(group.id)}" ${state.cleanup.skip.has(group.id) ? "" : "checked"} aria-label="Clean up ${escapeHtml(group.label)}">`
        : "";
    return `<div class="cleanup-group"><label class="cleanup-title">${box} <strong>${escapeHtml(group.label)}</strong></label>
        ${group.keep ? cleanupCopyLine(group.keep, "Keep") : ""}
        ${group.remove.map((item) => cleanupCopyLine(item, "Delete")).join("")}
        ${group.skipped.map((item) => cleanupCopyLine(item, "Left alone")).join("")}
    </div>`;
}

function renderCleanupConfirm() {
    const button = document.getElementById("cleanup-confirm");
    const data = state.cleanup.data || {};
    if (!button) return;
    const { copies, bytes } = cleanupCount();
    const ready = data.status === "ready" && copies > 0;
    const understood = data.trash_enabled !== false || !!(document.getElementById("cleanup-understood") || {}).checked;
    button.disabled = !ready || !understood;
    button.textContent = ready ? `Delete ${copies.toLocaleString()} ${copies === 1 ? "copy" : "copies"} (${fmtSize(bytes)})` : "Delete copies";
}

function renderCleanup() {
    const data = state.cleanup.data || {};
    const warn = document.getElementById("cleanup-warning");
    const days = Number(data.trash_days) || 30;
    const binOff = data.trash_enabled === false;
    warn.innerHTML = binOff
        ? `<strong>The recycle bin is off.</strong> Every copy listed will be deleted from disk at once and cannot be restored. Radarr, Sonarr and Lidarr are asked to rescan afterwards.
           <label class="choice"><input type="checkbox" id="cleanup-understood"> I understand these files cannot be brought back</label>`
        : `<strong>This deletes files from disk.</strong> Each listed copy moves to the recycle bin for ${days} day${days === 1 ? "" : "s"} and is then gone for good. Radarr, Sonarr and Lidarr are asked to rescan afterwards. Read the preview before you confirm.`;
    const status = document.getElementById("cleanup-status");
    const busy = ["planning", "running"].includes(data.status);
    status.className = `scan-status ${busy ? "is-running" : data.status === "failed" ? "is-failed" : ""}`;
    const progress = data.status === "running" && data.total ? ` (${data.processed}/${data.total})` : "";
    keepText(status, `${data.message || "Preview first. Nothing is deleted until you press the red button."}${progress}`);
    document.getElementById("cleanup-preview").disabled = busy;
    const host = document.getElementById("cleanup-list");
    const plan = data.plan;
    if (data.status === "ready" && plan) {
        host.innerHTML = plan.groups.length
            ? `<p>${plan.count.toLocaleString()} copies, ${escapeHtml(fmtSize(plan.bytes))}${plan.skipped ? `, ${plan.skipped.toLocaleString()} left alone` : ""}. Untick a title to leave it out.</p>${plan.groups.map(cleanupGroupHtml).join("")}`
            : `<p class="muted">Nothing to clean up.</p>`;
    } else if (data.log && !busy) {
        host.innerHTML = `<pre class="log-box">${escapeHtml(data.log)}</pre>`;
    } else if (!busy) {
        host.innerHTML = "";
    }
    renderCleanupConfirm();
}

async function confirmCleanup() {
    const data = state.cleanup.data || {};
    state.cleanup.data = await api("/api/v1/cleanup/run", { method: "POST", body: { token: data.token, skip_groups: [...state.cleanup.skip] } });
    renderCleanup();
    pollCleanup();
}

function onCleanupAction(name) {
    if (name === "cleanup-open") return runAction(openCleanup);
    if (name === "cleanup-preview") return runAction(previewCleanup, "Comparing copies…");
    if (name === "cleanup-confirm") return runAction(confirmCleanup, "Deleting…");
    return false;
}

document.addEventListener("change", (event) => {
    const target = event.target;
    if (!target) return;
    if (target.dataset && target.dataset.cleanupGroup) {
        if (target.checked) state.cleanup.skip.delete(target.dataset.cleanupGroup);
        else state.cleanup.skip.add(target.dataset.cleanupGroup);
        renderCleanupConfirm();
    } else if (target.id === "cleanup-understood") {
        renderCleanupConfirm();
    }
});
