state.videoScrape = { status: "idle", message: "Idle" };
state.videoScrapeTimer = 0;
state.videoScrapeTicket = 0;
state.videoSelected = new Set();
state.videoMenu = null;
state.videoMatch = null;

const LOCK_SVG = {
    on: `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="8" rx="1.5"/><path d="M5 7V5a3 3 0 0 1 6 0v2" fill="none" stroke-width="1.6"/></svg>`,
    off: `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="8" rx="1.5"/><path d="M5 7V5a3 3 0 0 1 5.6-1.5" fill="none" stroke-width="1.6"/></svg>`,
};

function lockIcon(locked) {
    return `<span class="vlock-icon${locked ? " is-locked" : ""}" title="${locked ? "Locked: scans, scrapes and edits leave it alone" : "Unlocked"}">${locked ? LOCK_SVG.on : LOCK_SVG.off}</span>`;
}

function lockButton(kind, item, action) {
    const locked = !!item.locked;
    const name = action || "video-lock";
    const identity = action ? "" : ` data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(item.id)}"`;
    return `<button type="button" class="vlock${locked ? " is-locked" : ""}" data-action="${name}"${identity} data-locked="${locked ? "1" : ""}" aria-pressed="${locked}">${locked ? LOCK_SVG.on : LOCK_SVG.off}<span class="vlock-label"><span class="vlock-now">${locked ? "Locked" : "Unlocked"}</span><span class="vlock-next">${locked ? "Unlock" : "Lock"}</span></span></button>`;
}

function videoScrapeRunning() {
    return (state.videoScrape || {}).status === "running";
}

function movieSelection(id) {
    return selectionIds("movie", id);
}

// Scrape modal and progress.

function scrapeTargetMedia() {
    const pick = state.videoScrapePick;
    if (pick && pick.media) return pick.media;
    return scrapeMedia();
}

function scrapeScopeLocked() {
    const media = state.videoScrapePick && state.videoScrapePick.media;
    return media === "episodes" || media === "seasons";
}

function scrapeScopeCount() {
    const pick = state.videoScrapePick;
    if (pick && pick.ids && pick.ids.length) return pick.ids.length;
    return selectedScrapeIds().length;
}

var SCRAPE_FIELDS = {
    movie: [
        ["title", "Title"], ["original_title", "Original title"], ["english_title", "English title"],
        ["mpaa", "MPAA"], ["certification", "Certification"], ["tagline", "Tagline"], ["plot", "Plot"],
        ["year", "Year"], ["release_date", "Release date"], ["rating", "Rating"], ["top250", "IMDb Top 250"],
        ["runtime", "Runtime"], ["genres", "Genres"], ["language", "Language"], ["country", "Country"],
        ["studio", "Studio"], ["tags", "Tags"], ["set", "Movie set"], ["trailer", "Trailer"],
        ["actors", "Actors"], ["crew", "Crew"], ["director", "Director"], ["premiered", "Premiered"],
        ["credits", "Credits"], ["ids", "Unique IDs"],
    ],
    show: [
        ["title", "Title"], ["original_title", "Original title"], ["english_title", "English title"],
        ["tagline", "Tagline"], ["plot", "Plot"], ["aired", "Aired"], ["year", "Year"], ["rating", "Rating"], ["tags", "Tags"],
        ["runtime", "Runtime"], ["certification", "Certification"], ["genres", "Genres"], ["language", "Language"],
        ["country", "Country"], ["studio", "Studio / network"], ["trailer", "Trailer"], ["actors", "Actors"],
        ["crew", "Crew"],
    ],
    season: [
        ["title", "Title"], ["season_name", "Season name"], ["sort_title", "Sort title"], ["year", "Year"],
        ["plot", "Plot"], ["premiered", "Premiered"],
        ["id_tmdb", "TMDB id"], ["id_imdb", "IMDb id"], ["id_tvdb", "TVDB id"], ["id_trakt", "Trakt id"],
        ["id_tvmaze", "TVMaze id"], ["id_wikidata", "Wikidata id"],
    ],
    episode: [
        ["title", "Title"], ["original_title", "Original title"], ["english_title", "English title"],
        ["plot", "Plot"], ["aired", "Aired"], ["rating", "Rating"], ["tags", "Tags"], ["runtime", "Runtime"],
        ["actors", "Actors"], ["crew", "Crew"], ["ids", "Unique IDs"], ["credits", "Credits"],
        ["director", "Director"], ["premiered", "Premiered"],
    ],
};

const SCRAPE_ART = {
    movie: [
        ["poster", "Poster"], ["fanart", "Fanart"], ["banner", "Banner"], ["clearart", "Clearart"],
        ["landscape", "Thumb"], ["clearlogo", "Clearlogo"], ["discart", "Disc art"], ["keyart", "Keyart"],
        ["squareart", "Square art"], ["extrafanart", "Extrafanart"], ["extrathumbs", "Extrathumb"],
    ],
    show: [
        ["poster", "Poster"], ["fanart", "Fanart"], ["banner", "Banner"], ["clearart", "Clearart"],
        ["landscape", "Thumb"], ["clearlogo", "Clearlogo"], ["keyart", "Keyart"], ["squareart", "Square art"],
        ["extrafanart", "Extrafanart"], ["extrathumbs", "Extrathumb"],
    ],
    season: [["poster", "Season poster"]],
    episode: [["thumb", "Episode thumb"]],
};

const SCRAPE_TITLES = { movie: "Movies", show: "TV shows", season: "Seasons", episode: "Episodes" };
const SCRAPE_SOURCE_LABELS = {
    tmdb: "TMDB", tvdb: "TheTVDB", tvmaze: "TVMaze", omdb: "OMDb", trakt: "Trakt", fanart: "Fanart.tv",
};

function scrapeLevels(media) {
    if (media === "tv") return ["show", "season", "episode"];
    if (media === "seasons") return ["season", "episode"];
    if (media === "episodes") return ["episode"];
    if (media === "sets") return [];
    return ["movie"];
}

function scrapeSourceOptions(names) {
    const options = [["", "Settings order"]];
    (names || []).forEach((name) => {
        const key = String(name || "").trim().toLowerCase();
        if (!key || options.some(([value]) => value === key)) return;
        options.push([key, SCRAPE_SOURCE_LABELS[key] || key]);
    });
    return options;
}

function scrapeMetaOptions(level) {
    const video = ((state.settings || {}).video) || {};
    const chain = level === "movie" ? video.movie_sources : video.tv_sources;
    const allowed = new Set(["tmdb", "tvdb", "omdb", "trakt"]);
    const names = (chain || []).filter((name) => allowed.has(name));
    if (level === "movie" && !names.includes("tvdb")) names.push("tvdb");
    return scrapeSourceOptions(names);
}

function scrapeArtOptions(level) {
    const video = ((state.settings || {}).video) || {};
    const tv = level === "show" || level === "season" || level === "episode";
    const chain = tv
        ? (Array.isArray(video.tv_art_sources) ? video.tv_art_sources : video.art_sources)
        : video.art_sources;
    const names = (chain || ["fanart", "tmdb", "tvdb"]).slice();
    if (!tv && !names.includes("tvdb")) names.push("tvdb");
    return scrapeSourceOptions(names);
}

function scrapeSelect(kind, level, options) {
    const attr = kind === "meta" ? `data-scrape-meta="${level}"` : `data-scrape-art-primary="${level}"`;
    const label = kind === "meta" ? "Metadata provider" : "Artwork provider";
    return `<label class="field">${label}
        <select ${attr}>${options.map(([value, text]) => `<option value="${escapeHtml(value)}">${escapeHtml(text)}</option>`).join("")}</select>
    </label>`;
}

function metaFieldOn(level, key) {
    const video = ((state.settings || {}).video) || {};
    const saved = video[{ movie: "movie_fields", show: "show_fields", season: "season_fields", episode: "episode_fields" }[level]];
    if (!Array.isArray(saved)) return true;
    return saved.includes(key);
}

function scrapeChecks(level, rows, art) {
    return rows.map(([key, label]) => {
        const attr = art ? "data-scrape-art" : "data-scrape-field";
        const on = art || metaFieldOn(level, key);
        return `<label class="choice"><input type="checkbox" ${attr} value="${level}:${key}" ${on ? "checked" : ""}> ${escapeHtml(label)}</label>`;
    }).join("");
}

function scrapePickTools(kind) {
    return `<span class="scrape-pick-tools">
        <button type="button" class="btn-ghost" data-action="video-scrape-picks" data-pick="${kind}" data-on="1">Select all</button>
        <button type="button" class="btn-ghost" data-action="video-scrape-picks" data-pick="${kind}" data-on="0">None</button>
    </span>`;
}

function setScrapePicks(action) {
    const head = action.closest(".scrape-pick-head");
    const box = head && head.nextElementSibling;
    if (!box) return;
    const on = action.dataset.on === "1";
    const attr = action.dataset.pick === "art" ? "data-scrape-art" : "data-scrape-field";
    box.querySelectorAll(`input[${attr}]`).forEach((input) => {
        if (input.dataset.fixed) return;
        input.checked = on;
    });
}

function paintScrapeBlocks() {
    const host = document.getElementById("video-scrape-blocks");
    if (!host) return;
    const media = scrapeTargetMedia();
    const levels = scrapeLevels(media);
    const signature = levels.join(",");
    if (host.dataset.levels === signature && host.childElementCount) return;
    host.dataset.levels = signature;
    if (!levels.length) {
        host.innerHTML = `<p class="muted">Movie sets use the artwork and overview settings for this library.</p>`;
        return;
    }
    host.innerHTML = levels.map((level) => {
        const meta = scrapeSelect("meta", level, scrapeMetaOptions(level));
        const seasonNumber = level === "season"
            ? `<label class="choice"><input type="checkbox" data-fixed="1" checked disabled> Season number</label>`
            : "";
        return `<section class="scrape-block">
            <h3>${escapeHtml(SCRAPE_TITLES[level])}</h3>
            ${meta}
            <div class="scrape-pick-head"><p class="field-label">Select metadata to be scraped</p>${scrapePickTools("field")}</div>
            <div class="scrape-picks">${seasonNumber}${scrapeChecks(level, SCRAPE_FIELDS[level], false)}</div>
            ${scrapeSelect("art", level, scrapeArtOptions(level))}
            <div class="scrape-pick-head"><p class="field-label">Select artwork to be scraped</p>${scrapePickTools("art")}</div>
            <div class="scrape-picks">${scrapeChecks(level, SCRAPE_ART[level], true)}</div>
        </section>`;
    }).join("");
}

function showRecord(id) {
    return (state.video.shows || []).find((show) => show.id === id) || null;
}

function scrapeParentShow(kind, id) {
    if (kind === "show" || kind === "tv") return showRecord(id);
    const row = (state.video.rows || []).find((item) => item.id === id && (item._kind === kind || item._kind === "episode" || item._kind === "season"));
    const showId = row && (row._showId || row.show_id);
    return showId ? showRecord(showId) : null;
}

function scrapeMatchRows() {
    const pick = state.videoScrapePick;
    const media = scrapeTargetMedia();
    if (media === "sets") return [];
    if (media === "movies") {
        const ids = (pick && pick.ids) || selectionIds("movie");
        return ids.map((id) => {
            const movie = (state.video.movies || []).find((item) => item.id === id);
            return { id, title: (movie && movie.title) || "Movie", matched: !!(movie && (movie.tmdb_id || movie.imdb_id)), kind: "movie" };
        });
    }
    const kind = media === "episodes" ? "episode" : media === "seasons" ? "season" : "show";
    const ids = (pick && pick.ids) || (kind === "show" ? selectedScrapeIds() : []);
    const seen = new Set();
    const rows = [];
    ids.forEach((id) => {
        const show = kind === "show" ? showRecord(id) : scrapeParentShow(kind, id);
        const key = (show && show.id) || id;
        if (seen.has(key)) return;
        seen.add(key);
        rows.push({
            id: (show && show.id) || "",
            title: (show && show.title) || "Show",
            matched: !!(show && (show.tmdb_id || show.tvdb_id)),
            kind: "show",
        });
    });
    return rows;
}

