// The movie and episode duplicate windows, and keeping the lists right after a copy is deleted.

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
    if (typeof sourceCovered === "function" && sourceCovered(group, format)) return sourceName(format);
    if (!groupKey || formatKey.includes(groupKey) || groupKey.includes(formatKey)) return format;
    return typeof sourceName === "function" ? `${sourceName(group)} ${sourceName(format)}` : `${group} ${format}`;
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
    if (arr.id && arr.linked === false) {
        // Sonarr has a record for this file but does not attach it to this episode: it is not the copy Sonarr uses.
        const other = (arr.episodes || []).length ? `attached to ${arr.episodes.join(", ")}` : "attached to no episode";
        return `<p class="dup-arr is-absent" title="Sonarr file ${escapeHtml(String(arr.id))}, ${escapeHtml(other)}">${icon}<span class="dup-arr-notin">Not this episode's file (${escapeHtml(other)})</span></p>`;
    }
    if (arr.id) {
        const label = arr.app === "Sonarr" ? "File" : "Id";
        const which = arr.linked ? " · in use" : "";
        return `<p class="dup-arr" title="${escapeHtml(arr.app)} ${label.toLowerCase()} ${escapeHtml(String(arr.id))}">${icon}<span class="dup-arr-id">${label} ${escapeHtml(String(arr.id))}${which}</span></p>`;
    }
    return `<p class="dup-arr is-absent"><span class="dup-arr-notin">Not in</span>${icon}</p>`;
}

// The Radarr and Sonarr lines are asked for after a copy window opened, so it opens without waiting for those apps.
// Each card's line is filled in place: nothing else in the window is redrawn, so a picked copy stays picked.
function fillArrLines(host, items, labels) {
    if (!host || !labels) return;
    const byId = new Map((items || []).map((item) => [String(item.id), item]));
    host.querySelectorAll(".video-dup-card").forEach((card) => {
        const item = byId.get(card.dataset.id);
        const label = labels[card.dataset.id];
        if (!item || !label) return;
        item.arr = label;
        const slot = card.querySelector(".dup-arr-slot");
        if (slot) slot.innerHTML = arrCopyLine(item);
    });
}

function videoDuplicateCard(item, kind, rows, suggested) {
    const shape = kind === "episode" ? "video-dup-thumb" : "video-dup-poster";
    const poster = item.poster
        ? `<img class="upgrade-cover ${shape}" src="${artUrl(item.poster, kind === "episode" ? 780 : 342)}" alt="">`
        : `<div class="art-fallback upgrade-cover ${shape}">${kind === "episode" ? "No thumbnail" : "No poster"}</div>`;
    const placeholder = /^(missing|wanted):\/\//.test(String(item.path || ""));
    const file = String(item.path || "").split(/[\\/]/).pop();
    const failed = typeof failPill === "function" ? failPill("probe", item.probe_error) : "";
    const notes = [
        placeholder ? `<p class="dup-keep">No file on disk, only a placeholder</p>` : "",
        failed ? `<p class="dup-probe">${failed}</p>` : "",
    ].join("");
    const attrs = `data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(item.id)}"`;
    return compareCardHtml({
        id: item.id,
        picture: poster,
        name: file || item.title || "Copy",
        lines: [videoDuplicateFactsHtml(item, rows || videoDuplicateFactRows([item]))],
        keep: !!suggested,
        note: notes,
        arr: arrCopyLine(item),
        path: placeholder ? "" : (item.filepath || item.path || ""),
        del: placeholder ? "" : `data-action="delete-video-duplicate" ${attrs}`,
        remove: `data-action="remove-video-duplicate" ${attrs}`,
    }).replace('class="video-dup-card compare-card', `class="video-dup-card compare-card${failed ? " is-probe-failed" : ""}`);
}

