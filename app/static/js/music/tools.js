function countryName(code) {
    const value = String(code || "").trim().toUpperCase();
    if (!value) return "";
    if (SPECIAL_COUNTRIES[value]) return SPECIAL_COUNTRIES[value];
    if (!/^[A-Z]{2}$/.test(value)) return value;
    try {
        const name = new Intl.DisplayNames(["en"], { type: "region" }).of(value);
        return name && name.toUpperCase() !== value ? name : value;
    } catch (error) {
        return value;
    }
}

function flagEmoji(country) {
    const code = String(country || "").trim().toUpperCase();
    if (SPECIAL_COUNTRIES[code] || !/^[A-Z]{2}$/.test(code) || countryName(code) === code) return "";
    return String.fromCodePoint(...[...code].map((char) => 127397 + char.charCodeAt(0)));
}

async function treatCompilation() {
    await api(`/api/albums/${state.album.album.id}/compilation`, { method: "POST", body: { enabled: true } });
    await selectAlbum(state.album.album.id, true);
    notify("Album artist set for this compilation.", "info");
}

async function groupCompilation() {
    const ids = albumActionIds();
    await api("/api/albums/group-compilation", { method: "POST", body: { album_ids: ids } });
    selectionReplace("album", []);
    await loadLibrary();
    notify("Selected albums now share one compilation row. Files stayed where they are.", "info");
}

async function runReplayGain() {
    const data = await api(`/api/albums/${state.album.album.id}/replaygain`, { method: "POST", body: {} });
    notify((data.lines || []).join(" ") || "ReplayGain finished.", "info");
    await selectAlbum(state.album.album.id, true);
}

async function runAudit() {
    const data = await api(`/api/albums/${state.album.album.id}/audit`, { method: "POST", body: {} });
    notify(`Checked ${data.processed || 0} tracks.`, "info");
    await selectAlbum(state.album.album.id, true);
}

function gapLabel(gap) {
    if (!gap || !gap.expected || gap.present >= gap.expected) return "";
    return `<span class="tag-pill">Incomplete album (${gap.present}/${gap.expected})</span>`;
}

function gapList(gap) {
    if (!gap || !(gap.missing || []).length) return "";
    const items = gap.missing.map((track) => `<li>Disc ${track.disc_number || 1} track ${track.track_number}: ${escapeHtml(track.title || "")}</li>`).join("");
    return `<ul class="gap-list">${items}</ul>`;
}

async function showUpgrade() {
    const data = await api(`/api/albums/${state.album.album.id}/upgrade`);
    if (!data.upgrade) {
        notify("No higher-quality copy is indexed.", "info");
        if (data.cleared) clearUpgradePill(state.album.album.id);
        await loadLibrary();
        return;
    }
    state.videoUpgrade = null;
    state.upgradeCopies = data.copies || [];
    state.upgradeNotice = data.notice || "";
    state.upgradeSource = data.upgrade.album_id;
    document.getElementById("upgrade-purge").checked = false;
    const actions = document.getElementById("upgrade-actions");
    if (actions) actions.classList.remove("hidden");
    renderUpgradeDialog();
    document.getElementById("upgrade-modal").classList.remove("hidden");
}

function resetVideoUpgradeButton() {
    const confirm = document.getElementById("upgrade-confirm");
    const modal = document.getElementById("upgrade-modal");
    if (modal) modal.classList.remove("is-replacing");
    if (!confirm) return;
    confirm.disabled = false;
    confirm.classList.remove("is-busy");
    confirm.textContent = "Replace and archive";
}

function renderUpgradeDialog() {
    if (state.videoUpgrade) {
        resetVideoUpgradeButton();
        return;
    }
    const copies = state.upgradeCopies || [];
    const chosen = copies.find((copy) => copy.album.id === state.upgradeSource) || copies.find((copy) => copy.better);
    if (chosen) state.upgradeSource = chosen.album.id;
    const heading = document.getElementById("upgrade-title");
    const current = copies.find((copy) => copy.current) || copies[0];
    const artistName = current && current.album ? current.album.artist : "";
    const albumTitle = current && current.album ? current.album.title : "";
    if (heading) heading.textContent = artistName && albumTitle ? `${artistName} - ${albumTitle}` : (albumTitle || "Upgrade available");
    document.getElementById("upgrade-summary").textContent = state.upgradeNotice || "Another folder has a higher-quality copy.";
    document.getElementById("upgrade-compare").innerHTML = upgradeTable(copies, state.upgradeSource);
    const confirm = document.getElementById("upgrade-confirm");
    if (confirm && !state.upgradeReplacing) {
        confirm.disabled = !chosen || !chosen.better;
        confirm.textContent = chosen && chosen.same_edition ? "Replace and archive" : "Replace and archive this edition";
    }
}

function setUpgradeReplacing(busy) {
    state.upgradeReplacing = busy;
    const modal = document.getElementById("upgrade-modal");
    const button = document.getElementById("upgrade-confirm");
    const purge = document.getElementById("upgrade-purge");
    const close = modal ? modal.querySelector("[data-close='upgrade-modal']") : null;
    if (modal) modal.classList.toggle("is-replacing", busy);
    if (purge) purge.disabled = busy;
    if (close) close.disabled = busy;
    if (button) button.disabled = busy || button.classList.contains("is-busy");
    if (!busy) {
        if (state.videoUpgrade) resetVideoUpgradeButton();
        else renderUpgradeDialog();
    }
}

async function confirmUpgrade(purge) {
    if (state.videoUpgrade) return confirmVideoUpgrade(purge);
    const data = await api(`/api/albums/${state.album.album.id}/upgrade`, {
        method: "POST",
        body: { source_id: state.upgradeSource, purge },
    });
    document.getElementById("upgrade-modal").classList.add("hidden");
    document.getElementById("delete-copy-modal").classList.add("hidden");
    await selectAlbum(state.album.album.id, true);
    await loadLibrary();
    if (data.warning) notify(data.warning, "warning");
    else if (purge && data.removed_source) notify("The higher-quality files replaced the old copy, and the other copy was removed from the library.", "info");
    else notify(purge ? "The higher-quality files replaced the old copy." : "The higher-quality files are in place and the old files were archived.", "info");
}

async function checkGaps() {
    const gap = await api(`/api/albums/${state.album.album.id}/gaps`, { method: "POST", body: {} });
    state.album.gap = gap;
    state.album.album.gap_present = gap.present;
    state.album.album.gap_expected = gap.expected;
    renderAlbum();
    notify(gap.expected && gap.present < gap.expected ? `Incomplete album (${gap.present}/${gap.expected}).` : "Every linked track has a file.", "info");
}