function paintScrapeMatch() {
    const host = document.getElementById("video-scrape-unmatched");
    if (!host) return;
    const scope = (document.querySelector("input[name='video-scrape-scope']:checked") || {}).value;
    const rows = scope === "selected" || scrapeScopeLocked() ? scrapeMatchRows() : [];
    const missing = rows.filter((row) => !row.matched);
    if (!missing.length) {
        host.classList.add("hidden");
        host.innerHTML = "";
        return;
    }
    const one = missing.length === 1 && missing[0].id;
    host.classList.remove("hidden");
    host.innerHTML = `<p class="restore-warning">${missing.length === rows.length
        ? "This needs a match before it can be scraped. Curator will not guess the title."
        : `${missing.length} ${missing.length === 1 ? "show has" : "shows have"} no match and will be skipped.`} ${missing.map((row) => escapeHtml(row.title)).join(", ")}</p>
        ${one ? `<p><button type="button" class="btn-ghost" data-action="video-scrape-fix" data-kind="${missing[0].kind}" data-id="${escapeHtml(missing[0].id)}">Fix match</button></p>` : ""}`;
}

function openVideoScrapeModal(scope, pick) {
    if (!pick && state.media === "tv") {
        const groups = selectedVideoGroups();
        if (groups.length === 1) {
            const group = groups[0];
            pick = { media: scrapeMediaFor(group.kind), ids: group.ids };
        } else if (!groups.length && state.video && state.video.tvSel) {
            const sel = state.video.tvSel;
            if (sel.type === "episode" || sel.type === "season") {
                pick = { media: scrapeMediaFor(sel.type), ids: [sel.id] };
            } else if (sel.type === "show") {
                pick = { media: "tv", ids: [sel.id] };
            }
        }
    }
    state.videoScrapePick = pick && pick.ids && pick.ids.length ? pick : null;
    const count = scrapeScopeCount();
    const locked = scrapeScopeLocked();
    const chosen = locked ? "selected" : (scope || (count ? "selected" : "missing"));
    document.getElementById("video-scrape-selected").textContent = String(count);
    document.querySelectorAll("input[name='video-scrape-scope']").forEach((input) => {
        if (input.value === "selected") input.disabled = !count;
        input.checked = input.value === chosen;
    });
    const host = document.getElementById("video-scrape-blocks");
    if (host) host.dataset.levels = "";
    if (!videoScrapeRunning()) {
        ["video-scrape-overwrite-meta", "video-scrape-overwrite-art"].forEach((id) => {
            const box = document.getElementById(id);
            if (box) box.checked = false;
        });
        const rewrite = document.getElementById("video-scrape-rewrite-nfo");
        if (rewrite) rewrite.checked = !!(((state.settings || {}).video || {}).scan_rewrite_nfo);
    }
    document.getElementById("video-scrape-modal").classList.remove("hidden");
    paintScrapeBlocks();
    paintScrapeMatch();
    renderVideoScrapeModal();
    pollVideoScrape();
}

function scrapeMedia() {
    return state.media === "tv" ? "tv" : state.media === "sets" ? "sets" : "movies";
}

function selectedScrapeIds() {
    if (state.media === "tv") {
        const pick = state.videoScrapePick;
        if (pick && pick.ids && pick.ids.length) return pick.ids;
        const groups = selectedVideoGroups();
        if (groups.length === 1) return groups[0].ids;
        const picked = tvCheckedShows();
        if (picked.length) return picked;
        const sel = state.video.tvSel;
        if (sel) {
            if (sel.type === "episode" || sel.type === "season" || sel.type === "show") return [sel.id];
        }
        return [];
    }
    if (state.media === "sets") {
        const picked = selectionIds("set");
        if (picked.length) return picked;
        return state.video.setId ? [state.video.setId] : [];
    }
    return selectionIds("movie");
}

function tvMenuIds(kind, id) {
    return selectionIds(kind, id);
}

async function scrapeSelectedRows() {
    if (state.media === "tv") {
        const groups = selectedVideoGroups();
        if (groups.length === 1) {
            const group = groups[0];
            const media = scrapeMediaFor(group.kind);
            return startVideoScrape("selected", group.ids, null, media);
        }
    }
    const ids = state.media === "tv" ? tvCheckedShows() : state.media === "sets" ? selectionIds("set") : selectionIds("movie");
    if (!ids.length) return;
    await startVideoScrape("selected", ids);
}

async function reloadSelectedRows(action) {
    const mode = (action && action.dataset && action.dataset.mode) || state.batchRescanMode || "deep";
    const word = { incremental: "Incremental", full: "Full", deep: "Deep" }[mode] || "Deep";
    let targets = [];
    if (state.media === "tv") {
        const ids = new Set(tvCheckedShows());
        targets = (state.video.shows || []).filter((show) => ids.has(show.id) && show.path && show.path.indexOf("wanted://") !== 0).map((show) => show.path);
    } else {
        targets = (state.video.movies || []).filter((movie) => selectionHas("movie", movie.id)).map((movie) => movie.folder || movie.path).filter((path) => path && path.indexOf("wanted://") !== 0);
    }
    targets = [...new Set(targets.filter(Boolean))];
    if (!targets.length) {
        notify("Nothing selected has a folder to scan yet.", "info");
        return;
    }
    const data = await api("/api/v1/scan", { method: "POST", body: { media: state.media === "tv" ? "tv" : "movies", mode, targets } });
    if (data.queued) {
        notify(data.duplicate ? "That scan is already queued." : `${word} scan queued for ${targets.length} folder${targets.length === 1 ? "" : "s"}. It starts when the current scan finishes.`, "info");
        return;
    }
    if (!data.started) notify("A scan is already running.", "info");
    else notify(`${word} scan of ${targets.length} folder${targets.length === 1 ? "" : "s"}.`, "info");
    applyVideoScan(data.scan || {});
    pollVideoScan();
}

function rememberLocalArt(kind, id, artKind) {
    if (!kind || !id || !artKind) return;
    const add = (row) => {
        if (!row || String(row.id) !== String(id)) return;
        const art = Array.isArray(row.artwork) ? row.artwork.slice() : Object.keys(row.artwork || {});
        if (!art.includes(artKind)) art.push(artKind);
        row.artwork = art;
    };
    (state.video.movies || []).forEach(add);
    (state.video.sets || []).forEach(add);
    (state.video.shows || []).forEach((show) => {
        add(show);
        (show.seasons || []).forEach(add);
        (show.episodes || []).forEach(add);
    });
    const details = state.video.showDetails;
    if (details && details.forEach) {
        details.forEach((detail) => {
            add(detail);
            (detail.seasons || []).forEach(add);
            (detail.episodes || []).forEach(add);
        });
    }
    state.video.paintToken = (state.video.paintToken || 0) + 1;
    if (typeof renderVideoList === "function") renderVideoList();
}

async function fetchVideoArtwork(action) {
    const data = await api("/api/v1/artwork/fetch", { method: "POST", body: { kind: action.dataset.kind, id: action.dataset.id } });
    if (data.saved) {
        (data.kinds || []).forEach((artKind) => rememberLocalArt(action.dataset.kind, action.dataset.id, artKind));
        notify("Artwork saved.", "success");
        return refreshOpenVideo();
    }
    applyVideoScrape(data.scrape || {});
    pollVideoScrape();
}

const VIDEO_ART_KINDS = {
    movie: [["poster", "Poster"], ["fanart", "Fanart"], ["clearlogo", "Clearlogo"], ["clearart", "Clearart"], ["banner", "Banner"], ["landscape", "Landscape"], ["discart", "Discart"], ["keyart", "Keyart"], ["squareart", "Square art"]],
    show: [["poster", "Poster"], ["fanart", "Fanart"], ["clearlogo", "Clearlogo"], ["clearart", "Clearart"], ["banner", "Banner"], ["landscape", "Landscape"], ["characterart", "Character art"], ["discart", "Discart"], ["squareart", "Square art"]],
    season: [["poster", "Season poster"], ["banner", "Season banner"], ["landscape", "Season landscape"], ["fanart", "Season fanart"]],
    episode: [["thumb", "Thumbnail"]],
    set: [["poster", "Poster"], ["fanart", "Fanart"], ["clearlogo", "Clearlogo"], ["clearart", "Clearart"], ["banner", "Banner"], ["landscape", "Landscape"], ["discart", "Discart"], ["squareart", "Square art"]],
};

function videoArtCard(item) {
    const caption = [item.kind, item.source, item.lang, item.selected ? "Selected" : ""].filter(Boolean).join(" · ");
    const classes = ["art-card", item.selected ? "selected" : "", item.suggested ? "suggested" : ""].filter(Boolean).join(" ");
    const choose = `<button type="button" class="art-download-btn" data-action="video-art-choose" data-url="${escapeHtml(item.url || "")}" data-art-kind="${escapeHtml(item.kind || "")}" title="Download and set this artwork" aria-label="Download and set this artwork"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/></svg></button>`;
    const reason = item.suggested && item.suggestion_reason ? ` · Suggested (${escapeHtml(item.suggestion_reason)})` : "";
    return `<div class="${classes}" data-asset="${escapeHtml(item.kind || "")}" data-selected="${item.selected ? "1" : ""}" data-suggested="${item.suggested ? "1" : ""}" data-local="${item.local ? "1" : ""}" data-url="${escapeHtml(item.url || "")}">
        <div class="art-shot">
            <button type="button" class="art-pick" data-action="video-art-highlight" title="Compare this artwork">
                <img src="${escapeHtml(item.preview || item.url)}" alt="">
            </button>
            ${choose}
            ${zoomButton("video-art-zoom", `data-src="${escapeHtml(item.url)}" data-caption="${escapeHtml(caption)}"`)}
        </div>
        <div class="art-meta-row">
            <div class="art-meta">${escapeHtml(item.source || "TMDB")}${item.width ? ` · ${item.width}×${item.height}` : ""}${item.lang ? ` · ${escapeHtml(item.lang)}` : ""}${item.selected ? " · Selected" : ""}${reason}</div>
            ${item.selected || item.local ? `<button type="button" class="art-delete" data-action="video-art-delete" data-art-kind="${escapeHtml(item.kind || "")}" title="Delete the current ${escapeHtml(item.kind || "")} file" aria-label="Delete the current ${escapeHtml(item.kind || "")} artwork">${trashIcon()}</button>` : ""}
        </div>
    </div>`;
}

