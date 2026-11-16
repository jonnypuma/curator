function placeMenu(menu, event) {
    const margin = 8;
    menu.classList.remove("hidden");
    menu.style.maxHeight = "none";
    menu.style.top = "0px";
    menu.style.left = "0px";
    const width = menu.offsetWidth || 220;
    const needed = menu.scrollHeight || menu.offsetHeight || 180;
    const available = Math.max(margin, window.innerHeight - margin * 2);
    const height = Math.min(needed, available);
    menu.style.maxHeight = `${height}px`;
    const left = Math.max(margin, Math.min(event.clientX, window.innerWidth - width - margin));
    let top = event.clientY;
    if (top + height > window.innerHeight - margin) top = Math.max(margin, window.innerHeight - height - margin);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
}

function onDiffMenu(event) {
    const cell = event.target.closest("[data-diff-key]");
    if (!cell || !proposalFor(currentTrack() && currentTrack().id)) return;
    event.preventDefault();
    const albumMenu = document.getElementById("album-menu");
    if (albumMenu) albumMenu.classList.add("hidden");
    state.diffCell = { key: cell.dataset.diffKey, side: cell.dataset.diffSide };
    const onProposed = state.diffCell.side === "proposed";
    const items = [
        ["edit", "Edit...", true],
        ["use-embedded", "Use embedded value", onProposed],
        ["remove", "Remove", true],
        ["copy", "Copy", true],
        ["paste", "Paste", true],
    ];
    const menu = document.getElementById("diff-menu");
    menu.innerHTML = items.map(([kind, label, enabled]) =>
        `<button type="button" role="menuitem" data-action="diff-command" data-diff-command="${kind}" ${enabled ? "" : "disabled"}>${escapeHtml(label)}</button>`
    ).join("");
    placeMenu(menu, event);
}

function menuAlbumIds(albumId) {
    const ids = selectionIds("album", albumId);
    state.contextAlbumIds = ids;
    return ids;
}

async function rewriteSelectedNfos(ids) {
    if (!ids || !ids.length) ids = albumActionIds().length ? albumActionIds() : (state.contextAlbum ? [state.contextAlbum] : []);
    if (!ids.length) return;
    const data = await api("/api/albums/nfo", { method: "POST", body: { album_ids: ids } });
    const written = Number(data.written) || 0;
    const problems = [...(data.errors || []), ...(data.skipped || []).map((title) => `${title} is on a read-only mount`)];
    if (written) notify(`Rewrote .nfo files for ${written} album${written === 1 ? "" : "s"}.`, "info");
    (data.ids || []).forEach((id) => applyAlbumNfoStale(id, false));
    if (data.ids && data.ids.length) renderTree();
    if (problems.length) notify(problems.slice(0, 3).join(" "), written ? "warning" : "error");
    else if (!written) notify("No .nfo files were written.", "warning");
    if (state.album && ids.includes(state.album.album.id)) await selectAlbum(state.album.album.id, true);
}

function onTreeMenu(event) {
    if (event.target.closest(".album-item, .album-line[data-album], .vgrid-card[data-album]")) return onAlbumMenu(event);
    const row = event.target.closest(".artist-row");
    if (row) onArtistMenu(event, row);
}

function fullySelectedArtistIds() {
    return (state.artists || []).filter((artist) => {
        const ids = visibleAlbumIds(artist);
        return ids.length > 0 && ids.every((id) => state.selected.has(id));
    }).map((artist) => artist.id);
}

function menuArtistIds(artistId) {
    const chosen = fullySelectedArtistIds();
    if (chosen.includes(artistId)) return chosen;
    const artist = (state.artists || []).find((row) => row.id === artistId);
    const ids = visibleAlbumIds(artist);
    selectionReplace("album", ids);
    renderTree();
    return [artistId];
}

// One grammar for every library's menu: verb and object, with the count in brackets when more than one is picked.
function menuLabel(text, count) {
    return count > 1 ? `${text} (${count})` : text;
}

function fillContextMenu(items, action) {
    const menu = document.getElementById("album-menu");
    menu.innerHTML = items.map(([kind, label, enabled, danger, title, raw]) => {
        const off = enabled === "off";
        const classes = [danger ? "menu-danger" : "", off ? "is-unavailable" : ""].filter(Boolean).join(" ");
        const trash = kind === "trash" ? " menu-trash" : "";
        const named = kind === "trash" && title ? ` aria-label="${escapeHtml(title)}"` : "";
        return `<button type="button" role="menuitem" class="${classes}${trash}" data-action="${action}" data-menu="${kind}" ${enabled ? "" : "disabled"}${title ? ` title="${escapeHtml(title)}"` : ""}${named}>${raw ? label : escapeHtml(label)}</button>`;
    }).join("");
    return menu;
}

