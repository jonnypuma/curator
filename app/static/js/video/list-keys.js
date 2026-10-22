function videoArtKeys(art) {
    if (Array.isArray(art)) return art;
    if (!art || typeof art !== "object") return [];
    return Object.keys(art).filter((key) => art[key] && !String(key).startsWith("_"));
}

function videoSelectableRows() {
    return (state.video.rows || []).filter((row) => row && row._kind !== "missing" && row._kind !== "loading");
}

function videoMissingArt(row) {
    const keys = videoArtKeys(row.artwork);
    if (state.media === "sets" || row._kind === "set") return !keys.includes("poster") || !keys.includes("fanart");
    return row._kind === "episode" ? !keys.includes("thumb") : !keys.includes("poster");
}

function videoMissingMeta(row) {
    if (state.media === "sets" || row._kind === "set") return !String(row.overview || "").trim() || !row.tmdb_collection_id;
    if (row._kind === "season") return !String(row.plot || "").trim();
    if (row._kind === "episode") return !row.has_plot;
    return !row.has_plot || !row.tmdb_id;
}

function videoUnscraped(row) {
    if (row._kind === "season") {
        const show = (state.video.shows || []).find((item) => item.id === row._showId);
        return show ? !show.scraped_at : true;
    }
    return !row.scraped_at;
}

function videoRowMatchesTier(row, tier) {
    if (tier === "new") return row.status === "NEW" || !!row.has_new || ((row._kind === "show" || row._kind === "season") && row.new_count);
    if (tier === "unscraped") return videoUnscraped(row);
    if (tier === "art") return videoMissingArt(row);
    if (tier === "meta") return videoMissingMeta(row);
    return true;
}

function selectVideoRows(rows) {
    if (state.media === "tv") selectionReplace("tv", rows.map((row) => `${row._kind}:${row.id}`));
    else if (state.media === "sets") selectionReplace("set", rows.map((row) => row.id));
    else selectionReplace("movie", rows.map((row) => row.id));
    paintCheckedRows();
}

function selectVideoTier(tier) {
    selectVideoRows(videoSelectableRows().filter((row) => videoRowMatchesTier(row, tier)));
}

function selectVideoAll(on) {
    selectVideoRows(on ? videoSelectableRows() : []);
}

function focusVideoList() {
    const list = document.getElementById("video-list");
    if (list) list.focus({ preventScroll: true });
}

function toggleCurrentVideoCheck() {
    let kind = "";
    let id = "";
    if (state.media === "movies") {
        kind = "movie";
        id = state.video.movieId;
    } else if (state.media === "sets") {
        kind = "set";
        id = state.video.setId;
    } else if (state.media === "tv" && state.video.tvSel) {
        kind = state.video.tvSel.type;
        id = state.video.tvSel.id;
    }
    if (!kind || !id) return;
    return selectionToggle(kind, id, false).then(() => paintCheckedRows());
}

function onVideoKey(event) {
    const step = { ArrowDown: 1, ArrowUp: -1, PageDown: 15, PageUp: -15 }[event.key];
    if (event.key === " " || event.code === "Space") {
        if (event.target && event.target.matches && event.target.matches("input, textarea, select")) return;
        event.preventDefault();
        toggleCurrentVideoCheck();
        return;
    }
    if (step) {
        event.preventDefault();
        if (state.media === "movies") moveMovieSelection(step);
        else if (state.media === "sets") moveSetSelection(step);
        else if (state.media === "tv") moveTvSelection(step);
        return;
    }
    if (state.media === "tv" && (event.key === "ArrowRight" || event.key === "ArrowLeft")) {
        event.preventDefault();
        expandTvSelection(event.key === "ArrowRight");
    }
}