async function downloadMissingArt(ids) {
    const albumIds = ids && ids.length ? [...ids] : (state.album ? [state.album.album.id] : []);
    if (!albumIds.length) throw new Error("Select an album before downloading artwork.");
    const data = await api("/api/artwork/deploy-missing", { method: "POST", body: { album_ids: albumIds } });
    if (!data.started) throw new Error("A missing artwork download is already running.");
    state.missingArtSeen = "running";
    state.working = true;
    schedulePoll(300);
    notify(albumIds.length === 1 ? "Downloading missing album artwork." : `Queued missing album artwork for ${albumIds.length} albums.`, "info");
}

async function confirmSplit() {
    const remove = document.getElementById("split-remove").checked;
    const data = await api(`/api/albums/${state.album.album.id}/split`, { method: "POST", body: { remove_image: remove } });
    document.getElementById("split-modal").classList.add("hidden");
    await selectAlbum(state.album.album.id, true);
    notify(`Split ${data.tracks || 0} tracks.`, "info");
}

function duplicateScope(focus) {
    if (focus && focus.media) return { media: focus.media, id: focus.id || "" };
    if (state.media === "movies") return { media: "movies", id: "" };
    if (state.media === "tv") return { media: "tv", id: "" };
    if (state.media === "music") return { media: "music", id: "" };
    return { media: "sets", id: "" };
}

async function openDuplicates(focus) {
    const scope = duplicateScope(focus);
    state.duplicateFocus = scope;
    const data = scope.media === "music"
        ? await api(`/api/duplicates${scope.id ? `?focus=${encodeURIComponent(scope.id)}` : ""}`)
        : { pairs: [] };
    // Marks the server found stale (the other copy is gone, or this window turned up empty) lose their pill.
    if (data.cleared && data.cleared.length) clearDuplicatePills(data.cleared);
    let video = { movies: [], episodes: [] };
    if (scope.media === "movies" || scope.media === "tv") {
        try {
            video = await api("/api/v1/video-duplicates");
        } catch (error) {
            video = { movies: [], episodes: [] };
        }
    }
    renderDuplicateList(data, video);
    document.getElementById("duplicates-modal").classList.remove("hidden");
}

function renderDuplicateList(data, video) {
    const host = document.getElementById("duplicates-list");
    const scope = state.duplicateFocus || { media: "music", id: "" };
    const pairs = Array.isArray(data.pairs) ? data.pairs : [];
    const wanted = scope.id
        ? pairs.filter((pair) => (pair.left && pair.left.id === scope.id) || (pair.right && pair.right.id === scope.id))
        : pairs;
    state.duplicatePairs = wanted;
    const undo = typeof duplicateUndoHtml === "function" ? duplicateUndoHtml() : "";
    const title = document.getElementById("duplicates-title");
    const note = document.getElementById("duplicates-note");
    const scan = document.getElementById("duplicates-scan");
    if (scan) scan.classList.toggle("hidden", scope.media !== "music" || !!scope.id);
    if (scope.media === "music") {
        if (title) title.textContent = scope.id ? "Duplicate album" : "Duplicate albums";
        if (note) note.textContent = "Albums that share an AcoustID or an identical fingerprint, or are the same release by artist and title or MusicBrainz id. Delete removes that copy from disk.";
        const acoustid = wanted.filter((pair) => pair.acoustid_matches);
        const fingerprint = wanted.filter((pair) => !pair.acoustid_matches && pair.fingerprint_matches);
        const release = wanted.filter((pair) => !pair.acoustid_matches && !pair.fingerprint_matches);
        const sections = [["Same recording", acoustid], ["Identical fingerprint", fingerprint]];
        if (release.length || scope.id) sections.push(["Same release", release]);
        host.innerHTML = undo + sections.map(([heading, items]) => {
            if (!items.length) return `<h3>${escapeHtml(heading)}</h3><p class="muted">None.</p>`;
            return `<h3>${escapeHtml(heading)}</h3>${items.map((pair) => duplicatePair(pair, wanted.indexOf(pair))).join("")}`;
        }).join("");
        return;
    }
    if (scope.media === "movies" || scope.media === "tv") {
        const kind = scope.media === "tv" ? "episode" : "movie";
        const groups = ((video || {})[scope.media === "tv" ? "episodes" : "movies"] || []).filter((group) => {
            if (!scope.id) return true;
            return (group.items || []).some((item) => item.id === scope.id);
        });
        const label = groups[0] && groups[0].label;
        if (title) title.textContent = scope.id ? (label || (kind === "episode" ? "Duplicate episode" : "Duplicate movie")) : (kind === "episode" ? "Duplicate episodes" : "Duplicate movies");
        if (note) note.textContent = kind === "episode"
            ? "Episodes that are the same release: same source, resolution and about the same size. Delete removes that copy from disk."
            : "Movies that are the same release: same source, resolution and about the same size. Delete removes that copy from disk.";
        state.videoDuplicateGroups = groups;
        host.innerHTML = undo + videoDuplicateSection(kind === "episode" ? "Episodes" : "Movies", groups, kind, !!scope.id);
        return;
    }
    if (title) title.textContent = "Duplicates";
    if (note) note.textContent = "Movie sets do not have a duplicate list. Open Movies, TV Shows, or Music.";
    host.innerHTML = `<p class="muted">None.</p>`;
}

function videoDuplicateEdition(item) {
    const edition = String((item && item.edition) || "").trim();
    if (!edition || edition.toLowerCase() === "none") return "";
    return edition;
}

function videoDuplicateSource(item) {
    const format = String((item && item.source_format) || "").replace(/_/g, "-").trim();
    const group = String((item && item.video_source) || "").replace(/_/g, "-").trim();
    if (!format) return group;
    if (!group) return format;
    const formatKey = typeof sourceKey === "function" ? sourceKey(format) : format.toLowerCase();
    const groupKey = typeof sourceKey === "function" ? sourceKey(group) : group.toLowerCase();
    if (!groupKey || formatKey.includes(groupKey) || groupKey.includes(formatKey)) return format;
    return `${group} ${format}`;
}

const VIDEO_DUPLICATE_FACTS = [
    ["Resolution", (item) => item.resolution || ""],
    ["Source", videoDuplicateSource],
    ["Codec", (item) => videoCodecName(item.video_codec || item.codec)],
    ["Container", containerLabel],
    ["HDR", (item) => (typeof hdrLabel === "function" ? hdrLabel(item) : "") || item.hdr_format || ""],
    ["Audio", (item) => item.audio || ""],
    ["Release group", (item) => item.release_group || ""],
    ["Bitrate", (item) => {
        const value = Number(item.bitrate_mbps);
        return value ? `${value} Mb/s` : "";
    }],
    ["Edition", videoDuplicateEdition],
    ["Runtime", (item) => {
        const minutes = item.duration_seconds ? Math.round(Number(item.duration_seconds) / 60) : 0;
        return minutes ? fmtRuntime(minutes) : "";
    }],
    ["Size", (item) => (item.size_bytes ? fmtSize(item.size_bytes) : "")],
    ["Date added", (item) => (typeof fmtDate === "function" ? fmtDate(item.date_added || item.created_at) : "")],
];

