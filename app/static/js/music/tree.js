function switchInspector(name) {
    state.inspector = name || "tags";
    document.querySelectorAll("[data-inspector]").forEach((button) => {
        button.classList.toggle("active", button.dataset.inspector === state.inspector);
    });
    const panels = {
        tags: "editor",
        diff: "editor-diff",
        sidecar: "editor-sidecar",
        "album-nfo": "editor-album-nfo",
        "album-art": "editor-album-art",
        "artist-nfo": "editor-artist-nfo",
        "artist-art": "editor-artist-art",
    };
    Object.entries(panels).forEach(([panel, id]) => {
        const node = document.getElementById(id);
        if (node) node.classList.toggle("hidden", state.inspector !== panel);
    });
    const clearNfo = document.getElementById("clear-artist-nfo");
    if (clearNfo) clearNfo.classList.toggle("hidden", state.inspector !== "artist-nfo");
    const save = document.getElementById("save-tags");
    if (save) {
        const artwork = state.inspector === "artist-art" || state.inspector === "album-art";
        save.classList.toggle("is-reserved", artwork);
        if (!artwork) {
            if (state.inspector === "artist-nfo") save.textContent = "Save artist.nfo";
            else if (state.inspector === "album-nfo") save.textContent = "Save album.nfo";
            else save.textContent = "Save tags";
        }
    }
    if (state.inspector === "artist-art") renderArtworkPanel("artist");
    if (state.inspector === "album-art") renderArtworkPanel("album");
}

function showArtistInspector() {
    document.querySelectorAll(".inspector-tabs [data-inspector]").forEach((button) => {
        const artistTab = button.dataset.inspector === "artist-nfo" || button.dataset.inspector === "artist-art";
        button.classList.toggle("hidden", !artistTab);
    });
    const title = document.getElementById("inspector-title");
    if (title) title.textContent = "Artist info";
    switchInspector(state.inspector === "artist-art" ? "artist-art" : "artist-nfo");
    const card = document.getElementById("completeness-card");
    if (card) card.innerHTML = "";
    const badge = document.getElementById("active-track-badge");
    if (badge) badge.textContent = "";
    renderArtistNfo();
}

function showAlbumInspector() {
    document.querySelectorAll(".inspector-tabs [data-inspector]").forEach((button) => {
        const artistOnly = button.dataset.inspector === "artist-nfo" || button.dataset.inspector === "artist-art";
        button.classList.toggle("hidden", artistOnly);
    });
    const title = document.getElementById("inspector-title");
    if (title) title.textContent = "ID3 tag sandbox";
    if (state.inspector === "artist-nfo" || state.inspector === "artist-art") switchInspector("tags");
    else switchInspector(state.inspector);
    renderAlbumNfo();
}

function setTotals(totals) {
    state.totals = totals;
    document.getElementById("hdr-artists").textContent = totals.artists || 0;
    document.getElementById("hdr-albums").textContent = totals.albums || 0;
    document.getElementById("hdr-tracks").textContent = totals.tracks || 0;
}

function dropLibraryRows(body) {
    const albumIds = new Set((body && body.album_ids) || []);
    const artistIds = new Set((body && body.artist_ids) || []);
    if (!albumIds.size && !artistIds.size) return;
    let albumsGone = 0;
    let tracksGone = 0;
    const artists = [];
    (state.artists || []).forEach((artist) => {
        if (artistIds.has(artist.id)) {
            (artist.albums || []).forEach((album) => {
                albumsGone += 1;
                tracksGone += Number(album.total_tracks) || 0;
                selectionSet("album", album.id, false);
            });
            return;
        }
        const albums = [];
        (artist.albums || []).forEach((album) => {
            if (!albumIds.has(album.id)) {
                albums.push(album);
                return;
            }
            albumsGone += 1;
            tracksGone += Number(album.total_tracks) || 0;
            selectionSet("album", album.id, false);
        });
        artist.albums = albums;
        artists.push(artist);
    });
    state.artists = artists;
    if (state.totals) {
        setTotals({
            artists: Math.max(0, (state.totals.artists || 0) - artistIds.size),
            albums: Math.max(0, (state.totals.albums || 0) - albumsGone),
            tracks: Math.max(0, (state.totals.tracks || 0) - tracksGone),
        });
    }
    renderTree();
}


