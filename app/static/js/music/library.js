function loadLibrary() {
    if (libraryFlight) {
        libraryFlight.again = true;
        return libraryFlight.promise;
    }
    const flight = { again: false, promise: null };
    libraryFlight = flight;
    flight.promise = runLibraryLoad(flight).finally(() => {
        if (libraryFlight === flight) libraryFlight = null;
    });
    return flight.promise;
}

async function runLibraryLoad(flight) {
    const boot = typeof watchBoot === "function" ? watchBoot("music") : null;
    try {
        do {
            flight.again = false;
            const root = document.getElementById("tree");
            if (root && !treeHasRows(root)) showTreeLoading();
            const serverFilter = state.filter === "pending" ? "all" : state.filter;
            const params = new URLSearchParams({ filter: serverFilter, q: state.query });
            try {
                const data = await api(`/api/library?${params}`);
                // The filter or the search changed while this was loading: this answer is for an
                // older question, so drop it and ask again instead of showing it.
                const nowFilter = state.filter === "pending" ? "all" : state.filter;
                if (nowFilter !== serverFilter || (state.query || "") !== params.get("q")) {
                    flight.again = true;
                    continue;
                }
                state.artists = data.artists || [];
                if (data.sort_ignore_the != null) state.sortIgnoreThe = data.sort_ignore_the !== false;
                state.libraryLoaded = true;
                state.libraryError = "";
                if (data.as_of) state.libraryAsOf = data.as_of;
                if (data.totals) setTotals(data.totals);
                state.filterCounts = data.filter_counts || {};
                // A saved filter that no longer matches anything (Duplicates after the copies are
                // gone, say) would leave the tree empty with no hint why. Fall back to All.
                if (!state.artists.length && !state.query && state.filter !== "all" && state.filter !== "pending"
                    && Number(state.filterCounts[state.filter]) === 0) {
                    state.filter = "all";
                    const select = document.getElementById("library-filter");
                    if (select) select.value = "all";
                    notify("That filter no longer matches anything, so the library is showing All.", "info");
                    flight.again = true;
                }
                if (typeof renderSelectedCount === "function") renderSelectedCount();
                if (typeof syncLibraryFilterButton === "function") syncLibraryFilterButton();
                renderTree();
                renderBatchBar();
                if (state.album && !findAlbum(state.album.album.id)) {
                    state.album = null;
                    state.trackId = null;
                    state.proposal = null;
                    renderCenter();
                    renderEditor();
                }
            } catch (error) {
                notify(error.message, "error");
                state.libraryLoaded = true;
                state.libraryError = error.message || "The library could not be loaded.";
                if (!state.artists.length) renderTree();
                return;
            }
        } while (flight.again);
    } finally {
        if (boot) boot.done();
        finishBoot();
    }
}

function finishBoot() {
    if (typeof completeBootBar === "function") {
        completeBootBar();
        return;
    }
    const boot = document.getElementById("boot-screen");
    if (boot) boot.classList.add("hidden");
}

function treeHasRows(root) {
    return !!(root && root.querySelector(".tree-window"));
}

let filterProgressTimer = 0;

function filterElapsed(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    if (minutes) return `${minutes}m ${seconds}s`;
    return `${seconds}s`;
}

function paintFilterProgress(data, count) {
    const label = document.getElementById("filter-overlay-label");
    const bar = document.getElementById("filter-progress-bar");
    if (!label || !bar) return;
    const phase = data && data.label ? data.label : "Filtering…";
    const done = Number(data && data.done) || 0;
    const total = Number(data && data.total) || 0;
    const known = total > 0 && data && data.phase !== "idle";
    if (known) {
        const shown = Math.min(done, total).toLocaleString();
        label.textContent = `${phase} · ${shown} of ${total.toLocaleString()}`;
        bar.classList.remove("is-unknown");
        bar.style.width = `${Math.max(2, Math.min(100, Math.round((done / total) * 100)))}%`;
        return;
    }
    const countLabel = count ? `Filtering ${count.toLocaleString()} albums` : "Filtering…";
    label.textContent = phase === "Filtering…" ? countLabel : phase;
    bar.classList.add("is-unknown");
    bar.style.width = "";
}

function startFilterProgress() {
    stopFilterProgress();
    const started = Date.now();
    const elapsed = document.getElementById("filter-overlay-elapsed");
    const count = typeof libraryFilterCount === "function" ? libraryFilterCount(state.filter) : null;
    paintFilterProgress(null, count);
    const tick = () => {
        if (elapsed) elapsed.textContent = filterElapsed(Date.now() - started);
        api("/api/library/progress").then((data) => paintFilterProgress(data, count)).catch(() => {});
    };
    if (elapsed) elapsed.textContent = "0s";
    filterProgressTimer = setInterval(tick, 500);
}

function stopFilterProgress() {
    if (filterProgressTimer) clearInterval(filterProgressTimer);
    filterProgressTimer = 0;
}

function showTreeLoading() {
    const root = document.getElementById("tree");
    if (!root || treeHasRows(root)) return;
    root.innerHTML = `<div class="tree-loading" role="status"><span class="activity-spin" aria-hidden="true"></span><span>Loading...</span></div>`;
}