function videoCodecName(value) {
    const raw = String(value || "").trim();
    const key = raw.toLowerCase().replace(/[^a-z0-9]/g, "");
    const names = {
        h264: "AVC", avc: "AVC",
        h265: "HEVC", hevc: "HEVC",
        vc1: "VC-1",
        mpeg2: "MPEG-2", mpeg2video: "MPEG-2",
        mpeg1: "MPEG-1", mpeg1video: "MPEG-1",
        mpeg4: "MPEG-4",
        av1: "AV1",
        vp9: "VP9", vp8: "VP8",
        vvc: "VVC", h266: "VVC",
        wmv3: "WMV3",
    };
    return names[key] || raw;
}

function containerLabel(item) {
    const path = String((item && (item.filepath || item.path)) || "").split("\n")[0];
    const ext = (path.match(/\.([a-z0-9]{2,5})$/i) || [])[1];
    if (ext && ext.toLowerCase() === "mkv") return "MKV";
    if (ext) return ext.toLowerCase();
    const stored = String((item && item.container) || "").toLowerCase();
    if (stored === "matroska" || stored === "mkv") return "MKV";
    if (stored === "mpegts") return "ts";
    if (stored === "mov") return "mp4";
    return stored;
}

function videoDuplicateFactRows(items) {
    return VIDEO_DUPLICATE_FACTS.filter(([, read]) => (items || []).some((item) => read(item)));
}