function albumTier(album) {
    return (album && album.match_tier) || "unmatched";
}

function renderMatchSelect() {
    const albums = state.artists.reduce((rows, artist) => rows.concat(artist.albums || []), []);
    const counts = { new: 0, gold: 0, silver: 0, unmatched: 0 };
    albums.forEach((album) => {
        if (album.status === "NEW") counts.new += 1;
        const tier = albumTier(album);
        if (counts[tier] != null) counts[tier] += 1;
    });
    const names = { new: "new", gold: "100% matched", silver: "partially matched", unmatched: "unmatched" };
    document.querySelectorAll("[data-action='select-tier']").forEach((button) => {
        const tier = button.dataset.tier;
        const count = counts[tier] || 0;
        const name = names[tier] || tier;
        button.disabled = count === 0;
        button.title = count
            ? `Select ${count} ${name} ${count === 1 ? "album" : "albums"}`
            : `No ${name} albums in this view`;
    });
}

function timeStamp(value) {
    const parsed = Date.parse(value || "");
    return Number.isFinite(parsed) ? parsed : 0;
}

function addedStamp(album) {
    return timeStamp(album && album.created_at);
}

function addedLabel(album) {
    const match = String((album && album.created_at) || "").match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : "";
}

function sortYear(album) {
    const original = Number(album && album.original_year);
    if (original) return original;
    const release = Number(album && album.release_year);
    return release || 0;
}

function artistSortName(name) {
    return librarySortName(name);
}

function compareArtistNames(left, right) {
    return artistSortName(left).localeCompare(artistSortName(right), undefined, { sensitivity: "base" });
}

function orderedArtists(artists) {
    const mode = state.librarySort || "name";
    const rows = artists.map((artist) => {
        const albums = [...(artist.albums || [])];
        albums.sort((a, b) => {
            if (mode === "albums") {
                const byAdded = timeStamp(b.created_at) - timeStamp(a.created_at);
                if (byAdded) return byAdded;
            } else if (mode === "modified") {
                const byModified = timeStamp(b.updated_at) - timeStamp(a.updated_at);
                if (byModified) return byModified;
            }
            const left = sortYear(a) || 9999;
            const right = sortYear(b) || 9999;
            if (left !== right) return left - right;
            return librarySortName(a.title).localeCompare(librarySortName(b.title), undefined, { sensitivity: "base" });
        });
        const newestAlbum = albums.reduce((max, album) => Math.max(max, timeStamp(album.created_at)), 0);
        const newestChange = Math.max(
            timeStamp(artist.updated_at),
            albums.reduce((max, album) => Math.max(max, timeStamp(album.updated_at)), 0),
        );
        return { artist, albums, newestAlbum, newestChange, artistAdded: timeStamp(artist.created_at) };
    });
    rows.sort((a, b) => {
        const byName = compareArtistNames(a.artist.name, b.artist.name);
        if (mode === "artists") return b.artistAdded - a.artistAdded || byName;
        if (mode === "albums") return b.newestAlbum - a.newestAlbum || byName;
        if (mode === "modified") return b.newestChange - a.newestChange || byName;
        return byName;
    });
    return rows.map((row) => ({ ...row.artist, albums: row.albums }));
}

function syncLibraryTools() {
    const count = Object.keys(state.pending).length;
    const button = document.getElementById("apply-all-matches");
    if (button) {
        button.disabled = count === 0 || state.busy;
        button.textContent = `Apply All Matches (${count} total matches)`;
    }
    const scanButton = document.getElementById("scan-apply-pending");
    if (scanButton) {
        const scanning = !!(state.scan && state.scan.status === "running");
        scanButton.classList.toggle("hidden", scanning || count === 0);
        scanButton.textContent = count === 1 ? "Apply match" : `Apply match (${count})`;
    }
}

function pendingArtists(artists) {
    if (state.filter !== "pending") return artists;
    return artists.map((artist) => ({
        ...artist,
        albums: (artist.albums || []).filter((album) => state.pending[album.id]),
    })).filter((artist) => (artist.albums || []).length);
}

function renderSelectedCount() {
    const node = document.getElementById("tree-selected-count");
    if (node) node.textContent = `Items Selected: ${state.selected.size}`;
    const held = document.getElementById("music-prune-held");
    if (held) {
        const count = Number((state.filterCounts || {})["prune-held"]);
        held.classList.toggle("hidden", Number.isFinite(count) && count === 0);
        held.textContent = Number.isFinite(count) && count > 0 ? `Remove all not found (${count.toLocaleString()})` : "Remove all not found";
    }
}

