// Music videos: the Music videos tab. A list with filters, scans, quality badges, damage checks, duplicates and an editor.

state.musicVideos = { items: [], scan: null, filter: "", corruptOnly: false, duplicatesOnly: false, editing: "", timer: 0, loaded: false };

// The tab, the header icon and the Tools menu all lead here.
async function openMusicVideos() {
    if (state.media !== "musicvideos") switchMedia("musicvideos");     // switching loads the list
    else await loadMusicVideos();
}

function renderMusicVideoStage() {
    if (state.musicVideos.loaded) renderMusicVideos();
    loadMusicVideos().catch((error) => notify(error.message, "error"));     // a scan may have run since the tab was last shown
    renderMusicVideoEditor();
}

async function loadMusicVideos() {
    const data = await api("/api/v1/musicvideos");
    state.musicVideos.items = data.items || [];
    state.musicVideos.scan = data.scan || null;
    state.musicVideos.loaded = true;
    renderMusicVideos();
    if ((data.scan || {}).status === "running") pollMusicVideoScan();
}

async function startMusicVideoScan(mode) {
    state.musicVideos.scan = await api("/api/v1/musicvideos/scan", { method: "POST", body: { mode } });
    state.musicVideos.wasRunning = true;
    renderMusicVideos();
    pollMusicVideoScan();
}

async function pollMusicVideoScan() {
    clearTimeout(state.musicVideos.timer);
    const scan = await api("/api/v1/musicvideos/scan");
    state.musicVideos.scan = scan;
    if (scan.status === "running") {
        renderMusicVideoStatus();
        state.musicVideos.timer = setTimeout(() => pollMusicVideoScan().catch(() => {}), 1500);
        return;
    }
    if (state.musicVideos.wasRunning) {
        state.musicVideos.wasRunning = false;
        notify(scan.message || "Music video scan finished.", scan.status === "failed" ? "error" : "info");
        await loadMusicVideos();
    }
}

async function writeMusicVideoNfos() {
    const data = await api("/api/v1/musicvideos/nfo", { method: "POST", body: { ids: [] } });
    notify(`${Number(data.written) || 0} .nfo file${Number(data.written) === 1 ? "" : "s"} written.`, "success");
}

// What the filters leave: the text boxes' words, and the Duplicates only and Corrupt only boxes.
function musicVideosShown() {
    const { items, filter, corruptOnly, duplicatesOnly } = state.musicVideos;
    const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
    return items.filter((item) => {
        if (corruptOnly && !(item.health || []).includes("corrupt")) return false;
        if (duplicatesOnly && !item.duplicate && !item.upgrade) return false;
        const text = `${item.artist} ${item.title} ${item.album} ${item.year || ""}`.toLowerCase();
        return words.every((word) => text.includes(word));
    });
}

function renderMusicVideoStatus() {
    const status = document.getElementById("musicvideos-status");
    const scan = state.musicVideos.scan || {};
    if (!status) return;
    const running = scan.status === "running";
    status.className = `scan-status ${running ? "is-running" : scan.status === "failed" ? "is-failed" : ""}`;
    const progress = running && scan.total ? ` (${scan.processed || 0}/${scan.total})` : "";
    const total = state.musicVideos.items.length;
    const shown = musicVideosShown().length;
    keepText(status, `${scan.message || `${total} music videos.`}${progress}${shown !== total ? ` Showing ${shown} of ${total}.` : ""}`);
}