function videoDuplicateFactsHtml(item, rows) {
    const body = rows.map(([label, read]) => {
        const value = read(item);
        return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "—")}</dd>`;
    }).join("");
    return body ? `<dl class="dup-facts">${body}</dl>` : "";
}

function arrCopyLine(item) {
    const arr = item && item.arr;
    if (!arr || !arr.app) return "";
    const icon = typeof providerIcon === "function"
        ? providerIcon(arr.app)
        : `<img class="provider-icon" src="/media/providers/${encodeURIComponent(arr.app.toLowerCase())}.png" alt="${escapeHtml(arr.app)}" title="${escapeHtml(arr.app)}">`;
    if (arr.id) {
        return `<p class="dup-arr">${icon}<span class="dup-arr-id">${escapeHtml(String(arr.id))}</span></p>`;
    }
    return `<p class="dup-arr is-absent"><span class="dup-arr-notin">Not in</span>${icon}</p>`;
}

function videoDuplicateCard(item, kind, rows, suggested) {
    const poster = item.poster
        ? `<img class="upgrade-cover video-dup-poster" src="${artUrl(item.poster, 342)}" alt="">`
        : `<div class="art-fallback upgrade-cover video-dup-poster">No poster</div>`;
    const file = String(item.path || "").split(/[\\/]/).pop();
    const keep = suggested ? `<p class="dup-keep">Suggested to keep</p>` : "";
    const failed = typeof failPill === "function" ? failPill("probe", item.probe_error) : "";
    const probe = failed ? `<p class="dup-probe">${failed}</p>` : "";
    return `<th class="video-dup-card${suggested ? " is-keep" : ""}${failed ? " is-probe-failed" : ""}" data-id="${escapeHtml(item.id)}">
        <button type="button" class="upgrade-delete" data-action="delete-video-duplicate" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(item.id)}" title="Delete this copy from disk" aria-label="Delete this copy from disk">${trashSvg()}</button>
        ${keep}
        ${probe}
        ${poster}
        <div class="dup-name">${escapeHtml(file || item.title || "Copy")}</div>
        ${videoDuplicateFactsHtml(item, rows || videoDuplicateFactRows([item]))}
        ${arrCopyLine(item)}
        <span class="upgrade-path">${escapeHtml(item.filepath || item.path || "")}</span>
        <p class="video-dup-actions"><button type="button" class="btn-ghost btn-remove" data-action="remove-video-duplicate" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(item.id)}">Remove from library</button></p>
    </th>`;
}

function videoDuplicateSection(title, groups, kind, focused) {
    const items = groups || [];
    if (!items.length) return `<p class="muted">None.</p>`;
    return items.map((group) => {
        const rows = videoDuplicateFactRows(group.items || []);
        const cards = (group.items || []).map((item) => videoDuplicateCard(item, kind, rows)).join("");
        const heading = focused ? "" : `<h3>${escapeHtml(group.label || title)}</h3>`;
        const pair = group.items || [];
        const dismiss = pair.length >= 2
            ? `<p><button type="button" class="btn-ghost" data-action="dismiss-video-duplicate" data-kind="${escapeHtml(kind)}" data-left="${escapeHtml(pair[0].id)}" data-right="${escapeHtml(pair[1].id)}">Not duplicates</button></p>`
            : "";
        return `<section class="duplicate-pair">${heading}
            <div class="upgrade-scroll"><table class="upgrade-table"><thead><tr>${cards}</tr></thead></table></div>
            ${dismiss}
        </section>`;
    }).join("");
}

function findVideoDuplicate(id) {
    for (const group of state.videoDuplicateGroups || []) {
        const item = (group.items || []).find((copy) => copy.id === id);
        if (item) return item;
    }
    const copies = (state.videoUpgrade && state.videoUpgrade.copies) || [];
    return copies.find((copy) => copy.id === id) || null;
}

function copySiblings(id) {
    const ids = new Set();
    for (const group of state.videoDuplicateGroups || []) {
        const items = group.items || [];
        if (!items.some((item) => item.id === id)) continue;
        items.forEach((item) => { if (item.id !== id) ids.add(item.id); });
    }
    ((state.videoUpgrade && state.videoUpgrade.copies) || []).forEach((item) => {
        if (item.id && item.id !== id) ids.add(item.id);
    });
    return [...ids];
}

function paintCopyDeleting(id, label) {
    document.querySelectorAll(".video-dup-card").forEach((card) => {
        if (card.dataset.id !== id) return;
        card.classList.add("is-deleting");
        if (card.querySelector(".dup-deleting")) return;
        const veil = document.createElement("div");
        veil.className = "dup-deleting";
        veil.innerHTML = `<span class="activity-spin" aria-hidden="true"></span><span>${escapeHtml(label)}</span>`;
        card.appendChild(veil);
    });
}

function clearCopyDeleting(id) {
    document.querySelectorAll(".video-dup-card").forEach((card) => {
        if (card.dataset.id !== id) return;
        card.classList.remove("is-deleting");
        const veil = card.querySelector(".dup-deleting");
        if (veil) veil.remove();
    });
}

function closeCopyModals() {
    const duplicates = document.getElementById("duplicates-modal");
    const upgrade = document.getElementById("upgrade-modal");
    if (duplicates) duplicates.classList.add("hidden");
    if (upgrade) upgrade.classList.add("hidden");
    state.videoUpgrade = null;
}

function askVideoDuplicate(action, disk) {
    const kind = action.dataset.kind;
    const id = action.dataset.id;
    const item = findVideoDuplicate(id) || {};
    const name = item.title || "this copy";
    if (disk) {
        askDanger(
            `Delete ${name} from disk?`,
            "This removes the video file and the .nfo, artwork and subtitles named after it. The other copies stay.",
            "Delete from disk",
            () => finishVideoDuplicate("delete", kind, id),
            true,
            () => finishVideoDuplicate("remove", kind, id),
        );
        return;
    }
    askDanger(
        `Remove ${name} from the library?`,
        "The file stays on disk. The next scan can add it again.",
        "Remove from library",
        () => finishVideoDuplicate("remove", kind, id),
        false,
    );
}

async function finishVideoDuplicate(mode, kind, id) {
    const label = mode === "delete" ? "Deleting duplicate…" : "Removing from library…";
    paintCopyDeleting(id, label);
    let peers = [];
    try {
        if (mode === "delete") {
            const data = await api("/api/v1/delete", { method: "POST", body: { kind, ids: [id] } });
            const deleted = data.deleted || [];
            const errors = data.errors || [];
            if (!deleted.length) {
                clearCopyDeleting(id);
                notify(errors[0] || "That copy was not deleted.", "error");
                return;
            }
            peers = data.peers || [];
            notify(errors.length ? `Deleted ${deleted[0]}. ${errors[0]}` : `${deleted[0]} was deleted from disk.`, errors.length ? "warning" : "success");
        } else {
            const data = await api("/api/v1/remove", { method: "POST", body: { kind, ids: [id] } });
            if (!data.removed) {
                clearCopyDeleting(id);
                notify("That copy is no longer in the library.", "info");
                return;
            }
            peers = data.peers || [];
            notify("Removed from the library. The file is still on disk.", "info");
        }
    } catch (error) {
        clearCopyDeleting(id);
        throw error;
    }
    dropVideoDuplicate(kind, id);
    applyPeerFlags(peers);
    forgetDuplicateUndo([id]);
    if (copyVersionsLeft() < 2) closeCopyModals();
    else refreshUpgradeCompare(kind);
}

function copyVersionsLeft() {
    const upgrade = document.getElementById("upgrade-modal");
    if (upgrade && !upgrade.classList.contains("hidden") && state.videoUpgrade) {
        return (state.videoUpgrade.copies || []).length;
    }
    const groups = state.videoDuplicateGroups || [];
    const focus = state.duplicateFocus && state.duplicateFocus.id;
    if (focus) {
        const group = groups.find((item) => (item.items || []).some((copy) => copy.id === focus));
        return group ? (group.items || []).length : 0;
    }
    return groups.length ? 2 : 0;
}

function refreshUpgradeCompare(kind) {
    const upgrade = document.getElementById("upgrade-modal");
    if (!upgrade || upgrade.classList.contains("hidden") || !state.videoUpgrade) return;
    const host = document.getElementById("upgrade-compare");
    if (!host) return;
    host.innerHTML = upgradeCompareHtml(state.videoUpgrade.copies || [], state.videoUpgrade.kind || kind);
}

function dropVideoDuplicate(kind, id) {
    let siblings = copySiblings(id);
    if (state.videoUpgrade && state.videoUpgrade.copies) {
        state.videoUpgrade.copies = state.videoUpgrade.copies.filter((item) => item.id !== id);
    }
    state.videoDuplicateGroups = (state.videoDuplicateGroups || []).flatMap((group) => {
        const items = group.items || [];
        if (!items.some((item) => item.id === id)) return [group];
        const left = items.filter((item) => item.id !== id);
        return left.length >= 2 ? [{ ...group, items: left }] : [];
    });
    if (state.duplicateFocus && state.duplicateFocus.id === id) {
        const still = (state.videoDuplicateGroups || []).find((group) => (group.items || []).length >= 2);
        const next = still && still.items && still.items[0];
        if (next) state.duplicateFocus = { ...state.duplicateFocus, id: next.id };
    }
    if (kind === "episode") dropEpisodeRow(id, siblings);
    else dropMovieRow(id, siblings);
    const video = { movies: [], episodes: [] };
    video[kind === "episode" ? "episodes" : "movies"] = state.videoDuplicateGroups || [];
    renderDuplicateList({ pairs: [] }, video);
    if (typeof loadMediaTotals === "function") loadMediaTotals();
}

function clearCopyMarks(item) {
    if (!item) return;
    item.duplicate_release = false;
    item.upgrade = false;
    item.upgrade_path = "";
}

function applyPeerFlags(peers) {
    const rows = peers || [];
    if (!rows.length) return;
    const byId = new Map(rows.map((row) => [String(row.id), row]));
    let video = false;
    let music = false;
    const paint = (item) => {
        const flag = byId.get(String(item && item.id));
        if (!flag) return false;
        item.duplicate_release = !!flag.duplicate_release;
        item.upgrade = !!flag.upgrade;
        item.upgrade_path = flag.upgrade_path || "";
        return true;
    };
    if (state.video) {
        (state.video.movies || []).forEach((movie) => { if (paint(movie)) video = true; });
        if (state.video.detail && paint(state.video.detail)) video = true;
        (state.video.showDetails || new Map()).forEach((detail) => {
            (detail.episodes || []).forEach((episode) => { if (paint(episode)) video = true; });
        });
    }
    (state.artists || []).forEach((artist) => {
        (artist.albums || []).forEach((album) => { if (paint(album)) music = true; });
    });
    if (state.album && state.album.album && paint(state.album.album)) music = true;
    if (video && typeof paintCurrentVideoList === "function") paintCurrentVideoList();
    if (video && state.video.detail && typeof renderVideoCenter === "function") renderVideoCenter();
    if (music && typeof renderTree === "function") renderTree();
}

function forgetDuplicateUndo(ids, trackIds) {
    const undo = state.duplicateUndo;
    if (!undo) return;
    const gone = new Set((ids || []).map((id) => String(id)));
    const tracks = new Set((trackIds || []).map((id) => String(id)));
    if (undo.media === "music") {
        const hit = (undo.pairs || []).some((pair) => tracks.has(String(pair.left_id)) || tracks.has(String(pair.right_id)));
        if (hit) state.duplicateUndo = null;
        return;
    }
    if (gone.has(String(undo.left_id)) || gone.has(String(undo.right_id))) state.duplicateUndo = null;
}

function dropMovieRow(id, siblingIds) {
    const movies = state.video.movies || [];
    const gone = movies.find((movie) => movie.id === id);
    state.video.movies = movies.filter((movie) => movie.id !== id);
    const alone = siblingIds.length < 2;
    state.video.movies.forEach((movie) => {
        if (alone && siblingIds.includes(movie.id)) clearCopyMarks(movie);
        else if (gone && gone.path && movie.upgrade_path === gone.path) clearCopyMarks(movie);
    });
    selectionSet("movie", id, false);
    const open = state.video.detail && state.video.detail.id === id;
    if (state.video.movieId === id) {
        state.video.movieId = null;
        state.video.detail = null;
    } else if (alone && state.video.detail && siblingIds.includes(state.video.detail.id)) {
        clearCopyMarks(state.video.detail);
        if (state.media === "movies") renderMovieInfo(state.video.detail);
    }
    if (state.media !== "movies") return;
    const host = document.getElementById("video-list");
    const scroll = host ? host.scrollTop : 0;
    renderMovieRibbons();
    if (!host || !host.querySelector(".vwin-rows")) renderMovieMatrix();
    else {
        state.video.rows = visibleMovies();
        state.video.paintToken += 1;
        paintMovieRows();
        renderVideoCounts(`${state.video.rows.length} of ${(state.video.movies || []).length} movies`);
        paintVideoSelection();
        host.scrollTop = scroll;
    }
    if (open) renderVideoCenter();
}

function dropEpisodeRow(id, siblingIds) {
    const alone = siblingIds.length < 2;
    let showId = "";
    (state.video.showDetails || new Map()).forEach((detail, key) => {
        const episodes = detail.episodes || [];
        const index = episodes.findIndex((episode) => episode.id === id);
        if (index < 0) return;
        const gone = episodes[index];
        showId = key;
        detail.episodes = episodes.filter((episode) => episode.id !== id);
        episodes.forEach((episode) => {
            if (alone && siblingIds.includes(episode.id)) clearCopyMarks(episode);
            else if (gone.path && episode.upgrade_path === gone.path) clearCopyMarks(episode);
        });
        const seasonId = gone.season_id;
        if (seasonId && !detail.episodes.some((episode) => episode.season_id === seasonId)) {
            detail.seasons = (detail.seasons || []).filter((season) => season.id !== seasonId);
        }
        if (typeof recountTvNew === "function") recountTvNew(key);
    });
    const show = showId && (state.video.shows || []).find((item) => item.id === showId);
    if (show) show.episode_count = Math.max(0, (show.episode_count || 0) - 1);
    selectionSet("episode", id, false);
    const open = state.video.tvSel && state.video.tvSel.type === "episode" && state.video.tvSel.id === id;
    if (open) state.video.tvSel = null;
    if (state.media !== "tv") return;
    if (typeof paintTvAfterStatus === "function") paintTvAfterStatus();
    else if (typeof renderTvTree === "function") renderTvTree();
    const shows = state.video.shows || [];
    const episodes = shows.reduce((sum, item) => sum + (item.episode_count || 0), 0);
    if (typeof renderVideoCounts === "function") {
        renderVideoCounts(shows.length ? `${shows.length} shows · ${episodes} episodes` : "No shows yet");
    }
    if (open && typeof renderVideoCenter === "function") {
        renderVideoCenter();
        return;
    }
    const sel = state.video.tvSel;
    const detail = showId && state.video.showDetails.get(showId);
    if (!sel || !detail) return;
    if (sel.type === "show" && sel.id === showId) renderShowInfo(detail);
    if (sel.type === "season" && sel.show === showId) {
        const season = (detail.seasons || []).find((item) => item.id === sel.id);
        if (season) renderSeasonInfo(detail, season);
    }
}

function duplicatePair(pair, index) {
    const leftCount = pair.left && pair.left.track_count;
    const rightCount = pair.right && pair.right.track_count;
    const parts = [];
    if (pair.acoustid_matches) parts.push(`${pair.acoustid_matches} AcoustID match${pair.acoustid_matches === 1 ? "" : "es"}`);
    if (pair.fingerprint_matches) parts.push(`${pair.fingerprint_matches} identical fingerprint${pair.fingerprint_matches === 1 ? "" : "s"}`);
    if (!parts.length && pair.reason) parts.push(pair.reason);
    const summary = `${parts.join(", ")}. The albums have ${leftCount} and ${rightCount} tracks.`;
    const dismiss = pair.acoustid_matches || pair.fingerprint_matches
        ? `<p><button type="button" class="btn-ghost" data-action="dismiss-duplicate" data-index="${index}">Not duplicates</button></p>`
        : "";
    const head = [pair.left, pair.right].map((album) => duplicateHead(album)).join("");
    const body = (pair.rows || []).map((row) => {
        return `<tr>${duplicateTrackCell(row.left, row.match)}${duplicateTrackCell(row.right, row.match)}</tr>`;
    }).join("");
    return `<section class="duplicate-pair">
        <p class="muted">${escapeHtml(summary)}</p>
        <div class="upgrade-scroll"><table class="upgrade-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
        ${dismiss}
    </section>`;
}

function duplicateHead(album) {
    const item = album || {};
    const id = item.id || "";
    const cover = `<img class="upgrade-cover" src="/api/albums/${encodeURIComponent(id)}/cover?w=160" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'art-fallback upgrade-cover', textContent:'No art'}))">`;
    const remove = `<button type="button" class="upgrade-delete" data-action="delete-duplicate" data-id="${escapeHtml(id)}" title="Delete this album" aria-label="Delete this album">${trashSvg()}</button>`;
    const name = [item.artist, item.title].filter(Boolean).join(" — ") || "Album";
    const original = item.original_year ? `Original year ${item.original_year}` : "Original year —";
    const release = item.year ? `Release year ${item.year}` : "Release year —";
    const meta = [item.version || "", release, item.track_count ? `${item.track_count} tracks` : ""].filter(Boolean).join(" · ");
    const audio = audioLine(item.audio || {});
    return `<th>${remove}${cover}<div class="upgrade-label">${escapeHtml(name)}</div><div class="upgrade-label">${escapeHtml(original)}</div><div class="upgrade-label">${escapeHtml(meta)}</div>${audio ? `<div class="upgrade-label">${escapeHtml(audio)}</div>` : ""}${arrCopyLine(item)}<span class="upgrade-path">${escapeHtml(item.path || "")}</span></th>`;
}