const TREE_ROW_HEIGHT = 36;

function renderMusicRibbons() {
    const host = document.getElementById("music-ribbons");
    if (!host) return;
    const allAlbums = [];
    (state.artists || []).forEach((artist) => {
        (artist.albums || []).forEach((album) => allAlbums.push({ artist, album }));
    });
    const counts = {
        all: allAlbums.length,
        new: allAlbums.filter(({ artist, album }) => album.status === "NEW" || artist.status === "NEW").length,
        unmatched: allAlbums.filter(({ album }) => albumTier(album) === "unmatched").length,
        gold: allAlbums.filter(({ album }) => albumTier(album) === "gold").length,
        silver: allAlbums.filter(({ album }) => albumTier(album) === "silver").length,
        "missing-art": allAlbums.filter(({ album }) => !album.has_artwork).length,
        "missing-nfo": allAlbums.filter(({ artist, album }) => !album.has_nfo || !artist.has_nfo).length,
        "nfo-changes": allAlbums.filter(({ artist, album }) => state.staleNfoAlbums.has(album.id) || album.nfo_stale || state.staleNfoArtists.has(artist.id) || artist.nfo_stale).length,
        duplicates: allAlbums.filter(({ album }) => album.duplicate_release).length,
        upgrade: allAlbums.filter(({ album }) => album.upgrade).length,
        "prune-held": allAlbums.filter(({ album }) => album.prune_held).length,
    };
    // The rest (100%, No Art, No NFO, Duplicates, Upgrade, ...) are in the filter menu.
    const pills = [
        ["all", "All", counts.all],
        ["new", "New", counts.new],
        ["unmatched", "Unmatched", counts.unmatched],
        ["silver", "Partial", counts.silver],
        ["nfo-changes", "NFO Change", counts["nfo-changes"]],
    ];
    const current = state.filter || "all";
    // Same badge style as the movie and TV quick filters: pressing a lit one clears it.
    host.innerHTML = pills.map(([key, label, count]) => {
        const on = current === key;
        return `<button type="button" class="vribbon${on ? " is-on" : ""}" data-action="library-filter-pick" data-filter="${on && key !== "all" ? "all" : escapeHtml(key)}" aria-pressed="${on}">${escapeHtml(label)} <small>${count}</small></button>`;
    }).join("");
}

function toggleMusicViewMode() {
    state.musicViewMode = state.musicViewMode === "grid" ? "list" : "grid";
    state.treeScroll = 0;
    state.treeWindow = null;
    const pane = document.getElementById("tree");
    if (pane) pane.scrollTop = 0;
    localStorage.setItem("curator.musicViewMode", state.musicViewMode);
    syncMusicViewToggleButton();
    renderTree();
}

function syncMusicViewToggleButton() {
    const btn = document.getElementById("music-view-toggle");
    if (!btn) return;
    const isGrid = state.musicViewMode === "grid";
    const gridIcon = btn.querySelector(".icon-grid");
    const listIcon = btn.querySelector(".icon-list");
    if (gridIcon) gridIcon.classList.toggle("hidden", isGrid);
    if (listIcon) listIcon.classList.toggle("hidden", !isGrid);
    const label = isGrid ? "Switch to List view" : "Switch to Poster Grid view";
    btn.title = label;
    btn.setAttribute("aria-label", label);
    btn.classList.toggle("is-active", isGrid);
    const sizeBox = document.querySelector('[data-size-toggle="music"]');
    if (sizeBox) sizeBox.classList.toggle("hidden", !isGrid);
}