function paintVideoArtChoices(kind, images, artwork) {
    const catalog = (VIDEO_ART_KINDS[kind] || VIDEO_ART_KINDS.movie).slice();
    const known = new Set(catalog.map(([key]) => key));
    const local = artwork || {};
    (images || []).forEach((item) => {
        if (item.kind && !known.has(item.kind)) {
            known.add(item.kind);
            catalog.push([item.kind, item.kind]);
        }
    });
    Object.keys(local).forEach((key) => {
        if (key.startsWith("_") || typeof local[key] !== "string" || known.has(key)) return;
        known.add(key);
        catalog.push([key, key]);
    });
    const empty = !(images || []).length && !Object.keys(local).some((key) => !key.startsWith("_") && typeof local[key] === "string");
    const note = empty ? `<p class="muted">No images were returned. Scrape the item so it has a TMDB id, or upload your own below.</p>` : "";
    return note + catalog.map(([key, label]) => {
        const rows = (images || []).filter((item) => item.kind === key);
        const path = typeof local[key] === "string" ? local[key] : "";
        const matched = rows.some((item) => item.selected);
        const current = path && !matched
            ? videoArtCard({ kind: key, source: "Current file", url: artUrl(path), preview: artUrl(path, 342), selected: true, local: true })
            : "";
        const cards = current + (rows.length ? rows.map(videoArtCard).join("") : "");
        const body = cards || `<p class="muted">No ${escapeHtml(label.toLowerCase())} candidates yet.</p>`;
        const currentSrc = path ? artUrl(path) : "";
        return `<div class="asset-type-head"><h3 class="section-label">${escapeHtml(label)}</h3><button type="button" class="btn-ghost art-upload" data-action="video-art-upload" data-art-kind="${escapeHtml(key)}" title="Upload ${escapeHtml(label)} from this computer" aria-label="Upload ${escapeHtml(label)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V5"/><path d="m7 10 5-5 5 5"/><path d="M5 20h14"/></svg><span>Upload</span></button></div><div class="art-grid" data-current="${escapeHtml(currentSrc)}">${body}</div>`;
    }).join("");
}