function onArtistMenu(event, row) {
    event.preventDefault();
    const artistId = row.dataset.openArtist;
    if (!artistId) return;
    const ids = menuArtistIds(artistId);
    state.contextArtists = ids;
    const count = ids.length;
    const artists = (state.artists || []).filter((artist) => ids.includes(artist.id));
    const writable = artists.some((artist) => libraryWritable(artist.path));
    const diffMenu = document.getElementById("diff-menu");
    if (diffMenu) diffMenu.classList.add("hidden");
    const items = [
        ["find-metadata", menuLabel("Find metadata", count), true],
        ["download-art", menuLabel("Download missing artwork", count), writable],
        ["lookup-art", menuLabel("Look up artwork…", count), true],
        ["download-lyrics", menuLabel("Download lyrics", count), writable],
        ["rewrite-nfo", menuLabel("Write .nfo", count), writable],
        ["arr-rescan", `Update library in ${providerIcon("lidarr")}${count > 1 ? ` (${count})` : ""}`, integrationOn("lidarr") ? true : "off", false, "Ask Lidarr to rescan", true],
        ["library-update", menuLabel("Update library", count), true, false, "Ask Kodi, Emby, Jellyfin and Plex to scan these artist folders"],
        ["move", menuLabel("Move…", count), writable],
        ["mark-processed", menuLabel("Mark as processed", count), true],
        ["ignore-artist", menuLabel(artists.length && artists.every((artist) => artist.status === "IGNORED") ? "Stop ignoring" : "Ignore", count), true],
        ["lock-artist", menuLabel(artists.length && artists.every((artist) => artist.locked) ? "Unlock" : "Lock", count), true],
        ["trash", `${trashSvg()}<span>${escapeHtml(menuLabel("Remove or delete…", count))}</span>`, true, true, menuLabel("Remove from library or delete from disk", count), true],
    ];
    placeMenu(fillContextMenu(items, "artist-menu"), event);
}

function onAlbumMenu(event) {
    const button = event.target.closest(".album-item, .album-line[data-album], .vgrid-card[data-album]");
    if (!button) return;
    event.preventDefault();
    const albumId = button.dataset.album;
    const ids = menuAlbumIds(albumId);
    const listed = visibleAlbums().find((row) => row.album.id === albumId);
    const album = listed && listed.album;
    state.contextAlbum = albumId;
    const writable = !album || libraryWritable(album.path);
    const targets = visibleAlbums().filter((row) => ids.includes(row.album.id));
    const anyWritable = targets.some((row) => libraryWritable(row.album.path));
    const count = ids.length || 1;
    const pending = ids.some((id) => state.pending[id] || (state.album && state.album.album.id === id && state.proposal));
    const alignable = !!(state.pending[albumId] || (state.album && state.album.album.id === albumId && state.proposal));
    const diffMenu = document.getElementById("diff-menu");
    if (diffMenu) diffMenu.classList.add("hidden");
    const items = [
        ["match", menuLabel("Find metadata", count), true],
        ["apply", menuLabel("Apply match", count), pending && anyWritable],
        ["cancel-proposal", menuLabel("Clear match", count), pending],
        ["toggle-aligner", menuLabel("Align tracks", count), alignable],
        ["artwork", menuLabel("Look up artwork…", count), true],
        ["download-missing-art", menuLabel("Download missing artwork", count), anyWritable],
        ["download-lyrics", menuLabel("Download lyrics", count), anyWritable],
        ["rewrite-nfo", menuLabel("Write .nfo", count), anyWritable],
        ["rename-items", menuLabel("Rename files…", count), anyWritable],
        ["library-update", menuLabel("Update library", count), true, false, "Ask Kodi, Emby, Jellyfin and Plex to scan the artist folders of these albums"],
        ["edit-fields", menuLabel("Edit fields…", count), count > 1],
        ["compilation", menuLabel("Treat as compilation", count), anyWritable],
        ["replaygain", menuLabel("Set ReplayGain", count), anyWritable],
        ["audit", menuLabel("Audit audio (integrity)", count), true],
        ["check-gaps", menuLabel("Check missing tracks", count), true],
        ["mark-album", menuLabel("Mark as processed", count), true],
        ["ignore-album", menuLabel(targets.length && targets.every((row) => row.album.status === "IGNORED") ? "Stop ignoring" : "Ignore", count), true],
        ["lock-album", menuLabel(targets.length && targets.every((row) => row.album.locked) ? "Unlock" : "Lock", count), true],
        ["trash", `${trashSvg()}<span>${escapeHtml(menuLabel("Remove or delete…", count))}</span>`, true, true, menuLabel("Remove from library or delete from disk", count), true],
    ];
    if (album && album.cue_image) items.push(["open-split", "Split into tagged tracks", writable]);
    if (album && album.upgrade) items.push(["show-upgrade", "Upgrade available", true]);
    placeMenu(fillContextMenu(items, "album-menu"), event);
}