function musicGridCardHtml(entry, size) {
    const { artist, album } = entry;
    const showBadge = typeof artBadgeAllowed === "function" && artBadgeAllowed("music");
    const active = state.album && state.album.album && state.album.album.id === album.id;
    const checked = state.selected.has(album.id);
    const cover = album.has_artwork
        ? `<img class="vgrid-poster" src="/api/albums/${encodeURIComponent(album.id)}/cover?w=342" alt="" loading="lazy"${showBadge ? ` onload="updateArtBadgeOnLoad(this)"` : ""} onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'vgrid-fallback', textContent:'No Art'}))">${showBadge ? `<span class="art-dim-badge hidden"></span>` : ""}`
        : `<div class="vgrid-fallback">No Art</div>`;
    const extra = size === "large"
        ? `<div class="vgrid-badges">${[album.type, album.format, album.track_count ? `${album.track_count} tracks` : ""].filter(Boolean).slice(0, 4).map((fact) => `<span class="vgrid-chip">${escapeHtml(String(fact))}</span>`).join("")}</div>`
        : "";
    return `<div class="vgrid-card${active ? " is-active" : ""}${checked ? " is-checked" : ""}" data-album="${escapeHtml(album.id)}" data-artist-id="${escapeHtml(artist.id)}">
        <div class="vgrid-poster-wrap" data-album="${escapeHtml(album.id)}" data-artist-id="${escapeHtml(artist.id)}">
            ${cover}
            <label class="vgrid-check" onclick="event.stopPropagation()"><input type="checkbox" data-check-album="${escapeHtml(album.id)}" ${checked ? "checked" : ""} aria-label="Select ${escapeHtml(album.title || "album")}"></label>
        </div>
        <button type="button" class="vgrid-meta" data-album="${escapeHtml(album.id)}" data-artist-id="${escapeHtml(artist.id)}">
            <span class="vgrid-title" title="${escapeHtml(album.title || "")}">${escapeHtml(album.title || "Untitled")}</span>
            <span class="vgrid-sub">${escapeHtml(artist.name || "")}${album.release_year ? ` · ${escapeHtml(String(album.release_year))}` : ""}</span>
            ${extra}
        </button>
    </div>`;
}

function renderMusicPosterGrid(artists) {
    const root = document.getElementById("tree");
    if (!root) return;
    const entries = [];
    artists.forEach((artist) => (artist.albums || []).forEach((album) => entries.push({ artist, album })));
    vgridMount(root, {
        kind: "music",
        items: entries,
        key: (entry) => entry.album.id,
        ratio: 1,
        render: musicGridCardHtml,
        after: () => syncArtistChecks(),
        empty: `<div class="empty-state">No albums match the current filter.</div>`,
    });
}

function renderTree() {
    const root = document.getElementById("tree");
    syncOpenNfoStale();
    renderSelectedCount();
    syncMusicViewToggleButton();
    renderMusicRibbons();
    if (typeof paintSelectToggle === "function") paintSelectToggle();
    syncLibraryTools();
    const artists = pendingArtists(orderedArtists(state.artists));
    const albumCount = artists.reduce((sum, artist) => sum + (artist.albums || []).length, 0);
    const treeStats = document.getElementById("tree-stats");
    if (treeStats) {
        const pending = state.filter === "pending";
        treeStats.textContent = pending ? `${albumCount} loaded ${albumCount === 1 ? "match" : "matches"}` : "";
        treeStats.classList.toggle("hidden", !pending);
    }
    renderMatchSelect();
    if (!state.libraryLoaded) {
        state.treeRows = [];
        showTreeLoading();
        return;
    }
    if (!state.artists.length) {
        state.treeRows = [];
        const message = state.libraryError || "No artists in this view. Scan a mounted music path to index the library.";
        root.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
        return;
    }
    if (!artists.length) {
        state.treeRows = [];
        root.innerHTML = `<div class="empty-state">No loaded matches. Find metadata, then load the releases you want to review.</div>`;
        return;
    }
    if (state.musicViewMode === "grid") {
        state.treeRows = [];
        renderMusicPosterGrid(artists);
        return;
    }
    const rows = [];
    artists.forEach((artist) => {
        rows.push({ kind: "artist", artist });
        if (!state.expanded.has(artist.id)) return;
        (artist.albums || []).forEach((album) => rows.push({ kind: "album", artist, album }));
        (artist.missing_releases || []).forEach((release) => rows.push({ kind: "missing", artist, release }));
    });
    state.treeRows = rows;
    state.treeToken = (state.treeToken || 0) + 1;
    paintTreeWindow(true);
}

function treeScrollTop(root) {
    const saved = state.treeScroll;
    if (Number.isFinite(saved)) return saved;
    return root ? root.scrollTop : 0;
}