function duplicateTrackCell(track, match) {
    if (!track) return "<td></td>";
    const kind = match === "acoustid" ? "dup-match" : match === "fingerprint" ? "dup-fingerprint" : "";
    const number = `${track.disc > 1 ? `${track.disc}.` : ""}${String(track.number || 0).padStart(2, "0")}`;
    const tag = match === "acoustid" ? `<span class="dup-tag">AcoustID</span>` : match === "fingerprint" ? `<span class="dup-tag">Fingerprint</span>` : "";
    const format = audioLine({
        format: track.format ? String(track.format).toUpperCase() : "",
        bit_depth: track.bit_depth,
        sample_rate: track.sample_rate,
        bitrate: track.bitrate,
    });
    const quality = format ? `<span class="upgrade-path">${escapeHtml(format)}</span>` : "";
    return `<td class="${kind}"><span class="mono">${escapeHtml(number)}</span> ${escapeHtml(track.title || "")}${tag}${quality}</td>`;
}

function findDuplicateAlbum(id) {
    for (const pair of state.duplicatePairs || []) {
        if (pair.left && pair.left.id === id) return pair.left;
        if (pair.right && pair.right.id === id) return pair.right;
    }
    return null;
}

function askDeleteDuplicate(id) {
    const album = findDuplicateAlbum(id);
    if (!album) return;
    state.deleteCopyId = id;
    state.deleteCopyFrom = "duplicates";
    const name = [album.artist, album.title].filter(Boolean).join(" - ") || "this album";
    document.getElementById("delete-copy-text").textContent = `Delete the files for ${name}?`;
    document.getElementById("delete-copy-path").textContent = album.path || "";
    document.getElementById("delete-copy-modal").classList.remove("hidden");
}

