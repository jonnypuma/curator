function onKeyDown(event) {
    if (state.fanartZoom && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
        const zoom = document.getElementById("art-zoom");
        const tag = event.target && event.target.tagName;
        if (zoom && !zoom.classList.contains("hidden") && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
            event.preventDefault();
            stepFanart(event.key === "ArrowLeft" ? -1 : 1);
            return;
        }
    }
    if (event.target && (event.target.id === "match-query-artist" || event.target.id === "match-query-title") && event.key === "Enter") {
        event.preventDefault();
        runAction(searchAgain, "Searching MusicBrainz…");
        return;
    }
    if (event.target && event.target.id === "artist-name-input") {
        if (event.key === "Enter") {
            event.preventDefault();
            runAction(saveArtistName, "Saving artist name…");
        } else if (event.key === "Escape") {
            event.preventDefault();
            cancelArtistNameEdit();
        }
        return;
    }
    if (event.target && event.target.id === "album-title-input") {
        if (event.key === "Enter") {
            event.preventDefault();
            runAction(saveAlbumTitle, "Saving album title…");
        } else if (event.key === "Escape") {
            event.preventDefault();
            cancelAlbumTitleEdit();
        }
        return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        togglePalette();
        return;
    }
    const palette = document.getElementById("palette");
    if (palette && !palette.classList.contains("hidden")) {
        if (event.key === "Escape") {
            event.preventDefault();
            closePalette();
            return;
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter") {
            event.preventDefault();
            movePalette(event.key);
            return;
        }
    }
    if (event.key === "Escape") {
        const zoom = document.getElementById("art-zoom");
        if (zoom && !zoom.classList.contains("hidden")) {
            zoom.classList.add("hidden");
            return;
        }
        const upgrade = document.getElementById("upgrade-modal");
        if (state.upgradeReplacing && upgrade && !upgrade.classList.contains("hidden")) return;
        // With windows stacked (a report over its history, say) Escape closes only the top one.
        const open = Array.from(document.querySelectorAll(".modal:not(.hidden):not(.is-prompt)"));
        if (open.length > 1) {
            const z = (el) => Number(getComputedStyle(el).zIndex) || 0;
            const top = open.reduce((best, el) => (z(el) >= z(best) ? el : best));
            top.classList.add("hidden");
            return;
        }
        closeModals();
    }
    if (event.key === "Enter" && event.target.id === "path-custom") {
        event.preventDefault();
        addMusicPath(event.target.value);
        return;
    }
    if (event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
        const media = { Digit1: "music", Digit2: "movies", Digit3: "sets", Digit4: "tv" }[event.code];
        if (media) {
            event.preventDefault();
            if (state.media !== media) switchMedia(media);
            return;
        }
    }
    const tag = event.target && event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || tag === "BUTTON" || (event.target && event.target.closest && event.target.closest("button")) || (event.target && event.target.isContentEditable)) return;
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "a" && !document.querySelector(".modal:not(.hidden)")) {
        event.preventDefault();
        if (state.media === "music") selectVisible(true);
        else if (typeof selectVideoAll === "function") selectVideoAll(true);
        return;
    }
    if (event.key === "?" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        const modal = document.getElementById("shortcuts-modal");
        if (modal) modal.classList.toggle("hidden");
        return;
    }
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        const input = state.media === "music" ? document.getElementById("artist-search") : document.getElementById("video-filter");
        if (input) input.focus();
        return;
    }
    const pathModal = document.getElementById("path-modal");
    if (pathModal && !pathModal.classList.contains("hidden") && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        jumpToFolder(folderInitial(event.key));
        return;
    }
    if ((event.key === " " || event.code === "Space") && event.target.closest && event.target.closest("#tree")) {
        event.preventDefault();
        toggleCurrentAlbumCheck();
        return;
    }
    if (state.media !== "music") return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveTags().catch((error) => notify(error.message, "error"));
        return;
    }
    if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        togglePreview();
        return;
    }
    if (document.querySelector(".modal:not(.hidden)")) return;
    const key = event.key.toLowerCase();
    const down = key === "j" || event.key === "ArrowDown";
    const up = key === "k" || event.key === "ArrowUp";
    if (!down && !up) return;
    event.preventDefault();
    const direction = down ? 1 : -1;
    if (event.target.closest && event.target.closest("#tracks")) moveTrack(direction);
    else moveAlbum(direction);
}

function toggleCurrentAlbumCheck() {
    const id = selectionFocusId();
    if (!id) return;
    selectionToggle("album", id);
    const box = document.querySelector(`input[data-check-album="${CSS.escape(id)}"]`);
    if (box) box.checked = selectionHas("album", id);
    syncArtistChecks();
    renderBatchBar();
    if (typeof refreshOpenLookup === "function") refreshOpenLookup();
}

