// The disk space dashboard: free space per library folder, growth over time, and the copies that could be freed.

state.disk = { data: null };

const DISK_KIND_NAMES = { movies: "Movies", tv: "TV shows", music: "Music", musicvideos: "Music videos" };
const DISK_REASONS = { upgrade: "A better copy exists", duplicate: "Duplicate", "extra copy": "Extra file of the episode" };

async function openDisk() {
    document.getElementById("disk-modal").classList.remove("hidden");
    document.getElementById("disk-body").innerHTML = `<p class="muted">Measuring…</p>`;
    state.disk.data = await api("/api/v1/disk");
    renderDisk();
}

function diskBar(row) {
    const total = Number(row.total_bytes) || 0;
    if (!total) return `<p class="muted">The drive size could not be read.</p>`;
    const free = Number(row.free_bytes) || 0;
    const library = Math.min(Number(row.library_bytes) || 0, total - free);
    const other = Math.max(0, total - free - library);
    const pct = (value) => `${((value / total) * 100).toFixed(2)}%`;
    return `<div class="disk-bar" role="img" aria-label="${escapeHtml(`${fmtSize(free)} free of ${fmtSize(total)}`)}">
            <span class="disk-lib" style="width:${pct(library)}" title="Library ${escapeHtml(fmtSize(library))}"></span>
            <span class="disk-other" style="width:${pct(other)}" title="Other files ${escapeHtml(fmtSize(other))}"></span>
        </div>
        <p class="muted">${escapeHtml(fmtSize(free))} free of ${escapeHtml(fmtSize(total))} · library ${escapeHtml(fmtSize(library))} · other files ${escapeHtml(fmtSize(other))}${Number(row.trash_bytes) ? ` · recycle bin ${escapeHtml(fmtSize(row.trash_bytes))}` : ""}</p>${row.low ? `<p class="danger-warn">This drive is under the free space limit set in Settings, General.</p>` : ""}`;
}

function diskGrowth(history, root) {
    const points = history.filter((row) => row.root === root);
    if (points.length < 2) return `<p class="muted">Growth shows after Curator has measured this folder on two days.</p>`;
    const width = 560;
    const height = 120;
    const values = points.flatMap((row) => [Number(row.library_bytes) || 0, Number(row.free_bytes) || 0]);
    const max = Math.max(1, ...values);
    const x = (index) => (index / (points.length - 1)) * (width - 8) + 4;
    const y = (value) => height - 6 - (value / max) * (height - 12);
    const line = (key) => points.map((row, index) => `${x(index).toFixed(1)},${y(Number(row[key]) || 0).toFixed(1)}`).join(" ");
    const first = points[0];
    const last = points[points.length - 1];
    const grown = (Number(last.library_bytes) || 0) - (Number(first.library_bytes) || 0);
    return `<svg class="disk-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Library size and free space over time">
            <polyline class="disk-line-lib" points="${line("library_bytes")}" />
            <polyline class="disk-line-free" points="${line("free_bytes")}" />
        </svg>
        <p class="muted"><span class="disk-key disk-key-lib"></span> Library <span class="disk-key disk-key-free"></span> Free space · ${escapeHtml(fmtDate(first.day))} to ${escapeHtml(fmtDate(last.day))}: library ${grown >= 0 ? "grew" : "shrank"} by ${escapeHtml(fmtSize(Math.abs(grown)))}</p>`;
}

function diskSavingsHtml(savings) {
    if (!savings || !savings.count) return `<p class="muted">No duplicate, upgrade or extra copies are marked. Nothing to free there.</p>`;
    const folders = (savings.folders || []).map((entry) => `<tr>
            <td><small class="mono">${escapeHtml(entry.folder)}</small></td>
            <td class="queue-fit">${entry.count}</td>
            <td class="queue-fit">${escapeHtml(fmtSize(entry.size_bytes))}</td>
        </tr>`).join("");
    const items = (savings.items || []).map((item, index) => {
        const remove = `<button type="button" class="btn-ghost btn-remove" data-action="disk-delete" data-index="${index}">Delete…</button>`;
        return `<tr>
            <td><strong>${escapeHtml(item.label || "")}</strong> <small class="muted">${escapeHtml(DISK_REASONS[item.reason] || item.reason)}</small><br><small class="mono muted">${escapeHtml(item.path || "")}</small></td>
            <td class="queue-fit">${escapeHtml(fmtSize(item.size_bytes))}</td>
            <td class="queue-fit">${remove}</td>
        </tr>`;
    }).join("");
    return `<p>${savings.count.toLocaleString()} weaker copies hold ${escapeHtml(fmtSize(savings.total_bytes))}.</p>
        <h4>Folders that would free the most</h4>
        <table class="queue-table"><thead><tr><th>Folder</th><th>Copies</th><th>Size</th></tr></thead><tbody>${folders}</tbody></table>
        <h4>Biggest copies</h4>
        <table class="queue-table"><tbody>${items}</tbody></table>`;
}

function renderDisk() {
    const data = state.disk.data || {};
    const history = data.history || [];
    const cards = (data.folders || []).map((row) => `<div class="ins-card ins-wide">
            <h3>${escapeHtml(DISK_KIND_NAMES[row.kind] || row.kind)} <small class="mono muted">${escapeHtml(row.root)}</small></h3>
            ${diskBar(row)}
            ${diskGrowth(history, row.root)}
        </div>`).join("");
    document.getElementById("disk-body").innerHTML = `${cards || `<p class="muted">No library folder is mounted.</p>`}
        <div class="ins-card ins-wide"><h3>Could be freed</h3>${diskSavingsHtml(data.savings)}</div>`;
}

function deleteDiskCopyAsk(index) {
    const item = (((state.disk.data || {}).savings || {}).items || [])[Number(index)];
    if (!item) return;
    askDanger(
        `Delete ${item.label || "this copy"}?`,
        item.path,
        "Delete from disk",
        async () => {
            if (item.kind === "album") {
                await api(`/api/albums/${encodeURIComponent(item.id)}/delete`, { method: "POST", body: {} });
            } else {
                const result = await api("/api/v1/delete", { method: "POST", body: { kind: item.kind, ids: [item.id], keep_copy: true } });
                if ((result.errors || []).length) throw new Error(result.errors[0]);
            }
            notify(`Deleted ${item.label}.`, "success");
            await openDisk();
        },
        true,
        null,
        true,
    );
}

function onDiskAction(name, action) {
    if (name === "disk-open") return runAction(openDisk, "Measuring…");
    if (name === "disk-delete") return deleteDiskCopyAsk(action.dataset.index);
    return false;
}