async function runAlbumMenu(kind) {
    document.getElementById("album-menu").classList.add("hidden");
    const albumId = state.contextAlbum;
    const ids = selectedAlbumIds();
    if (!albumId || !kind || !ids.length) return;
    if (kind === "match") {
        if (ids.length > 1) return openLookupModal();
        if (!state.album || state.album.album.id !== albumId) await selectAlbum(albumId);
        return findMetadata();
    }
    if (kind === "apply") return applySelectedMatches();
    if (kind === "cancel-proposal") return clearSelectedMatches();
    if (kind === "toggle-aligner") {
        if (!state.album || state.album.album.id !== albumId) await selectAlbum(albumId);
        state.proposal = state.pending[albumId] || state.proposal;
        if (!state.proposal) return;
        state.aligner = !state.aligner;
        renderTracks();
        return;
    }
    if (kind === "download-missing-art") return downloadMissingArt(ids);
    if (kind === "download-lyrics") return downloadLyrics({ album_ids: ids });
    if (kind === "artwork") return startArtworkQueue(ids);
    if (kind === "rewrite-nfo") return rewriteSelectedNfos();
    if (kind === "rename-items") return openRenameModal();
    if (kind === "edit-fields") return openBatchEdit("album", ids);
    if (kind === "compilation") return treatSelectedCompilations(ids);
    if (kind === "replaygain") return runSelectedAlbumJobs(ids, "replaygain");
    if (kind === "audit") return runSelectedAlbumJobs(ids, "audit");
    if (kind === "check-gaps") return runSelectedAlbumJobs(ids, "gaps");
    if (kind === "mark-album") return completeSelectedProcessed(ids);
    if (kind === "library-update") {
        const owners = new Map();
        visibleAlbums().filter((row) => ids.includes(row.album.id)).forEach((row) => {
            if (!owners.has(row.artist.id)) owners.set(row.artist.id, row.album.id);
        });
        return sendMusicLibraryUpdates([...owners.values()]);
    }
    if (kind === "ignore-album") {
        const albums = visibleAlbums().filter((row) => ids.includes(row.album.id)).map((row) => row.album);
        const status = albums.length && albums.every((album) => album.status === "IGNORED") ? "new" : "ignored";
        const data = await api("/api/albums/mark", { method: "POST", body: { ids, status } });
        paintAlbumStatus(data.updated || ids, data.status || status);
        notify(status === "ignored" ? "Selected albums ignored." : "Selected albums are back in the library.", "info");
        return;
    }
    if (kind === "lock-album") {
        const albums = visibleAlbums().filter((row) => ids.includes(row.album.id)).map((row) => row.album);
        return lockLibraryRows("album", ids, !(albums.length && albums.every((album) => album.locked)));
    }
    if (kind === "trash") {
        const count = ids.length;
        const label = `${count} album${count === 1 ? "" : "s"}`;
        const albums = visibleAlbums().filter((row) => ids.includes(row.album.id)).map((row) => row.album);
        return askMusicRemoval(label, albums.some((album) => libraryWritable(album.path)),
            `Delete from disk removes ${count === 1 ? "the album folder" : "each album folder"} and the audio files in it.`,
            () => deleteLibrary({ album_ids: ids }, label), () => forgetLibrary({ album_ids: ids }, label));
    }
    if (!state.album || state.album.album.id !== albumId) await selectAlbum(albumId);
    if (!state.album) return;
    if (kind === "open-split") {
        document.getElementById("split-modal").classList.remove("hidden");
        return;
    }
    if (kind === "show-upgrade") return showUpgrade();
}

// One library update per artist folder, the same request as Send library update on the album page.
async function sendMusicLibraryUpdates(albumIds) {
    let sent = 0;
    const errors = [];
    for (const id of albumIds) {
        try {
            await api(`/api/albums/${encodeURIComponent(id)}/library-update`, { method: "POST", body: {} });
            sent += 1;
        } catch (error) {
            errors.push(error.message);
        }
    }
    if (!sent && errors.length) throw new Error(errors[0]);
    const done = `Library update queued for ${sent} artist${sent === 1 ? "" : "s"}.`;
    notify(errors.length ? `${done} ${errors[0]}` : done, errors.length ? "warning" : "info");
}

