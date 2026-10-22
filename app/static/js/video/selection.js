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

async function selectionToggle(kind, id, shift) {
    if (!id || kind === "missing" || kind === "loading") return;
    if (kind === "movie" || kind === "set") {
        const bucket = selectionChecked(kind);
        const rows = state.video.rows || [];
        if (shift && state.video.checkAnchor) {
            const from = rows.findIndex((row) => row.id === state.video.checkAnchor);
            const to = rows.findIndex((row) => row.id === id);
            if (from >= 0 && to >= 0) {
                const [low, high] = from < to ? [from, to] : [to, from];
                rows.slice(low, high + 1).forEach((row) => {
                    if (row && row.id && row._kind !== "missing" && row._kind !== "loading") bucket.add(row.id);
                });
            }
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

async function selectionToggleVisible(on) {
    const rows = state.video.rows || [];
    if (state.media === "sets") {
        rows.forEach((row) => selectionSet("set", row.id, on));
        return;
    }
    const showIds = [];
    rows.forEach((row) => {
        if (!row || row._kind === "missing" || row._kind === "loading") return;
        if (row._kind && row._kind !== "movie") {
            selectionSet(row._kind, row.id, on);
            if (row._kind === "show") showIds.push(row.id);
        } else selectionSet("movie", row.id, on);
    });
    if (showIds.length && typeof showDetail === "function") {
        const needed = showIds.filter((id) => !state.video.showDetails.has(id));
        const limit = 5;
        for (let i = 0; i < needed.length; i += limit) {
            const batch = needed.slice(i, i + limit);
            await Promise.all(batch.map((id) => showDetail(id).catch(() => null)));
        }
        if (typeof applyTvChildChecks === "function") showIds.forEach((id) => applyTvChildChecks("show", id, on));
    }
}

function paintCheckedRows() {
    state.video.paintToken += 1;
    if (typeof paintVideoRows === "function") paintVideoRows();
    if (typeof paintVideoSelection === "function") paintVideoSelection();
    const all = document.querySelector("#video-list .vm-head .vm-check input, #video-list .vl-head input");
    if (all) all.checked = (state.video.rows || []).length > 0 && (state.video.rows || []).every((row) => matrixChecked(row));
}
