/* One check set per library. A click changes the open row. These functions change the checks. */

function selectionChecked(kind) {
    if (kind === "album" || kind === "music") return state.selected;
    if (kind === "set" || kind === "sets") return state.video.setChecked;
    if (kind === "tv" || kind === "show" || kind === "season" || kind === "episode") return state.video.tvChecked;
    if (!state.videoSelected) state.videoSelected = new Set();
    return state.videoSelected;
}

function selectionKey(kind, id) {
    const text = String(id || "");
    if (kind === "show" || kind === "season" || kind === "episode") {
        return text.includes(":") ? text : `${kind}:${text}`;
    }
    return text;
}

function selectionHas(kind, id) {
    if (!id || kind === "missing" || kind === "loading") return false;
    return selectionChecked(kind).has(selectionKey(kind, id));
}

function selectionSet(kind, id, on) {
    if (!id || kind === "missing" || kind === "loading") return;
    if ((kind === "show" || kind === "season" || kind === "episode") && typeof setTvChecked === "function") {
        setTvChecked(kind, id, on);
        return;
    }
    const bucket = selectionChecked(kind);
    const key = selectionKey(kind, id);
    if (on) bucket.add(key);
    else bucket.delete(key);
}

function selectionDrop(kind, ids) {
    (ids || []).forEach((id) => selectionSet(kind, id, false));
}

function selectionReplace(kind, ids) {
    const bucket = selectionChecked(kind);
    bucket.clear();
    (ids || []).forEach((id) => {
        if (!id || id === "missing" || id === "loading") return;
        if (kind === "tv") bucket.add(String(id));
        else bucket.add(selectionKey(kind, id));
    });
    if (kind === "album") state.contextAlbumIds = null;
}

function selectionIds(kind, id) {
    if (kind === "show" || kind === "season" || kind === "episode") {
        const bucket = selectionChecked(kind);
        const key = selectionKey(kind, id);
        if (id && !bucket.has(key)) return [String(id)];
        const prefix = `${kind}:`;
        const ids = [...bucket].filter((item) => String(item).startsWith(prefix)).map((item) => String(item).slice(prefix.length));
        if (id && !ids.length) return [String(id)];
        return ids;
    }
    const bucket = selectionChecked(kind);
    const key = id ? String(id) : "";
    if (key && bucket.has(key)) return [...bucket];
    if (key) return [key];
    return [...bucket];
}

function selectionFocusId() {
    if (state.media === "movies") return state.video.movieId || "";
    if (state.media === "sets") return state.video.setId || "";
    if (state.media === "tv") {
        const sel = state.video.tvSel;
        return sel && sel.id ? sel.id : "";
    }
    return state.treeCursor || (state.album && state.album.album && state.album.album.id) || "";
}

function albumActionIds() {
    if (state.contextAlbumIds && state.contextAlbumIds.length) return state.contextAlbumIds.slice();
    return [...selectionChecked("album")];
}

async function selectionToggle(kind, id, shift, versions) {
    if (!id || kind === "missing" || kind === "loading") return;
    if (kind === "movie" || kind === "set") {
        const bucket = selectionChecked(kind);
        const rows = state.video.rows || [];
        // A collapsed versions row stands for every version in it.
        const idsOf = (row) => (kind === "movie" && typeof movieRowIds === "function" ? movieRowIds(row) : [row.id]);
        if (shift && state.video.checkAnchor) {
            const from = rows.findIndex((row) => row.id === state.video.checkAnchor);
            const to = rows.findIndex((row) => row.id === id);
            if (from >= 0 && to >= 0) {
                const [low, high] = from < to ? [from, to] : [to, from];
                rows.slice(low, high + 1).forEach((row) => {
                    if (row && row.id && row._kind !== "missing" && row._kind !== "loading") idsOf(row).forEach((one) => bucket.add(one));
                });
            }
        } else if (versions && versions.length > 1) {
            const on = !versions.every((one) => bucket.has(one));
            versions.forEach((one) => (on ? bucket.add(one) : bucket.delete(one)));
        } else if (bucket.has(id)) bucket.delete(id);
        else bucket.add(id);
        state.video.checkAnchor = id;
        return;
    }
    if (kind === "album") {
        const bucket = selectionChecked("album");
        if (bucket.has(id)) bucket.delete(id);
        else bucket.add(id);
        state.contextAlbumIds = null;
        return;
    }
    const on = !selectionHas(kind, id);
    selectionSet(kind, id, on);
    if ((kind === "show" || kind === "season") && typeof ensureTvChildChecks === "function") {
        await ensureTvChildChecks(kind, id, on);
    }
}