async function runArtistMenu(kind) {
    document.getElementById("album-menu").classList.add("hidden");
    const ids = state.contextArtists || [];
    if (!ids.length || !kind) return;
    if (kind === "find-metadata") return findMetadataForArtists(ids);
    if (kind === "download-art") return downloadArtistArtwork(ids);
    if (kind === "download-lyrics") return downloadLyrics({ artist_ids: ids });
    if (kind === "lookup-art") {
        state.artworkQueueSubject = "artist";
        state.artworkQueue = ids.slice(1);
        state.artworkQueueTotal = ids.length;
        return openQueuedArtwork(ids[0]);
    }
    if (kind === "arr-rescan") {
        if (arrSearchBlocked("lidarr")) return;
        notify("Asking Lidarr to rescan…", "info");
        const data = await api("/api/v1/library/arr-rescan", { method: "POST", body: { kind: "artist", ids } });
        notify(data.message || "Rescan queued.", data.sent ? "success" : "warning");
        return;
    }
    if (kind === "rewrite-nfo") return rewriteArtistNfos(ids);
    if (kind === "library-update") {
        const albums = (state.artists || []).filter((row) => ids.includes(row.id) && (row.albums || []).length)
            .map((row) => row.albums[0].id);
        if (!albums.length) throw new Error("These artists have no albums to send.");
        return sendMusicLibraryUpdates(albums);
    }
    if (kind === "move") return openVideoMove("artist", ids);
    if (kind === "mark-processed") return markArtistsProcessed(ids);
    if (kind === "ignore-artist") {
        const artists = (state.artists || []).filter((row) => ids.includes(row.id));
        return markArtistsStatus(ids, artists.length && artists.every((row) => row.status === "IGNORED") ? "new" : "ignored");
    }
    if (kind === "lock-artist") {
        const artists = (state.artists || []).filter((row) => ids.includes(row.id));
        return lockLibraryRows("artist", ids, !(artists.length && artists.every((row) => row.locked)));
    }
    if (kind === "trash") {
        const count = ids.length;
        const label = `${count} artist${count === 1 ? "" : "s"}`;
        const artists = (state.artists || []).filter((row) => ids.includes(row.id));
        return askMusicRemoval(label, artists.some((artist) => libraryWritable(artist.path)),
            "Delete from disk removes the artist folders with their albums and music files.",
            () => deleteLibrary({ artist_ids: ids }, label), () => forgetLibrary({ artist_ids: ids }, label));
    }
}

/* The window behind the menu's red bin: Delete from disk, or Remove from library. A folder Curator cannot write to
   only offers Remove from library. */
function askMusicRemoval(label, writable, diskText, deleteAction, forgetAction) {
    if (!writable) {
        return askDanger(
            `Remove ${label} from the library?`,
            "The files are on a folder Curator cannot write to, so they can only be removed from the library. The files stay on disk.",
            "Remove from library",
            forgetAction,
            false,
        );
    }
    return askDanger(
        `Remove ${label}?`,
        `${diskText} This cannot be undone. Removing from the library leaves the files in place.`,
        "Delete from disk",
        deleteAction,
        true,
        forgetAction,
    );
}

// What happens to a deleted file: the recycle bin keeps it for some days, or it is gone at once.
function trashWarning() {
    const cfg = state.settings || {};
    if (cfg.trash_enabled === false) return "Delete from disk cannot be undone.";
    const days = Math.max(1, Number(cfg.trash_days) || 30);
    return `Delete from disk moves the files to the recycle bin for ${days} day${days === 1 ? "" : "s"} (Settings, General).`;
}

// libraryAction is the function behind the "Remove from library" button (none: no button). trashNote shows the recycle
// bin warning without that button, for a delete that has no "remove from the library only" alternative.
function askDanger(title, text, confirmLabel, action, danger, libraryAction, trashNote) {
    state.dangerAction = action;
    state.dangerLibraryAction = libraryAction || null;
    document.getElementById("danger-title").textContent = title;
    document.getElementById("danger-text").textContent = text;
    const button = document.getElementById("danger-confirm");
    button.textContent = confirmLabel;
    button.className = danger ? "btn-danger" : "";
    const library = document.getElementById("danger-library");
    if (library) library.classList.toggle("hidden", !libraryAction);
    const warn = document.getElementById("danger-warn");
    if (warn) {
        const show = !!(danger && (libraryAction || trashNote));
        warn.classList.toggle("hidden", !show);
        warn.textContent = show ? trashWarning() : "";
    }
    document.getElementById("danger-modal").classList.remove("hidden");
}

async function confirmDanger() {
    const action = state.dangerAction;
    state.dangerAction = null;
    state.dangerLibraryAction = null;
    document.getElementById("danger-modal").classList.add("hidden");
    if (action) await action();
}

