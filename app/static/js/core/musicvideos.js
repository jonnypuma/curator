// Music videos: the Music videos tab. A list with filters, scans, quality badges, damage checks, duplicates and an editor.

state.musicVideos = { items: [], scan: null, filter: "", corruptOnly: false, duplicatesOnly: false, editing: "", timer: 0, loaded: false,
    ribbons: new Set(), checked: new Set() };

// The quick filters, as on the Movies and TV tabs: several can be on at once and they must all hold.
const MUSIC_VIDEO_RIBBONS = [
    ["no-nfo", "No NFO", (item) => !item.nfo_path],
    ["no-thumb", "No picture", (item) => !item.thumb_path],
    ["no-year", "No year", (item) => !item.year],
    ["no-album", "No album", (item) => !item.album],
    ["4k", "4K", (item) => Number(item.height) >= 2000],
    ["1080p", "1080p", (item) => Number(item.height) >= 1000 && Number(item.height) < 2000],
    ["sd", "Below 720p", (item) => Number(item.height) > 0 && Number(item.height) < 700],
    ["duplicate", "Duplicate", (item) => !!item.duplicate],
    ["upgrade", "Upgrade available", (item) => !!item.upgrade],
    ["corrupt", "Corrupt", (item) => (item.health || []).includes("corrupt")],
    ["locked", "Locked", (item) => !!item.locked],
];

function musicVideoRibbonsHtml() {
    const { items, ribbons } = state.musicVideos;
    const pills = MUSIC_VIDEO_RIBBONS.map(([key, label, test]) => {
        const count = items.reduce((sum, item) => sum + (test(item) ? 1 : 0), 0);
        const on = ribbons.has(key);
        return `<button type="button" class="vribbon${on ? " is-on" : ""}" data-action="musicvideos-ribbon" data-ribbon="${key}" aria-pressed="${on}" ${count || on ? "" : "disabled"}>${escapeHtml(label)} <small>${count}</small></button>`;
    }).join("");
    const clear = ribbons.size ? `<button type="button" class="btn-ghost vribbon-clear" data-action="musicvideos-filters-clear">Clear all</button>` : "";
    return `<div class="vribbons mv-ribbons">${pills}${clear}</div>`;
}

// The bar for the ticked music videos.
function musicVideoSelectionHtml() {
    const ids = [...state.musicVideos.checked].filter((id) => state.musicVideos.items.some((item) => item.id === id));
    if (!ids.length) return "";
    const rows = state.musicVideos.items.filter((item) => ids.includes(item.id));
    const allLocked = rows.every((item) => item.locked);
    const button = (action, label, cls = "btn-ghost") => `<button type="button" class="${cls}" data-action="${action}">${escapeHtml(label)}</button>`;
    return `<div class="art-bulk mv-selection"><span class="art-bulk-count">${ids.length} selected</span>
        ${button("musicvideos-sel-nfo", "Write .nfo")}${button("musicvideos-sel-rename", "Rename…")}
        ${button("musicvideos-sel-lock", allLocked ? "Unlock" : "Lock")}${button("musicvideos-sel-check", "Quick integrity check")}
        ${button("musicvideos-sel-delete", "Remove or delete…", "btn-danger")}${button("musicvideos-sel-clear", "Clear")}</div>`;
}