function treeAlbums() {
    const albums = [];
    const grid = state.musicViewMode === "grid";
    pendingArtists(orderedArtists(state.artists)).forEach((artist) => {
        if (!grid && !state.expanded.has(artist.id)) return;
        (artist.albums || []).forEach((album) => albums.push({ artist, album }));
    });
    return albums;
}

function highlightedAlbumId() {
    if (state.treeCursor) return state.treeCursor;
    return state.album && state.album.album ? state.album.album.id : "";
}

function moveAlbum(direction) {
    const albums = treeAlbums();
    if (!albums.length) return;
    const current = highlightedAlbumId();
    let index = albums.findIndex((row) => row.album.id === current);
    if (index < 0) index = direction > 0 ? -1 : albums.length;
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= albums.length) return;
    const next = albums[nextIndex];
    state.treeCursor = next.album.id;
    state.expanded.add(next.artist.id);
    persistExpanded();
    selectAlbum(next.album.id);
}

function moveTrack(direction) {
    if (!state.album || !(state.album.tracks || []).length) return moveAlbum(direction);
    const ids = state.album.tracks.map((track) => track.id);
    const index = Math.max(0, ids.indexOf(state.trackId));
    const next = ids[Math.min(ids.length - 1, Math.max(0, index + direction))];
    if (!next || next === state.trackId) return;
    selectTrack(next, { shiftKey: false, ctrlKey: false, metaKey: false });
    renderTracks();
    renderEditor();
    const row = document.querySelector(`#tracks tr[data-track="${next}"]`);
    if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
}

function selectTrack(id, event) {
    const ids = (state.album && state.album.tracks || []).map((track) => track.id);
    if (event.shiftKey && state.trackAnchor && ids.includes(state.trackAnchor)) {
        const start = ids.indexOf(state.trackAnchor);
        const end = ids.indexOf(id);
        const [from, to] = start < end ? [start, end] : [end, start];
        state.trackIds = new Set(ids.slice(from, to + 1));
    } else if (event.ctrlKey || event.metaKey) {
        if (state.trackIds.has(id)) state.trackIds.delete(id);
        else state.trackIds.add(id);
        state.trackAnchor = id;
    } else {
        state.trackIds = new Set([id]);
        state.trackAnchor = id;
    }
    state.trackId = id;
    if (!state.trackIds.size) state.trackIds.add(id);
}

function selectedTracks() {
    if (!state.album) return [];
    const ids = state.trackIds.size ? state.trackIds : new Set(state.trackId ? [state.trackId] : []);
    return state.album.tracks.filter((track) => ids.has(track.id));
}

function renderBulkEditor(tracks, host, diffHost, sideHost, card, badge) {
    showTrackLocation(tracks.length === 1 ? tracks[0] : null);
    if (badge) badge.textContent = `${tracks.length} tracks`;
    if (card) card.innerHTML = "";
    const fields = [
        ["year", "Year"],
        ["genre", "Genre"],
        ["albumartist", "Album artist"],
        ["albumartists", "Album artists"],
        ["artists", "Artists"],
        ["disc_number", "Disc number"],
    ];
    const inputs = fields.map(([key, label]) => {
        const values = tracks.map((track) => String(fieldValue(track, key) ?? ""));
        const shared = values.every((value) => value === values[0]) ? values[0] : "";
        return `<div class="input-group"><label>${label}</label><input data-bulk="${key}" value="${escapeHtml(shared)}" placeholder="${shared ? "" : "Mixed"}"></div>`;
    }).join("");
    host.innerHTML = `<p class="muted">Shared fields for ${tracks.length} tracks. An empty box is left unchanged.</p><div class="tag-grid">${inputs}</div>`;
    host.querySelectorAll("[data-bulk]").forEach((input) => {
        input.addEventListener("input", () => {
            input.dataset.touched = input.value.trim() ? "1" : "";
            const dirty = [...host.querySelectorAll("[data-bulk]")].some((item) => item.dataset.touched === "1" && item.value.trim());
            state.bulkDirtyAlbum = dirty && state.album ? state.album.album.id : "";
            if (state.album) noteAlbumChanges(state.album.album.id, state.album.tracks);
        });
    });
    if (diffHost) {
        diffHost.innerHTML = `<div class="empty-state">The comparison stays on a single track.</div>`;
        diffHost.classList.remove("has-diff");
    }
    const bulkTab = document.querySelector("[data-inspector='diff']");
    if (bulkTab) bulkTab.classList.remove("has-diff");
    if (sideHost) sideHost.innerHTML = `<div class="empty-state">Sidecars stay on a single track.</div>`;
}

function audioBadge(track) {
    const flag = track.audio_flag;
    if (flag === "verified") return `<span class="tag-pill ok">FLAC OK</span>`;
    if (flag === "corrupt") return `<span class="tag-pill bad">Corrupt</span>`;
    if (flag === "upscaled") return `<span class="tag-pill bad">Upscaled</span>`;
    return "";
}