async function confirmDangerLibrary() {
    const action = state.dangerLibraryAction;
    state.dangerAction = null;
    state.dangerLibraryAction = null;
    document.getElementById("danger-modal").classList.add("hidden");
    if (action) await action();
}

function askBatchAlbumRemoval(disk) {
    const ids = [...selectionChecked("album")];
    if (!ids.length) return;
    const count = ids.length;
    const label = `${count} album${count === 1 ? "" : "s"}`;
    if (!disk) {
        return askDanger(
            `Remove ${label} from the library?`,
            "Files on disk are not touched. The next scan adds them back unless you delete or move them.",
            "Remove from library",
            () => forgetLibrary({ album_ids: ids }, label),
            false,
        );
    }
    return askDanger(
        `Delete ${label} from disk?`,
        "Delete from disk removes each album folder and the audio files in it. This cannot be undone. Removing from the library leaves the files in place.",
        "Delete from disk",
        () => deleteLibrary({ album_ids: ids }, label),
        true,
        () => forgetLibrary({ album_ids: ids }, label),
    );
}

async function removeAllNotFoundMusic() {
    const data = await api("/api/library/held-albums");
    const ids = data.ids || [];
    if (!ids.length) {
        state.filterCounts = { ...(state.filterCounts || {}), "prune-held": 0 };
        renderSelectedCount();
        notify("No albums are marked Not found.", "info");
        return;
    }
    const label = `${ids.length} album${ids.length === 1 ? "" : "s"}`;
    askDanger(
        `Remove ${label} marked Not found?`,
        "A scan could not find these albums, and prune safety kept them because too much was missing at once. Check that the drive is mounted and the folders are there before you continue. The albums leave the database; files on disk are not touched, and the next scan adds them back if the folders exist.",
        "Remove from database",
        async () => {
            await forgetLibrary({ album_ids: ids }, label);
            state.filterCounts = { ...(state.filterCounts || {}), "prune-held": 0 };
            renderSelectedCount();
        },
        true,
    );
}

async function forgetLibrary(body, label) {
    const data = await api("/api/library/forget", { method: "POST", body });
    selectionReplace("album", []);
    state.contextArtists = [];
    if (state.album && body.album_ids && body.album_ids.includes(state.album.album.id)) state.album = null;
    if (state.album && state.album.artist && body.artist_ids && body.artist_ids.includes(state.album.artist.id)) {
        state.album = null;
        state.trackId = null;
        state.proposal = null;
    }
    if (state.artistId && body.artist_ids && body.artist_ids.includes(state.artistId)) {
        state.artistId = null;
        state.artistDetail = null;
        state.center = "album";
    }
    applyPeerFlags(data.peers);
    forgetDuplicateUndo(body.album_ids, data.track_ids);
    dropLibraryRows(body);
    renderCenter();
    notify(`Removed ${label} from the database. The files are still on disk.`, "info");
    return data;
}

async function deleteLibrary(body, label) {
    const data = await api("/api/library/delete", { method: "POST", body });
    selectionReplace("album", []);
    state.contextArtists = [];
    if (state.album && body.album_ids && body.album_ids.includes(state.album.album.id)) state.album = null;
    if (state.album && state.album.artist && body.artist_ids && body.artist_ids.includes(state.album.artist.id)) {
        state.album = null;
        state.trackId = null;
        state.proposal = null;
    }
    if (state.artistId && body.artist_ids && body.artist_ids.includes(state.artistId)) {
        state.artistId = null;
        state.artistDetail = null;
        state.center = "album";
    }
    applyPeerFlags(data.peers);
    forgetDuplicateUndo(body.album_ids, data.track_ids);
    dropLibraryRows(body);
    renderCenter();
    const errors = data.errors || [];
    if (errors.length) notify(`Deleted ${ (data.deleted || []).length }. ${errors[0]}`, "warning");
    else notify(`Deleted ${label} from disk.`, "info");
}

async function applySelectedMatches() {
    commitOpenDiffEdit();
    stashProposal();
    const ids = albumActionIds().filter((id) => state.pending[id]);
    if (state.album && state.proposal && albumActionIds().includes(state.album.album.id) && !ids.includes(state.album.album.id)) {
        ids.push(state.album.album.id);
        setPending(state.album.album.id, state.proposal);
    }
    if (!ids.length) return;
    return applyMatchesInBulk(ids);
}

// Bulk album and artist actions run as one job in the Jobs panel (resonance/bulk.py), with progress and Stop, instead
// of one request per album. Resolves with the finished job: status, message, log, and the done and failed ids.
async function runBulkJob(action, ids, proposals) {
    const data = await api("/api/bulk", { method: "POST", body: { action, ids, proposals: proposals || {} } });
    if (!data.started) throw new Error("Another bulk job is running. Let it finish, or stop it in the Jobs panel.");
    if (typeof schedulePoll === "function") schedulePoll(300);
    const id = data.job.id;
    let wait = 400;
    for (;;) {
        await new Promise((resolve) => setTimeout(resolve, wait));
        wait = 1500;
        const job = await api(`/api/bulk/${encodeURIComponent(id)}`);
        if (job.status !== "running") return job;
    }
}