function musicVideoCheckedIds() {
    return [...state.musicVideos.checked].filter((id) => state.musicVideos.items.some((item) => item.id === id));
}

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
    state.musicVideos.roots = data.roots || [];
    state.musicVideos.loaded = true;
    paintMusicVideoAddButton();
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
    const { items, filter, corruptOnly, duplicatesOnly, ribbons } = state.musicVideos;
    const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
    const tests = MUSIC_VIDEO_RIBBONS.filter(([key]) => ribbons.has(key)).map(([, , test]) => test);
    return items.filter((item) => {
        if (!tests.every((test) => test(item))) return false;
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
        host.innerHTML = `${musicVideoRibbonsHtml()}<p class="muted">Nothing matches these filters. <button type="button" class="link" data-action="musicvideos-filters-clear">Clear filters</button></p>`;
        return;
    }
    const checked = state.musicVideos.checked;
    const allOn = rows.every((item) => checked.has(item.id));
    host.innerHTML = `${musicVideoRibbonsHtml()}${musicVideoSelectionHtml()}<table class="queue-table"><thead><tr><th class="queue-fit"><input type="checkbox" data-action="musicvideos-check-all" ${allOn ? "checked" : ""} aria-label="Select every music video shown" title="Select every music video shown"></th><th></th><th>Artist</th><th>Title</th><th>Year</th><th>Quality</th><th>.nfo</th><th></th></tr></thead><tbody>${rows.map((item) => `<tr${item.id === state.musicVideos.editing ? ' class="is-selected"' : ""}>
            <td class="queue-fit"><input type="checkbox" data-action="musicvideos-tick" data-id="${escapeHtml(item.id)}" ${checked.has(item.id) ? "checked" : ""} aria-label="Select ${escapeHtml(item.title || "music video")}"></td>
            <td class="queue-fit">${item.thumb_path ? `<img class="mv-thumb" src="/api/v1/musicvideos/${encodeURIComponent(item.id)}/thumb" alt="" loading="lazy">` : ""}</td>
            <td>${escapeHtml(item.artist || "")}</td>
            <td><strong>${escapeHtml(item.title || "")}</strong>${item.locked ? ` <span class="muted" title="Locked">${typeof lockIcon === "function" ? lockIcon(true) : "Locked"}</span>` : ""}${item.album ? ` <small class="muted">${escapeHtml(item.album)}</small>` : ""}<br><small class="mono muted">${escapeHtml(item.path || "")}</small></td>
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

// Several at once: the same two choices as for one, Delete from disk (to the recycle bin) or Remove from library only.
function deleteMusicVideosAsk(ids) {
    if (!ids.length) return;
    const done = async () => {
        state.musicVideos.checked.clear();
        state.musicVideos.editing = "";
        await loadMusicVideos();
        renderMusicVideoEditor();
    };
    askDanger(`Delete ${ids.length} music video${ids.length === 1 ? "" : "s"}?`, "The videos go to the recycle bin with their .nfo and pictures, unless the bin is off in Settings.",
        "Delete from disk", async () => {
            const data = await api("/api/v1/musicvideos/delete", { method: "POST", body: { ids } });
            if ((data.errors || []).length) notify(`${(data.deleted || []).length} deleted, ${data.errors.length} failed: ${data.errors[0]}`, "warning");
            await done();
        }, true, async () => {
            await api("/api/v1/musicvideos/remove", { method: "POST", body: { ids } });
            notify("Removed from the library. The files are still on disk, and the next scan adds them back.", "info");
            await done();
        }, true);
}

// Rename to "Artist - Title (Year)": shows what would change first, then renames after a yes.
async function renameMusicVideosAsk() {
    const ids = musicVideoCheckedIds();
    const { plan } = await api("/api/v1/musicvideos/rename", { method: "POST", body: { ids, preview: true } });
    const ready = (plan || []).filter((entry) => !entry.error);
    const blocked = (plan || []).filter((entry) => entry.error);
    if (!ready.length) {
        notify(blocked.length ? `Nothing can be renamed: ${blocked[0].error}.` : "These files are already named Artist - Title (Year).", "info");
        return;
    }
    const name = (path) => String(path || "").split(/[\\/]/).pop();
    const sample = ready.slice(0, 3).map((entry) => `${name(entry.from)} → ${name(entry.to)}`).join("; ");
    askDanger(`Rename ${ready.length} music video${ready.length === 1 ? "" : "s"}?`,
        `${sample}${ready.length > 3 ? `; and ${ready.length - 3} more` : ""}. The .nfo and pictures are renamed with the video.${blocked.length ? ` ${blocked.length} cannot be renamed and stay as they are.` : ""}`,
        "Rename", () => runAction(async () => {
            const data = await api("/api/v1/musicvideos/rename", { method: "POST", body: { ids: ready.map((entry) => entry.id) } });
            const failed = (data.errors || []).length;
            notify(`${(data.renamed || []).length} renamed${failed ? `, ${failed} failed: ${data.errors[0]}` : ""}.`, failed ? "warning" : "success");
            await loadMusicVideos();
        }, "Renaming…"), false);
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

// Add from YouTube: search, pick a result, confirm the names, download. One download at a time.
// + Add from YouTube has nowhere to save to until a Music videos folder is set, so it is off until then.
function paintMusicVideoAddButton() {
    const button = document.querySelector(`[data-action="musicvideos-add"]`);
    if (!button) return;
    const ready = (state.musicVideos.roots || []).length > 0;
    button.disabled = !ready;
    button.title = ready
        ? "Search YouTube and download a music video into the library"
        : "Add a folder with the media type Music videos under Settings, General, first. The download is saved there.";
}

async function loadMusicVideoArtists() {
    if (state.musicVideos.artists) return;
    try {
        state.musicVideos.artists = (await api("/api/v1/musicvideos/artists")).artists || [];
    } catch (error) {
        state.musicVideos.artists = [];
    }
    const list = document.getElementById("mv-youtube-artists");
    if (list) list.innerHTML = state.musicVideos.artists.map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
}

// Under the names: which library artist the typed name is linked to, and the folder the file will be saved in.
function musicVideoPlanText(plan) {
    if (!plan || !plan.ready) return "No Music videos folder is set under Settings, General.";
    if (!plan.artist) return "Type the artist. Pick one from the list to link the video to an artist you already have.";
    const who = plan.known ? `Linked to ${plan.artist}, an artist already in your library.` : `${plan.artist} is new to your library.`;
    const where = plan.folder === plan.root ? `Saved at the top of ${plan.root}.`
        : plan.folder_exists ? `Saved in the existing folder ${plan.folder}.` : `A new folder is made: ${plan.folder}.`;
    return `${who} ${where}`;
}

async function paintMusicVideoPlan() {
    const note = document.getElementById("mv-youtube-plan");
    if (!note) return;
    const value = (field) => ((document.getElementById(field) || {}).value || "").trim();
    const query = `artist=${encodeURIComponent(value("mv-youtube-artist"))}&title=${encodeURIComponent(value("mv-youtube-name"))}&root=${encodeURIComponent(value("mv-youtube-root"))}`;
    try {
        const plan = await api(`/api/v1/musicvideos/youtube/plan?${query}`);
        if (document.getElementById("mv-youtube-plan") !== note) return;
        note.textContent = musicVideoPlanText(plan);
        note.classList.toggle("is-linked", !!plan.known);
    } catch (error) {
        note.textContent = "";
    }
}

function openMusicVideoAdd() {
    if (!(state.musicVideos.roots || []).length) {
        return notify("Add a folder with the media type Music videos under Settings, General, first. The download is saved there.", "warning");
    }
    loadMusicVideoArtists();
    state.musicVideos.youtube = { results: [], picked: "" };
    document.getElementById("mv-youtube-results").innerHTML = "";
    document.getElementById("mv-youtube-modal").classList.remove("hidden");
    const box = document.getElementById("mv-youtube-query");
    box.value = "";
    box.focus();
}

async function searchMusicVideoYoutube() {
    const query = (document.getElementById("mv-youtube-query").value || "").trim();
    const host = document.getElementById("mv-youtube-results");
    if (query.length < 2) return notify("Type an artist and a title to search for.", "info");
    host.innerHTML = `<p class="muted">Searching YouTube…</p>`;
    try {
        const data = await api(`/api/v1/musicvideos/youtube?q=${encodeURIComponent(query)}`);
        state.musicVideos.youtube = { results: data.results || [], picked: "" };
    } catch (error) {
        host.innerHTML = `<p class="settings-warning">${escapeHtml(error.message || "The search failed.")}</p>`;
        return;
    }
    paintMusicVideoYoutube();
}

function musicVideoLength(seconds) {
    const total = Number(seconds) || 0;
    return total ? `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}` : "";
}

function paintMusicVideoYoutube() {
    const host = document.getElementById("mv-youtube-results");
    const { results, picked } = state.musicVideos.youtube || { results: [], picked: "" };
    if (!results.length) {
        host.innerHTML = `<p class="muted">YouTube found nothing for that.</p>`;
        return;
    }
    host.innerHTML = results.map((item) => {
        const on = item.id === picked;
        const form = on ? `<div class="mv-youtube-form">
                <label class="field">Artist <input id="mv-youtube-artist" type="text" list="mv-youtube-artists" autocomplete="off" value="${escapeHtml(item.guess_artist || "")}"></label>
                <label class="field">Title <input id="mv-youtube-name" type="text" value="${escapeHtml(item.guess_title || "")}"></label>
                <label class="field">Year <input id="mv-youtube-year" type="number" min="1900" max="2199" value=""></label>
                ${(state.musicVideos.roots || []).length > 1 ? `<label class="field">Folder <select id="mv-youtube-root">${state.musicVideos.roots.map((root) => `<option value="${escapeHtml(root)}">${escapeHtml(root)}</option>`).join("")}</select></label>` : ""}
                <button type="button" data-action="musicvideos-youtube-download" data-id="${escapeHtml(item.id)}">Download</button>
                <p id="mv-youtube-plan" class="muted mv-youtube-plan"></p>
            </div>` : "";
        return `<div class="mv-youtube-row${on ? " is-picked" : ""}">
            <img src="${escapeHtml(item.picture || "")}" alt="" loading="lazy">
            <div class="mv-youtube-text"><strong>${escapeHtml(item.title || "")}</strong>
                <small class="muted">${escapeHtml([item.channel, musicVideoLength(item.seconds), item.views ? `${Number(item.views).toLocaleString()} views` : ""].filter(Boolean).join(" · "))}</small>
                ${form}</div>
            ${on ? "" : `<button type="button" class="btn-ghost" data-action="musicvideos-youtube-pick" data-id="${escapeHtml(item.id)}">Pick</button>`}
        </div>`;
    }).join("");
    if (picked) paintMusicVideoPlan();
}

async function downloadMusicVideoYoutube(id) {
    const value = (field) => ((document.getElementById(field) || {}).value || "").trim();
    const body = { id, artist: value("mv-youtube-artist"), title: value("mv-youtube-name"), year: value("mv-youtube-year"), root: value("mv-youtube-root") || null };
    if (!body.artist || !body.title) return notify("Fill in the artist and the title.", "info");
    await api("/api/v1/musicvideos/youtube", { method: "POST", body });
    document.getElementById("mv-youtube-modal").classList.add("hidden");
    notify(`Downloading ${body.artist} - ${body.title}. It shows in the Jobs panel and joins the list when it is done.`, "info");
    pollMusicVideoDownload();
}

async function pollMusicVideoDownload() {
    clearTimeout(state.musicVideos.downloadTimer);
    const status = await api("/api/v1/musicvideos/youtube/status");
    if (status.status === "running") {
        state.musicVideos.downloadTimer = setTimeout(() => pollMusicVideoDownload().catch(() => {}), 3000);
        return;
    }
    if (status.status === "done") {
        notify(status.message || "The music video was added.", "success");
        if (state.media === "musicvideos") await loadMusicVideos();
    } else if (status.status === "failed") notify(status.message || "The download failed.", "error");
}

function onMusicVideoAction(name, action) {
    if (name === "musicvideos-add") return openMusicVideoAdd();
    if (name === "musicvideos-youtube-pick") {
        state.musicVideos.youtube.picked = action.dataset.id;
        return paintMusicVideoYoutube();
    }
    if (name === "musicvideos-youtube-download") return runAction(() => downloadMusicVideoYoutube(action.dataset.id), "Starting the download…");
    if (name === "musicvideos-scan") return runAction(() => startMusicVideoScan(action.dataset.mode || "incremental"));
    if (name === "musicvideos-nfo") return runAction(writeMusicVideoNfos, "Writing .nfo files…");
    if (name === "musicvideos-lookup") return runAction(lookupMusicVideos);
    if (name === "musicvideos-check") return runAction(() => checkMusicVideos(musicVideosShown().map((item) => item.id), false));
    if (name === "musicvideos-check-full") return runAction(() => checkMusicVideos(musicVideosShown().map((item) => item.id), true));
    if (name === "musicvideos-check-one") return runAction(() => checkMusicVideos([action.dataset.id], false));
    if (name === "musicvideos-ribbon") {
        const ribbons = state.musicVideos.ribbons;
        if (ribbons.has(action.dataset.ribbon)) ribbons.delete(action.dataset.ribbon);
        else ribbons.add(action.dataset.ribbon);
        return renderMusicVideos();
    }
    if (name === "musicvideos-tick") {
        if (action.checked) state.musicVideos.checked.add(action.dataset.id);
        else state.musicVideos.checked.delete(action.dataset.id);
        return renderMusicVideos();
    }
    if (name === "musicvideos-check-all") {
        musicVideosShown().forEach((item) => (action.checked ? state.musicVideos.checked.add(item.id) : state.musicVideos.checked.delete(item.id)));
        return renderMusicVideos();
    }
    if (name === "musicvideos-sel-clear") {
        state.musicVideos.checked.clear();
        return renderMusicVideos();
    }
    if (name === "musicvideos-sel-nfo") return runAction(async () => {
        const data = await api("/api/v1/musicvideos/nfo", { method: "POST", body: { ids: musicVideoCheckedIds() } });
        notify(`${Number(data.written) || 0} .nfo file${Number(data.written) === 1 ? "" : "s"} written.`, "success");
        await loadMusicVideos();
    }, "Writing .nfo files…");
    if (name === "musicvideos-sel-check") return runAction(() => checkMusicVideos(musicVideoCheckedIds(), false));
    if (name === "musicvideos-sel-lock") return runAction(async () => {
        const ids = musicVideoCheckedIds();
        const rows = state.musicVideos.items.filter((item) => ids.includes(item.id));
        const locked = !rows.every((item) => item.locked);
        const data = await api("/api/v1/musicvideos/lock", { method: "POST", body: { ids, locked } });
        notify(`${data.changed || 0} music video${data.changed === 1 ? "" : "s"} ${locked ? "locked" : "unlocked"}.`, "success");
        await loadMusicVideos();
    });
    if (name === "musicvideos-sel-rename") return runAction(renameMusicVideosAsk);
    if (name === "musicvideos-sel-delete") return deleteMusicVideosAsk(musicVideoCheckedIds());
    if (name === "musicvideos-filters-clear") {
        state.musicVideos.ribbons.clear();
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

document.addEventListener("submit", (event) => {
    if (event.target && event.target.id === "mv-youtube-form") {
        event.preventDefault();
        runAction(searchMusicVideoYoutube, "Searching YouTube…");
    }
});

document.addEventListener("input", (event) => {
    const id = event.target && event.target.id;
    if (id !== "mv-youtube-artist" && id !== "mv-youtube-name" && id !== "mv-youtube-root") return;
    clearTimeout(state.musicVideos.planTimer);
    state.musicVideos.planTimer = setTimeout(() => paintMusicVideoPlan(), 300);
});