function videoDuplicateSection(title, groups, kind, focused) {
    const items = groups || [];
    if (!items.length) return `<p class="muted">None.</p>`;
    return items.map((group) => {
        const copies = group.items || [];
        const rows = videoDuplicateFactRows(copies);
        const keep = typeof suggestedKeepId === "function" ? suggestedKeepId(copies) : "";
        const cards = copies.map((item) => videoDuplicateCard(item, kind, rows, item.id === keep)).join("");
        // A second file of an episode cannot be marked Not duplicates.
        const dismiss = copies.some((copy) => copy.extra) ? "" : compareDismissButtons(
            copies.map((copy) => ({ ...copy, label: String(copy.path || "").split(/[\\/]/).pop() })),
            (left, right) => `data-action="dismiss-video-duplicate" data-kind="${escapeHtml(kind)}" data-left="${escapeHtml(left.id)}" data-right="${escapeHtml(right.id)}"`,
        );
        return compareGroupHtml({
            heading: focused ? "" : (group.label || title),
            reason: group.reason || "",
            warning: typeof showFolderWarning === "function" ? showFolderWarning(copies) : "",
            cards,
            actions: dismiss,
        });
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
    // What the info pane shows and which copies belong together, read before the copy leaves the lists.
    const before = copyPaneBefore(kind, id);
    let peers = [];
    let kept = false;
    try {
        if (mode === "delete") {
            const data = await api("/api/v1/delete", { method: "POST", body: { kind, ids: [id], keep_copy: true } });
            const deleted = data.deleted || [];
            const errors = data.errors || [];
            if (!deleted.length) {
                clearCopyDeleting(id);
                notify(errors[0] || "That copy was not deleted.", "error");
                return;
            }
            peers = data.peers || [];
            kept = (data.promoted || []).includes(id);
            notify(errors.length ? `Deleted ${deleted[0]}. ${errors[0]}` : `${deleted[0]} was deleted from disk.`, errors.length ? "warning" : "success");
        } else {
            const data = await api("/api/v1/remove", { method: "POST", body: { kind, ids: [id], keep_copy: true } });
            if (!data.removed) {
                clearCopyDeleting(id);
                notify("That copy is no longer in the library.", "info");
                return;
            }
            peers = data.peers || [];
            kept = (data.promoted || []).includes(id);
            notify("Removed from the library. The file is still on disk.", "info");
        }
    } catch (error) {
        clearCopyDeleting(id);
        throw error;
    }
    dropVideoDuplicate(kind, id, kept);
    applyPeerFlags(peers);
    forgetDuplicateUndo([id]);
    refreshCopyPane(before, kept);
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

// keepRow: the episode stays in the library with its other file, so only that file is gone from the lists.
function dropVideoDuplicate(kind, id, keepRow) {
    const found = findVideoDuplicate(id);
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
    if (kind === "episode" && (keepRow || String(id).startsWith("file:"))) {
        const owner = (found && found.owner_id) || id;
        reloadEpisodeShow(owner);
    } else if (kind === "episode") dropEpisodeRow(id, siblings);
    else dropMovieRow(id, siblings);
    const video = { movies: [], episodes: [] };
    video[kind === "episode" ? "episodes" : "movies"] = state.videoDuplicateGroups || [];
    renderDuplicateList({ pairs: [] }, video);
    if (typeof loadMediaTotals === "function") loadMediaTotals();
}

// The info pane and the copies of one title, as they were before a copy was deleted or removed.
function copyPaneBefore(kind, id) {
    const found = findVideoDuplicate(id) || {};
    const owner = String(found.owner_id || id);
    const siblings = copySiblings(id).map((item) => String(item)).filter((item) => !item.startsWith("file:"));
    const sel = (state.video && state.video.tvSel) || null;
    const showIds = kind === "episode" && typeof tvShowIdFor === "function"
        ? [...new Set([owner, ...siblings].map((item) => tvShowIdFor("episode", item)).filter(Boolean))]
        : [];
    return {
        kind, id: String(id), owner, siblings, showIds,
        episode: sel && sel.type === "episode" ? String(sel.id) : "",
        movie: state.video && state.video.movieId ? String(state.video.movieId) : "",
    };
}

// After a copy is deleted or removed, the info pane shows the file that is left: the open item is read again, and
// when the open item was the one that went, the pane moves to a copy that stayed.
async function refreshCopyPane(before, kept) {
    if (!before) return;
    const family = new Set([before.id, before.owner, ...before.siblings]);
    try {
        if (before.kind === "episode") {
            for (const showId of before.showIds) await showDetail(showId, true);
            if (before.showIds.length && state.media === "tv" && typeof renderTvTree === "function") renderTvTree();
            if (!before.episode || !family.has(before.episode) || typeof openEpisode !== "function") return;
            const gone = before.episode === before.id && !kept;
            const target = gone ? before.siblings[0] : before.episode;
            if (target) await openEpisode(target, true);
            return;
        }
        if (!before.movie || !family.has(before.movie) || typeof openMovie !== "function") return;
        const target = before.movie === before.id ? before.siblings[0] : before.movie;
        if (target && state.media === "movies") await openMovie(target, true);
    } catch (error) {
        // The list is read again on the next refresh.
    }
}

// Read the show of an episode again so its row shows the file it has now, and its versions.
async function reloadEpisodeShow(episodeId) {
    const showId = typeof tvShowIdFor === "function" ? tvShowIdFor("episode", episodeId) : "";
    if (!showId) return;
    try {
        await showDetail(showId, true);
        if (state.media === "tv" && typeof renderTvTree === "function") renderTvTree();
        const sel = state.video.tvSel;
        if (sel && sel.type === "episode" && String(sel.id) === String(episodeId) && typeof openEpisode === "function") openEpisode(episodeId, true);
    } catch (error) {
        // The list is read again on the next refresh.
    }
}

function clearCopyMarks(item) {
    if (!item) return;
    item.duplicate_release = false;
    item.upgrade = false;
    item.upgrade_path = "";
}

// A show or season carries the pill when any of its episodes does, so it follows its episodes.
function rollUpEpisodeMarks(detail) {
    const episodes = (detail.episodes || []).filter((episode) => !episode.missing);
    const upgrade = episodes.some((episode) => episode.upgrade);
    const duplicate = episodes.some((episode) => episode.duplicate_release);
    const apply = (item, list) => {
        if (!item) return;
        item.upgrade = list.some((episode) => episode.upgrade);
        item.duplicate_release = list.some((episode) => episode.duplicate_release);
    };
    apply(detail, episodes);
    apply((state.video.shows || []).find((show) => String(show.id) === String(detail.id)), episodes);
    (detail.seasons || []).forEach((season) => apply(season, episodes.filter((episode) => episode.season_id === season.id)));
    return upgrade || duplicate;
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
            let touched = false;
            (detail.episodes || []).forEach((episode) => { if (paint(episode)) { video = true; touched = true; } });
            if (touched) rollUpEpisodeMarks(detail);
        });
    }
    (state.artists || []).forEach((artist) => {
        (artist.albums || []).forEach((album) => { if (paint(album)) music = true; });
    });
    if (state.album && state.album.album && paint(state.album.album)) music = true;
    if (state.video && typeof showDetail === "function") {
        // Shows that were never opened keep their pill until their episodes are read again.
        const loaded = state.video.showDetails || new Map();
        [...new Set(rows.map((row) => row.show_id).filter((id) => id && !loaded.has(String(id))))].forEach((id) => {
            showDetail(id, true).then((detail) => {
                rollUpEpisodeMarks(detail);
                state.video.showDetails.delete(id);
                if (typeof paintCurrentVideoList === "function") paintCurrentVideoList();
            }).catch(() => {});
        });
    }
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