function bulkNotice(job) {
    const failed = (job.failed || []).length;
    const firstFailure = String(job.log || "").split(/\r?\n/).find((line) => line.startsWith("Failed")) || "";
    if (failed || job.status === "cancelled") notify(`${job.message}.${firstFailure ? ` ${firstFailure}` : ""}`, "warning");
    else notify(`${job.message}.`, "info");
}

async function applyMatchesInBulk(ids) {
    const proposals = {};
    ids.forEach((id) => { if (state.pending[id]) proposals[id] = state.pending[id]; });
    const job = await runBulkJob("apply", Object.keys(proposals), proposals);
    for (const id of job.done || []) {
        const proposal = proposals[id];
        setPending(id, null);
        if (state.album && state.album.album.id === id) state.proposal = null;
        ((proposal && proposal.tracks) || []).forEach((track) => { delete state.tagDrafts[track.id]; });
    }
    await refreshLibraryItems(ids);
    renderCenter();
    renderEditor();
    bulkNotice(job);
}

function clearSelectedMatches() {
    albumActionIds().forEach((id) => { setPending(id, null); });
    if (state.album && albumActionIds().includes(state.album.album.id)) {
        state.proposal = null;
        state.aligner = false;
    }
    renderTree();
    renderCenter();
    renderEditor();
    notify("Cleared the loaded matches for the selected albums.", "info");
}

async function treatSelectedCompilations(ids) {
    const job = await runBulkJob("compilation", ids);
    await refreshLibraryItems(ids);
    if (state.center === "album" && state.album && ids.includes(state.album.album.id)) await selectAlbum(state.album.album.id, true);
    bulkNotice(job);
}

async function runSelectedAlbumJobs(ids, kind) {
    const job = await runBulkJob(kind, ids);
    await refreshLibraryItems(ids);
    if (state.center === "album" && state.album && ids.includes(state.album.album.id)) await selectAlbum(state.album.album.id, true);
    bulkNotice(job);
}

async function findMetadataForArtists(ids) {
    if (ids.length === 1) {
        if (state.artistId !== ids[0]) await selectArtist(ids[0]);
        return scrapeArtist();
    }
    const job = await runBulkJob("artist-metadata", ids);
    await refreshLibraryItems([], ids);
    if (state.center === "artist" && state.artistId) await selectArtist(state.artistId);
    bulkNotice(job);
}

async function downloadLyrics(body) {
    const data = await api("/api/lyrics/download", { method: "POST", body });
    if (!data.started) throw new Error("A lyrics download is already running.");
    state.missingLyricsSeen = "running";
    state.working = true;
    schedulePoll(300);
    notify("Searching and downloading lyrics. Tracks that already have lyrics are skipped. Progress is in the Jobs panel, and a notice says what was saved when it ends.", "info");
}

async function downloadArtistArtwork(ids) {
    const data = await api("/api/artwork/deploy-missing-artists", { method: "POST", body: { artist_ids: ids } });
    if (!data.started) throw new Error("An artist artwork download is already running.");
    state.missingArtistArtSeen = "running";
    state.working = true;
    schedulePoll(300);
    notify(ids.length === 1 ? "Downloading missing artist artwork." : `Downloading missing artist artwork for ${ids.length} artists.`, "info");
}

async function rewriteArtistNfos(ids) {
    let done = 0;
    const errors = [];
    for (const id of ids) {
        try {
            const data = await api(`/api/artists/${id}/nfo`, { method: "POST", body: {} });
            if (data.nfo_warning) errors.push(data.nfo_warning);
            else done += 1;
        } catch (error) {
            errors.push(error.message);
        }
    }
    if (state.center === "artist" && ids.includes(state.artistId)) await selectArtist(state.artistId);
    if (errors.length) notify(`Wrote ${done} artist.nfo files. ${errors[0]}`, "warning");
    else notify(`Rewrote artist.nfo for ${done} artist${done === 1 ? "" : "s"}.`, "info");
}

async function markArtistsStatus(ids, status) {
    let done = 0;
    const errors = [];
    const updated = [];
    for (const id of ids) {
        try {
            await api(`/api/artists/${id}/mark`, { method: "POST", body: { status } });
            updated.push(id);
            done += 1;
        } catch (error) {
            errors.push(error.message);
        }
    }
    paintArtistStatus(updated, status);
    const label = status === "ignored" ? "ignored" : "set back to new";
    if (errors.length) notify(`Updated ${done}. ${errors[0]}`, "warning");
    else notify(`${done} artist${done === 1 ? "" : "s"} ${label}.`, "info");
}