async function openVideoArtPicker(kind, id, currentSrc) {
    if (!kind || !id) return;
    state.videoArtPick = { kind, id };
    if (typeof fitModalChrome === "function") fitModalChrome();
    document.getElementById("video-art-modal").classList.remove("hidden");
    revealCompare(
        document.getElementById("video-art-compare"),
        document.getElementById("video-compare-current"),
        document.getElementById("video-compare-candidate"),
        document.getElementById("video-compare-label"),
        currentSrc || "",
        currentSrc || "",
        "Compare"
    );
    document.getElementById("video-art-body").innerHTML = `<p class="muted">Searching artwork…</p>`;
    let data;
    let problem = "";
    try {
        data = await api(`/api/v1/artwork/choices/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
    } catch (error) {
        // The online lookup failed (no TMDB key, no TMDB id yet). Uploading still works.
        data = { images: [], artwork: {} };
        problem = `<p class="muted">The online artwork search did not work: ${escapeHtml(error.message || "unknown error")}. You can still upload your own image below.</p>`;
    }
    const title = document.getElementById("video-art-title");
    if (title) title.textContent = data.title ? `Artwork · ${data.title}` : "Artwork";
    document.getElementById("video-art-body").innerHTML = problem + paintVideoArtChoices(kind, data.images || [], data.artwork || {});
    primeVideoCompare();
}

function primeVideoCompare() {
    const body = document.getElementById("video-art-body");
    if (!body) return;
    const kind = (state.videoArtPick && state.videoArtPick.kind) || "movie";
    const asset = kind === "episode" ? "thumb" : "poster";
    const section = [...body.querySelectorAll(".art-grid")].find((grid) => {
        const sample = grid.querySelector(".art-card");
        return sample && sample.dataset.asset === asset;
    });
    const cards = section ? [...section.querySelectorAll(".art-card")] : [...body.querySelectorAll(".art-card")];
    const ranked = cards.find((item) => item.dataset.suggested === "1" && item.dataset.local !== "1" && item.dataset.selected !== "1")
        || cards.find((item) => item.dataset.local !== "1");
    if (ranked && ranked.dataset.selected !== "1") {
        ranked.dataset.suggested = "1";
        ranked.classList.add("suggested");
        showVideoCompare(ranked);
        return;
    }
    const current = cards.find((item) => item.dataset.local === "1" || item.dataset.selected === "1") || cards[0];
    if (current) showVideoCompare(current);
}

function showVideoCompare(card) {
    const frame = document.getElementById("video-art-compare");
    const current = document.getElementById("video-compare-current");
    const candidate = document.getElementById("video-compare-candidate");
    const label = document.getElementById("video-compare-label");
    const image = card && card.querySelector("img");
    if (!frame || !image) return;
    document.querySelectorAll("#video-art-body .art-card.is-compared").forEach((other) => other.classList.remove("is-compared"));
    card.classList.add("is-compared");
    const grid = card.closest(".art-grid");
    const currentUrl = (grid && grid.dataset.current) || "";
    const kind = card.dataset.asset || "artwork";
    frame.dataset.asset = kind;
    const suggested = card.dataset.suggested === "1" && card.dataset.selected !== "1";
    const caption = !currentUrl
        ? `Preview ${kind} · no artwork saved yet`
        : (suggested ? `Compare ${kind} · suggested` : `Compare ${kind}`);
    // The card shows a small copy. The download button holds the original, which is what quality is judged on.
    const original = card.querySelector("[data-action='video-art-choose']");
    revealCompare(frame, current, candidate, label, currentUrl, fullImageUrl((original && original.dataset.url) || image.src), caption);
}

function chooseVideoArtFile(artKind) {
    const input = document.getElementById("video-art-file");
    if (!input || !artKind || !state.videoArtPick) return;
    state.videoArtUpload = artKind;
    input.value = "";
    input.click();
}

async function uploadVideoArt(file, artKind) {
    const pick = state.videoArtPick || {};
    if (!pick.kind || !pick.id) throw new Error("Open an item's artwork first.");
    if (file.size > 25 * 1024 * 1024) throw new Error("Artwork files must be 25 MB or smaller");
    const form = new FormData();
    form.append("file", file);
    form.append("art_kind", artKind);
    const response = await fetch(`/api/v1/artwork/upload/${encodeURIComponent(pick.kind)}/${encodeURIComponent(pick.id)}`, { method: "POST", body: form });
    const saved = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(saved.error || saved.detail || response.statusText);
    noteArtVersion(saved && saved.path);
    rememberLocalArt(pick.kind, pick.id, artKind);
    notify("Artwork uploaded.", "success");
    const data = await api(`/api/v1/artwork/choices/${encodeURIComponent(pick.kind)}/${encodeURIComponent(pick.id)}`);
    const body = document.getElementById("video-art-body");
    if (body) body.innerHTML = paintVideoArtChoices(pick.kind, data.images || [], data.artwork || {});
    primeVideoCompare();
    await refreshOpenVideo();
}

async function chooseVideoArt(action) {
    const card = action.closest(".art-card");
    if (card && card.dataset.local === "1") {
        notify("Current artwork kept.", "info");
        return;
    }
    const pick = state.videoArtPick || {};
    const saved = await api(`/api/v1/artwork/choices/${encodeURIComponent(pick.kind)}/${encodeURIComponent(pick.id)}`, {
        method: "POST",
        body: { url: action.dataset.url, art_kind: action.dataset.artKind },
    });
    noteArtVersion(saved && saved.path);
    const frame = document.getElementById("video-art-compare");
    if (saved && saved.path && frame && frame.dataset.asset === action.dataset.artKind) {
        const grid = action.closest(".art-grid");
        const currentUrl = artUrl(saved.path);
        if (grid) grid.dataset.current = currentUrl;
        const current = document.getElementById("video-compare-current");
        if (current && !frame.classList.contains("hidden")) current.src = currentUrl;
    }
    rememberLocalArt(pick.kind, pick.id, action.dataset.artKind);
    notify("Artwork saved.", "success");
    const kind = action.dataset.artKind;
    document.querySelectorAll("#video-art-body .art-card").forEach((other) => {
        if (other.dataset.asset !== kind) return;
        if (other.dataset.local === "1") {
            other.remove();
            return;
        }
        other.classList.remove("selected");
        other.dataset.selected = "";
        const meta = other.querySelector(".art-meta");
        if (meta) meta.textContent = meta.textContent.replace(/ · Selected$/, "");
    });
    if (card && card.isConnected) {
        card.classList.add("selected");
        card.dataset.selected = "1";
        const meta = card.querySelector(".art-meta");
        if (meta && !meta.textContent.endsWith(" · Selected")) meta.textContent += " · Selected";
    }
    await refreshOpenVideo();
}

async function deleteVideoArt(action) {
    const pick = state.videoArtPick || {};
    const owner = action.dataset.kind && action.dataset.id ? { kind: action.dataset.kind, id: action.dataset.id } : pick;
    const artKind = action.dataset.artKind;
    if (!owner.kind || !owner.id || !artKind) return;
    await api(`/api/v1/artwork/${encodeURIComponent(owner.kind)}/${encodeURIComponent(owner.id)}/${encodeURIComponent(artKind)}`, { method: "DELETE" });
    notify(`The ${artKind} artwork was deleted.`, "success");
    const modal = document.getElementById("video-art-modal");
    if (modal && !modal.classList.contains("hidden") && pick.kind === owner.kind && pick.id === owner.id) {
        await openVideoArtPicker(owner.kind, owner.id, "");
    }
    await refreshOpenVideo();
}

// Reopening the item after an artwork change must not move the library list.
async function refreshOpenVideo() {
    const list = document.getElementById("video-list");
    const top = list ? list.scrollTop : 0;
    try {
        return await openCurrentVideo();
    } finally {
        if (list && list.isConnected && top > 0 && typeof pinListScroll === "function") pinListScroll(list, top);
    }
}

function openCurrentVideo() {
    if (state.media === "movies" && state.video.movieId) return openMovie(state.video.movieId);
    if (state.media === "sets" && state.video.setId) return openSet(state.video.setId);
    const sel = state.video.tvSel || {};
    if (sel.type === "episode") return openEpisode(sel.id);
    if (sel.type === "season") return openSeason(sel.id, sel.show || "", true);
    if (sel.type === "show") return openShow(sel.id);
    return null;
}

function upgradeFactItem(item) {
    return {
        resolution: item.resolution || "",
        source_format: item.source_format || (!item.video_source ? (item.source || "") : ""),
        video_source: item.video_source || "",
        video_codec: item.codec || item.video_codec || "",
        hdr_format: item.hdr_format || "",
        audio: item.audio || "",
        edition: item.edition || "",
        release_group: item.release_group || "",
        bitrate_mbps: item.bitrate_mbps || 0,
        duration_seconds: item.duration_seconds || 0,
        size_bytes: item.size_bytes || 0,
    };
}

function suggestedKeepId(items) {
    const ranked = [...(items || [])].sort((left, right) => {
        const leftFailed = left.probe_error ? 1 : 0;
        const rightFailed = right.probe_error ? 1 : 0;
        return leftFailed - rightFailed
            || (Number(right.score) || 0) - (Number(left.score) || 0)
            || (Number(right.size_bytes) || 0) - (Number(left.size_bytes) || 0);
    });
    return ranked[0] ? ranked[0].id : "";
}

function upgradeCompareHtml(copies, kind) {
    const items = (copies || []).map((item) => ({
        ...item,
        video_codec: item.video_codec || item.codec || "",
    }));
    const keep = suggestedKeepId(items);
    const rows = videoDuplicateFactRows(items);
    const cards = items.map((item) => videoDuplicateCard(item, kind, rows, item.id === keep)).join("");
    return `<div class="upgrade-scroll"><table class="upgrade-table"><thead><tr>${cards}</tr></thead></table></div>`;
}

function clearVideoCopyMarks(kind, id) {
    const wipe = (item) => {
        if (item && String(item.id) === String(id)) {
            item.duplicate_release = false;
            item.upgrade = false;
            item.upgrade_path = "";
        }
    };
    if (kind === "movie") (state.video.movies || []).forEach(wipe);
    (state.video.showDetails || new Map()).forEach((detail) => (detail.episodes || []).forEach(wipe));
    wipe(state.video.detail);
    if (state.media === "movies" && typeof renderMovieMatrix === "function") renderMovieMatrix();
    else if (state.media === "tv" && typeof renderTvTree === "function") renderTvTree();
    if (state.video.detail && typeof renderVideoCenter === "function") renderVideoCenter();
}

async function showVideoUpgrade(kind, id) {
    const data = await api(`/api/v1/copies/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
    const copies = data.copies || [];
    if (copies.length < 2) {
        notify("No other copy is stored for this item.", "info");
        if (data.cleared) clearVideoCopyMarks(kind, id);
        return;
    }
    state.videoUpgrade = { kind, id, copies };
    document.getElementById("upgrade-title").textContent = kind === "episode" ? "Episode upgrade" : "Movie upgrade";
    document.getElementById("upgrade-summary").textContent = "The green copy is the one to keep. Delete removes that copy from disk. Remove from library leaves the file.";
    document.getElementById("upgrade-compare").innerHTML = upgradeCompareHtml(copies, kind);
    const actions = document.getElementById("upgrade-actions");
    if (actions) actions.classList.add("hidden");
    document.getElementById("upgrade-modal").classList.remove("hidden");
}

async function confirmVideoUpgrade(purge) {
    const pick = state.videoUpgrade;
    if (!pick) return;
    if (!purge) {
        notify("Turn on the checkbox to delete the other copies.", "warning");
        return;
    }
    const chosen = document.querySelector("input[name='video-upgrade-keep']:checked");
    if (!chosen) {
        notify("Choose the copy to keep.", "warning");
        return;
    }
    const data = await api(`/api/v1/copies/${encodeURIComponent(pick.kind)}/${encodeURIComponent(pick.id)}/replace`, {
        method: "POST",
        body: { keep_id: chosen.value, purge },
    });
    state.videoUpgrade = null;
    document.getElementById("upgrade-modal").classList.add("hidden");
    notify(purge ? "The other copies were deleted." : "Nothing was deleted. Turn on the checkbox to remove the other copies.", purge ? "success" : "info");
    const removed = (data.removed || []).filter((id) => id && id !== data.kept);
    forgetLocalVideo(pick.kind === "episode" ? "episode" : "movie", removed);
    if (typeof applyPeerFlags === "function") applyPeerFlags(data.peers);
    if (typeof forgetDuplicateUndo === "function") forgetDuplicateUndo(removed);
    if (pick.kind === "movie" && data.kept) return openMovie(data.kept);
    if (pick.kind === "episode" && data.kept) return openEpisode(data.kept);
}

function selectedVideoGroups() {
    if (state.media === "movies") {
        const ids = selectionIds("movie");
        return ids.length ? [{ kind: "movie", ids }] : [];
    }
    if (state.media === "sets") {
        const ids = selectionIds("set");
        return ids.length ? [{ kind: "set", ids }] : [];
    }
    const groups = { show: [], season: [], episode: [] };
    selectionChecked("tv").forEach((key) => {
        const split = key.indexOf(":");
        const kind = key.slice(0, split);
        if (groups[kind]) groups[kind].push(key.slice(split + 1));
    });
    return Object.entries(groups).filter(([, ids]) => ids.length).map(([kind, ids]) => ({ kind, ids }));
}

function noteScrapeStart(data) {
    if (data && data.queued) {
        state.scanQueue = data.scan_queue || state.scanQueue || [];
        const place = Number(data.place) || 0;
        notify(data.duplicate ? "That scrape is already queued." : `Job queued as number ${place}. It starts when the current job finishes.`, "info");
        if (typeof pollSystem === "function") pollSystem();
        return;
    }
    applyVideoScrape((data && data.scrape) || {});
    pollVideoScrape();
}

// True when every selected item is locked, so the one Lock button becomes Unlock.
function videoItemLocked(kind, id) {
    if (kind === "set") return !!((state.video.sets || []).find((item) => item.id === id) || {}).locked;
    if (kind === "movie") return !!((state.video.movies || []).find((item) => item.id === id) || {}).locked;
    if (kind === "show") return !!((state.video.shows || []).find((item) => item.id === id) || {}).locked;
    let found = null;
    (state.video.showDetails || new Map()).forEach((detail) => {
        const list = kind === "season" ? detail.seasons : detail.episodes;
        const hit = (list || []).find((item) => item.id === id);
        if (hit) found = hit;
    });
    return !!(found && found.locked);
}

function videoSelectionAllLocked() {
    const groups = selectedVideoGroups();
    if (!groups.length) return false;
    return groups.every((group) => group.ids.every((id) => videoItemLocked(group.kind, id)));
}

async function runVideoBatch(op) {
    const groups = selectedVideoGroups();
    if (!groups.length) return;
    if (op === "scrape" || op === "artwork") {
        if (state.media !== "tv") {
            const media = state.media === "sets" ? "sets" : "movies";
            const data = await api("/api/v1/scrape", { method: "POST", body: { media, scope: "selected", ids: groups[0].ids, art_only: op === "artwork" } });
            noteScrapeStart(data);
            return;
        }
        if (op === "artwork") {
            const shows = tvCheckedShows();
            const data = await api("/api/v1/scrape", { method: "POST", body: { media: "tv", scope: "selected", ids: shows, art_only: true } });
            noteScrapeStart(data);
            return;
        }
        let last = null;
        for (const group of groups) {
            const media = scrapeMediaFor(group.kind);
            if (!media || !group.ids.length) continue;
            last = await api("/api/v1/scrape", { method: "POST", body: { media, scope: "selected", ids: group.ids } });
        }
        if (last) noteScrapeStart(last);
        return;
    }
    if (op === "processed") {
        for (const group of groups) {
            await api("/api/v1/status", { method: "POST", body: { kind: group.kind, ids: group.ids, status: "PROCESSED" } });
            applyLocalVideoStatus(group.kind, group.ids, "PROCESSED");
        }
        notify("Marked as processed.", "success");
        return;
    }
    if (op === "lock" || op === "unlock") {
        const locked = op === "lock";
        for (const group of groups) {
            await setVideoLock(group.kind, group.ids, locked);
        }
        return;
    }
    if (op === "subs" && groups.length === 1 && typeof openVideoFiles === "function") {
        return openVideoFiles("subtitles", groups[0]);  // shows what would change first
    }
    for (const group of groups) {
        if (op === "trailers" && group.kind === "episode") continue;
        if (op === "thumbs" && group.kind !== "show" && group.kind !== "season" && group.kind !== "episode") continue;
        if (op === "nfo") {
            await writeVideoNfo(group.kind, group.ids);
        } else {
            const fileOp = op === "subs" ? "subtitles" : op;
            await api("/api/v1/files/run", { method: "POST", body: { op: fileOp, kind: group.kind, ids: group.ids } });
        }
    }
    if (op !== "nfo") notify("Started on the selection.", "info");
}

async function scrapeAllSets() {
    const data = await api("/api/v1/scrape", { method: "POST", body: { media: "sets", scope: "all" } });
    noteScrapeStart(data);
}

async function lookupInRadarr(ids) {
    const movies = (state.video.movies || []).filter((movie) => ids.includes(movie.id) && movie.tmdb_id);
    if (!movies.length) throw new Error("Look up in Radarr needs a TMDB id. Scrape the movie first.");
    const data = await api("/api/v1/radarr/search", { method: "POST", body: { tmdb_ids: movies.map((movie) => movie.tmdb_id) } });
    if (data.queued) {
        notify(data.message || "Radarr search queued.", "info");
        return;
    }
    const results = data.results || [];
    const ok = results.filter((item) => item.ok).length;
    notify(`Radarr looked up ${ok} of ${movies.length} movie${movies.length === 1 ? "" : "s"}.`, ok ? "success" : "warning");
}

async function startVideoScrape(scope, ids, policy, media, groups, primary, fields, art, artPrimary, metaPolicy, artPolicy, rewriteNfo) {
    const body = { media: media || scrapeMedia(), scope, ids: ids || [], policy: policy || null };
    if (metaPolicy) body.meta_policy = metaPolicy;
    if (artPolicy) body.art_policy = artPolicy;
    if (typeof rewriteNfo === "boolean") body.rewrite_nfo = rewriteNfo;
    if (groups && groups.length) body.groups = groups;
    if (fields && fields.length) body.fields = fields;
    if (art && art.length) body.art = art;
    if (artPrimary && Object.keys(artPrimary).length) body.art_primary = artPrimary;
    if (primary) body.primary = primary;
    const data = await api("/api/v1/scrape", { method: "POST", body });
    noteScrapeStart(data);
}

function scrapeMediaFor(kind) {
    if (kind === "episode") return "episodes";
    if (kind === "season") return "seasons";
    if (kind === "show") return "tv";
    if (kind === "movie") return "movies";
    if (kind === "set") return "sets";
    return null;
}

function scrapeStartBlocked() {
    const scope = scrapeScopeLocked() ? "selected" : ((document.querySelector("input[name='video-scrape-scope']:checked") || {}).value || "missing");
    if (scope !== "selected") return false;
    const rows = scrapeMatchRows();
    return rows.length > 0 && rows.every((row) => !row.matched);
}

function scrapePicks() {
    const fields = [...document.querySelectorAll("#video-scrape-blocks [data-scrape-field]:checked")].map((input) => input.value);
    const art = [...document.querySelectorAll("#video-scrape-blocks [data-scrape-art]:checked")].map((input) => input.value);
    const primary = {};
    document.querySelectorAll("#video-scrape-blocks [data-scrape-meta]").forEach((select) => {
        if (select.value) primary[select.dataset.scrapeMeta] = select.value;
    });
    const artPrimary = {};
    document.querySelectorAll("#video-scrape-blocks [data-scrape-art-primary]").forEach((select) => {
        if (select.value) artPrimary[select.dataset.scrapeArtPrimary] = select.value;
    });
    return { fields, art, primary, artPrimary };
}

async function startVideoScrapeFromModal() {
    const picked = document.querySelector("input[name='video-scrape-scope']:checked");
    const scope = scrapeScopeLocked() ? "selected" : (picked ? picked.value : "missing");
    const metaPolicy = document.getElementById("video-scrape-overwrite-meta").checked ? "overwrite" : null;
    const artPolicy = document.getElementById("video-scrape-overwrite-art").checked ? "overwrite" : null;
    const rewriteNfo = !!document.getElementById("video-scrape-rewrite-nfo").checked;
    const media = scrapeTargetMedia();
    const picks = scrapePicks();
    if (media !== "sets" && !picks.fields.length && !picks.art.length) {
        notify("Pick at least one thing to update.", "warning");
        return;
    }
    const pinned = state.videoScrapePick && state.videoScrapePick.ids;
    let ids = scope === "selected" ? (pinned && pinned.length ? pinned.slice() : selectedScrapeIds()) : [];
    if (scope === "selected") {
        const rows = scrapeMatchRows();
        const skipped = rows.filter((row) => !row.matched);
        if (rows.length && skipped.length === rows.length) {
            notify("Match this item before scraping it.", "warning");
            return;
        }
        if (skipped.length && media !== "movies") {
            const skipIds = new Set(skipped.map((row) => row.id));
            if (media === "tv") ids = ids.filter((id) => !skipIds.has(id));
        }
        if (skipped.length && media === "movies") {
            const skipIds = new Set(scrapeMatchRows().filter((row) => !row.matched).map((row) => row.id));
            ids = ids.filter((id) => !skipIds.has(id));
        }
        if (media === "seasons" || media === "episodes") {
            const blockedShows = new Set(skipped.map((row) => row.id));
            ids = ids.filter((id) => {
                const show = scrapeParentShow(media === "episodes" ? "episode" : "season", id);
                return show && !blockedShows.has(show.id);
            });
        }
        if (!ids.length) {
            notify("Match this item before scraping it.", "warning");
            return;
        }
    }
    await startVideoScrape(scope, ids, null, media, null, picks.primary, picks.fields, picks.art, picks.artPrimary, metaPolicy, artPolicy, rewriteNfo);
}

async function cancelVideoScrape() {
    if (!videoScrapeRunning()) return;
    try {
        await api("/api/v1/scrape/cancel", { method: "POST", body: {} });
        notify("Stopping the scrape. Items already scraped are kept.", "info");
    } catch (error) {
        notify(error.message, "error");
    }
    pollVideoScrape();
}

async function pollVideoScrape() {
    clearTimeout(state.videoScrapeTimer);
    const ticket = (state.videoScrapeTicket += 1);
    let data;
    try {
        data = await api("/api/v1/scrape/status");
    } catch (error) {
        return;
    }
    if (ticket !== state.videoScrapeTicket) return;
    applyVideoScrape(data);
    if (videoScrapeRunning()) state.videoScrapeTimer = setTimeout(pollVideoScrape, 1500);
}

function onVideoScrapeLive(snapshot) {
    if (snapshot && snapshot.embedded) return;
    const wasRunning = videoScrapeRunning();
    applyVideoScrape(snapshot || {});
    if (!wasRunning && videoScrapeRunning()) pollVideoScrape();
}

function applyVideoScrape(scrape) {
    if (scrape && scrape.embedded) return;
    const previous = state.videoScrape || {};
    const log = scrape.log !== undefined ? scrape.log : previous.log;
    state.videoScrape = { ...scrape, log };
    if (!state.videoScans) state.videoScans = {};
    if (scrape && scrape.media === "sets") {
        const prevSets = state.videoScans.sets || {};
        const sLog = log !== undefined ? log : prevSets.log;
        state.videoScans.sets = { ...prevSets, ...scrape, log: sLog };
    } else if (scrape && scrape.sets) {
        const prevSets = state.videoScans.sets || {};
        const sLog = scrape.sets.log !== undefined ? scrape.sets.log : prevSets.log;
        state.videoScans.sets = { ...prevSets, ...scrape.sets, log: sLog };
    }
    const started = previous.status !== "running" && scrape.status === "running";
    const finished = previous.status === "running" && scrape.status !== "running";
    const startStamp = scrape.started_at || "running";
    if (started && state.videoScrapeStarted !== startStamp) {
        state.videoScrapeStarted = startStamp;
        notify(`${scrapeJobLabel(scrape)} started.`, "info");
    }
    if (finished) {
        const failedItems = Number((scrape.result && scrape.result.failed) || 0);
        const name = scrapeJobLabel(scrape);
        if (scrape.status === "failed") notify(scrape.message || `${name} failed.`, "error");
        else if (scrape.status === "cancelled") notify(scrape.message || `${name} stopped.`, "info");
        else if (failedItems) notify(`${name} finished with ${failedItems} error${failedItems === 1 ? "" : "s"}. ${scrape.message || ""}`.trim(), "warning");
        else notify(`${name} finished. ${scrape.message || ""}`.trim(), "info");
        reloadVideoAfterScan(scrape.media);
        if (state.media !== "music") renderVideoCenter();
    }
    paintScrapeButton();
    renderVideoScrapeModal();
    if (state.videoScanFocus === "sets") {
        renderVideoScanModal();
        paintVideoScanFooter();
    }
    if (typeof syncActivity === "function") syncActivity();
    if (typeof renderJobs === "function" && state.system) renderJobs(state.system);
}

function paintScrapeButton() {
    const button = document.getElementById("video-scrape-btn");
    if (!button) return;
    const scrape = state.videoScrape || {};
    const running = scrape.status === "running";
    button.classList.toggle("is-running", running);
    button.textContent = running ? `Scraping ${scrape.processed || 0}/${scrape.total || 0}` : "Scrape";
}

function renderVideoScrapeModal() {
    const modal = document.getElementById("video-scrape-modal");
    if (!modal || modal.classList.contains("hidden")) return;
    const scrape = state.videoScrape || {};
    const running = scrape.status === "running";
    const noun = { tv: "TV", sets: "Movie set", episodes: "Episode", seasons: "Season" }[running ? scrape.media : scrapeTargetMedia()] || "Movie";
    document.getElementById("video-scrape-title").textContent = `${noun} scrape`;
    const width = scrape.total ? Math.round(100 * (scrape.processed || 0) / scrape.total) : (scrape.status === "completed" ? 100 : 0);
    const bar = document.getElementById("video-scrape-progress");
    bar.style.width = `${width}%`;
    bar.classList.toggle("low", scrape.status === "failed");
    const status = document.getElementById("video-scrape-status");
    const tones = { running: "is-running", completed: "is-done", failed: "is-failed", cancelled: "is-stopped" };
    status.className = `scan-status ${tones[scrape.status] || ""}`;
    keepText(status, running
        ? [scrape.message, scrape.current].filter(Boolean).join(" · ")
        : (scrape.status && scrape.status !== "idle" ? scrape.message || scrape.status : "Ready."));
    setLogText(document.getElementById("video-scrape-log"), scrape.log || scrape.message || "Idle.");
    const lockedScope = scrapeScopeLocked();
    document.getElementById("video-scrape-missing-mode").classList.toggle("hidden", lockedScope);
    document.getElementById("video-scrape-all-mode").classList.toggle("hidden", lockedScope);
    document.getElementById("video-scrape-selected").textContent = String(scrapeScopeCount());
    paintScrapeBlocks();
    paintScrapeMatch();
    document.querySelectorAll("#video-scrape-modal input, #video-scrape-modal select").forEach((input) => {
        if (running || input.dataset.fixed) input.disabled = true;
        else if (input.name === "video-scrape-scope" && input.value === "selected") input.disabled = !scrapeScopeCount();
        else if (input.name === "video-scrape-scope") input.disabled = lockedScope;
        else input.disabled = false;
    });
    document.querySelectorAll("#video-scrape-modal [data-action='video-scrape-picks']").forEach((button) => {
        button.disabled = running;
    });
    const start = document.getElementById("video-scrape-start");
    const blocked = !running && scrapeStartBlocked();
    start.classList.toggle("is-cancel", running);
    const selectedScope = scrapeScopeLocked() || ((document.querySelector("input[name='video-scrape-scope']:checked") || {}).value === "selected");
    const skipped = !running && selectedScope ? scrapeMatchRows().filter((row) => !row.matched).length : 0;
    const skipping = !blocked && skipped;
    start.textContent = running ? "Stop scrape" : (skipping ? `Start scrape, skip ${skipped}` : "Start scrape");
    start.dataset.action = running ? "video-scrape-cancel" : "video-scrape-start";
    if (!running) start.disabled = blocked;
}

// Context menu on matrix rows and tree rows.

function onVideoMenu(event) {
    if (state.media === "music") return;
    const list = document.getElementById("video-list");
    const row = event.target.closest(".vm-row, .vl-row, .vgrid-card");
    if (!row || !list || !list.contains(row)) return;
    if (row.dataset.kind === "missing") {
        event.preventDefault();
        const season = Number(row.dataset.season);
        const episode = Number(row.dataset.episode);
        state.videoMenu = { kind: "missing", ids: [row.dataset.id], show: row.dataset.show, season, episode };
        const code = `S${String(season).padStart(2, "0")}E${String(episode).padStart(2, "0")}`;
        paintVideoMenu([
            ["sonarr-missing-episode", `Search ${code} in Sonarr`, integrationOn("sonarr") ? Number.isFinite(season) && Number.isFinite(episode) : "off"],
            ["sonarr-missing", "Search missing episodes in this season", integrationOn("sonarr") ? Number.isFinite(season) : "off"],
        ], event);
        return;
    }
    if (!row.matches("[data-action^='video-open-']")) return;
    event.preventDefault();
    const name = row.dataset.action;
    let target;
    if (name === "video-open-movie") {
        const ids = movieSelection(row.dataset.id);
        const movies = (state.video.movies || []).filter((movie) => ids.includes(movie.id));
        target = { kind: "movie", ids, locked: movies.length > 0 && movies.every((movie) => movie.locked) };
    } else if (name === "video-open-show") {
        const ids = tvMenuIds("show", row.dataset.id);
        const shows = (state.video.shows || []).filter((item) => ids.includes(item.id));
        target = { kind: "show", ids, locked: shows.length > 0 && shows.every((item) => item.locked) };
    } else if (name === "video-open-season") {
        const detail = state.video.showDetails.get(row.dataset.show);
        const season = detail && (detail.seasons || []).find((item) => item.id === row.dataset.id);
        target = { kind: "season", ids: tvMenuIds("season", row.dataset.id), show: row.dataset.show, season: season && season.season_number, locked: !!(season && season.locked) };
    } else if (name === "video-open-episode") {
        const node = (state.video.rows || []).find((item) => item._kind === "episode" && item.id === row.dataset.id);
        target = { kind: "episode", ids: tvMenuIds("episode", row.dataset.id), show: (node && node._showId) || row.dataset.show, locked: !!(node && node.locked), season: node && node.season_number };
    } else if (name === "video-open-set") {
        const ids = selectionIds("set", row.dataset.id);
        const sets = (state.video.sets || []).filter((item) => ids.includes(item.id));
        target = { kind: "set", ids, locked: sets.length > 0 && sets.every((item) => item.locked) };
    } else {
        return;
    }
    state.videoMenu = target;
    const count = target.ids.length;
    const many = count > 1 ? ` (${count})` : "";
    const items = [];
    if (target.kind === "set") {
        items.push(["scrape", `Scrape${many}…`, !target.locked]);
        items.push(["match", count > 1 ? `Fix Match… (${count})` : "Fix Match…", !target.locked]);
        items.push(["nfo", `Write .nfo${many}`, true]);
        items.push(["edit", "Edit…", count === 1 && !target.locked]);
        items.push([target.locked ? "unlock" : "lock", `${target.locked ? "Unlock" : "Lock"}${many}`, true]);
        items.push(processedToggleItem(target, many), ["status-IGNORED", `Mark as ignored${many}`, true]);
        items.push(["sep"]);
        items.push(["remove", `Remove from library${many}`, true]);
        items.push(["delete-disk", `Delete from disk${many}…`, true]);
        paintVideoMenu(items, event);
        return;
    }
    if (target.kind === "movie" || target.kind === "show" || target.kind === "season" || target.kind === "episode") {
        let canRescan = true;
        if (target.kind === "movie") {
            const movies = (state.video.movies || []).filter((movie) => target.ids.includes(movie.id));
            canRescan = movies.some((movie) => (movie.folder || movie.path) && String(movie.path || "").indexOf("wanted://") !== 0);
        } else if (target.kind === "show") {
            const shows = (state.video.shows || []).filter((show) => target.ids.includes(show.id));
            canRescan = shows.some((show) => show.path && show.path.indexOf("wanted://") !== 0);
        } else if (target.kind === "season") {
            const show = (state.video.shows || []).find((item) => item.id === target.show);
            canRescan = !show || (show.path && show.path.indexOf("wanted://") !== 0);
        } else {
            const rows = episodeMenuRows(target.ids);
            canRescan = rows.some((row) => String(row.path || "").indexOf("missing://") !== 0);
        }
        items.push(["rescan", `Rescan${many}`, canRescan]);
    }
    if (target.kind === "movie" || target.kind === "show") {
        items.push(["library-update", `Update library…${many}`, true]);
        const arr = target.kind === "movie" ? "radarr" : "sonarr";
        items.push(["arr-rescan", `Update library in ${providerIcon(arr)}${many}`, integrationOn(arr) ? true : "off", false, `Ask ${arr === "radarr" ? "Radarr" : "Sonarr"} to rescan ${count > 1 ? "these items" : "this item"}`, true]);
        items.push(["move", `Move…${many}`, true]);
    }
    if (target.kind === "movie" || target.kind === "show" || target.kind === "season" || target.kind === "episode") {
        items.push(["scrape", `Scrape${many}…`, !target.locked]);
    }
    if (target.kind === "movie" || target.kind === "show") {
        const matchLabel = count > 1 ? `Fix Match… (${count})` : "Fix Match…";
        items.push(["match", matchLabel, !target.locked]);
    }
    items.push(["nfo", `Write .nfo${many}`, true]);
    if (target.kind !== "season") items.push(["edit", "Edit…", count === 1 && !target.locked]);
    else items.push(["edit", "Edit season…", count === 1 && !target.locked]);
    if ((target.kind === "movie" || target.kind === "show" || target.kind === "episode") && count > 1) {
        items.push(["edit-fields", `Edit fields${many}…`, true]);
    }
    if (target.kind === "movie" || target.kind === "show" || target.kind === "episode") {
        items.push(["ratings", "Update ratings", count === 1 && !target.locked]);
    }
    if (target.kind === "movie" || target.kind === "episode") {
        items.push(["mediainfo", `Update media info${many}`, true]);
    }
    if (target.kind === "movie" || target.kind === "show" || target.kind === "episode") items.push(["tags", `Tags${many}…`, !target.locked]);
    if (target.kind !== "set") items.push([target.locked ? "unlock" : "lock", `${target.locked ? "Unlock" : "Lock"}${many}`, true]);
    items.push(processedToggleItem(target, many), ["status-IGNORED", `Mark as ignored${many}`, true]);
    items.push(["sep"]);
    items.push(["files-rename", `Rename files${many}…`, !target.locked]);
    items.push(["files-subtitles", `Normalize subtitles${many}`, true]);
    if (target.kind === "movie" || target.kind === "episode") {
        items.push(["subs-find", "Find subtitles…", count === 1, false, count === 1 ? "Search OpenSubtitles.com" : "Pick one item to search for its subtitles"]);
    }
    if (target.kind === "movie") {
        const movies = (state.video.movies || []).filter((movie) => target.ids.includes(movie.id));
        items.push(["radarr", `${lookUpIn("radarr")}${many}`, integrationOn("radarr") ? movies.some((movie) => movie.tmdb_id) : "off", false, "Look up in Radarr", true]);
        items.push(["files-extras", `Organize extras${many}…`, true]);
    }
    if (target.kind === "show") items.push(["sonarr-missing", `Look up all episodes in ${providerIcon("sonarr")}${many}`, integrationOn("sonarr") ? true : "off", false, "Look up all episodes in Sonarr", true]);
    if (target.kind === "season") items.push(["sonarr-missing", `Search missing episodes in ${providerIcon("sonarr")}${many}`, integrationOn("sonarr") ? true : "off", false, "Search missing episodes in Sonarr", true]);
    if (target.kind === "episode") {
        items.push(["sonarr", `${lookUpIn("sonarr")}${many}`, integrationOn("sonarr") ? true : "off", false, "Look up in Sonarr", true]);
        items.push(["sonarr-missing", `Look up all episodes in ${providerIcon("sonarr")}${many}`, integrationOn("sonarr") ? true : "off", false, "Look up all episodes in Sonarr", true]);
        const rows = episodeMenuRows(target.ids);
        const multi = rows.filter((row) => typeof isMultiEpisodeFile === "function" && isMultiEpisodeFile(row));
        if (multi.length) {
            const mixed = rows.length !== multi.length;
            const files = mixed || typeof splitTargets !== "function" ? [] : splitTargets(target.ids);
            const label = !mixed && files.length > 1 ? `Split episodes (${files.length})` : "Split episodes";
            items.push(["split", label, !mixed && files.length > 0]);
        }
    }
    if (target.kind === "show" || target.kind === "episode") items.push(["files-extras", `Organize extras${many}…`, true]);
    if (target.kind === "movie" || target.kind === "show" || target.kind === "season") {
        items.push(["files-trailers", `Download trailer${count > 1 ? "s" : ""}${many}`, true]);
    }
    if (target.kind === "movie" || target.kind === "show") {
        items.push(["files-themes", `Download theme song${count > 1 ? "s" : ""}${many}`, true]);
    }
    if (target.kind === "show" || target.kind === "season" || target.kind === "episode") {
        items.push(["files-thumbs", `Generate episode thumbnail${count > 1 ? "s" : ""}${many}`, true]);
    }
    items.push(["sep"]);
    items.push(["remove", `Remove from library${many}`, true]);
    items.push(["delete-disk", `Delete from disk${many}…`, true]);
    paintVideoMenu(items, event);
}

function menuTargetRows(target) {
    const pools = { movie: state.video.movies, show: state.video.shows, set: state.video.sets };
    if (pools[target.kind]) return (pools[target.kind] || []).filter((row) => target.ids.includes(row.id));
    return (state.video.rows || []).filter((row) => row._kind === target.kind && target.ids.includes(row.id));
}

// One item that flips between Mark as processed and Mark as new. A mix of both is greyed out.
function processedToggleItem(target, many) {
    const rows = menuTargetRows(target);
    const isNew = (row) => row.status === "NEW" || ((row._kind === "show" || row._kind === "season" || target.kind === "show") && !!row.new_count);
    const done = rows.filter((row) => row.status === "PROCESSED" && !isNew(row)).length;
    if (rows.length && done === rows.length) return ["status-NEW", `Mark as new${many}`, true];
    if (done === 0) return ["status-PROCESSED", `Mark as processed${many}`, true];
    return ["status-PROCESSED", `Mark as processed${many}`, false, false, "The selection mixes processed and unprocessed items"];
}

function paintVideoMenu(items, event) {
    const menu = document.getElementById("video-menu");
    menu.innerHTML = items.map(([cmd, label, enabled, danger, title, raw]) => {
        if (cmd === "sep") return `<hr class="menu-sep">`;
        const off = enabled === "off";
        const classes = [off ? "is-unavailable" : "", danger || cmd === "delete-disk" || cmd === "remove" ? "btn-remove" : ""].filter(Boolean).join(" ");
        return `<button type="button" role="menuitem" data-action="video-menu-cmd" data-cmd="${cmd}" ${enabled ? "" : "disabled"}${classes ? ` class="${classes}"` : ""}${title ? ` title="${escapeHtml(title)}"` : ""}>${raw ? label : escapeHtml(label)}</button>`;
    }).join("");
    placeMenu(menu, event);
}

function closeVideoMenu() {
    const menu = document.getElementById("video-menu");
    if (menu) menu.classList.add("hidden");
}

async function runVideoMenu(cmd) {
    closeVideoMenu();
    const target = state.videoMenu;
    if (!target) return;
    if (cmd === "scrape" || cmd === "scrape-overwrite") {
        openVideoScrapeModal("selected", { media: scrapeMediaFor(target.kind), ids: target.ids });
        return;
    }
    if (cmd === "rescan") return rescanFromMenu(target);
    if (cmd === "library-update") return openLibraryUpdate(target.kind, target.ids);
    if (cmd === "arr-rescan") {
        const arr = target.kind === "movie" ? "radarr" : "sonarr";
        if (arrSearchBlocked(arr)) return;
        notify(`Asking ${arr === "radarr" ? "Radarr" : "Sonarr"} to rescan…`, "info");
        const data = await api("/api/v1/library/arr-rescan", { method: "POST", body: { kind: target.kind, ids: target.ids } });
        notify(data.message || "Rescan queued.", data.sent ? "success" : "warning");
        return;
    }
    if (cmd === "match") return openFixMatchBulk(target.kind, target.ids);
    if (cmd === "edit") return openVideoEdit(target.kind, target.ids[0]);
    if (cmd === "edit-fields") return openBatchEdit(target.kind, target.ids);
    if (cmd === "ratings") return refreshVideoRatings(target.kind, target.ids[0]);
    if (cmd === "mediainfo") return refreshVideoMediaInfo(target.kind, target.ids);
    if (cmd === "tags") return openTagManager(target);
    if (cmd === "nfo") return writeVideoNfo(target.kind, target.ids);
    if (cmd === "lock" || cmd === "unlock") return setVideoLock(target.kind, target.ids, cmd === "lock");
    if (cmd.startsWith("status-")) {
        const status = cmd.slice(7);
        await api("/api/v1/status", { method: "POST", body: { kind: target.kind, ids: target.ids, status } });
        applyLocalVideoStatus(target.kind, target.ids, status);
        return;
    }
    if (cmd === "radarr") {
        if (arrSearchBlocked("radarr")) return;
        return lookupInRadarr(target.ids);
    }
    if (cmd === "subs-find") return openSubtitleFinder(target.kind, target.ids[0]);
    if (cmd === "split") {
        if (!splitTargets(target.ids).length) return;
        return openEpisodeSplits(target.ids);
    }
    if (cmd === "sonarr" || cmd === "sonarr-missing" || cmd === "sonarr-missing-episode") {
        if (arrSearchBlocked("sonarr")) return;
    }
    if (cmd === "sonarr") return lookupEpisodesInSonarr(target);
    if (cmd === "sonarr-missing-episode") return searchMissingEpisode(target);
    if (cmd === "sonarr-missing") return searchMissingFromMenu(target);
    if (cmd.startsWith("files-")) return openVideoFiles(cmd.slice(6), target);
    if (cmd === "move") return openVideoMove(target.kind, target.ids);
    if (cmd === "remove") return target.kind === "set" ? removeSets(target.ids) : removeVideoItems(target);
    if (cmd === "delete-disk") return target.kind === "set" ? deleteSetsAsk(target.ids) : deleteVideoItemsAsk(target);
}

async function rescanFromMenu(target) {
    if (target.kind === "movie" || target.kind === "show") {
        const rows = target.kind === "movie" ? (state.video.movies || []) : (state.video.shows || []);
        const paths = [...new Set(rows.filter((item) => target.ids.includes(item.id)).map((item) => (
            target.kind === "movie" ? (item.folder || item.path) : item.path
        )).filter((path) => path && path.indexOf("wanted://") !== 0))];
        if (!paths.length) {
            notify(target.kind === "movie" ? "This movie has no folder to scan yet." : "This show has no folder to scan yet.", "info");
            return;
        }
        const data = await api("/api/v1/scan", {
            method: "POST",
            body: { media: target.kind === "movie" ? "movies" : "tv", mode: "deep", targets: paths },
        });
        noteScanStart(data);
        return;
    }
    if (target.kind !== "season" && target.kind !== "episode") return;
    if (!target.ids.length) return;
    const path = target.kind === "season" ? "seasons" : "episodes";
    let first = null;
    let queued = 0;
    for (const id of target.ids) {
        const data = await api(`/api/v1/tv/${path}/${encodeURIComponent(id)}/rescan`, { method: "POST", body: {} });
        if (!first) first = data;
        else if (data.queued) queued += 1;
    }
    noteScanStart(first || {});
    if (queued) notify(`${queued} more ${target.kind} scan${queued === 1 ? "" : "s"} queued.`, "info");
}

async function refreshVideoItems(kind) {
    if (kind === "movie" || kind === "set") {
        state.video.stale.movies = true;
        state.video.stale.sets = true;
    }
    if (kind !== "movie") {
        state.video.stale.tv = kind !== "set";
        if (kind !== "set") state.video.showDetails.clear();
    }
    await loadVideo(state.media, { keepScroll: true, quiet: true });
    renderVideoCenter();
}

function episodeMenuRows(ids) {
    return (state.video.rows || []).filter((row) => row._kind === "episode" && ids.includes(row.id));
}

async function lookupEpisodesInSonarr(target) {
    const ids = target.kind === "episode" ? target.ids : [];
    if (target.kind === "show") {
        const data = await api("/api/v1/sonarr/missing", { method: "POST", body: { show_id: target.ids[0] } });
        notify(data.message || "Sonarr is searching.", "success");
        return;
    }
    if (!ids.length) return;
    const data = await api("/api/v1/sonarr/episodes", { method: "POST", body: { episode_ids: ids } });
    notify(data.message || "Sonarr is searching.", "success");
}

async function searchMissingEpisode(target) {
    const data = await api("/api/v1/sonarr/missing", {
        method: "POST",
        body: { show_id: target.show, season_number: target.season, episode_number: target.episode },
    });
    notify(data.message || "Sonarr is searching.", "success");
}

async function searchMissingFromMenu(target) {
    if (target.kind === "show") {
        const data = await api("/api/v1/sonarr/missing", { method: "POST", body: { show_id: target.ids[0] } });
        notify(data.message || "Sonarr is searching.", "success");
        return;
    }
    const seasons = new Map();
    if (target.kind === "season") {
        const wanted = new Set((target.ids || []).map((id) => String(id)));
        (state.video.rows || []).forEach((row) => {
            if (row._kind === "season" && wanted.has(String(row.id)) && row._showId != null && row.season_number != null) {
                seasons.set(`${row._showId}:${row.season_number}`, { show_id: row._showId, season_number: row.season_number });
            }
        });
        (state.video.showDetails || new Map()).forEach((detail, showId) => {
            (detail.seasons || []).forEach((season) => {
                if (wanted.has(String(season.id)) && season.season_number != null) {
                    seasons.set(`${showId}:${season.season_number}`, { show_id: showId, season_number: season.season_number });
                }
            });
        });
    } else {
        episodeMenuRows(target.ids).forEach((row) => {
            if (row._showId != null && row.season_number != null) seasons.set(`${row._showId}:${row.season_number}`, { show_id: row._showId, season_number: row.season_number });
        });
    }
    if (!seasons.size && target.show != null && target.season != null) seasons.set("one", { show_id: target.show, season_number: target.season });
    if (!seasons.size) throw new Error("Open the show so the season is known, then try again.");
    let last = null;
    for (const body of seasons.values()) {
        last = await api("/api/v1/sonarr/missing", { method: "POST", body });
    }
    notify((last && last.message) || "Sonarr is searching.", "success");
}

async function writeVideoNfo(kind, ids) {
    const data = await api("/api/v1/nfo", { method: "POST", body: { kind, ids } });
    const written = Number(data.written) || 0;
    notify(written ? `Wrote ${written} .nfo file${written === 1 ? "" : "s"}.` : "The .nfo files were already up to date.", "info");
    if (written) patchVideoRows(kind, ids, { has_nfo: true });
    await refreshWrittenNfo(kind, ids);
}

async function refreshWrittenNfo(kind, ids) {
    if (kind === "set") {
        const wanted = new Set((ids || []).map((id) => String(id)));
        if (state.video && state.video.setId && wanted.has(String(state.video.setId)) && typeof openSet === "function") {
            return openSet(state.video.setId);
        }
        return;
    }
    if (kind === "movie" && state.video && state.video.movieId && (ids || []).map((id) => String(id)).includes(String(state.video.movieId)) && typeof openMovie === "function") {
        return openMovie(state.video.movieId);
    }
    const details = state.video && state.video.showDetails;
    if (!details || (kind !== "show" && kind !== "season" && kind !== "episode")) return;
    const wanted = new Set((ids || []).map((id) => String(id)));
    const shows = [];
    if (kind === "show") shows.push(...wanted);
    else {
        details.forEach((detail, showId) => {
            const rows = kind === "season" ? detail.seasons : detail.episodes;
            if ((rows || []).some((row) => wanted.has(String(row.id)))) shows.push(String(showId));
        });
    }
    for (const id of shows) {
        details.delete(id);
        try {
            const detail = await showDetail(id);
            const show = (state.video.shows || []).find((item) => String(item.id) === String(id));
            if (show && detail) {
                show.nfo_stale = !!detail.nfo_stale;
                show.nfo_family_stale = !!detail.nfo_family_stale;
                if (detail.has_nfo) show.has_nfo = true;
            }
        } catch (error) {
            notify(error.message, "error");
        }
    }
    if (shows.length && typeof renderTvTree === "function") renderTvTree();
    repaintOpenShow(shows);
}

function repaintOpenShow(showIds) {
    const open = new Set((showIds || []).map((id) => String(id)));
    const sel = (state.video && state.video.tvSel) || {};
    const showId = sel.type === "show" ? String(sel.id || "") : String(sel.show || "");
    if (!open.has(showId) || typeof renderShowInfo !== "function") return;
    const detail = state.video.showDetails.get(showId);
    if (!detail) return;
    if (sel.type === "show") renderShowInfo(detail);
    else if (sel.type === "season") {
        const season = (detail.seasons || []).find((item) => String(item.id) === String(sel.id));
        if (season) renderSeasonInfo(detail, season);
    } else if (sel.type === "episode" && typeof openEpisode === "function") openEpisode(sel.id);
}

async function setVideoLock(kind, ids, locked) {
    await api("/api/v1/lock", { method: "POST", body: { kind, ids, locked } });
    const cascade = kind === "show" ? " with its seasons and episodes" : kind === "season" ? " with its episodes" : "";
    notify(`${locked ? "Locked" : "Unlocked"}${cascade}.`, "info", { undo: () => setVideoLock(kind, ids, !locked) });
    patchVideoRows(kind, ids, { locked });
}

function videoItemsLabel(target) {
    const count = target.ids.length;
    const noun = { movie: "movie", show: "show", season: "season", episode: "episode" }[target.kind];
    return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

const VIDEO_DELETE_TEXT = {
    movie: "Delete from disk removes the movie folder with everything in it. A movie without its own folder loses its video files and the .nfo, artwork and subtitles named after them.",
    show: "Delete from disk removes the show folder with every season, episode and artwork file in it.",
    season: "Delete from disk removes the season folder, or the episode files with their sidecars when the season has no folder of its own, plus the season artwork in the show folder.",
    episode: "Delete from disk removes the episode file and the .nfo, thumbnail and subtitles named after it. Episodes that share the file are removed too.",
};

function askVideoBatchRemoval(disk) {
    const groups = selectedVideoGroups();
    if (!groups.length) return;
    if (groups.length === 1 && groups[0].kind === "set") {
        return disk ? deleteSetsAsk(groups[0].ids) : removeSets(groups[0].ids);
    }
    if (groups.length === 1) {
        return disk ? deleteVideoItemsAsk(groups[0]) : removeVideoItems(groups[0]);
    }
    const count = groups.reduce((sum, group) => sum + group.ids.length, 0);
    const label = `${count} item${count === 1 ? "" : "s"}`;
    if (!disk) {
        return askDanger(
            `Remove ${label} from the library?`,
            "Files on disk are not touched. The next scan adds them back unless you delete or move them.",
            "Remove from library",
            () => forgetVideoGroups(groups),
            false,
        );
    }
    return askDanger(
        `Delete ${label} from disk?`,
        "Shows, seasons and episodes in this selection are deleted with their files. A folder that also holds another item in the library is refused. This cannot be undone. Removing from the library leaves the files in place.",
        "Delete from disk",
        () => deleteVideoGroups(groups),
        true,
        () => forgetVideoGroups(groups),
    );
}

async function forgetVideoGroups(groups) {
    let removed = 0;
    let busy = 0;
    for (const group of groups) {
        const data = await api("/api/v1/remove", { method: "POST", body: { kind: group.kind, ids: group.ids } });
        removed += Number(data.removed) || 0;
        busy += Number(data.busy) || 0;
        await afterVideoRemoval({ kind: group.kind, ids: data.ids || [], peers: data.peers || [] });
    }
    if (busy) notify(`Removed ${removed} from the library. ${busy} stayed because a running job is using ${busy === 1 ? "it" : "them"}.`, "warning");
    else notify(`Removed ${removed} from the library. The files are still on disk.`, "info");
}

async function deleteVideoGroups(groups) {
    let deleted = 0;
    const errors = [];
    for (const group of groups) {
        const data = await api("/api/v1/delete", { method: "POST", body: { kind: group.kind, ids: group.ids } });
        deleted += (data.deleted || []).length;
        (data.errors || []).forEach((error) => errors.push(error));
        await afterVideoRemoval({ kind: group.kind, ids: data.ids || [], peers: data.peers || [] });
    }
    if (errors.length) notify(`Deleted ${deleted}. ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1} more)` : ""}`, "warning");
    else notify(`Deleted ${deleted} from disk.`, "info");
}

function removeAllNotFoundVideo() {
    const tv = state.media === "tv";
    const rows = (tv ? state.video.shows : state.video.movies) || [];
    const ids = rows.filter((row) => row.prune_held).map((row) => row.id);
    if (!ids.length) {
        notify(`No ${tv ? "shows" : "movies"} are marked Not found.`, "info");
        return;
    }
    const label = `${ids.length} ${tv ? (ids.length === 1 ? "show" : "shows") : (ids.length === 1 ? "movie" : "movies")}`;
    askDanger(
        `Remove ${label} marked Not found from the library?`,
        "A scan could not find these, and prune safety kept them because too much was missing at once. Check that the drive is mounted and the folders are there before you continue. They leave the library; files on disk are not touched, and the next scan adds them back if the folders exist.",
        "Remove from library",
        () => forgetVideoItems({ kind: tv ? "show" : "movie", ids }),
        true,
    );
}

function removeVideoItems(target) {
    askDanger(
        `Remove ${videoItemsLabel(target)} from the library?`,
        "Files on disk are not touched. The next scan adds them back unless you delete or move them.",
        "Remove from library",
        () => forgetVideoItems(target),
        false,
    );
}

function deleteVideoItemsAsk(target) {
    askDanger(
        `Remove ${videoItemsLabel(target)}?`,
        `${VIDEO_DELETE_TEXT[target.kind]} A folder that also holds another movie or episode in the library is refused. Removing from the library leaves the files in place.`,
        "Delete from disk",
        () => deleteVideoItems(target),
        true,
        () => forgetVideoItems(target),
    );
}

async function forgetVideoItems(target) {
    const data = await api("/api/v1/remove", { method: "POST", body: { kind: target.kind, ids: target.ids } });
    const busy = Number(data.busy) || 0;
    const removed = data.removed || 0;
    if (busy) notify(`Removed ${removed} from the library. ${busy} stayed because a running job is using ${busy === 1 ? "it" : "them"}.`, "warning");
    else notify(`Removed ${removed} from the library. The files are still on disk.`, "info");
    await afterVideoRemoval({ ...target, ids: data.ids || [], peers: data.peers || [] });
}

async function deleteVideoItems(target) {
    const data = await api("/api/v1/delete", { method: "POST", body: { kind: target.kind, ids: target.ids } });
    const deleted = data.deleted || [];
    const errors = data.errors || [];
    if (errors.length) notify(`Deleted ${deleted.length}. ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1} more)` : ""}`, "warning");
    else notify(`Deleted ${videoItemsLabel(target)} from disk.`, "info");
    await afterVideoRemoval({ ...target, ids: data.ids || [], peers: data.peers || [] });
}