/* The master box in the header. The rows are checked and painted at once.
   A show's seasons and episodes come from its detail, so those load afterwards
   in the background and the list repaints as they arrive. */
function selectionToggleVisible(on) {
    const rows = state.video.rows || [];
    state.video.checkAllToken = (state.video.checkAllToken || 0) + 1;
    const token = state.video.checkAllToken;
    if (state.media === "sets") {
        rows.forEach((row) => selectionSet("set", row.id, on));
        return Promise.resolve();
    }
    const showIds = [];
    rows.forEach((row) => {
        if (!row || row._kind === "missing" || row._kind === "loading") return;
        if (row._kind && row._kind !== "movie") {
            selectionSet(row._kind, row.id, on);
            if (row._kind === "show") showIds.push(row.id);
        } else (typeof movieRowIds === "function" ? movieRowIds(row) : [row.id]).forEach((one) => selectionSet("movie", one, on));
    });
    if (!showIds.length || typeof applyTvChildChecks !== "function") return Promise.resolve();
    // Shows that are already loaded follow straight away.
    showIds.forEach((id) => applyTvChildChecks("show", id, on));
    // Unchecking has nothing to fetch: an unloaded show has no checked children.
    if (!on) return Promise.resolve();
    return selectionCascadeShows(showIds, on, token);
}

async function selectionCascadeShows(showIds, on, token) {
    if (typeof showDetail !== "function") return;
    const needed = showIds.filter((id) => !state.video.showDetails.has(id));
    if (!needed.length) return;
    state.video.tvCascadeActive = (state.video.tvCascadeActive || 0) + 1;
    state.video.tvCascading = true;
    try {
        // One request for all of them. Filters the server cannot judge fall back to opening each show.
        if (await tvBulkChildren(needed, on, token)) return;
        await selectionCascadeByDetail(needed, on, token);
    } finally {
        // Every counting pass ends the message, also one that a later click on the master box replaced.
        state.video.tvCascadeActive = Math.max(0, (state.video.tvCascadeActive || 1) - 1);
        if (!state.video.tvCascadeActive) {
            state.video.tvCascading = false;
            if (typeof renderVideoSelectBar === "function") renderVideoSelectBar();
        }
    }
}

// The seasons and episodes of many shows in one request, already narrowed by the filters that are on.
async function tvBulkChildren(ids, on, token) {
    if (tvColumnFiltersOn()) return false;
    let data;
    try {
        data = await api("/api/v1/tv/selection", { method: "POST", body: { show_ids: ids, filters: tvRibbonKeys() } });
    } catch (error) {
        return false;
    }
    if (!data || data.unsupported || !data.by_show) return false;
    if (token !== state.video.checkAllToken || state.media !== "tv") return true;
    if (!state.video.tvKids) state.video.tvKids = new Map();
    ids.forEach((id) => {
        if (selectionHas("show", id) !== on) return;
        const kids = data.by_show[String(id)] || { seasons: [], episodes: [] };
        const keys = kids.seasons.map((item) => `season:${item}`).concat(kids.episodes.map((item) => `episode:${item}`));
        keys.forEach((key) => state.video.tvChecked.add(key));
        state.video.tvKids.set(String(id), keys);
    });
    return true;
}

async function selectionCascadeByDetail(needed, on, token) {
    const limit = 5;
    let painted = Date.now();
    for (let i = 0; i < needed.length; i += limit) {
        if (token !== state.video.checkAllToken || state.media !== "tv") return;
        const batch = needed.slice(i, i + limit);
        await Promise.all(batch.map((id) => showDetail(id).catch(() => null)));
        // A later click on the master box, All or None, or a single box, wins.
        if (token !== state.video.checkAllToken || state.media !== "tv") return;
        batch.forEach((id) => {
            if (selectionHas("show", id) === on) applyTvChildChecks("show", id, on);
        });
        if (Date.now() - painted > 400) {
            painted = Date.now();
            paintCheckedRows();
        }
    }
}

function paintCheckedRows() {
    state.video.paintToken += 1;
    if (typeof paintVideoRows === "function") paintVideoRows();
    if (typeof paintVideoSelection === "function") paintVideoSelection();
    const all = document.querySelector("#video-list .vm-head .vm-check input, #video-list .vl-head input");
    if (all) {
        // Rows that cannot be checked (missing episodes, loading rows) do not count.
        const real = (state.video.rows || []).filter((row) => row && row._kind !== "missing" && row._kind !== "loading");
        const done = real.filter((row) => matrixChecked(row)).length;
        all.checked = real.length > 0 && done === real.length;
        all.indeterminate = done > 0 && done < real.length;
    }
}