async function scanDuplicates() {
    const data = await api("/api/duplicates/scan", { method: "POST", body: {} });
    notify(data.started ? "Fingerprint scan started." : "A fingerprint scan is already running.", "info");
}

async function dismissDuplicatePair(index) {
    const pair = (state.duplicatePairs || [])[Number(index)];
    if (!pair) return;
    const pairs = (pair.rows || []).filter((row) => row.match && row.left && row.right).map((row) => ({
        left_id: row.left.id,
        right_id: row.right.id,
    }));
    if (!pairs.length) return;
    const data = await api("/api/duplicates/dismiss", { method: "POST", body: { pairs } });
    clearDuplicatePills(data.cleared);
    state.duplicateUndo = { media: "music", pairs: data.pairs || pairs };
    await openDuplicates(state.duplicateFocus);
}

async function undoDuplicateDismiss() {
    const undo = state.duplicateUndo;
    if (!undo) return;
    if (undo.media === "music") {
        const data = await api("/api/duplicates/restore", { method: "POST", body: { pairs: undo.pairs } });
        markDuplicatePills(data.marked);
    } else {
        const data = await api("/api/v1/video-duplicates/restore", { method: "POST", body: { kind: undo.kind, left_id: undo.left_id, right_id: undo.right_id } });
        markVideoDuplicatePills(data.marked);
        clearVideoDuplicatePills(data.cleared);
    }
    state.duplicateUndo = null;
    notify("Those copies are marked as duplicates again.", "info");
    await openDuplicates(state.duplicateFocus);
}

function duplicateUndoHtml() {
    const undo = state.duplicateUndo;
    if (!undo) return "";
    const scope = state.duplicateFocus || { media: "music" };
    if ((undo.media || "music") !== scope.media) return "";
    return `<p><button type="button" class="btn-ghost" data-action="undo-duplicate">Undo not duplicates</button></p>`;
}

function setDuplicatePills(ids, on) {
    const wanted = new Set((ids || []).map((id) => String(id)));
    if (!wanted.size) return;
    (state.artists || []).forEach((artist) => {
        (artist.albums || []).forEach((album) => {
            if (wanted.has(String(album.id))) album.duplicate_release = on;
        });
    });
    if (state.album && state.album.album && wanted.has(String(state.album.album.id))) {
        state.album.album.duplicate_release = on;
    }
    if (typeof renderTree === "function") renderTree();
}

function clearUpgradePill(id) {
    (state.artists || []).forEach((artist) => {
        (artist.albums || []).forEach((album) => {
            if (String(album.id) === String(id)) {
                album.upgrade = false;
                album.upgrade_path = "";
            }
        });
    });
    if (state.album && state.album.album && String(state.album.album.id) === String(id)) state.album.album.upgrade = false;
    if (typeof renderTree === "function") renderTree();
    if (state.center === "album" && state.album && typeof renderAlbum === "function") renderAlbum();
}

function clearDuplicatePills(ids) {
    setDuplicatePills(ids, false);
}

function markDuplicatePills(ids) {
    setDuplicatePills(ids, true);
}

function setVideoDuplicatePills(ids, on) {
    const wanted = new Set((ids || []).map((id) => String(id)));
    if (!wanted.size) return;
    (state.video.movies || []).forEach((movie) => {
        if (wanted.has(String(movie.id))) movie.duplicate_release = on;
    });
    if (state.video.detail && wanted.has(String(state.video.detail.id))) state.video.detail.duplicate_release = on;
    (state.video.showDetails || new Map()).forEach((detail) => {
        (detail.episodes || []).forEach((episode) => {
            if (wanted.has(String(episode.id))) episode.duplicate_release = on;
        });
    });
    if (state.media === "movies" && typeof renderMovieMatrix === "function") renderMovieMatrix();
    else if (state.media === "tv" && typeof renderTvTree === "function") renderTvTree();
    if (state.video.detail && typeof renderVideoCenter === "function") renderVideoCenter();
}

function clearVideoDuplicatePills(ids) {
    setVideoDuplicatePills(ids, false);
}

function markVideoDuplicatePills(ids) {
    setVideoDuplicatePills(ids, true);
}

function trashSvg() {
    return `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M7 7l1 13h8l1-13"/><path d="M10 11v6M14 11v6"/></svg>`;
}

function upgradeHead(copy, selectedId, current) {
    const picked = copy.album.id === selectedId ? " picked" : "";
    const cover = `<img class="upgrade-cover" src="/api/albums/${encodeURIComponent(copy.album.id)}/cover?w=160" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'art-fallback upgrade-cover', textContent:'No art'}))">`;
    const remove = `<button type="button" class="upgrade-delete" data-action="delete-upgrade" data-id="${escapeHtml(copy.album.id)}" title="Delete these files" aria-label="Delete these files">${trashSvg()}</button>`;
    const path = `${arrCopyLine(copy)}<span class="upgrade-path">${escapeHtml(copy.path || "")}</span>`;
    let label = "Current";
    if (!copy.current && !copy.better) {
        label = Number(copy.quality_rank) === Number((current || {}).quality_rank) ? "Same quality" : "Lower quality";
    } else if (!copy.current) {
        const active = copy.album.id === selectedId ? " active" : "";
        label = `<button type="button" class="btn-ghost pick-upgrade${active}" data-action="pick-upgrade" data-id="${escapeHtml(copy.album.id)}">Use this copy</button>`;
    }
    return `<th class="${picked.trim()}">${remove}${cover}<div class="upgrade-label">${label}</div>${path}</th>`;
}

function askDeleteCopy(id) {
    const copy = (state.upgradeCopies || []).find((item) => item.album.id === id);
    if (!copy) return;
    state.deleteCopyId = id;
    const artistName = copy.album.artist || "This artist";
    const albumTitle = copy.album.title || "this album";
    document.getElementById("delete-copy-text").textContent = `Delete the files for ${artistName} - ${albumTitle}?`;
    document.getElementById("delete-copy-path").textContent = copy.path || "";
    document.getElementById("delete-copy-modal").classList.remove("hidden");
}