async function afterVideoRemoval(target) {
    const ids = target.ids || [];
    if (target.kind === "movie" && ids.includes(state.video.movieId)) state.video.movieId = null;
    else if (state.video.tvSel && ids.includes(state.video.tvSel.id)) state.video.tvSel = null;
    forgetLocalVideo(target.kind, ids);
    if (typeof applyPeerFlags === "function") applyPeerFlags(target.peers);
    if (typeof forgetDuplicateUndo === "function") forgetDuplicateUndo(ids);
}

// Fix Match.

/* ---------- bulk fix-match queue ----------------------------------------- */

let _bulkMatchQueue = [];   // { kind, id }[]
let _bulkMatchIndex = 0;

function openFixMatchBulk(kind, ids) {
    if (!ids || ids.length === 0) return;
    _bulkMatchQueue = ids.map((id) => ({ kind, id }));
    _bulkMatchIndex = 0;
    _openNextBulkMatch();
}

function _openNextBulkMatch() {
    if (_bulkMatchIndex >= _bulkMatchQueue.length) {
        _bulkMatchQueue = [];
        _bulkMatchIndex = 0;
        return;
    }
    const { kind, id } = _bulkMatchQueue[_bulkMatchIndex];
    _updateBulkMatchHeader();
    openFixMatch(kind, id);
}