async function markArtistsProcessed(ids) {
    let done = 0;
    const errors = [];
    const updated = [];
    for (const id of ids) {
        try {
            await api(`/api/artists/${id}/mark`, { method: "POST", body: { status: "processed" } });
            updated.push(id);
            done += 1;
        } catch (error) {
            errors.push(error.message);
        }
    }
    paintArtistStatus(updated, "processed");
    if (errors.length) notify(`Marked ${done}. ${errors[0]}`, "warning");
    else notify(`Marked ${done} artist${done === 1 ? "" : "s"} as processed.`, "info");
}

function onTrackMenu(event) {
    const row = event.target.closest("tr[data-track], [data-side='local']");
    if (!state.album || !row) return;
    const trackId = row.dataset.track;
    if (!trackId) return;
    const track = (state.album.tracks || []).find((item) => item.id === trackId);
    const already = state.trackIds.has(trackId);
    const many = already && selectedTracks().length >= 2;
    const songDiffers = !!(track && songTagsDiffer(track));
    const albumDiffers = albumTagsDiffer();
    if (!songDiffers && !albumDiffers && !many) return;
    event.preventDefault();
    state.contextTrack = trackId;
    if (!already) {
        selectTrack(trackId, { shiftKey: false, ctrlKey: false, metaKey: false });
        renderTracks();
        renderEditor();
    }
    const albumMenu = document.getElementById("album-menu");
    if (albumMenu) albumMenu.classList.add("hidden");
    const diffMenu = document.getElementById("diff-menu");
    if (diffMenu) diffMenu.classList.add("hidden");
    const items = [];
    if (state.proposal) {
        items.push(["keep-old-song", "Keep old song ID3 values", songDiffers]);
        items.push(["keep-old-album", "Keep old album ID3 values", albumDiffers]);
    }
    const menu = document.getElementById("track-menu");
    const keep = items.map(([kind, label, enabled]) =>
        `<button type="button" data-action="${kind}" ${enabled ? "" : "disabled"}>${escapeHtml(label)}</button>`
    ).join("");
    const numbering = many
        ? `<button type="button" data-action="auto-number">Auto-number tracks (${selectedTracks().length})</button>
            <label>Disc number <input id="menu-disc" type="number" min="1" value="1"></label>
            <button type="button" data-action="set-disc">Set disc number (${selectedTracks().length})</button>`
        : "";
    menu.innerHTML = keep + numbering;
    placeMenu(menu, event);
}

function songTagsDiffer(track) {
    const proposal = proposalFor(track && track.id);
    if (!track || !proposal) return false;
    return FIELDS.some(([key]) => String(fieldValue(track, key) ?? "") !== String(proposal[key] ?? ""));
}

function albumTagsDiffer() {
    if (!state.proposal || !state.album) return false;
    const locals = new Map((state.album.tracks || []).map((track) => [track.id, track]));
    const trackDiffers = (state.proposal.tracks || []).some((proposed) => {
        const local = locals.get(proposed.id);
        if (!local) return false;
        return ALBUM_ID3_FIELDS.some((key) => String(fieldValue(local, key) ?? "") !== String(proposed[key] ?? ""));
    });
    if (trackDiffers) return true;
    const album = state.album.album;
    return String(state.proposal.album_title || "") !== String(album.title || "")
        || String(state.proposal.year || "") !== String(album.release_year || "")
        || String(state.proposal.edition || "") !== String(album.edition || "")
        || String(state.proposal.label || "") !== String(album.label || "")
        || String(state.proposal.catalognumber || "") !== String(album.catalog || "")
        || String(state.proposal.barcode || "") !== String(album.barcode || "")
        || String(state.proposal.country || state.proposal.releasecountry || "") !== String(album.country || "")
        || String(state.proposal.releasestatus || "") !== String(album.release_status || "");
}

function keepOldField() {
    const menu = document.getElementById("diff-menu");
    if (menu) menu.classList.add("hidden");
    const target = state.tagMenu;
    const track = currentTrack();
    if (!target || !track || track.id !== target.trackId) return;
    const key = target.key;
    if (state.tagDrafts[track.id]) {
        delete state.tagDrafts[track.id][key];
        if (!Object.keys(state.tagDrafts[track.id]).length) delete state.tagDrafts[track.id];
    }
    if (!target.extra) {
        const proposal = proposalFor(track.id);
        if (proposal) proposal[key] = String(fieldValue(track, key) ?? "");
    }
    storeProposalEdits();
}