async function confirmDeleteCopy() {
    const id = state.deleteCopyId;
    const fromDuplicates = state.deleteCopyFrom === "duplicates";
    document.getElementById("delete-copy-modal").classList.add("hidden");
    if (!id) return;
    if (fromDuplicates) {
        const wasOpen = state.album && state.album.album && state.album.album.id === id;
        const data = await api(`/api/albums/${id}/delete`, { method: "POST", body: {} });
        applyPeerFlags(data.peers);
        forgetDuplicateUndo([id], data.track_ids);
        notify("The files were deleted.", "info");
        state.deleteCopyFrom = "";
        if (wasOpen) state.album = null;
        dropLibraryRows({ album_ids: [id] });
        if (wasOpen) renderCenter();
        else if (state.album) await selectAlbum(state.album.album.id, true);
        await openDuplicates(state.duplicateFocus);
        return;
    }
    const wasCurrent = (state.upgradeCopies || []).some((copy) => copy.current && copy.album.id === id);
    const data = await api(`/api/albums/${id}/delete`, { method: "POST", body: {} });
    applyPeerFlags(data.peers);
    forgetDuplicateUndo([id], data.track_ids);
    state.upgradeCopies = (state.upgradeCopies || []).filter((copy) => copy.album.id !== id);
    if (state.upgradeSource === id) {
        const next = state.upgradeCopies.find((copy) => copy.better);
        state.upgradeSource = next ? next.album.id : "";
    }
    notify("The files were deleted.", "info");
    if (wasCurrent || state.upgradeCopies.length < 2) {
        document.getElementById("upgrade-modal").classList.add("hidden");
        if (wasCurrent) state.album = null;
        dropLibraryRows({ album_ids: [id] });
        if (wasCurrent) renderCenter();
        else if (state.album) await selectAlbum(state.album.album.id, true);
        return;
    }
    renderUpgradeDialog();
    dropLibraryRows({ album_ids: [id] });
    if (state.album) await selectAlbum(state.album.album.id, true);
}

function upgradeTable(copies, selectedId) {
    const fields = [
        ["Folder", (copy) => folderName(copy.path)],
        ["Original year", (copy) => (copy.release || {}).original_year],
        ["Release year", (copy) => (copy.release || {}).year],
        ["Country", (copy) => countryLabel((copy.release || {}).country)],
        ["Tracks", (copy) => (copy.release || {}).tracks],
        ["Version", (copy) => (copy.release || {}).version],
        ["Catalog", (copy) => (copy.release || {}).catalog],
        ["Label", (copy) => (copy.release || {}).label],
        ["Audio", (copy) => audioLine(copy.audio)],
    ];
    const current = copies.find((copy) => copy.current) || copies[0] || { quality_rank: 0 };
    const head = copies.map((copy) => upgradeHead(copy, selectedId, current)).join("");
    const body = fields.map(([label, read]) => {
        const texts = copies.map((copy) => {
            const value = read(copy);
            return value === null || value === undefined || value === "" ? "—" : String(value);
        });
        const base = texts[0];
        const cells = texts.map((text, index) => {
            const picked = copies[index].album.id === selectedId ? " picked" : "";
            const changed = index > 0 && text !== base;
            return `<td class="${(changed ? "diff" : "") + picked}">${escapeHtml(text)}</td>`;
        }).join("");
        return `<tr><th>${escapeHtml(label)}</th>${cells}</tr>`;
    }).join("");
    return `<div class="upgrade-scroll"><table class="upgrade-table"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function countryLabel(code) {
    const value = String(code || "").trim().toUpperCase();
    if (!value) return "";
    const name = countryName(value);
    return name || value;
}

function audioLine(audio) {
    const source = audio || {};
    const parts = [source.format || ""];
    if (source.bit_depth) parts.push(`${source.bit_depth}-bit`);
    if (source.sample_rate) parts.push(rateLabel(source.sample_rate));
    if (source.bitrate) parts.push(`${source.bitrate} kbps`);
    return parts.filter(Boolean).join(" · ");
}

function rateLabel(rate) {
    const value = Number(rate);
    if (!value) return "";
    if (value % 1000 === 0) return `${value / 1000} kHz`;
    if (value % 100 === 0) return `${(value / 1000).toFixed(1)} kHz`;
    return `${value} Hz`;
}

async function loadDiscography(artistId) {
    const data = await api(`/api/artists/${artistId}/discography`);
    if (state.artistId !== artistId) return;
    paintDiscography(data);
}

async function refreshDiscography() {
    const data = await api(`/api/artists/${state.artistId}/discography`, { method: "POST", body: {} });
    paintDiscography(data);
}

function paintDiscography(data) {
    state.discography = data;
    state.discographyArtist = state.artistId;
    const count = document.getElementById("studio-count");
    const host = document.getElementById("discography-grid");
    if (!count || !host) return;
    const local = (state.artistDetail && state.artistDetail.albums) || [];
    if (!data.total) {
        count.textContent = data.message
            || (data.fetched_at
                ? "On disk: 0 / 0"
                : "MusicBrainz discography stays blank until you refresh.");
        host.innerHTML = discographyHtml(local);
        return;
    }
    count.textContent = `On disk: ${data.owned} / ${data.total} (${data.percent}%)`;
    const seen = new Set((data.releases || []).map((release) => String(release.album_id || "")).filter(Boolean));
    const extra = local.filter((album) => !seen.has(String(album.id)));
    host.innerHTML = `${catalogDiscography(data.releases || [])}${extra.length ? `<h4 class="section-label">In the library, not in this MusicBrainz list</h4>${discographyHtml(extra)}` : ""}`;
}

function catalogDiscography(releases) {
    const buckets = new Map(DISCOG_GROUPS.map(([key]) => [key, []]));
    releases.forEach((release) => {
        const key = buckets.has(release.type) ? release.type : "unknown";
        buckets.get(key).push(release);
    });
    return DISCOG_GROUPS.filter(([key]) => buckets.get(key).length).map(([key, label]) => {
        const rows = buckets.get(key);
        return `<h4 class="section-label">${escapeHtml(label)} <span class="muted">${rows.length}</span></h4>
            <div class="discog">${rows.map(catalogCard).join("")}</div>`;
    }).join("");
}

function catalogCard(release) {
    const owned = !!release.owned;
    const cover = owned && release.album_id
        ? `/api/albums/${encodeURIComponent(release.album_id)}/cover?w=160`
        : (release.id ? `https://coverartarchive.org/release-group/${encodeURIComponent(release.id)}/front-250` : "");
    const image = cover
        ? `<img src="${cover}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'art-fallback', textContent:'No art'}))">`
        : `<div class="art-fallback">No art</div>`;
    const jump = owned && release.album_id ? `data-action="jump-album" data-jump-album="${escapeHtml(release.album_id)}"` : "";
    return `<button type="button" class="discog-card${owned ? " is-owned" : " is-missing"}" ${jump}
        data-discog-group="${escapeHtml(release.id || "")}" data-discog-album="${escapeHtml(owned ? release.album_id || "" : "")}" data-discog-title="${escapeHtml(release.title || "")}" data-discog-year="${escapeHtml(release.year || "")}" data-discog-owned="${owned ? "1" : "0"}">
        <span class="discog-cover">${owned ? "" : `<span class="missing-flag">Album missing</span>`}${image}</span>
        <strong>${escapeHtml(release.title || "")}</strong>
        <div class="muted">${escapeHtml(release.year || "")}</div>
    </button>`;
}

