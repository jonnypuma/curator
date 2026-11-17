// The recycle bin window: what Delete from disk moved aside, with Restore, Delete now and Empty.

async function openTrash() {
    const modal = document.getElementById("trash-modal");
    if (!modal) return;
    modal.classList.remove("hidden");
    await loadTrash();
}

async function loadTrash() {
    const host = document.getElementById("trash-list");
    if (!host) return;
    host.innerHTML = `<p class="muted">Loading…</p>`;
    state.trash = await api("/api/v1/trash");
    state.trashPicked = new Set();
    renderTrash();
}

function trashItems() {
    return (state.trash && state.trash.items) || [];
}

function trashPicked() {
    if (!state.trashPicked) state.trashPicked = new Set();
    const known = new Set(trashItems().map((item) => item.id));
    for (const id of [...state.trashPicked]) if (!known.has(id)) state.trashPicked.delete(id);
    return state.trashPicked;
}

// Paint the list from what the page already holds. A restore or a delete takes its rows out of state.trash and
// calls this, so the bin is not read again and the list does not jump back to the top.
function renderTrash() {
    const host = document.getElementById("trash-list");
    const summary = document.getElementById("trash-summary");
    if (!host) return;
    const data = state.trash || {};
    const items = trashItems();
    const keep = host.querySelector(".trash-scroll") ? host.querySelector(".trash-scroll").scrollTop : 0;
    if (summary) {
        const size = items.reduce((total, item) => total + (Number(item.size_bytes) || 0), 0);
        const when = data.enabled ? `Items are deleted for good after ${data.days} day${data.days === 1 ? "" : "s"}.` : "The recycle bin is off: Delete from disk deletes at once.";
        summary.textContent = items.length ? `${items.length} item${items.length === 1 ? "" : "s"}, ${fmtSize(size)}. ${when}` : when;
    }
    const empty = document.getElementById("trash-empty");
    if (empty) empty.disabled = !items.length;
    host.innerHTML = items.length
        ? `<div class="trash-scroll"><table class="queue-table trash-table"><thead><tr><th class="queue-fit"><input type="checkbox" id="trash-tick-all" aria-label="Select all" title="Select or deselect all"></th><th>Item</th><th>Deleted</th><th>Gone for good</th><th>Size</th><th></th></tr></thead><tbody>${items.map(trashRow).join("")}</tbody></table></div>`
        : `<p class="muted">The recycle bin is empty.</p>`;
    const scroll = host.querySelector(".trash-scroll");
    if (scroll) scroll.scrollTop = keep;
    paintTrashPicked();
}

