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

// What the search box, the type choice and the clicked column heading leave, in that order.
const TRASH_KINDS = { video: "Video", episode: "Episode", set: "Movie set", musicvideo: "Music video", album: "Album",
    artist: "Artist", track: "Track", artwork: "Artwork", subtitle: "Subtitle", orphan: "Orphan file" };
const TRASH_SORTS = {
    item: (item) => String(item.label || "").toLowerCase(),
    kind: (item) => String(TRASH_KINDS[item.kind] || item.kind || "").toLowerCase(),
    reason: (item) => String(item.reason || "").toLowerCase(),
    deleted: (item) => String(item.deleted_at || ""),
    size: (item) => Number(item.size_bytes) || 0,
};

function trashView() {
    if (!state.trashView) state.trashView = { search: "", kind: "", sort: "deleted", down: true };
    return state.trashView;
}

function trashShown() {
    const view = trashView();
    const words = view.search.toLowerCase().split(/\s+/).filter(Boolean);
    const rows = trashItems().filter((item) => {
        if (view.kind && (item.kind || "") !== view.kind) return false;
        const text = `${item.label || ""} ${item.original_path || ""} ${item.reason || ""} ${TRASH_KINDS[item.kind] || item.kind || ""}`.toLowerCase();
        return words.every((word) => text.includes(word));
    });
    const key = TRASH_SORTS[view.sort] || TRASH_SORTS.deleted;
    const way = view.down ? -1 : 1;
    return rows.map((item, index) => [key(item), index, item])
        .sort((a, b) => (a[0] < b[0] ? -way : a[0] > b[0] ? way : a[1] - b[1]))
        .map((entry) => entry[2]);
}

function trashHeading(key, label) {
    const view = trashView();
    const mark = view.sort === key ? (view.down ? " ▼" : " ▲") : "";
    return `<th><button type="button" class="link trash-sort" data-action="trash-sort" data-sort="${key}" title="Sort by ${escapeHtml(label.toLowerCase())}">${escapeHtml(label)}${mark}</button></th>`;
}

function sortTrash(key) {
    const view = trashView();
    if (view.sort === key) view.down = !view.down;
    else Object.assign(view, { sort: key, down: key === "size" || key === "deleted" });
    renderTrash();
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
    const shown = trashShown();
    if (summary && items.length && shown.length !== items.length) {
        const part = shown.reduce((total, item) => total + (Number(item.size_bytes) || 0), 0);
        summary.textContent += ` Showing ${shown.length} of ${items.length} (${fmtSize(part) || "0 MB"}).`;
    }
    const kinds = document.getElementById("trash-kind");
    if (kinds) {
        const found = [...new Set(items.map((item) => item.kind || ""))].filter(Boolean).sort();
        const chosen = trashView().kind;
        kinds.innerHTML = `<option value="">All types</option>${found.map((kind) => `<option value="${escapeHtml(kind)}" ${kind === chosen ? "selected" : ""}>${escapeHtml(TRASH_KINDS[kind] || kind)}</option>`).join("")}`;
    }
    host.innerHTML = !items.length
        ? `<p class="muted">The recycle bin is empty.</p>`
        : !shown.length
            ? `<p class="muted">Nothing in the recycle bin matches the search and the type.</p>`
            : `<div class="trash-scroll"><table class="queue-table trash-table"><thead><tr><th class="queue-fit"><input type="checkbox" id="trash-tick-all" aria-label="Select all" title="Select or deselect all that are shown"></th>${trashHeading("item", "Item")}${trashHeading("kind", "Type")}${trashHeading("reason", "Why")}${trashHeading("deleted", "Deleted")}<th>Gone for good</th>${trashHeading("size", "Size")}<th></th></tr></thead><tbody>${shown.map(trashRow).join("")}</tbody></table></div>`;
    const scroll = host.querySelector(".trash-scroll");
    if (scroll) scroll.scrollTop = keep;
    paintTrashPicked();
}

function trashRow(item) {
    const missing = item.present === false ? `<br><small class="muted">No longer in the bin folder</small>` : "";
    const type = `${TRASH_KINDS[item.kind] || item.kind || ""}${item.is_dir ? " folder" : ""}`;
    const why = item.reason ? escapeHtml(item.reason) : `<span class="muted" title="Deleted before Curator kept the reason with the item, and Activity history has none for it.">Not recorded</span>`;
    const on = trashPicked().has(item.id);
    return `<tr data-trash-id="${escapeHtml(item.id)}"${on ? ` class="is-picked"` : ""}>
        <td class="queue-fit"><input type="checkbox" class="trash-tick" data-id="${escapeHtml(item.id)}" aria-label="Select ${escapeHtml(item.label || "item")}" ${on ? "checked" : ""}></td>
        <td><strong>${escapeHtml(item.label || "")}</strong><br><small class="mono muted">${escapeHtml(item.original_path || "")}</small>${missing}</td>
        <td class="queue-fit">${escapeHtml(type)}</td>
        <td class="trash-why">${why}</td>
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
    const shownIds = trashShown().map((item) => item.id);
    const total = shownIds.length;
    const count = picked.size;
    const shownPicked = shownIds.filter((id) => picked.has(id)).length;
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
        toggle.textContent = total && shownPicked === total ? "Deselect all" : "Select all";
    }
    const master = document.getElementById("trash-tick-all");
    if (master) {
        master.checked = total > 0 && shownPicked === total;
        master.indeterminate = shownPicked > 0 && shownPicked < total;
    }
}

function pickAllTrash(on) {
    const picked = trashPicked();
    const shown = trashShown();
    const all = on === undefined ? !shown.every((item) => picked.has(item.id)) : !!on;
    // Only the rows the search and type leave: what is hidden keeps its tick or its blank.
    shown.forEach((item) => (all ? picked.add(item.id) : picked.delete(item.id)));
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
    if (name === "trash-sort") return sortTrash(action.dataset.sort);
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

document.addEventListener("input", (event) => {
    if (!event.target || event.target.id !== "trash-search") return;
    trashView().search = event.target.value || "";
    renderTrash();
});

document.addEventListener("change", (event) => {
    if (!event.target || event.target.id !== "trash-kind") return;
    trashView().kind = event.target.value || "";
    renderTrash();
});