async function selectAlbum(id, keepTrack) {
    const requestId = ++albumRequest;
    state.treeCursor = id;
    const currentId = state.album && state.album.album ? state.album.album.id : "";
    if (currentId && currentId !== id) {
        hideUndo();
        state.albumTitleEditing = false;
        state.albumTitleDraft = "";
        state.albumTitleFocus = false;
    }
    if (!keepTrack) state.proposal = state.pending[id] || null;
    state.center = "album";
    try {
        const data = await api(`/api/albums/${id}`);
        if (requestId !== albumRequest) return;
        state.album = data;
        state.artistId = data.artist ? data.artist.id : null;
        const stillThere = keepTrack && data.tracks.some((track) => track.id === state.trackId);
        if (!stillThere) {
            state.trackId = data.tracks[0] ? data.tracks[0].id : null;
            state.trackIds = state.trackId ? new Set([state.trackId]) : new Set();
            state.trackAnchor = state.trackId;
        } else {
            const live = new Set(data.tracks.map((track) => track.id));
            state.trackIds = new Set([...state.trackIds].filter((id) => live.has(id)));
            if (!state.trackIds.size && state.trackId) state.trackIds.add(state.trackId);
        }
        renderTree();
        revealTreeAlbum(id);
        renderCenter();
        renderEditor();
    } catch (error) {
        notify(error.message, "error");
    }
}

async function selectArtist(id) {
    const requestId = ++artistRequest;
    const leavingAlbum = state.center === "album";
    const switchingArtist = state.center === "artist" && state.artistId && state.artistId !== id;
    if (leavingAlbum || switchingArtist) hideUndo();
    if (state.artistNameEditing && state.artistNameId !== id) {
        state.artistNameEditing = false;
        state.artistNameDraft = "";
        state.artistNameFocus = false;
    }
    holdBioDraft();
    state.center = "artist";
    state.artistId = id;
    state.bioEditing = Boolean(state.bioDrafts[id]);
    state.bioDraft = state.bioDrafts[id] || "";
    state.album = null;
    state.trackId = null;
    state.trackIds = new Set();
    state.trackAnchor = null;
    state.proposal = null;
    if (state.discographyArtist !== id) {
        state.discography = null;
        state.discographyArtist = "";
    }
    try {
        const data = await api(`/api/artists/${id}`);
        if (requestId !== artistRequest) return;
        state.artistDetail = data;
        renderTree();
        renderCenter();
        renderEditor();
        await loadDiscography(id);
    } catch (error) {
        if (requestId !== artistRequest) return;
        notify(error.message, "error");
    }
}

function libraryFilterChoices() {
    const select = document.getElementById("library-filter");
    if (!select) return [];
    return [...select.options].map((option) => ({
        value: option.value,
        label: option.textContent.trim(),
        title: option.title || "",
    })).sort((left, right) => left.label.localeCompare(right.label, undefined, { sensitivity: "base" }));
}

function libraryFilterCount(value) {
    if (value === "pending") return Object.keys(state.pending || {}).length;
    const counts = state.filterCounts || {};
    if (!Object.prototype.hasOwnProperty.call(counts, value)) return null;
    const number = Number(counts[value]);
    return Number.isFinite(number) ? number : null;
}

function libraryFilterLabel(choice) {
    const count = libraryFilterCount(choice.value);
    return count == null ? choice.label : `${choice.label} (${count.toLocaleString()})`;
}

function syncLibraryFilterButton() {
    const select = document.getElementById("library-filter");
    const button = document.getElementById("library-filter-btn");
    if (!select || !button) return;
    const choice = libraryFilterChoices().find((item) => item.value === select.value) || libraryFilterChoices()[0];
    if (!choice) return;
    button.textContent = libraryFilterLabel(choice);
    button.title = choice.title || choice.label;
    paintLibraryFilterOptions();
}

function paintLibraryFilterOptions() {
    const host = document.getElementById("library-filter-options");
    const select = document.getElementById("library-filter");
    const find = document.getElementById("library-filter-find");
    if (!host || !select) return;
    const needle = String((find && find.value) || "").trim().toLowerCase();
    const rows = libraryFilterChoices().filter((choice) => !needle || choice.label.toLowerCase().includes(needle));
    host.innerHTML = rows.map((choice) => {
        const current = choice.value === select.value ? " is-current" : "";
        const title = choice.title ? ` title="${escapeHtml(choice.title)}"` : "";
        return `<button type="button" class="filter-option${current}" data-action="library-filter-pick" data-filter="${escapeHtml(choice.value)}"${title}>${escapeHtml(libraryFilterLabel(choice))}</button>`;
    }).join("") || `<p class="muted filter-option-empty">No matching filters</p>`;
}

function toggleLibraryFilterMenu() {
    const menu = document.getElementById("library-filter-menu");
    const button = document.getElementById("library-filter-btn");
    if (!menu || !button) return;
    const open = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
    if (!open) return;
    const find = document.getElementById("library-filter-find");
    if (find) find.value = "";
    paintLibraryFilterOptions();
    if (find) find.focus();
}

function closeLibraryFilterMenu() {
    const menu = document.getElementById("library-filter-menu");
    const button = document.getElementById("library-filter-btn");
    if (menu) menu.classList.add("hidden");
    if (button) button.setAttribute("aria-expanded", "false");
}

function pickLibraryFilter(value) {
    const select = document.getElementById("library-filter");
    if (!select) return;
    select.value = value || "all";
    closeLibraryFilterMenu();
    syncLibraryFilterButton();
    select.dispatchEvent(new Event("change"));
}