function _updateBulkMatchHeader() {
    const total = _bulkMatchQueue.length;
    const current = _bulkMatchIndex + 1;
    const progressEl = document.getElementById("video-match-bulk-progress");
    if (progressEl) {
        progressEl.textContent = total > 1 ? `Item ${current} of ${total}` : "";
        progressEl.classList.toggle("hidden", total <= 1);
    }
    const skipBtn = document.getElementById("video-match-skip-btn");
    if (skipBtn) skipBtn.classList.toggle("hidden", total <= 1 || _bulkMatchIndex >= total - 1);
}

function advanceBulkMatch() {
    _bulkMatchIndex++;
    if (_bulkMatchIndex >= _bulkMatchQueue.length) {
        _bulkMatchQueue = [];
        _bulkMatchIndex = 0;
        return false;
    }
    _openNextBulkMatch();
    return true;
}

function skipBulkMatch() {
    advanceBulkMatch();
}

function openFixMatch(kind, id) {
    const item = kind === "movie"
        ? (state.video.movies || []).find((movie) => movie.id === id)
        : kind === "set"
            ? (state.video.sets || []).find((set) => set.id === id)
            : (state.video.shows || []).find((show) => show.id === id);
    if (!item) return;
    state.videoMatch = { kind, id };
    const title = item.title || item.name || "";
    document.getElementById("video-match-item").textContent = `${title}${item.year ? ` (${item.year})` : ""}${item.path ? ` · ${item.path}` : ""}`;
    document.getElementById("video-match-query").value = title;
    document.getElementById("video-match-year").value = item.year || "";
    const srcEl = document.getElementById("video-match-source");
    srcEl.value = "tmdb";
    srcEl.disabled = kind === "set";
    document.getElementById("video-match-id").value = "";
    document.getElementById("video-match-results").innerHTML = "";
    document.getElementById("video-match-modal").classList.remove("hidden");
    searchFixMatch();
}

