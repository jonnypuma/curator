// The recycle bin window: what Delete from disk moved aside, with Restore, Delete now and Empty.

async function openTrash() {
    const modal = document.getElementById("trash-modal");
    if (!modal) return;
    modal.classList.remove("hidden");
    await loadTrash();
}

async function loadTrash() {
    const host = document.getElementById("trash-list");
    const summary = document.getElementById("trash-summary");
    if (!host) return;
    host.innerHTML = `<p class="muted">Loading…</p>`;
    const data = await api("/api/v1/trash");
    state.trash = data;
    const items = data.items || [];
    if (summary) {
        const when = data.enabled ? `Items are deleted for good after ${data.days} day${data.days === 1 ? "" : "s"}.` : "The recycle bin is off: Delete from disk deletes at once.";
        summary.textContent = items.length ? `${items.length} item${items.length === 1 ? "" : "s"}, ${fmtSize(data.size_bytes)}. ${when}` : when;
    }
    const empty = document.getElementById("trash-empty");
    if (empty) empty.disabled = !items.length;
    if (!items.length) {
        host.innerHTML = `<p class="muted">The recycle bin is empty.</p>`;
        return;
    }
    host.innerHTML = `<table class="queue-table trash-table"><thead><tr><th>Item</th><th>Deleted</th><th>Gone for good</th><th>Size</th><th></th></tr></thead><tbody>${items.map(trashRow).join("")}</tbody></table>`;
}

function trashRow(item) {
    const missing = item.present === false ? `<br><small class="muted">No longer in the bin folder</small>` : "";
    const kind = item.kind ? `<small class="muted">${escapeHtml(item.kind)}${item.is_dir ? " folder" : ""}</small> ` : "";
    return `<tr data-trash-id="${escapeHtml(item.id)}">
        <td>${kind}<strong>${escapeHtml(item.label || "")}</strong><br><small class="mono muted">${escapeHtml(item.original_path || "")}</small>${missing}</td>
        <td class="queue-fit">${escapeHtml(fmtDate(item.deleted_at))}</td>
        <td class="queue-fit">${escapeHtml(fmtDate(item.expires_at))}</td>
        <td class="queue-fit">${escapeHtml(fmtSize(item.size_bytes))}</td>
        <td class="queue-fit">
            <button type="button" class="btn-ghost" data-action="trash-restore" data-id="${escapeHtml(item.id)}">Restore</button>
            <button type="button" class="btn-ghost btn-remove" data-action="trash-delete" data-id="${escapeHtml(item.id)}">Delete now</button>
        </td>
    </tr>`;
}

async function restoreTrash(id) {
    const data = await api("/api/v1/trash/restore", { method: "POST", body: { ids: [id] } });
    const restored = data.restored || [];
    const errors = data.errors || [];
    if (restored.length) notify(`Restored ${restored[0].split("/").pop()}.${data.queued ? " It is being scanned back into the library." : " Scan its folder to bring it back into the library."}`, "success");
    if (errors.length) notify(errors[0], "warning");
    await loadTrash();
}

function deleteTrashAsk(id) {
    const item = ((state.trash && state.trash.items) || []).find((row) => row.id === id) || {};
    askDanger(
        `Delete ${item.label || "this item"} for good?`,
        "It is removed from the recycle bin and from disk. This cannot be undone.",
        "Delete for good",
        async () => {
            await api("/api/v1/trash/delete", { method: "POST", body: { ids: [id] } });
            await loadTrash();
        },
        true,
    );
}

function emptyTrashAsk() {
    const count = ((state.trash && state.trash.items) || []).length;
    askDanger(
        "Empty the recycle bin?",
        `${count} item${count === 1 ? "" : "s"} will be deleted from disk for good. This cannot be undone.`,
        "Empty recycle bin",
        async () => {
            const data = await api("/api/v1/trash/empty", { method: "POST", body: {} });
            notify(`Deleted ${data.deleted || 0} item${data.deleted === 1 ? "" : "s"} for good.`, "info");
            await loadTrash();
        },
        true,
    );
}

function onTrashAction(name, action) {
    if (name === "trash-open") return runAction(openTrash);
    if (name === "trash-restore") return runAction(() => restoreTrash(action.dataset.id), "Restoring…");
    if (name === "trash-delete") return deleteTrashAsk(action.dataset.id);
    if (name === "trash-empty") return emptyTrashAsk();
    if (name === "trash-reload") return runAction(loadTrash);
}