function trashRow(item) {
    const missing = item.present === false ? `<br><small class="muted">No longer in the bin folder</small>` : "";
    const kind = item.kind ? `<small class="muted">${escapeHtml(item.kind)}${item.is_dir ? " folder" : ""}</small> ` : "";
    const on = trashPicked().has(item.id);
    return `<tr data-trash-id="${escapeHtml(item.id)}"${on ? ` class="is-picked"` : ""}>
        <td class="queue-fit"><input type="checkbox" class="trash-tick" data-id="${escapeHtml(item.id)}" aria-label="Select ${escapeHtml(item.label || "item")}" ${on ? "checked" : ""}></td>
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

// The buttons that work on the ticked rows, their count, and the master box. Touches no row, so ticking is instant.
function paintTrashPicked() {
    const picked = trashPicked();
    const total = trashItems().length;
    const count = picked.size;
    const blob = count ? ` <span class="album-count trash-count">${count}</span>` : "";
    const remove = document.getElementById("trash-delete-picked");
    if (remove) {
        remove.disabled = !count;
        remove.innerHTML = `Delete selected${blob}`;
    }
    const restore = document.getElementById("trash-restore-picked");
    if (restore) {
        restore.disabled = !count;
        restore.innerHTML = `Restore selected${blob}`;
    }
    const toggle = document.getElementById("trash-pick-all");
    if (toggle) {
        toggle.disabled = !total;
        toggle.textContent = total && count === total ? "Deselect all" : "Select all";
    }
    const master = document.getElementById("trash-tick-all");
    if (master) {
        master.checked = total > 0 && count === total;
        master.indeterminate = count > 0 && count < total;
    }
}

function pickAllTrash(on) {
    const picked = trashPicked();
    const all = on === undefined ? picked.size !== trashItems().length : !!on;
    picked.clear();
    if (all) trashItems().forEach((item) => picked.add(item.id));
    document.querySelectorAll("#trash-list .trash-tick").forEach((box) => {
        box.checked = all;
        const row = box.closest("tr");
        if (row) row.classList.toggle("is-picked", all);
    });
    paintTrashPicked();
}

function dropTrashRows(ids) {
    const gone = new Set(ids);
    if (state.trash) state.trash.items = trashItems().filter((item) => !gone.has(item.id));
    renderTrash();
}

async function restoreTrash(ids) {
    const wanted = trashItems().filter((item) => ids.includes(item.id));
    const data = await api("/api/v1/trash/restore", { method: "POST", body: { ids } });
    const restored = data.restored || [];
    const errors = data.errors || [];
    if (restored.length) {
        const what = restored.length === 1 ? restored[0].split("/").pop() : `${restored.length} items`;
        notify(`Restored ${what}.${data.queued ? (restored.length === 1 ? " It is being scanned back into the library." : " They are being scanned back into the library.") : " Scan the folder to bring it back into the library."}`, "success");
    }
    if (errors.length) notify(errors.length === 1 ? errors[0] : `${errors[0]} (and ${errors.length - 1} more)`, "warning");
    const back = new Set(restored);
    dropTrashRows(wanted.filter((item) => back.has(item.original_path)).map((item) => item.id));
}

async function deleteTrash(ids) {
    const data = await api("/api/v1/trash/delete", { method: "POST", body: { ids } });
    const left = new Set(data.left || []);
    if (left.size) notify(`${left.size} item${left.size === 1 ? "" : "s"} could not be deleted and stay in the recycle bin.`, "warning");
    else if (ids.length > 1) notify(`Deleted ${data.deleted || 0} items for good.`, "info");
    dropTrashRows(ids.filter((id) => !left.has(id)));
}

function deleteTrashAsk(ids) {
    const items = trashItems().filter((item) => ids.includes(item.id));
    if (!items.length) return;
    const size = fmtSize(items.reduce((total, item) => total + (Number(item.size_bytes) || 0), 0));
    askDanger(
        items.length === 1 ? `Delete ${items[0].label || "this item"} for good?` : `Delete ${items.length} selected items for good?`,
        items.length === 1
            ? "It is removed from the recycle bin and from disk. This cannot be undone."
            : `They are removed from the recycle bin and from disk${size ? ` (${size})` : ""}. This cannot be undone.`,
        "Delete for good",
        () => deleteTrash(items.map((item) => item.id)),
        true,
    );
}

function emptyTrashAsk() {
    const count = trashItems().length;
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
    if (name === "trash-restore") return runAction(() => restoreTrash([action.dataset.id]), "Restoring…");
    if (name === "trash-delete") return deleteTrashAsk([action.dataset.id]);
    if (name === "trash-pick-all") return pickAllTrash();
    if (name === "trash-delete-picked") return deleteTrashAsk([...trashPicked()]);
    if (name === "trash-restore-picked") return runAction(() => restoreTrash([...trashPicked()]), "Restoring…");
    if (name === "trash-empty") return emptyTrashAsk();
    if (name === "trash-reload") return runAction(loadTrash);
}

document.addEventListener("change", (event) => {
    const box = event.target;
    if (!box || !box.classList) return;
    if (box.id === "trash-tick-all") return pickAllTrash(box.checked);
    if (!box.classList.contains("trash-tick")) return;
    const picked = trashPicked();
    if (box.checked) picked.add(box.dataset.id);
    else picked.delete(box.dataset.id);
    const row = box.closest("tr");
    if (row) row.classList.toggle("is-picked", box.checked);
    paintTrashPicked();
});