function bindTrackDrag() {
    let dragged = "";
    document.querySelectorAll("#tracks tr[data-track], #tracks [data-side='local']").forEach((row) => {
        row.addEventListener("dragstart", () => { dragged = row.dataset.track; });
        row.addEventListener("dragover", (event) => { if (state.proposal) event.preventDefault(); });
        row.addEventListener("drop", (event) => {
            event.preventDefault();
            if (!state.proposal || !dragged || dragged === row.dataset.track) return;
            swapProposal(dragged, row.dataset.track);
            renderTracks();
            renderEditor();
        });
    });
}

function swapProposal(fromId, toId) {
    const tracks = state.proposal.tracks || [];
    const from = tracks.find((track) => track.id === fromId);
    const to = tracks.find((track) => track.id === toId);
    if (!from || !to) return;
    const keys = new Set([...Object.keys(from), ...Object.keys(to)]);
    keys.delete("id");
    keys.forEach((key) => {
        const current = from[key];
        from[key] = to[key];
        to[key] = current;
    });
}

function libraryWritable(path) {
    const mounts = (state.mounts || []).filter((mount) => mount.path && (path === mount.path || String(path || "").startsWith(`${mount.path}/`)));
    if (!mounts.length) return true;
    mounts.sort((left, right) => right.path.length - left.path.length);
    return !!mounts[0].writable;
}

function playbackCap(audio) {
    if (!state.fullPlayback) return 15;
    const duration = audio && Number.isFinite(audio.duration) ? audio.duration : 0;
    return duration || 0;
}

function applySeekLimit(audio) {
    if (!audio) return;
    const cap = playbackCap(audio) || 15;
    const clock = document.getElementById("player-clock");
    if (clock) clock.setAttribute("aria-valuemax", String(Math.round(cap)));
    if (!state.fullPlayback && audio.currentTime > 15) audio.pause();
}

function playerClock(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = String(total % 60).padStart(2, "0");
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${secs}`;
}

function paintPlayerClock(audio) {
    const clock = document.getElementById("player-time");
    const box = document.getElementById("player-clock");
    if (!clock) return;
    const cap = audio ? (playbackCap(audio) || (state.fullPlayback ? 0 : 15)) : 15;
    const now = audio && Number.isFinite(audio.currentTime) ? Math.min(cap || audio.currentTime, audio.currentTime) : 0;
    clock.textContent = `${playerClock(now)} / ${playerClock(cap)}`;
    const ratio = cap ? Math.min(1, Math.max(0, now / cap)) : 0;
    const fill = document.getElementById("player-clock-fill");
    if (fill) fill.style.width = `${ratio * 100}%`;
    if (box) {
        box.setAttribute("aria-valuemax", String(Math.round(cap)));
        box.setAttribute("aria-valuenow", String(Math.round(now)));
        box.setAttribute("aria-valuetext", clock.textContent);
    }
}

function paintPlayerStatus() {}

function paintPlayerIdentity() {
    const line = document.getElementById("player-now-text");
    const stage = document.getElementById("player-stage");
    if (!line) return;
    const track = currentTrack();
    if (!track) {
        line.textContent = "";
        if (stage) stage.classList.remove("has-track");
        if (typeof updateLyricsEditButton === "function") updateLyricsEditButton();
        return;
    }
    const artist = (state.album && state.album.artist && state.album.artist.name) || track.artist_name || "";
    const album = (state.album && state.album.album && state.album.album.title) || "";
    const number = String(track.track_number || 0).padStart(2, "0");
    line.textContent = [artist, album, number, track.title || ""].filter(Boolean).join(" - ");
    if (stage) stage.classList.toggle("has-track", Boolean(line.textContent));
    if (typeof updateLyricsEditButton === "function") updateLyricsEditButton();
}

function togglePreview() {
    const audio = document.getElementById("player");
    const track = currentTrack();
    if (!audio || !track) return;
    const source = `/api/tracks/${track.id}/audio`;
    const mode = state.fullPlayback ? "full" : "preview";
    const sameTrack = audio.dataset.track === track.id && Boolean(audio.currentSrc);
    if (sameTrack && audio.dataset.mode === mode && !audio.paused) {
        audio.pause();
        syncSeek();
        paintPlayerStatus(audio);
        return;
    }
    if (!sameTrack) {
        audio.src = source;
        audio.currentTime = 0;
    }
    audio.dataset.track = track.id;
    audio.dataset.mode = mode;
    if (!state.fullPlayback && audio.currentTime >= 15) audio.currentTime = 0;
    applySeekLimit(audio);
    const graph = ensureWave(audio);
    if (graph) graph.context.resume().catch(() => {});
    audio.play().then(() => {
        syncSeek();
        drawWave();
    }).catch((error) => notify(error.message, "error"));
    paintPlayerStatus(audio);
    paintPlayerIdentity();
    audio.ontimeupdate = () => {
        paintPlayerClock(audio);
        if (!state.fullPlayback && audio.currentTime >= 15) {
            audio.pause();
            paintPlayerStatus(audio);
        }
    };
}