function onDiscogMenu(event) {
    const card = event.target.closest("[data-discog-group]");
    if (!card) return;
    event.preventDefault();
    state.discogTarget = {
        release_group_id: card.dataset.discogGroup || "",
        album_id: card.dataset.discogAlbum || "",
        title: card.dataset.discogTitle || "",
        year: card.dataset.discogYear || "",
        owned: card.dataset.discogOwned === "1",
    };
    const diffMenu = document.getElementById("diff-menu");
    if (diffMenu) diffMenu.classList.add("hidden");
    const inLibrary = !!state.discogTarget.album_id;
    placeMenu(fillContextMenu([
        ["lidarr", lookUpIn("lidarr"), integrationOn("lidarr") ? true : "off", false, "Look up in Lidarr", true],
        ["missing-art", "Download missing artwork", inLibrary, false, inLibrary ? "" : "This album is not in the library"],
    ], "discog-menu"), event);
}

async function downloadDiscogArtwork() {
    const target = state.discogTarget;
    document.getElementById("album-menu").classList.add("hidden");
    if (!target || !target.album_id) throw new Error("This album is not in the library.");
    await downloadMissingArt([target.album_id]);
}

async function searchLidarrRelease() {
    if (arrSearchBlocked("lidarr")) return;
    const target = state.discogTarget;
    if (!target || !state.artistId) return;
    document.getElementById("album-menu").classList.add("hidden");
    const data = await api(`/api/artists/${state.artistId}/lidarr`, { method: "POST", body: target });
    notify(data.message || "Lidarr search queued.", "info");
    if (data.pending || data.started) pollSystem();
}

async function searchMissingLidarr() {
    if (arrSearchBlocked("lidarr")) return;
    if (!state.artistId) throw new Error("Open an artist first.");
    const data = await api(`/api/artists/${state.artistId}/lidarr/missing`, { method: "POST", body: {} });
    notify(data.message || "Lidarr search queued.", "info");
    pollSystem();
}

function offlinePathList(map) {
    const groups = map || {};
    const out = [];
    ["music", "movies", "tv"].forEach((kind) => {
        (groups[kind] || []).forEach((path) => out.push(path));
    });
    return out;
}

function noteOfflinePaths(map) {
    const paths = offlinePathList(map);
    const stamp = paths.slice().sort().join("|");
    if (stamp === state.offlinePathStamp) return;
    state.offlinePathStamp = stamp;
    document.querySelectorAll("[data-offline-paths]").forEach((node) => {
        node.textContent = paths.length
            ? `${paths.length} library folder${paths.length === 1 ? " is" : "s are"} offline: ${paths.join(", ")}`
            : "";
        node.classList.toggle("hidden", !paths.length);
    });
    if (!paths.length) return;
    const label = paths.length === 1 ? "folder" : "folders";
    notify(
        `${paths.length} library ${label} cannot be read: ${paths.join(", ")}. ` +
        `Scans skip offline folders and will not remove anything indexed under them.`,
        "warning",
    );
}

function noteUnreadablePaths(map) {
    const paths = offlinePathList(map);
    const stamp = paths.slice().sort().join("|");
    if (stamp === state.unreadablePathStamp) return;
    state.unreadablePathStamp = stamp;
    document.querySelectorAll("[data-unreadable-paths]").forEach((node) => {
        node.textContent = paths.length
            ? `${paths.length} library folder${paths.length === 1 ? "" : "s"} cannot be listed: ${paths.join(", ")}`
            : "";
        node.classList.toggle("hidden", !paths.length);
    });
    if (!paths.length) return;
    const label = paths.length === 1 ? "folder" : "folders";
    notify(
        `${paths.length} library ${label} exist but cannot be listed: ${paths.join(", ")}. ` +
        `Check permissions or the mount. Scans skip them and will not remove anything indexed ` +
        `under them.`,
        "error",
    );
}

function noteEmptyPaths(map) {
    const paths = offlinePathList(map);
    const stamp = paths.slice().sort().join("|");
    if (stamp === state.emptyPathStamp) return;
    state.emptyPathStamp = stamp;
    document.querySelectorAll("[data-empty-paths]").forEach((node) => {
        node.textContent = paths.length
            ? `${paths.length} library folder${paths.length === 1 ? " is" : "s are"} empty: ${paths.join(", ")}`
            : "";
        node.classList.toggle("hidden", !paths.length);
    });
    if (!paths.length) return;
    const label = paths.length === 1 ? "folder is" : "folders are";
    notify(
        `${paths.length} library ${label} empty: ${paths.join(", ")}. ` +
        `Nothing indexed under them is removed while they are empty. If a folder is finished ` +
        `with, take the path out in Settings and scan again to clear its items.`,
        "warning",
    );
}

function noteConnections(data) {
    paintConnectionErrors(data && data.connections);
    const items = (data && data.connection_notices) || [];
    if (!items.length) return;
    let seen = Number(sessionStorage.getItem("connection-notice") || 0);
    const newest = items.reduce((max, item) => Math.max(max, Number(item.id) || 0), 0);
    if (newest && newest < seen) seen = 0;
    items.forEach((item) => {
        const id = Number(item.id) || 0;
        if (id <= seen) return;
        notify(item.message, item.kind || "error");
        seen = id;
    });
    if (seen) sessionStorage.setItem("connection-notice", String(seen));
}

function paintConnectionErrors(connections) {
    const map = connections || {};
    document.querySelectorAll("[data-connection]").forEach((node) => {
        const item = map[node.dataset.connection];
        const text = item && item.message ? item.message : "";
        node.textContent = text ? `Connection error: ${text}` : "";
        node.classList.toggle("hidden", !text);
    });
}

function noteLidarr(data) {
    const items = (data.lidarr && data.lidarr.notices) || [];
    if (!items.length) return;
    let seen = Number(sessionStorage.getItem("lidarr-notice") || 0);
    const newest = items.reduce((max, item) => Math.max(max, Number(item.id) || 0), 0);
    if (newest && newest < seen) seen = 0;
    items.forEach((item) => {
        const id = Number(item.id) || 0;
        if (id <= seen) return;
        notify(item.message, item.kind || "info");
        seen = id;
    });
    if (seen) sessionStorage.setItem("lidarr-notice", String(seen));
}

async function rollbackBatch() {
    const data = await api("/api/batch/rollback", { method: "POST", body: {} });
    notify(`Rolled back ${data.tags || 0} tag snapshots and ${data.moves || 0} moves.`, "info");
    if (state.album) await selectAlbum(state.album.album.id, true);
    else await loadLibrary();
}