function pinTreeScroll(root, top) {
    state.treePainting = true;
    state.treeScroll = top;
    state.treeScrollAt = performance.now();
    let frames = 0;
    const apply = () => {
        const next = Number.isFinite(state.treeScroll) ? state.treeScroll : top;
        if (!root.isConnected) return true;
        if (root.scrollTop !== next) root.scrollTop = next;
        const max = Math.max(0, root.scrollHeight - root.clientHeight);
        return next <= 0 || max + 1 >= next;
    };
    const step = () => {
        frames += 1;
        if (apply() || frames > 30) {
            state.treePainting = false;
            return;
        }
        requestAnimationFrame(step);
    };
    apply();
    requestAnimationFrame(step);
}

function noteTreeScroll(root) {
    // The poster grid scrolls the same pane; its position must not become the list's saved position.
    if (!root || state.treePainting || state.musicViewMode === "grid") return;
    const top = root.scrollTop;
    const saved = state.treeScroll;
    if (top === 0 && saved > 80) {
        const max = Math.max(0, root.scrollHeight - root.clientHeight);
        if (max + 1 < saved || performance.now() - (state.treeScrollAt || 0) < 1500) return;
    }
    state.treeScroll = top;
}

function paintTreeWindow(force) {
    const root = document.getElementById("tree");
    const rows = state.treeRows || [];
    if (!root || !rows.length) return;
    const height = TREE_ROW_HEIGHT;
    const view = root.clientHeight || 640;
    // A saved position past the end of the list (for example one left by the grid) would paint nothing.
    const scroll = Math.max(0, Math.min(treeScrollTop(root), rows.length * height - view));
    const buffer = 10;
    const start = Math.max(0, Math.floor(scroll / height) - buffer);
    const end = Math.min(rows.length, Math.ceil((scroll + view) / height) + buffer);
    const token = state.treeToken || 0;
    const painted = state.treeWindow;
    if (!force && painted && painted.start === start && painted.end === end && painted.count === rows.length && painted.token === token) return;
    state.treeWindow = { start, end, count: rows.length, token };
    const html = rows.slice(start, end).map(treeRowHtml).join("");
    state.treePainting = true;
    root.innerHTML = `<div class="tree-spacer" style="height:${rows.length * height}px"><div class="tree-window" style="top:${start * height}px">${html}</div></div>`;
    pinTreeScroll(root, scroll);
    syncArtistChecks();
}

function revealTreeAlbum(albumId) {
    const root = document.getElementById("tree");
    if (!root) return;
    if (state.musicViewMode === "grid") {
        if (typeof vgridReveal === "function") vgridReveal(root, albumId);
        const card = root.querySelector(`.vgrid-card[data-album="${CSS.escape(albumId)}"]`);
        if (card) card.scrollIntoView({ block: "nearest" });
        return;
    }
    const rows = state.treeRows || [];
    const index = rows.findIndex((row) => row.kind === "album" && row.album.id === albumId);
    if (index < 0) return;
    const rowTop = index * TREE_ROW_HEIGHT;
    const bottom = rowTop + TREE_ROW_HEIGHT;
    let next = root.scrollTop;
    if (rowTop < root.scrollTop) next = rowTop;
    else if (bottom > root.scrollTop + root.clientHeight) next = Math.max(0, bottom - root.clientHeight);
    state.treeScroll = next;
    if (root.scrollTop !== next) root.scrollTop = next;
}

function treeRowHtml(row) {
    if (row.kind === "album") return treeAlbumHtml(row.artist, row.album);
    if (row.kind === "missing") return treeMissingHtml(row.artist, row.release);
    return treeArtistHtml(row.artist);
}

function treeMissingHtml(artist, release) {
    const year = release.year || "----";
    return `<div class="album-line is-missing">
        <span class="album-check-spacer" aria-hidden="true"></span>
        <button type="button" class="album-item" data-open-artist="${escapeHtml(artist.id)}">
            <span class="match-icon unmatched">○</span>
            <span class="album-label">${escapeHtml(`${year} - ${release.title}`)}</span>
            <span class="tree-pills"><span class="tag-pill missing-pill">Not on disk</span></span>
        </button>
    </div>`;
}