function keepOldSongValues() {
    const menu = document.getElementById("track-menu");
    if (menu) menu.classList.add("hidden");
    const track = (state.album && state.album.tracks || []).find((item) => item.id === state.contextTrack) || currentTrack();
    const proposal = proposalFor(track && track.id);
    if (!track || !proposal) return;
    for (const [key] of FIELDS) proposal[key] = String(fieldValue(track, key) ?? "");
    delete state.tagDrafts[track.id];
    storeProposalEdits();
}

function keepOldAlbumValues() {
    const menu = document.getElementById("track-menu");
    if (menu) menu.classList.add("hidden");
    if (!state.album || !state.proposal) return;
    const locals = new Map((state.album.tracks || []).map((track) => [track.id, track]));
    for (const proposed of state.proposal.tracks || []) {
        const local = locals.get(proposed.id);
        if (!local) continue;
        for (const key of ALBUM_ID3_FIELDS) proposed[key] = String(fieldValue(local, key) ?? "");
        const drafts = state.tagDrafts[proposed.id];
        if (drafts) {
            for (const key of ALBUM_ID3_FIELDS) delete drafts[key];
            if (!Object.keys(drafts).length) delete state.tagDrafts[proposed.id];
        }
    }
    const album = state.album.album;
    state.proposal.album_title = album.title || "";
    state.proposal.year = album.release_year || "";
    state.proposal.edition = album.edition || "";
    state.proposal.label = album.label || "";
    state.proposal.catalognumber = album.catalog || "";
    state.proposal.barcode = album.barcode || "";
    state.proposal.country = album.country || "";
    state.proposal.releasecountry = album.country || "";
    state.proposal.releasestatus = album.release_status || "";
    if (album.type) state.proposal.type = album.type;
    storeProposalEdits();
}

function storeProposalEdits() {
    if (!state.album) {
        renderEditor();
        return;
    }
    noteAlbumChanges(state.album.album.id, state.album.tracks);
    if (state.proposal && proposalTagsMatch()) {
        clearMatchIfTagsMatch();
        return;
    }
    if (state.proposal) setPending(state.album.album.id, state.proposal);
    renderTree();
    renderAlbum();
    renderEditor();
}

function onTagMenu(event) {
    const group = event.target.closest(".input-group");
    if (!group) return;
    const input = group.querySelector("[data-field], [data-extra]");
    const track = currentTrack();
    if (!input || !track) return;
    const key = input.dataset.field || input.dataset.extra;
    const extra = !!input.dataset.extra;
    const proposal = extra ? null : proposalFor(track.id);
    const stored = extra ? String((track.tags || {})[key] ?? "") : String(fieldValue(track, key) ?? "");
    const drafts = state.tagDrafts[track.id] || {};
    const drafted = Object.prototype.hasOwnProperty.call(drafts, key);
    const differs = !!(proposal && String(proposal[key] ?? "") !== stored) || (drafted && String(drafts[key] ?? "") !== stored);
    if (!proposal && !drafted) return;
    event.preventDefault();
    state.tagMenu = { trackId: track.id, key, extra };
    const trackMenu = document.getElementById("track-menu");
    if (trackMenu) trackMenu.classList.add("hidden");
    const albumMenu = document.getElementById("album-menu");
    if (albumMenu) albumMenu.classList.add("hidden");
    const menu = document.getElementById("diff-menu");
    menu.innerHTML = `<button type="button" role="menuitem" data-action="keep-old-field" ${differs ? "" : "disabled"}>Keep old value</button>`;
    placeMenu(menu, event);
}

async function autoNumber() {
    document.getElementById("track-menu").classList.add("hidden");
    const groups = new Map();
    state.album.tracks.forEach((track) => {
        if (!state.trackIds.has(track.id)) return;
        const disc = track.disc_number || 1;
        if (!groups.has(disc)) groups.set(disc, []);
        groups.get(disc).push(track.id);
    });
    const ids = [];
    const numbers = [];
    groups.forEach((list) => {
        list.forEach((id, index) => {
            ids.push(id);
            numbers.push(index + 1);
        });
    });
    await api("/api/tracks/bulk", { method: "POST", body: { track_ids: ids, fields: {}, numbers } });
    await selectAlbum(state.album.album.id, true);
    showUndo("Album saved");
}

async function setDiscNumber() {
    document.getElementById("track-menu").classList.add("hidden");
    const value = document.getElementById("menu-disc").value;
    const ids = selectedTracks().map((track) => track.id);
    await api("/api/tracks/bulk", { method: "POST", body: { track_ids: ids, fields: { disc_number: value } } });
    await selectAlbum(state.album.album.id, true);
    showUndo("Album saved");
}