function renderMusicVideos() {
    renderMusicVideoStatus();
    const host = document.getElementById("musicvideos-list");
    if (!host) return;
    const rows = musicVideosShown();
    if (!state.musicVideos.items.length) {
        host.innerHTML = `<p class="muted">No music videos yet. Add a folder with the media type Music videos under Settings, General, then press Scan.</p>`;
        return;
    }
    if (!rows.length) {
        host.innerHTML = `<p class="muted">Nothing matches these filters. <button type="button" class="link" data-action="musicvideos-filters-clear">Clear filters</button></p>`;
        return;
    }
    host.innerHTML = `<table class="queue-table"><thead><tr><th></th><th>Artist</th><th>Title</th><th>Year</th><th>Quality</th><th>.nfo</th><th></th></tr></thead><tbody>${rows.map((item) => `<tr${item.id === state.musicVideos.editing ? ' class="is-selected"' : ""}>
            <td class="queue-fit">${item.thumb_path ? `<img class="mv-thumb" src="/api/v1/musicvideos/${encodeURIComponent(item.id)}/thumb" alt="" loading="lazy">` : ""}</td>
            <td>${escapeHtml(item.artist || "")}</td>
            <td><strong>${escapeHtml(item.title || "")}</strong>${item.album ? ` <small class="muted">${escapeHtml(item.album)}</small>` : ""}<br><small class="mono muted">${escapeHtml(item.path || "")}</small></td>
            <td class="queue-fit">${escapeHtml(item.year ? String(item.year) : "")}</td>
            <td><span class="queue-quality">${queueQualityBadges({ kind: "video", ...item })}</span>${typeof healthPill === "function" ? healthPill(item) : ""}${musicVideoDuplicatePill(item)}</td>
            <td class="queue-fit">${item.nfo_path ? "Yes" : "No"}</td>
            <td class="queue-fit"><button type="button" class="btn-ghost" data-action="musicvideos-edit" data-id="${escapeHtml(item.id)}">Edit</button></td>
        </tr>`).join("")}</tbody></table>`;
}

// The same rules as movies: Duplicate for copies of the same release, Upgrade available when a better file exists.
function musicVideoDuplicatePill(item) {
    const key = escapeHtml(`${item.artist} ${item.title}`);
    let pills = "";
    if (item.duplicate) {
        const copies = Number(item.copies) || 2;
        pills += ` <button type="button" class="tag-pill duplicate-pill" data-action="musicvideos-dups" data-key="${key}" data-id="${escapeHtml(item.id)}" title="${copies} copies of the same release. Click to compare them.">Duplicate</button>`;
    }
    if (item.upgrade) {
        const better = item.upgrade_path ? ` A better copy: ${item.upgrade_path}` : "";
        pills += ` <button type="button" class="tag-pill upgrade-pill" data-action="musicvideos-dups" data-key="${key}" data-id="${escapeHtml(item.id)}" title="${escapeHtml(`A better copy of this video is in the library.${better} Click to compare the copies.`)}">Upgrade available</button>`;
    }
    return pills;
}

function renderMusicVideoEditor() {
    const host = document.getElementById("musicvideos-detail");
    if (!host) return;
    const item = state.musicVideos.items.find((row) => row.id === state.musicVideos.editing);
    if (!item) {
        host.innerHTML = `<p class="muted">Pick Edit on a music video to change its details.</p>`;
        return;
    }
    const field = (key, label, value) => `<label class="field">${label} <input data-mv-field="${key}" type="text" value="${escapeHtml(value == null ? "" : String(value))}"></label>`;
    host.innerHTML = `<div class="ins-card ins-wide">
        ${item.thumb_path ? `<img class="mv-thumb-large" src="/api/v1/musicvideos/${encodeURIComponent(item.id)}/thumb?t=${Date.now()}" alt="">` : ""}
        ${field("artist", "Artist", item.artist)}${field("title", "Title", item.title)}${field("album", "Album", item.album)}
        ${field("year", "Year", item.year)}${field("director", "Director", item.director)}${field("genres", "Genres (comma between)", (item.genres || []).join(", "))}
        <label class="field">Plot <textarea data-mv-field="plot" rows="3">${escapeHtml(item.plot || "")}</textarea></label>
        <label class="choice"><input type="checkbox" id="mv-locked" ${item.locked ? "checked" : ""}> Locked (scans, lookups and the cleanup keep these values)</label>
        <small class="mono muted">${escapeHtml(item.path || "")}</small>
        <p>
            <button type="button" data-action="musicvideos-save" data-id="${escapeHtml(item.id)}">Save</button>
            <button type="button" class="btn-ghost" data-action="musicvideos-thumb" data-id="${escapeHtml(item.id)}">Take a picture from the video</button>
            <button type="button" class="btn-ghost" data-action="musicvideos-check-one" data-id="${escapeHtml(item.id)}">Quick integrity check</button>
            <button type="button" class="btn-ghost" data-action="musicvideos-close">Close</button>
            <button type="button" class="btn-ghost btn-remove" data-action="musicvideos-delete" data-id="${escapeHtml(item.id)}">Remove or delete…</button>
        </p>
    </div>`;
}