async function searchFixMatch(event) {
    if (event) event.preventDefault();
    const match = state.videoMatch;
    if (!match) return;
    const query = document.getElementById("video-match-query").value.trim();
    const year = document.getElementById("video-match-year").value.trim();
    const source = document.getElementById("video-match-source").value;
    const box = document.getElementById("video-match-results");
    if (!query) return;
    box.innerHTML = `<p class="muted">Searching…</p>`;
    const media = match.kind === "movie" ? "movies" : match.kind === "set" ? "sets" : "tv";
    const params = new URLSearchParams({ media, query, source });
    if (year && match.kind !== "set") params.set("year", year);
    try {
        const data = await api(`/api/v1/match/search?${params}`);
        const hits = data.results || [];
        box.innerHTML = hits.length ? hits.map((hit) => {
            const ids = hit.ids || {};
            return `<button type="button" class="vmatch-hit" data-action="video-match-pick" data-source="${escapeHtml(hit.source)}" data-id="${escapeHtml(hit.id)}" data-tmdb="${escapeHtml(ids.tmdb || "")}" data-imdb="${escapeHtml(ids.imdb || "")}" data-tvdb="${escapeHtml(ids.tvdb || "")}" data-trakt="${escapeHtml(ids.trakt || "")}">
            ${hit.poster ? `<img loading="lazy" src="${escapeHtml(hit.poster)}" alt="">` : `<span class="vposter is-empty"></span>`}
            <span><strong>${escapeHtml(hit.title)}</strong>${hit.year ? ` <span class="muted">(${hit.year})</span>` : ""}
            ${hit.original_title && hit.original_title !== hit.title ? `<br><span class="muted">${escapeHtml(hit.original_title)}</span>` : ""}
            <br><small class="muted">${escapeHtml(hit.source.toUpperCase())} ${escapeHtml(hit.id)}</small>
            <br><small>${escapeHtml(String(hit.overview || "").slice(0, 240))}</small></span>
        </button>`;
        }).join("") : `<p class="muted">Nothing found. Try the original title or drop the year.</p>`;
    } catch (error) {
        box.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
    }
}