function treeAlbumHtml(artist, album) {
    const active = state.album && state.album.album.id === album.id ? " active" : "";
    const pending = state.pending[album.id] ? " has-pending" : "";
    const badge = [
        album.gap_expected && album.gap_present < album.gap_expected ? `<span class="tag-pill">Incomplete album (${album.gap_present}/${album.gap_expected})</span>` : "",
    ].join("");
    const musicCfg = typeof videoCfg === "function" ? videoCfg() : {};
    const added = musicCfg.ui_music_date_added === false ? "" : addedLabel(album);
    const showProcessed = musicCfg.ui_music_processed !== false;
    const tracks = Number(album.total_tracks) || 0;
    const trackTitle = tracks === 1 ? "1 track" : `${tracks} tracks`;
    const duplicate = !!album.duplicate_release;
    const trailing = [
        countryFlag(album.country),
        album.status === "IGNORED"
            ? `<span class="tag-pill" title="Left out of scans and scrapes">Ignored</span>`
            : !showProcessed ? ""
            : album.status === "PROCESSED"
            ? `<span class="process-mark ok" title="Processed">✓</span>`
            : `<span class="process-mark bad" title="Not processed">✕</span>`,
        album.locked ? `<span class="tag-pill" title="Scans and scrapes leave this album alone">Locked</span>` : "",
        state.pending[album.id] ? `<span class="tag-pill pending-pill" title="Loaded match, not applied">Match</span>` : "",
        album.upgrade ? `<span class="tag-pill upgrade-pill">Upgrade available</span>` : "",
        album.prune_held ? `<span class="tag-pill prune-held-pill" title="Not found at the last scan, but kept because removing it would break a prune safety limit. Remove it from the database if it is really gone.">Not found</span>` : "",
        duplicate ? `<span class="tag-pill duplicate-pill" title="Another copy of this release is in the library">Duplicate</span>` : "",
        state.dirtyAlbums.has(album.id) ? changesPill() : "",
        state.staleNfoAlbums.has(album.id) || album.nfo_stale ? nfoStalePill("album.nfo", album.id) : "",
        album.status === "NEW" ? `<span class="badge-new">NEW</span>` : "",
    ].join("");
    const checked = state.selected.has(album.id) ? "checked" : "";
    return `<div class="album-line${pending}">
        <input type="checkbox" data-check-album="${escapeHtml(album.id)}" ${checked} aria-label="Select ${escapeHtml(album.title)}">
        <button type="button" class="album-item${active}" data-album="${escapeHtml(album.id)}" data-artist-id="${escapeHtml(artist.id)}">
            <span class="match-icon ${escapeHtml(album.match_tier || "unmatched")}">${matchIcon(album.match_tier)}</span>
            <span class="album-label">${escapeHtml(albumLabel(album))}</span>
            ${badge}
            <span class="album-count" title="${escapeHtml(trackTitle)}">${tracks}</span>
            ${album.version && (typeof videoCfg !== "function" || videoCfg().ui_music_edition_badge !== false) ? `<span class="tag-pill version-pill" title="${escapeHtml(album.version)}">${escapeHtml(album.version)}</span>` : ""}
            ${added ? `<span class="added-date" title="Added to the library">${escapeHtml(added)}</span>` : ""}
            ${trailing ? `<span class="tree-pills">${trailing}</span>` : ""}
        </button>
    </div>`;
}