async function saveMusicVideo(id) {
    const fields = {};
    document.querySelectorAll("[data-mv-field]").forEach((node) => { fields[node.dataset.mvField] = node.value; });
    const locked = !!(document.getElementById("mv-locked") || {}).checked;
    await api(`/api/v1/musicvideos/${encodeURIComponent(id)}`, { method: "POST", body: { fields, locked } });
    notify("Saved, and the .nfo was rewritten.", "success");
    await loadMusicVideos();
    renderMusicVideoEditor();
}

async function thumbMusicVideo(id) {
    await api(`/api/v1/musicvideos/${encodeURIComponent(id)}/thumb`, { method: "POST", body: {} });
    await loadMusicVideos();
    renderMusicVideoEditor();
}

// The same window as for movies and episodes: Delete from disk (to the recycle bin), or Remove from library only.
function deleteMusicVideoAsk(id) {
    const item = state.musicVideos.items.find((row) => row.id === id) || {};
    const done = async () => {
        state.musicVideos.editing = "";
        await loadMusicVideos();
        renderMusicVideoEditor();
        refreshMusicVideoCompare();
    };
    askDanger(`Delete ${item.title || "this music video"}?`, item.path || "", "Delete from disk", async () => {
        const data = await api("/api/v1/musicvideos/delete", { method: "POST", body: { ids: [id] } });
        if ((data.errors || []).length) throw new Error(data.errors[0]);
        await done();
    }, true, async () => {
        await api("/api/v1/musicvideos/remove", { method: "POST", body: { ids: [id] } });
        notify("Removed from the library. The file is still on disk, and the next scan adds it back.", "info");
        await done();
    }, true);
}

function removeMusicVideoAsk(id) {
    const item = state.musicVideos.items.find((row) => row.id === id) || {};
    askDanger(`Remove ${item.title || "this music video"} from the library?`, `${item.path || ""} The file stays on disk, and the next scan adds it back.`,
        "Remove from library", async () => {
            await api("/api/v1/musicvideos/remove", { method: "POST", body: { ids: [id] } });
            state.musicVideos.editing = "";
            await loadMusicVideos();
            renderMusicVideoEditor();
            refreshMusicVideoCompare();
        }, false);
}