function rememberMatchIdentity(kind, id, ids) {
    const apply = (row) => {
        if (!row || String(row.id) !== String(id) || !ids) return;
        if (ids.tmdb) row.tmdb_id = ids.tmdb;
        if (ids.imdb) row.imdb_id = ids.imdb;
        if (ids.tvdb) row.tvdb_id = ids.tvdb;
        if (ids.trakt) row.trakt_id = ids.trakt;
    };
    if (kind === "movie") (state.video.movies || []).forEach(apply);
    if (kind === "set") {
        (state.video.sets || []).forEach((row) => {
            if (row && String(row.id) === String(id) && ids && ids.tmdb) row.tmdb_collection_id = Number(ids.tmdb) || row.tmdb_collection_id;
        });
    }
    if (kind === "show") {
        (state.video.shows || []).forEach(apply);
        (state.video.showDetails || new Map()).forEach(apply);
    }
}

async function applyFixMatch(source, sourceId, ids) {
    const match = state.videoMatch;
    if (!match) return;
    const data = await api("/api/v1/match", { method: "POST", body: { kind: match.kind, id: match.id, source, source_id: String(sourceId), ids: ids || {} } });
    rememberMatchIdentity(match.kind, match.id, ids || {});
    if (typeof applyPeerFlags === "function" && data.peers && data.peers.length) applyPeerFlags(data.peers);
    else if (typeof renderVideoList === "function") renderVideoList();
    document.getElementById("video-match-modal").classList.add("hidden");
    const waitingRow = document.querySelector(`#pending-match-list tr[data-pending-id="${match.id}"]`);
    if (waitingRow && typeof removePendingMatchRow === "function") removePendingMatchRow(waitingRow);
    if (data.queued) notify(`Matched. Another scrape is running, so this one is queued (${data.queued} waiting) and starts when it finishes.`, "info");
    else notify("Matched. Scraping with the new id…", "info");
    pollVideoScrape();
    // advance bulk queue — if there are more items, open next
    if (_bulkMatchQueue.length > 1) {
        _bulkMatchIndex++;
        if (_bulkMatchIndex < _bulkMatchQueue.length) {
            setTimeout(() => _openNextBulkMatch(), 300);
        } else {
            _bulkMatchQueue = [];
            _bulkMatchIndex = 0;
        }
    }
}

function bindVideoScrape() {
    const list = document.getElementById("video-list");
    if (list) list.addEventListener("contextmenu", onVideoMenu);
    const form = document.getElementById("video-match-form");
    if (form) form.addEventListener("submit", (event) => runAction(() => searchFixMatch(event)));
    document.addEventListener("click", (event) => {
        if (!event.target.closest("#video-menu")) closeVideoMenu();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeVideoMenu();
    });
    pollVideoScrape();
    pollVideoFiles();
}

function matchById() {
    const source = document.getElementById("video-match-source").value;
    const value = document.getElementById("video-match-id").value.trim();
    const imdb = /^tt\d{5,}$/i.test(value);
    if (source === "omdb" ? !imdb : !/^\d+$/.test(value)) {
        notify(source === "omdb" ? "Paste an IMDb id, such as tt1144811." : "Paste the number from the TMDB, TVDB or Trakt address.", "warning");
        return;
    }
    const ids = {};
    ids[source === "omdb" ? "imdb" : source] = value;
    runAction(() => applyFixMatch(source, value, ids));
}

const LIBRARY_PLAYERS = [
    ["kodi", "Kodi", "kodi_video_enabled", "kodi_library_enabled"],
    ["emby", "Emby", "emby_video_enabled", "emby_enabled"],
    ["jellyfin", "Jellyfin", "jellyfin_video_enabled", "jellyfin_enabled"],
    ["plex", "Plex", "plex_video_enabled", "plex_enabled"],
];

function libraryPlayerOn(flag, legacy) {
    const cfg = notifyCfg();
    const player = String(flag || "").replace(/_video_enabled$/, "");
    if (cfg[`${player}_on`] === false) return false;
    if (Object.prototype.hasOwnProperty.call(cfg, flag)) return cfg[flag] !== false;
    return cfg[legacy] !== false;
}

function openLibraryUpdate(kind, ids) {
    state.libraryUpdate = { kind, ids: (ids || []).slice() };
    const rows = LIBRARY_PLAYERS.map(([key, label, flag, legacy]) => {
        const on = libraryPlayerOn(flag, legacy);
        return `<label class="library-update-row choice">
            <input type="checkbox" data-library-player="${key}" ${on ? "checked" : "disabled"}>
            <span class="library-update-name">${providerIcon(key)}<span>${escapeHtml(label)}</span></span>
            <span class="muted">${on ? "On in Settings" : "Off in Settings"}</span>
        </label>`;
    }).join("");
    const count = (ids || []).length;
    const noun = kind === "show" ? "TV show" : "movie";
    document.getElementById("library-update-note").textContent = count > 1
        ? `Send these ${count} ${noun}s to the libraries you pick.`
        : `Send this ${noun} to the libraries you pick.`;
    document.getElementById("library-update-players").innerHTML = rows;
    document.getElementById("library-update-modal").classList.remove("hidden");
}

async function sendLibraryUpdate() {
    const pending = state.libraryUpdate;
    if (!pending) return;
    const players = [...document.querySelectorAll("#library-update-players input:checked")].map((input) => input.dataset.libraryPlayer);
    if (!players.length) throw new Error("Choose a library.");
    const data = await api("/api/v1/library/update", { method: "POST", body: { kind: pending.kind, ids: pending.ids, players } });
    document.getElementById("library-update-modal").classList.add("hidden");
    notify(data.message || "Library update queued.", "success");
}

const VIDEO_SCRAPE_ACTIONS = {
    "video-scrape-open": () => openVideoScrapeModal(),
    "video-scrape-start": () => runAction(startVideoScrapeFromModal),
    "video-scrape-fix": (action) => openFixMatch(action.dataset.kind, action.dataset.id),
    "video-scrape-cancel": () => cancelVideoScrape(),
    "video-scrape-picks": (action) => setScrapePicks(action),
    "video-menu-cmd": (action) => runAction(() => runVideoMenu(action.dataset.cmd)),
    "video-library-update": (action) => openLibraryUpdate(action.dataset.kind, [action.dataset.id]),
    "library-update-send": () => runAction(sendLibraryUpdate, "Queuing…"),
    "video-lock": (action) => runAction(() => setVideoLock(action.dataset.kind, [action.dataset.id], !action.dataset.locked)),
    "video-match-skip": () => skipBulkMatch(),
    "video-match-pick": (action) => runAction(() => applyFixMatch(action.dataset.source, action.dataset.id, {
        tmdb: action.dataset.tmdb || "", imdb: action.dataset.imdb || "", tvdb: action.dataset.tvdb || "", trakt: action.dataset.trakt || "",
    })),
    "video-match-id": () => matchById(),
    "video-chain-move": (action) => moveVideoChain(action),
};

function onVideoScrapeAction(name, action) {
    const run = VIDEO_SCRAPE_ACTIONS[name];
    if (!run) return false;
    run(action);
    return true;
}