function treeArtistHtml(artist) {
    const open = state.expanded.has(artist.id);
    const activeArtist = state.center === "artist" && state.artistId === artist.id ? " active" : "";
    const pendingCount = (artist.albums || []).filter((album) => state.pending[album.id]).length;
    const newAlbums = (artist.albums || []).filter((album) => album.status === "NEW").length;
    const missingCount = (artist.missing_releases || []).length;
    const artistCfg = typeof videoCfg === "function" ? videoCfg() : {};
    const artistAdded = artistCfg.ui_music_date_added === false ? "" : addedLabel(artist);
    const albumTotal = state.filter === "missing-releases" ? missingCount : (artist.albums || []).length;
    const albumCountTitle = state.filter === "missing-releases"
        ? (albumTotal === 1 ? "1 studio album not on disk" : `${albumTotal} studio albums not on disk`)
        : (albumTotal === 1 ? "1 album" : `${albumTotal} albums`);
    const artistDirty = state.dirtyArtists.has(artist.id) || (artist.albums || []).some((album) => state.dirtyAlbums.has(album.id));
    const staleAlbum = (artist.albums || []).find((album) => state.staleNfoAlbums.has(album.id) || album.nfo_stale);
    const albumNfoStale = !!staleAlbum;
    const newAlbumsTitle = newAlbums === 1 ? "1 album is not processed yet" : `${newAlbums} albums are not processed yet`;
    const newAlbumsLabel = newAlbums === 1 ? "New album" : `New albums (${newAlbums})`;
    const folderTitle = state.filter === "case-folders" && artist.path ? ` title="${escapeHtml(artist.path)}"` : "";
    const artistPills = [
        newAlbums ? `<span class="tag-pill new-albums-pill" title="${escapeHtml(newAlbumsTitle)}">${escapeHtml(newAlbumsLabel)}</span>` : "",
        missingCount ? `<span class="tag-pill missing-pill" title="Studio albums in the stored discography that are not on disk">${missingCount === 1 ? "1 missing" : `${missingCount} missing`}</span>` : "",
        pendingCount ? `<span class="tag-pill pending-pill" title="Loaded matches, not applied">${pendingCount === 1 ? "1 match" : `${pendingCount} matches`}</span>` : "",
        artistDirty ? changesPill() : "",
        state.staleNfoArtists.has(artist.id) || artist.nfo_stale ? nfoStalePill("artist.nfo", null, artist.id) : "",
        albumNfoStale ? `<span class="tag-pill changes-pill" title="The database has changes that are not in a stored album.nfo">NFO changes</span>` : "",
        artist.duplicate ? `<span class="tag-pill duplicate-pill" title="Another artist entry has the same name, for example the same band in another library path. Merge with… on the artist page joins them.">Duplicate</span>` : "",
        artist.status === "IGNORED" ? `<span class="tag-pill" title="Left out of scans and scrapes">Ignored</span>` : "",
        artist.locked ? `<span class="tag-pill" title="Scans and scrapes leave this artist alone">Locked</span>` : "",
        artist.status === "NEW" ? `<span class="badge-new">NEW</span>` : "",
    ].filter(Boolean).join("");
    return `<div class="artist-row${activeArtist}${pendingCount ? " has-pending" : ""}" data-open-artist="${escapeHtml(artist.id)}">
        <button type="button" class="caret-btn" data-toggle-artist="${escapeHtml(artist.id)}" aria-label="Expand">${open ? "▼" : "▶"}</button>
        <input type="checkbox" class="artist-check" data-check-artist="${escapeHtml(artist.id)}" aria-label="Select all albums by ${escapeHtml(artist.name)}">
        <button type="button" class="artist-name"${folderTitle}>${escapeHtml(artist.name)}</button>
        <span class="album-count" title="${escapeHtml(albumCountTitle)}">${albumTotal}</span>
        ${artistAdded ? `<span class="added-date" title="Added to the library">${escapeHtml(artistAdded)}</span>` : ""}
        ${artistCfg.ui_music_processed === false ? "" : artist.status === "PROCESSED"
            ? `<span class="process-mark ok" title="Processed">✓</span>`
            : `<span class="process-mark bad" title="Not processed">✕</span>`}
        ${artistPills ? `<span class="tree-pills">${artistPills}</span>` : ""}
    </div>`;
}

function visibleAlbumIds(artist) {
    const albums = (artist && artist.albums) || [];
    const shown = state.filter === "pending" ? albums.filter((album) => state.pending[album.id]) : albums;
    return shown.map((album) => album.id);
}

function syncArtistChecks() {
    document.querySelectorAll("[data-check-artist]").forEach((box) => {
        const artist = state.artists.find((row) => row.id === box.dataset.checkArtist);
        const ids = visibleAlbumIds(artist);
        const picked = ids.filter((id) => state.selected.has(id)).length;
        box.disabled = ids.length === 0;
        box.indeterminate = picked > 0 && picked < ids.length;
        box.checked = ids.length > 0 && picked === ids.length;
    });
}

function albumLabel(album) {
    const year = sortYear(album);
    return `${year || "----"} - ${album.title}`;
}

function matchPill(album) {
    const tier = album.match_tier || "unmatched";
    const ratio = album.match_ratio || 0;
    if (tier === "gold") return `<span class="pill pill-gold">100% MusicBrainz match</span>`;
    if (tier === "silver") return `<span class="pill pill-silver">${ratio}% partial match</span>`;
    return `<span class="pill">Unmatched</span>`;
}

function matchIcon(tier) {
    if (tier === "gold") return "📀";
    if (tier === "silver") return "💿";
    return "⚪";
}