// The compare window behind a music video's Duplicate or Upgrade pill: the shared Duplicates window (renderDuplicateList).
function musicVideoKey(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function musicVideoCopies(id) {
    const items = state.musicVideos.items || [];
    const focus = items.find((item) => item.id === id);
    if (!focus) return { focus: null, copies: [] };
    const key = `${musicVideoKey(focus.artist)}|${musicVideoKey(focus.title)}`;
    return { focus, copies: items.filter((item) => `${musicVideoKey(item.artist)}|${musicVideoKey(item.title)}` === key) };
}

function musicVideoCompareHtml(copies) {
    const best = [...copies].sort((a, b) => (Number(b.height) || 0) - (Number(a.height) || 0)
        || (Number(b.size_bytes) || 0) - (Number(a.size_bytes) || 0))[0] || {};
    const cards = copies.map((item) => compareCardHtml({
        id: item.id,
        picture: item.thumb_path
            ? `<img class="upgrade-cover video-dup-thumb" src="/api/v1/musicvideos/${encodeURIComponent(item.id)}/thumb" alt="">`
            : `<div class="art-fallback upgrade-cover video-dup-thumb">No picture</div>`,
        name: String(item.path || "").split("/").pop() || item.title || "Copy",
        lines: [
            `<span class="queue-quality">${queueQualityBadges({ kind: "video", ...item })}</span>`,
            escapeHtml([item.video_codec, item.audio_main, item.duration_seconds ? fmtDuration(item.duration_seconds) : "", item.size_bytes ? fmtSize(item.size_bytes) : ""].filter(Boolean).join(" · ")),
            escapeHtml([item.duplicate ? "Duplicate" : "", item.upgrade ? "Upgrade available" : "", item.locked ? "Locked" : ""].filter(Boolean).join(" · ")),
        ],
        keep: copies.length > 1 && item.id === best.id,
        path: item.path || "",
        del: `data-action="musicvideos-delete" data-id="${escapeHtml(item.id)}"`,
        remove: `data-action="musicvideos-remove" data-id="${escapeHtml(item.id)}"`,
    })).join("");
    return compareGroupHtml({
        reason: "Copies of one music video: the same artist and title. Duplicates are the same release (source, resolution and about the same size); a weaker copy shows Upgrade available. Lock a copy to keep the duplicate cleanup away from it.",
        cards,
    });
}

function refreshMusicVideoCompare() {
    const modal = document.getElementById("duplicates-modal");
    if (!modal || modal.classList.contains("hidden") || !state.duplicateFocus || state.duplicateFocus.media !== "musicvideos") return;
    renderDuplicateList({ pairs: [] }, null);
}

async function lookupMusicVideos() {
    state.musicVideos.scan = await api("/api/v1/musicvideos/lookup", { method: "POST", body: {} });
    state.musicVideos.wasRunning = true;
    renderMusicVideos();
    pollMusicVideoScan();
}

// The damage check runs as a file job, in the same window as for movies and episodes.
function checkMusicVideos(ids, full) {
    if (!ids.length) {
        notify("No music video is shown.", "info");
        return;
    }
    return openVideoFiles(full ? "integrity_full" : "integrity", { kind: "musicvideo", ids });
}

function onMusicVideoAction(name, action) {
    if (name === "musicvideos-scan") return runAction(() => startMusicVideoScan(action.dataset.mode || "incremental"));
    if (name === "musicvideos-nfo") return runAction(writeMusicVideoNfos, "Writing .nfo files…");
    if (name === "musicvideos-lookup") return runAction(lookupMusicVideos);
    if (name === "musicvideos-check") return runAction(() => checkMusicVideos(musicVideosShown().map((item) => item.id), false));
    if (name === "musicvideos-check-full") return runAction(() => checkMusicVideos(musicVideosShown().map((item) => item.id), true));
    if (name === "musicvideos-check-one") return runAction(() => checkMusicVideos([action.dataset.id], false));
    if (name === "musicvideos-filters-clear") {
        Object.assign(state.musicVideos, { filter: "", duplicatesOnly: false, corruptOnly: false });
        ["musicvideos-filter", "musicvideos-dupes", "musicvideos-corrupt"].forEach((id) => {
            const node = document.getElementById(id);
            if (node && node.type === "checkbox") node.checked = false;
            else if (node) node.value = "";
        });
        return renderMusicVideos();
    }
    if (name === "musicvideos-dups") return runAction(() => openDuplicates({ media: "musicvideos", id: action.dataset.id }));
    if (name === "musicvideos-remove") return removeMusicVideoAsk(action.dataset.id);
    if (name === "musicvideos-edit") {
        state.musicVideos.editing = action.dataset.id;
        renderMusicVideos();
        return renderMusicVideoEditor();
    }
    if (name === "musicvideos-close") {
        state.musicVideos.editing = "";
        renderMusicVideos();
        return renderMusicVideoEditor();
    }
    if (name === "musicvideos-save") return runAction(() => saveMusicVideo(action.dataset.id), "Saving…");
    if (name === "musicvideos-thumb") return runAction(() => thumbMusicVideo(action.dataset.id), "Taking a picture…");
    if (name === "musicvideos-delete") return deleteMusicVideoAsk(action.dataset.id);
    return false;
}

document.addEventListener("input", (event) => {
    if (event.target && event.target.id === "musicvideos-filter") {
        state.musicVideos.filter = event.target.value || "";
        renderMusicVideos();
    }
});

document.addEventListener("change", (event) => {
    const target = event.target;
    if (!target) return;
    if (target.id === "musicvideos-dupes") state.musicVideos.duplicatesOnly = !!target.checked;
    else if (target.id === "musicvideos-corrupt") state.musicVideos.corruptOnly = !!target.checked;
    else return;
    renderMusicVideos();
});
