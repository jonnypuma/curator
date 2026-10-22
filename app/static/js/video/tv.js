function seasonLabel(season, show) {
    if (!season) return "";
    const names = (show && show.season_names) || {};
    const given = String(season.title || "").trim();
    const number = Number(season.season_number);
    const generic = !given || (number === 0
        ? /^(specials|season 0|series 0)$/i.test(given)
        : new RegExp(`^(season|series)\\s+0*${number}$`, "i").test(given));
    const named = (!generic && given) || names[String(season.season_number)] || given;
    if (named) return named;
    return number === 0 ? "Specials" : `Season ${season.season_number}`;
}

function episodeCode(episode) {
    return `Episode ${episode.episode_number}`;
}

function episodeHeading(episode, sep) {
    const code = episodeCode(episode);
    const title = String((episode && episode.title) || "").trim();
    if (!title) return code;
    const num = Number(episode && episode.episode_number);
    const match = title.match(/^episode\s*#?\s*0*(\d+)\b(.*)$/i);
    if (match && Number(match[1]) === num) {
        const rest = String(match[2] || "").replace(/^[\s:.\-–—·]+/, "").trim();
        return rest ? `${code}${sep || " "}${rest}` : code;
    }
    if (title.toLowerCase().startsWith("episode")) return title;
    return `${code}${sep || " "}${title}`;
}

function alertMark(title) {
    return `<span class="alert-mark" title="${escapeHtml(title || "Not in the season info from TMDB")}">!</span>`;
}

function showHaystack(show) {
    if (!show._hay) {
        show._hay = [
            show.title, show.original_title, show.year, show.imdb_id, show.tvdb_id, show.tmdb_id, show.show_status,
            (show.genres || []).join(" "), (show.studios || []).join(" "), (show.countries || []).join(" "),
            (show.directors || []).join(" "), show.search_extra,
        ].filter(Boolean).join(" ").toLowerCase();
    }
    return show._hay;
}

function tvNodes() {
    const match = textMatcher(state.video.filter.tv);
    const nodes = [];
    (state.video.shows || []).forEach((show) => {
        if (match && !match(showHaystack(show))) return;
        nodes.push({ type: "show", id: show.id, show });
        if (!state.video.expanded.has(`show:${show.id}`)) return;
        const detail = state.video.showDetails.get(show.id);
        if (!detail) {
            nodes.push({ type: "loading", id: `loading:${show.id}` });
            return;
        }
        (detail.seasons || []).forEach((season) => {
            nodes.push({ type: "season", id: season.id, season, show: detail });
            if (!state.video.expanded.has(`season:${season.id}`)) return;
            seasonRows(detail, season).forEach((row) => nodes.push({ ...row, show: detail }));
        });
    });
    return nodes;
}

function seasonRows(detail, season) {
    const have = (detail.episodes || []).filter((episode) => episode.season_id === season.id);
    const byNumber = new Map(have.map((episode) => [episode.episode_number, episode]));
    const missing = new Set(season.missing_episodes || []);
    const numbers = [...new Set([...byNumber.keys(), ...missing])].sort((left, right) => left - right);
    return numbers.map((number) => {
        if (byNumber.has(number)) return { type: "episode", id: byNumber.get(number).id, episode: byNumber.get(number), season };
        return { type: "missing", id: `missing:${season.id}:${number}`, episode_number: number, season };
    });
}

function tvView(node) {
    if (node.type === "show") return { ...node.show, _kind: "show", _showId: node.show.id, id: node.show.id };
    if (node.type === "season") return { ...node.season, _kind: "season", _showId: node.show.id, mpaa: node.show.mpaa, countries: node.show.countries, studios: node.show.studios, title: seasonLabel(node.season, node.show), id: node.season.id };
    if (node.type === "missing") return { _kind: "missing", id: node.id, _showId: node.show.id, season_id: node.season.id, season_number: node.season.season_number, episode_number: node.episode_number, title: "", mpaa: node.show.mpaa, countries: node.show.countries, studios: node.show.studios };
    if (node.type === "episode") return { ...node.episode, _kind: "episode", _showId: node.show.id, mpaa: node.show.mpaa, countries: node.show.countries, studios: (node.episode && node.episode.show_studios) || (node.show && node.show.studios), title: node.episode.title || episodeCode(node.episode), id: node.episode.id };
    return { _kind: "loading", id: node.id, title: "Loading…", _showId: String(node.id).split(":")[1] || "" };
}

const TV_RIBBONS = [
    ["new", "New", (row) => row.status === "NEW" || !!row.new_count],
    ["latest", "Latest added", (row) => recentAdded(row)],
    ["upgrade", "Upgrade available", (row) => !!row.upgrade],
    ["uhd", "4K", (row) => row.resolution === "4K" || row.resolution === "8K"],
    ["fhd", "1080p", (row) => row.resolution === "1080p"],
    ["fel", "P7 FEL", (row) => String(row.dovi_profile || "").startsWith("7") && row.dovi_el_type === "FEL"],
    ["dv", "DV", (row) => row.hdr_format === "dovi"],
    ["hdr10plus", "HDR10+", (row) => row.hdr_format === "hdr10plus" || row.hdr_secondary === "HDR10+"],
    ["hdr10", "HDR10", (row) => row.hdr_format === "hdr10" || row.hdr_secondary === "HDR10"],
    ["hlg", "HLG", (row) => row.hdr_format === "hlg" || row.hdr_secondary === "HLG"],
    ["sdr", "SDR", (row) => row.hdr_format === "sdr"],
    ["missing", "Missing episodes", (row) => row._kind === "missing" || !!row.missing || Number(row.missing_count) > 0 || ((row.missing_episodes || []).length > 0)],
    ["health", "Health warnings", (row) => healthWords(row).length > 0],
    ["nonfo", "No NFO", (row) => row.has_nfo === false],
    ["nfo", "NFO changes", (row) => !!row.nfo_stale || !!row.nfo_family_stale],
    ["noposter", "No poster", (row) => {
        if (row._kind && row._kind !== "show") return false;
        const art = row.artwork;
        if (Array.isArray(art)) return !art.includes("poster");
        return !(art && art.poster);
    }],
    ["noimdb", "No IMDb rating", (row) => {
        if (row._kind === "episode") return !(Number(row.rating_imdb) > 0);
        if (row._kind === "season" || row._kind === "show") {
            const detail = row._kind === "show" ? state.video.showDetails.get(row.id) : (state.video.showDetails.get(row._showId) || state.video.showDetails.get(row.show_id));
            if (detail && detail.episodes && detail.episodes.length) {
                const eps = row._kind === "season" ? detail.episodes.filter((e) => e.season_id === row.id) : detail.episodes;
                return eps.some((e) => !(Number(e.rating_imdb) > 0));
            }
            return true;
        }
        return false;
    }],
    ["probefail", "Probe failed", (row) => !!row.probe_error],
    ["scrapefail", "Scrape failed", (row) => !!row.scrape_error],
    ["unscraped", "Not scraped", (row) => row._kind === "season" ? false : !row.scraped_at],
    ["unmatched", "Unmatched", (row) => !row.tmdb_id && !row.imdb_id && !row.tvdb_id],
    ["duplicate", "Duplicate", (row) => !!row.duplicate_release],
    ["held", "Not found", (row) => !!row.prune_held],
    ["locked", "Locked", (row) => !!row.locked],
    ["ignored", "Ignored", (row) => row.status === "IGNORED"],
    ["multi", "Multi-episode", (row) => isMultiRow(row)],
    ["nosubs", "No subtitles", (row) => {
        if (row._kind === "episode") return !(row.sub_langs && row.sub_langs.length);
        if (row._kind === "season" || row._kind === "show") {
            const detail = row._kind === "show" ? state.video.showDetails.get(row.id) : (state.video.showDetails.get(row._showId) || state.video.showDetails.get(row.show_id));
            if (detail && detail.episodes && detail.episodes.length) {
                const eps = row._kind === "season" ? detail.episodes.filter((e) => e.season_id === row.id) : detail.episodes;
                return eps.some((e) => !(e.sub_langs && e.sub_langs.length));
            }
            return true;
        }
        return false;
    }],
    ["noen_subs", "Missing English subtitles", (row) => {
        if (row._kind === "episode") return !(row.sub_langs || []).some((l) => /^en/i.test(String(l)));
        if (row._kind === "season" || row._kind === "show") {
            const detail = row._kind === "show" ? state.video.showDetails.get(row.id) : (state.video.showDetails.get(row._showId) || state.video.showDetails.get(row.show_id));
            if (detail && detail.episodes && detail.episodes.length) {
                const eps = row._kind === "season" ? detail.episodes.filter((e) => e.season_id === row.id) : detail.episodes;
                return eps.some((e) => !(row.sub_langs || []).some((l) => /^en/i.test(String(l))));
            }
            return true;
        }
        return false;
    }],
    ["multi_audio", "Multi-audio", (row) => {
        if (row._kind === "episode") return (row.audio_langs || []).length > 1;
        if (row._kind === "season" || row._kind === "show") {
            const detail = row._kind === "show" ? state.video.showDetails.get(row.id) : (state.video.showDetails.get(row._showId) || state.video.showDetails.get(row.show_id));
            if (detail && detail.episodes && detail.episodes.length) {
                const eps = row._kind === "season" ? detail.episodes.filter((e) => e.season_id === row.id) : detail.episodes;
                return eps.some((e) => (e.audio_langs || []).length > 1);
            }
            return true;
        }
        return false;
    }],
    ["unknown_audio", "Unknown audio language", (row) => {
        if (row._kind === "episode") return Number(row.audio_unknown) > 0;
        if (row._kind === "season" || row._kind === "show") {
            const detail = row._kind === "show" ? state.video.showDetails.get(row.id) : (state.video.showDetails.get(row._showId) || state.video.showDetails.get(row.show_id));
            if (detail && detail.episodes && detail.episodes.length) {
                const eps = row._kind === "season" ? detail.episodes.filter((e) => e.season_id === row.id) : detail.episodes;
                return eps.some((e) => Number(e.audio_unknown) > 0);
            }
            return true;
        }
        return false;
    }],
    ["unknown_subs", "Unknown subtitle language", (row) => {
        if (row._kind === "episode") return Number(row.sub_unknown) > 0;
        if (row._kind === "season" || row._kind === "show") {
            const detail = row._kind === "show" ? state.video.showDetails.get(row.id) : (state.video.showDetails.get(row._showId) || state.video.showDetails.get(row.show_id));
            if (detail && detail.episodes && detail.episodes.length) {
                const eps = row._kind === "season" ? detail.episodes.filter((e) => e.season_id === row.id) : detail.episodes;
                return eps.some((e) => Number(e.sub_unknown) > 0);
            }
            return true;
        }
        return false;
    }],
    ["nothumb", "No episode thumb", (row) => {
        if (row._kind === "episode") return !(Array.isArray(row.artwork) ? row.artwork.includes("thumb") : (row.artwork && row.artwork.thumb));
        if (row._kind === "season" || row._kind === "show") {
            const detail = row._kind === "show" ? state.video.showDetails.get(row.id) : (state.video.showDetails.get(row._showId) || state.video.showDetails.get(row.show_id));
            if (detail && detail.episodes && detail.episodes.length) {
                const eps = row._kind === "season" ? detail.episodes.filter((e) => e.season_id === row.id) : detail.episodes;
                return eps.some((e) => !(Array.isArray(e.artwork) ? e.artwork.includes("thumb") : (e.artwork && e.artwork.thumb)));
            }
            return true;
        }
        return false;
    }],
    ["notrailer", "No trailer", (row) => (row._kind === "show" || row._kind === "season") && !row.has_trailer && !row.trailer && !row.trailer_file],
    // Seasons carry the file found when their show was opened; a show carries the stored check.
    ["missing_trailer", "Missing trailer", (row) => (row._kind === "show" && row.has_local_trailer === false) || (row._kind === "season" && row.trailer_file === null)],
    ["missing_theme", "Missing theme song", (row) => row._kind === "show" && row.has_local_theme === false],
];

function visibleTvRows(exceptKey) {
    let views = tvNodes().map(tvView);
    const filters = { ...(state.video.tvFilters || {}) };
    if (exceptKey) delete filters[exceptKey];
    const ribbons = TV_RIBBONS.filter(([key]) => libraryRibbons().has(key));
    if (Object.values(filters).some(Boolean) || ribbons.length) {
        const keep = new Set();
        views.forEach((view) => {
            const ribbonOk = !ribbons.length || view._kind === "loading" || ribbons.every(([, , test]) => test(view));
            if ((view._kind === "loading" || rowMatchesFilters(view, filters)) && ribbonOk) {
                keep.add(`${view._kind}:${view.id}`);
                if (view._showId) keep.add(`show:${view._showId}`);
                if (view.season_id) keep.add(`season:${view.season_id}`);
            }
        });
        views = views.filter((view) => keep.has(`${view._kind}:${view.id}`));
    }
    const sort = matrixSort();
    const column = MOVIE_COLUMNS.find((item) => item.key === sort.key) || MOVIE_COLUMNS[1];
    const value = column.sort || ((row) => columnPlain(column, row).toLowerCase());
    const dir = sort.dir === "desc" ? -1 : 1;
    const shows = views.filter((view) => view._kind === "show").sort((a, b) => {
        const left = value(a);
        const right = value(b);
        if (left < right) return -dir;
        if (left > right) return dir;
        return titleSortKey(a).localeCompare(titleSortKey(b));
    });
    const children = new Map();
    views.forEach((view) => {
        if (view._kind === "show") return;
        const list = children.get(view._showId) || [];
        list.push(view);
        children.set(view._showId, list);
    });
    const rows = [];
    shows.forEach((show) => {
        rows.push(show);
        (children.get(show.id) || []).forEach((child) => rows.push(child));
    });
    return rows;
}

function fileSpanList(span) {
    if (typeof span === "string") {
        try { span = JSON.parse(span); } catch (error) { return []; }
    }
    return Array.isArray(span) ? span : [];
}

function isMultiFile(row) {
    return fileSpanList(row && row.file_span).length > 1;
}

function isMultiRow(row) {
    if (!row) return false;
    if (isMultiFile(row)) return true;
    return (row._kind === "show" || row._kind === "season") && Number(row.multi_count) > 0;
}

function multiSortValue(row) {
    const span = fileSpanList(row && row.file_span).length;
    if (span > 1) return span;
    return Number(row && row.multi_count) || 0;
}

function fileSpanText(span) {
    span = fileSpanList(span);
    if (span.length < 2) return "";
    const groups = [];
    span.forEach((item) => {
        const season = Number(item.season);
        const episode = Number(item.episode);
        if (!Number.isFinite(season) || !Number.isFinite(episode)) return;
        const last = groups[groups.length - 1];
        if (!last || last.season !== season) groups.push({ season, numbers: [episode] });
        else if (!last.numbers.includes(episode)) last.numbers.push(episode);
    });
    const piece = (season, numbers) => {
        const ordered = numbers.slice().sort((left, right) => left - right);
        const pad = (value) => String(value).padStart(2, "0");
        const contiguous = ordered.every((value, index) => value === ordered[0] + index);
        const body = ordered.length === 1
            ? pad(ordered[0])
            : (contiguous ? `${pad(ordered[0])}-E${pad(ordered[ordered.length - 1])}` : ordered.map((value) => pad(value)).join("E"));
        return `S${pad(season)}E${body}`;
    };
    return groups.map((group) => piece(group.season, group.numbers)).join("");
}

function multiFlag(row) {
    const text = fileSpanText(row && row.file_span);
    if (!text) return "";
    return `<span class="tag-pill multi-pill" title="This file holds ${escapeHtml(text)}">Multi</span>`;
}

function multiColumnChip(row) {
    if (isMultiFile(row)) {
        const text = fileSpanText(row.file_span);
        return `<span class="tag-pill multi-pill" title="Episodes in this file">${escapeHtml(text || "Multi")}</span>`;
    }
    const count = Number(row && row.multi_count) || 0;
    if (!count || (row._kind !== "show" && row._kind !== "season")) return "";
    return `<span class="tag-pill multi-pill" title="${count} multi-episode file${count === 1 ? "" : "s"}">${count}</span>`;
}

function fileSpanNote(span) {
    const text = fileSpanText(span);
    return text ? ` <span class="tag-pill multi-pill" title="This file holds ${escapeHtml(text)}">Multi</span>` : "";
}

function tvTitleCell(row) {
    if (row._kind === "loading") return `<span class="muted">Loading…</span>`;
    const cfg = typeof videoCfg === "function" ? videoCfg() : {};
    const showYearSetting = cfg.ui_tv_year !== false;
    const pad = row._kind === "season" ? " vm-indent-1" : (row._kind === "episode" || row._kind === "missing") ? " vm-indent-2" : "";
    const key = `${row._kind}:${row.id}`;
    const open = state.video.expanded.has(key);
    const caret = row._kind === "show" || row._kind === "season"
        ? `<button type="button" class="vl-caret" data-action="video-toggle" data-key="${escapeHtml(key)}" aria-label="${open ? "Collapse" : "Expand"}">${open ? "▾" : "▸"}</button>`
        : "";
    const episodeLabel = row._kind === "episode" || row._kind === "missing";
    const rawTitle = String(row.title || "").trim();
    let cleanTitle = rawTitle;
    if (row._kind === "show" && row.year && new RegExp(`\\(\\s*${row.year}\\s*\\)\\s*$`).test(rawTitle)) {
        cleanTitle = rawTitle.replace(new RegExp(`\\s*\\(\\s*${row.year}\\s*\\)\\s*$`), "");
    }
    const yearPart = showYearSetting && row._kind === "show" && row.year
        ? ` <span class="muted">(${escapeHtml(row.year)})</span>`
        : "";
    const labelText = episodeLabel
        ? episodeHeading(row, " ")
        : (cleanTitle + (showYearSetting && row._kind === "show" && row.year ? ` (${row.year})` : ""));
    const headingHtml = episodeLabel
        ? escapeHtml(episodeHeading(row, " "))
        : `${escapeHtml(cleanTitle)}${yearPart}`;
    const extra = row.extra || (row._kind === "season" && (row.extra_episodes || []).length) ? alertMark(row._kind === "season" ? "This season has episodes that are not in the TMDB season" : "This episode is not in the TMDB season") : "";
    const missing = (row.missing || row._kind === "missing") ? chip("Missing", "is-muted") : "";
    const span = fileSpanNote(row.file_span);
    return `<span class="vl-title${pad}" title="${escapeHtml(labelText)}">${caret}${headingHtml} ${missing}${extra}${span}</span>${titleFacts(row)}`;
}

function setTvChecked(kind, id, on) {
    if (!kind || !id || kind === "missing" || kind === "loading") return;
    const key = `${kind}:${id}`;
    if (on) state.video.tvChecked.add(key);
    else state.video.tvChecked.delete(key);
}

function tvShowIdFor(kind, id) {
    if (kind === "show") return id;
    const row = (state.video.rows || []).find((item) => item._kind === kind && item.id === id);
    if (row && row._showId) return row._showId;
    for (const [showId, detail] of state.video.showDetails || []) {
        if (kind === "season" && (detail.seasons || []).some((season) => season.id === id)) return showId;
        if (kind === "episode" && (detail.episodes || []).some((episode) => episode.id === id)) return showId;
    }
    return "";
}

function applyTvChildChecks(kind, id, on) {
    const showId = tvShowIdFor(kind, id);
    const detail = showId ? state.video.showDetails.get(showId) : null;
    if (!detail) return;
    const seasons = kind === "season"
        ? (detail.seasons || []).filter((season) => String(season.id) === String(id))
        : (detail.seasons || []);
    seasons.forEach((season) => {
        if (kind === "show") setTvChecked("season", season.id, on);
        (detail.episodes || []).filter((episode) => String(episode.season_id) === String(season.id)).forEach((episode) => {
            setTvChecked("episode", episode.id, on);
        });
    });
}

async function ensureTvChildChecks(kind, id, on) {
    if (kind !== "show" && kind !== "season") return;
    const showId = tvShowIdFor(kind, id);
    if (!showId) return;
    if (!state.video.showDetails.has(showId)) {
        try {
            await showDetail(showId);
        } catch (error) {
            notify(error.message, "error");
            return;
        }
    }
    applyTvChildChecks(kind, id, on);
}

function tvCheckedShows() {
    const shows = new Set();
    selectionChecked("tv").forEach((key) => {
        const split = key.indexOf(":");
        const kind = key.slice(0, split);
        const id = key.slice(split + 1);
        if (kind === "show") shows.add(id);
        else {
            const row = (state.video.rows || []).find((item) => item._kind === kind && item.id === id);
            if (row && row._showId) shows.add(row._showId);
        }
    });
    return [...shows];
}

const _pendingShowDetails = new Set();
function ensureExpandedTvShows() {
    const missing = (state.video.shows || [])
        .filter((show) => state.video.expanded.has(`show:${show.id}`) && !state.video.showDetails.has(show.id) && !_pendingShowDetails.has(show.id))
        .map((show) => show.id);
    if (!missing.length) return;
    missing.forEach((id) => _pendingShowDetails.add(id));
    Promise.all(missing.map((id) => showDetail(id).catch(() => null))).then(() => {
        missing.forEach((id) => _pendingShowDetails.delete(id));
        if (state.media === "tv") renderTvTree();
    }).catch(() => {
        missing.forEach((id) => _pendingShowDetails.delete(id));
    });
}

function renderTvTree() {
    ensureExpandedTvShows();
    const host = document.getElementById("video-list");
    const scroll = typeof pinnedListScroll === "function" ? pinnedListScroll(host) : (host ? host.scrollTop : 0);
    if (host) state.videoScrollPin = true;
    document.getElementById("video-ribbons").innerHTML = ribbonBarHtml(TV_RIBBONS, (state.video.shows || []).concat(
        [...(state.video.showDetails || new Map()).values()].flatMap((detail) => (detail.episodes || []).map((episode) => ({ ...episode, _kind: "episode" })))
    ));
    const shows = state.video.shows || [];
    const episodes = shows.reduce((sum, show) => sum + (show.episode_count || 0), 0);
    if (!shows.length) {
        renderVideoCounts("No shows yet");
        host.innerHTML = `<p class="muted vpad">Each subfolder of a TV folder is a show. Add a TV folder in Settings, then scan.</p>`;
        state.videoScrollPin = false;
        paintVideoSelection();
        return;
    }
    const columns = movieColumns();
    state.video.rows = visibleTvRows();
    const shownShows = state.video.rows.filter((row) => row._kind === "show").length;
    renderVideoCounts(shownShows !== shows.length ? `${shownShows} of ${shows.length} shows · ${episodes} episodes` : `${shows.length} shows · ${episodes} episodes`);
    if (typeof videoViewMode === "function" && videoViewMode() === "grid") {
        renderVideoPosterGrid(state.video.rows.filter((row) => row._kind === "show"), "show");
        state.videoScrollPin = false;
        paintVideoSelection();
        return;
    }
    host.innerHTML = `<div class="vmatrix" style="${matrixTemplate(columns).style}">
        <div class="vm-head" role="row">${matrixHeadHtml(columns)}</div>
        <div class="vwin-rows"></div>
    </div>`;
    bindMatrixChrome(host);
    state.video.paintToken += 1;
    pinListScroll(host, scroll);
    paintTvRows();
    paintVideoSelection();
}

function tvMatrixRowHtml(row, index) {
    const action = { show: "video-open-show", season: "video-open-season", episode: "video-open-episode" }[row._kind] || "";
    const sel = state.video.tvSel;
    const selected = sel && sel.type === row._kind && sel.id === row.id ? " is-selected" : "";
    const cells = movieColumns().map((column) => matrixCell(column, row)).join("");
    const box = row._kind === "loading" || row._kind === "missing" ? `<span class="vm-cell vm-check"></span>`
        : `<span class="vm-cell vm-check"><input type="checkbox" data-action="video-check" data-kind="${row._kind}" data-id="${escapeHtml(row.id)}" ${matrixChecked(row) ? "checked" : ""} aria-label="Select"></span>`;
    const marked = row.status === "NEW" || ((row._kind === "show" || row._kind === "season") && row.new_count);
    const missingAttrs = row._kind === "missing"
        ? ` data-kind="missing" data-season="${Number(row.season_number)}" data-episode="${Number(row.episode_number)}"`
        : "";
    return `<div class="vm-row${selected}${marked ? " is-new" : ""}" style="top:${index * VIDEO_ROW}px" ${action ? `data-action="${action}"` : ""} data-id="${escapeHtml(row.id)}" data-show="${escapeHtml(row._showId || "")}"${missingAttrs} role="row">${box}${cells}</div>`;
}

function paintTvRows() {
    if (typeof videoViewMode === "function" && videoViewMode() === "grid") return paintVideoRows();
    const host = document.getElementById("video-list");
    const head = host.querySelector(".vm-head");
    paintWindow(host, state.video.rows || [], tvMatrixRowHtml, head ? head.offsetHeight : 0);
}

async function showDetail(id, force) {
    if (!force && state.video.showDetails.has(id)) return state.video.showDetails.get(id);
    const detail = await api(`/api/v1/tv/shows/${encodeURIComponent(id)}`);
    state.video.showDetails.set(id, detail);
    return detail;
}

async function toggleTvNode(key) {
    if (state.video.expanded.has(key)) state.video.expanded.delete(key);
    else state.video.expanded.add(key);
    renderTvTree();
    if (key.startsWith("show:") && state.video.expanded.has(key)) {
        const id = key.slice(5);
        if (!state.video.showDetails.has(id)) {
            try {
                await showDetail(id);
            } catch (error) {
                state.video.expanded.delete(key);
                notify(error.message, "error");
            }
            renderTvTree();
        }
    }
}

function tvSelect(type, id, showId) {
    state.video.tvSel = { type, id, show: showId };
    state.video.paintToken += 1;
    paintTvRows();
    return (state.video.detailToken += 1);
}

async function openShow(id) {
    const token = tvSelect("show", id);
    const center = document.getElementById("video-center");
    center.innerHTML = `<p class="muted vpad">Loading…</p>`;
    try {
        const show = await showDetail(id, true);
        if (token !== state.video.detailToken) return;
        renderShowInfo(show);
        if (state.video.expanded.has(`show:${id}`)) renderTvTree();
    } catch (error) {
        if (token === state.video.detailToken) center.innerHTML = `<p class="vpad">${escapeHtml(error.message)}</p>`;
    }
}

function renderShowInfo(show) {
    const art = show.artwork || {};
    const genreLinks = clickableFilterLinks(show.genres);
    const lineParts = [show.year ? `<button type="button" class="vlink-chip" data-action="video-filter-query" data-query="${escapeHtml(String(show.year))}">${escapeHtml(String(show.year))}</button>` : "", show.show_status ? escapeHtml(show.show_status) : "", genreLinks].filter(Boolean);
    const line = lineParts.join(" · ");
    const rating = ratingMarks(show);
    const episodes = show.episodes || [];
    const fresh = episodes.filter((episode) => episode.status === "NEW").length;
    const missingCount = episodes.filter((episode) => episode.missing).length + (show.seasons || []).reduce((sum, season) => sum + ((season.missing_episodes || []).length), 0);
    const onDisk = episodes.length - episodes.filter((episode) => episode.missing).length;
    const totalShowEps = onDisk + missingCount;
    const showProgress = tvProgressBarHtml(onDisk, totalShowEps, missingCount > 0);
    const extraCount = (show.seasons || []).reduce((sum, season) => sum + ((season.extra_episodes || []).length), 0);
    const head = `${infoTitle(escapeHtml(show.title || ""), { kind: "show", id: show.id, locked: show.locked })}
        <p class="vhero-edition">${certBadge(show)}${line} ${rating}</p>`;
    const body = `${brandRow(head, show.network_icons)}
        <div class="vchips vchips-art">${artMarks(show.artwork, INFO_ART.show)}${nfoChip("tvshow.nfo", show.nfo_path, "show", show.id, show.nfo_stale)}</div>
        <div class="vchips vchips-media">${chip(`${(show.seasons || []).length} seasons`)}${chip(`${onDisk} episodes`)}${missingCount ? chip(`${missingCount} missing`, "is-muted") : ""}${extraCount ? alertMark(`${extraCount} episode${extraCount === 1 ? "" : "s"} are not in the TMDB season`) : ""}${fresh ? chip(fresh === 1 ? "1 new episode" : `${fresh.toLocaleString()} new episodes`, "is-new") : ""}${show.episode_order && show.episode_order !== "aired" ? chip(`${show.episode_order} order`) : ""}</div>
        ${isWanted(show) ? `<p class="muted">Waiting for the files.</p>` : ""}
        ${videoItemActions("show", show)}`;
    const seasons = (show.seasons || []).map((season) => {
        const poster = (season.artwork || {}).poster || "";
        const sHave = Math.max(0, (season.episode_count || 0) - (season.missing_count || 0));
        const sMissing = (season.missing_count || 0) + ((season.missing_episodes || []).length);
        const sTotal = sHave + sMissing;
        const sProgress = tvProgressBarHtml(sHave, sTotal, sMissing > 0);
        return `<button type="button" class="vset-card" data-action="video-open-season" data-id="${escapeHtml(season.id)}" data-show="${escapeHtml(show.id)}">
            ${poster ? `<img loading="lazy" src="${artUrl(poster, 342)}" alt="">` : `<span class="vposter is-empty">${escapeHtml(seasonLabel(season, show))}</span>`}
            ${sProgress}
            <strong>${escapeHtml(seasonLabel(season, show))} ${(season.extra_episodes || []).length ? alertMark("This season has episodes that are not in the TMDB season") : ""}</strong>
            <small>${sHave} episodes${sMissing ? ` · ${sMissing} missing` : ""}</small>
        </button>`;
    }).join("");
    document.getElementById("video-center").innerHTML = `<article class="vinfo">
        ${videoHero(art, art.poster, body, { kind: "show", id: show.id }, coverActions("show", show), { actions: videoHeroActions("show", show), progressHtml: showProgress, badges: `${toneBadge(`${(show.seasons || []).length} ${(show.seasons || []).length === 1 ? "season" : "seasons"}`, "badge-plain")}${toneBadge(`${onDisk} ${onDisk === 1 ? "episode" : "episodes"}`, "badge-plain")}` })}
        <section class="vsection">${filePathBlock(shownPath(show))}${mediaFlagSection(show)}
            ${factRows([["Premiered", fmtDate(show.premiered)], ["Certification", certFact(show)], ["Studio", clickableFilterLinks(show.studios), true], ["Country", clickableFilterLinks(show.countries), true], ["Tags", clickableFilterLinks(show.tags), true], ["Language", show.original_language], ["User rating", show.user_rating ?? ""], ["Top 250", show.top250 ?? ""], ["Links", idLinks(show), true]])}
        </section>
        ${trailerSection(show, { kind: "show", id: show.id })}
        <section class="vsection"><h3>Seasons</h3><div class="vset-grid">${seasons || `<p class="muted">No seasons.</p>`}</div></section>
        <section class="vsection">${castHtml(show.actors)}</section>
        <section class="vsection"><h3>Artwork</h3>${artGallery(art, { kind: "show", id: show.id })}</section>
    </article>`;
}

async function openSeason(id, showId, force) {
    const token = tvSelect("season", id, showId);
    const center = document.getElementById("video-center");
    try {
        const show = await showDetail(showId, force);
        if (token !== state.video.detailToken) return;
        const season = (show.seasons || []).find((item) => item.id === id);
        if (!season) throw new Error("That season is not in the library any more");
        renderSeasonInfo(show, season);
        if (force && state.video.expanded.has(`show:${showId}`)) renderTvTree();
    } catch (error) {
        if (token === state.video.detailToken) center.innerHTML = `<p class="vpad">${escapeHtml(error.message)}</p>`;
    }
}

function seasonYear(season) {
    if (season.year) return season.year;
    const premiered = String(season.premiered || "");
    return /^\d{4}/.test(premiered) ? premiered.slice(0, 4) : "";
}

function renderSeasonInfo(show, season) {
    const art = season.artwork || {};
    const episodes = (show.episodes || []).filter((episode) => episode.season_id === season.id);
    const missing = new Set(season.missing_episodes || []);
    const byNumber = new Map(episodes.map((episode) => [episode.episode_number, episode]));
    const numbers = [...new Set([...byNumber.keys(), ...missing])].sort((left, right) => left - right);
    const missingRows = episodes.filter((episode) => episode.missing).length;
    const gap = (season.missing_episodes || []).length;
    const missingTotal = missingRows + gap;
    const onDisk = Math.max(0, episodes.length - missingRows);
    const seasonProgress = tvProgressBarHtml(onDisk, onDisk + missingTotal, missingTotal > 0);
    const rows = numbers.map((number) => {
        const episode = byNumber.get(number);
        if (!episode) {
            return `<tr class="is-missing"><td class="num">${number}</td><td colspan="6">Episode ${number} is missing</td></tr>`;
        }
        return `<tr class="${episode.missing ? "is-missing" : episode.status === "NEW" ? "is-new" : ""}" data-action="video-open-episode" data-id="${escapeHtml(episode.id)}">
        <td class="num">${episode.episode_number}</td>
        <td>${escapeHtml(episode.title || "")} ${episode.missing ? chip("Missing", "is-muted") : ""} ${episode.extra ? alertMark("This episode is not in the TMDB season") : ""}</td>
        <td>${escapeHtml(fmtDate(episode.aired))}</td>
        <td>${fileChips(episode)}</td>
        <td>${escapeHtml(langText(episode.sub_langs))}</td>
        <td>${episode.has_nfo ? "✓" : "—"}</td>
        <td>${videoStatus(episode)}</td>
    </tr>`;
    }).join("");
    const head = `${infoTitle(`${escapeHtml(seasonLabel(season, show))}${seasonYear(season) ? ` <span class="muted">· ${escapeHtml(String(seasonYear(season)))}</span>` : ""}`, { kind: "season", id: season.id, locked: season.locked })}
        <p class="vline">${onDisk} episodes${missingTotal ? ` · ${missingTotal} missing` : ""} ${(season.extra_episodes || []).length ? alertMark("This season has episodes that are not in the TMDB season") : ""}</p>`;
    const body = `<p class="muted"><button type="button" class="link" data-action="video-open-show" data-id="${escapeHtml(show.id)}">${escapeHtml(show.title || "")}</button></p>
        ${brandRow(head, (season && season.network_icons) || (show && show.network_icons))}
        <div class="vchips vchips-art">${artMarks(season.artwork, INFO_ART.season)}${nfoChip("season.nfo", season.nfo_path, "season", season.id, season.nfo_stale)}</div>
        <div class="vactions">
            <button type="button" class="btn-ghost" data-action="video-edit" data-kind="season" data-id="${escapeHtml(season.id)}" ${season.locked ? "disabled" : ""}>Edit</button>
            <button type="button" class="btn-ghost" data-action="video-scrape-prefs" data-kind="season" data-id="${escapeHtml(season.id)}">Custom scrapers…</button>
            <button type="button" class="btn-ghost" data-action="video-nfo-one" data-kind="season" data-id="${escapeHtml(season.id)}">Write season.nfo</button>
            <button type="button" class="btn-ghost${integrationOn("sonarr") ? "" : " is-unavailable"}" data-action="video-sonarr-missing" data-show="${escapeHtml(show.id)}" data-season="${season.season_number}" title="Ask Sonarr to search monitored episodes in this season that it has no file for">Search missing episodes</button>
        </div>
        ${storyCopy(season)}`;
    document.getElementById("video-center").innerHTML = `<article class="vinfo">
        ${videoHero(art, art.poster || (show.artwork || {}).poster, body, { kind: "season", id: season.id }, coverActions("season", season), { fallback: show.artwork || {}, actions: videoHeroActions("season", season), progressHtml: seasonProgress, badges: onDisk ? toneBadge(`${onDisk} ${onDisk === 1 ? "episode" : "episodes"}`, "badge-plain") : "" })}
        <section class="vsection">${filePathBlock(shownPath(season))}${mediaFlagSection(season)}</section>
        <section class="vsection"><table class="vtracks vclick"><thead><tr><th>#</th><th>Title</th><th>Aired</th><th>Video</th><th>Subtitles</th><th>NFO</th><th></th></tr></thead><tbody>${rows}</tbody></table></section>
        ${trailerSection(season, { kind: "season", id: season.id })}
        <section class="vsection"><h3>Artwork</h3>${artGallery(art, { kind: "season", id: season.id })}</section>
    </article>`;
}

async function openEpisode(id, keepScroll) {
    if (!keepScroll && state.video) state.video.keepCenterScroll = false;
    const token = tvSelect("episode", id);
    const center = document.getElementById("video-center");
    center.innerHTML = `<p class="muted vpad">Loading…</p>`;
    try {
        const episode = await api(`/api/v1/tv/episodes/${encodeURIComponent(id)}`);
        if (token !== state.video.detailToken) return;
        renderEpisodeInfo(episode);
    } catch (error) {
        if (state.video) state.video.keepCenterScroll = false;
        if (token === state.video.detailToken) center.innerHTML = `<p class="vpad">${escapeHtml(error.message)}</p>`;
    }
}

function splitEpisodesButton(episode) {
    // Lives in the main action row next to Write .nfo, so it gets the standard button size.
    const path = String((episode || {}).path || "");
    const span = Array.isArray((episode || {}).file_span) ? episode.file_span : [];
    const shared = Array.isArray((episode || {}).shares_file_with) && episode.shares_file_with.length > 0;
    if (!(span.length > 1 || shared)) return "";
    if (!path.toLowerCase().endsWith(".mkv") || path.toLowerCase().includes(".split-source-eps-")) return "";
    return `<button type="button" class="btn-ghost" data-action="video-split-open" data-id="${escapeHtml(episode.id)}">Split episodes</button>`;
}

function splitButtons(episode) {
    const buttons = [];
    if (episode.split_source) {
        buttons.push(`<button type="button" class="btn-ghost" data-action="video-split-restore" data-id="${escapeHtml(episode.id)}">Restore original</button>`);
        buttons.push(`<button type="button" class="btn-ghost btn-remove" data-action="video-split-delete-source" data-id="${escapeHtml(episode.id)}">Delete source file</button>`);
    }
    return buttons.length ? `<p class="job-actions">${buttons.join("")}</p>` : "";
}

const SPLIT_SOURCES = {
    chapter: "Chapter",
    "black-silence": "Black and silence",
    "black-silence-wide": "Uncertain, wide window",
    "black-short-silence": "Uncertain, black picture with brief silence",
    "black-only": "Uncertain, black picture only",
    "silence-only": "Uncertain, silence only",
    manual: "Manual",
};

function splitCode(item) {
    const pad = (value) => String(value).padStart(2, "0");
    return `S${pad(item.season)}E${pad(item.episode)}`;
}

function stopSplitPoll() {
    clearTimeout(state.episodeSplitTimer);
    state.episodeSplitTimer = null;
    const vid = document.getElementById("episode-split-video");
    if (vid) {
        vid.pause();
        vid.removeAttribute("src");
        vid.load();
    }
    const wrap = document.getElementById("episode-split-player-wrap");
    if (wrap) wrap.classList.add("hidden");
    state._splitFocusedInput = null;
}

function isMultiEpisodeFile(row) {
    const span = fileSpanList(row && row.file_span);
    const path = String((row && row.path) || "");
    return span.length > 1 && path.toLowerCase().endsWith(".mkv") && !path.toLowerCase().includes(".split-source-eps-");
}

function episodeById(id) {
    const visible = (state.video.rows || []).find((item) => item._kind === "episode" && String(item.id) === String(id));
    if (visible) return visible;
    for (const detail of (state.video.showDetails || new Map()).values()) {
        const episode = (detail.episodes || []).find((item) => String(item.id) === String(id));
        if (episode) return { ...episode, _kind: "episode" };
    }
    return null;
}

function selectedSplitEpisodeIds() {
    if (state.media !== "tv") return [];
    const ids = [];
    for (const key of selectionChecked("tv")) {
        const text = String(key);
        const cut = text.indexOf(":");
        if (cut < 0 || text.slice(0, cut) !== "episode") continue;
        ids.push(text.slice(cut + 1));
    }
    if (!ids.length || !splitTargets(ids).length) return [];
    return ids;
}

function splitFileTitle(row) {
    const name = String((row && row.path) || "").split(/[/\\]/).pop() || "File";
    const span = fileSpanText(row && row.file_span);
    return span ? `${name} · ${span}` : name;
}

function splitTargets(ids) {
    const rows = (ids || []).map((id) => episodeById(id));
    if (!rows.length || rows.some((row) => !isMultiEpisodeFile(row))) return [];
    const seen = new Set();
    const files = [];
    rows.forEach((row) => {
        const path = String(row.path || row.id || "");
        if (seen.has(path)) return;
        seen.add(path);
        files.push({ id: row.id, title: splitFileTitle(row) });
    });
    return files;
}

function openEpisodeSplit(id) {
    return openEpisodeSplits([id], true);
}

async function openEpisodeSplits(ids, force) {
    let files = splitTargets(ids);
    if (!files.length && force) files = (ids || []).filter(Boolean).map((id) => ({ id, title: "" }));
    if (!files.length) return;
    stopSplitPoll();
    state.episodeSplitToken = (state.episodeSplitToken || 0) + 1;
    const token = state.episodeSplitToken;
    state.episodeSplitPlans = [];
    const modal = document.getElementById("episode-split-modal");
    document.getElementById("episode-split-body").innerHTML = `${splitWarningHtml()}<p class="muted">Finding cut points…</p>`;
    modal.classList.remove("hidden");
    for (let index = 0; index < files.length; index += 1) {
        if (state.episodeSplitToken !== token) return;
        document.getElementById("episode-split-body").innerHTML = `${splitWarningHtml()}<p class="muted">Finding cut points… file ${index + 1} of ${files.length}: ${escapeHtml(files[index].title || "")}</p>${splitPlanHtml(state.episodeSplitPlans, false)}`;
        try {
            const plan = await api(`/api/v1/episodes/${encodeURIComponent(files[index].id)}/split/plan`, { method: "POST", body: {} });
            state.episodeSplitPlans.push(plan);
        } catch (error) {
            state.episodeSplitPlans.push({ episode_id: files[index].id, title: files[index].title, error: error.message });
        }
    }
    if (state.episodeSplitToken === token) paintEpisodeSplits();
}

function splitPartCard(part, index, join, isLast) {
    const code = splitCode(part);
    const title = String(part.title || "").trim();
    const name = title ? ` · ${escapeHtml(title)}` : "";

    if (isLast) {
        return `<div class="split-part-card is-last" data-split-part-index="${index}">
            <div class="split-part-header">
                <span class="split-part-badge">${index + 1}</span>
                <div class="split-part-info">
                    <strong>${escapeHtml(code)}</strong><span class="split-part-title">${name}</span>
                </div>
                <span class="split-part-tag muted">End of video</span>
            </div>
        </div>`;
    }

    const sourceLabel = escapeHtml(SPLIT_SOURCES[join.source] || join.source || "Cut point");
    const targetLabel = `${code}${title ? ' · ' + title : ''}`;

    return `<div class="split-part-card is-cuttable" data-split-part-index="${index}" data-target-label="${escapeHtml(targetLabel)}" tabindex="0">
        <div class="split-part-header">
            <span class="split-part-badge">${index + 1}</span>
            <div class="split-part-info">
                <strong>${escapeHtml(code)}</strong><span class="split-part-title">${name}</span>
            </div>
            <span class="split-part-tag">Cut at end</span>
        </div>
        <div class="split-part-cut">
            <label class="field">
                <span class="muted">${sourceLabel}</span>
                <input data-split-time data-part-index="${index}" value="${escapeHtml(join.time_text || "")}" placeholder="0:00:00.000" spellcheck="false" autocomplete="off">
            </label>
        </div>
    </div>`;
}

function splitJoinFallbackCard(join, index) {
    const targetLabel = `${splitCode(join.after)} → ${splitCode(join.before)}`;
    const sourceLabel = escapeHtml(SPLIT_SOURCES[join.source] || join.source || "Cut point");
    return `<div class="split-part-card is-cuttable" data-split-part-index="${index}" data-target-label="${escapeHtml(targetLabel)}" tabindex="0">
        <div class="split-part-header">
            <span class="split-part-badge">${index + 1}</span>
            <div class="split-part-info">
                <strong>${escapeHtml(splitCode(join.after))} → ${escapeHtml(splitCode(join.before))}</strong>
            </div>
            <span class="split-part-tag">${sourceLabel}</span>
        </div>
        <div class="split-part-cut">
            <label class="field">
                <span class="muted">Cut time</span>
                <input data-split-time data-part-index="${index}" value="${escapeHtml(join.time_text || "")}" placeholder="0:00:00.000" spellcheck="false" autocomplete="off">
            </label>
        </div>
    </div>`;
}

function splitWarningHtml() {
    return `<p class="muted">Experimental. A file name can list more episodes than the video contains, so check every cut before splitting. The source file is kept until you delete it, and Restore puts it back.</p>`;
}

function splitPlanHtml(plans, actions) {
    return (plans || []).map((plan) => {
        const title = plan.title || String(plan.source || plan.parked || "").split(/[/\\]/).pop() || "File";
        if (plan.error) {
            return `<section class="vsection" data-split-id="${escapeHtml(plan.episode_id)}"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(plan.error)}</p></section>`;
        }
        const file = String(plan.source || (plan.outputs && plan.outputs[0]) || plan.parked || "").split(/[/\\]/).pop();
        const parts = Array.isArray(plan.parts) ? plan.parts : [];
        const joins = plan.joins || [];

        const rows = parts.length
            ? parts.map((part, index) => {
                const isLast = index >= joins.length;
                const join = isLast ? null : joins[index];
                return splitPartCard(part, index, join, isLast);
            }).join("")
            : joins.map((join, index) => splitJoinFallbackCard(join, index)).join("");

        const parked = String(plan.parked || "").split(/[/\\]/).pop();
        return `<section class="vsection" data-split-id="${escapeHtml(plan.episode_id)}">
            <h3>${escapeHtml(file || title)}</h3>
            <div class="split-parts-list">${rows}</div>
            <p class="muted">The source is kept as ${escapeHtml(parked)}.</p>
            ${actions ? `<p class="job-actions"><button type="button" class="btn-ghost" data-action="video-split-run" data-id="${escapeHtml(plan.episode_id)}">${plan.ready ? "Split" : "Split anyway"}</button></p>` : ""}
        </section>`;
    }).join("");
}

function selectSplitPartCard(card) {
    if (!card) return;
    const body = document.getElementById("episode-split-body");
    if (!body) return;
    body.querySelectorAll(".split-part-card.is-active").forEach((el) => el.classList.remove("is-active"));
    card.classList.add("is-active");

    const markTarget = document.getElementById("episode-split-mark-target");
    const input = card.querySelector("[data-split-time]");
    if (input) {
        state._splitFocusedInput = input;
        const targetLabel = card.dataset.targetLabel || input.placeholder || "Cut point";
        if (markTarget) {
            markTarget.textContent = `Target: End of ${targetLabel}`;
            markTarget.classList.remove("muted");
        }
    } else {
        state._splitFocusedInput = null;
        if (markTarget) {
            const strong = card.querySelector("strong");
            markTarget.textContent = `${strong ? strong.textContent : "Episode"} ends at end of video`;
            markTarget.classList.add("muted");
        }
    }
}

function paintEpisodeSplits() {
    const plans = state.episodeSplitPlans || [];
    const ready = plans.filter((plan) => plan.joins);
    const allLabel = ready.length > 1 ? `Split all ${ready.length}` : "";
    document.getElementById("episode-split-body").innerHTML = `${splitWarningHtml()}${splitPlanHtml(plans, true)}
        <p id="episode-split-status" class="muted"></p>
        <div class="job-actions">
            <button type="button" class="btn-ghost" data-close="episode-split-modal">Cancel</button>
            ${allLabel ? `<button type="button" class="btn-ghost" data-action="video-split-all">${escapeHtml(allLabel)}</button>` : ""}
        </div>`;
    // Bind video player when there is exactly one plan
    const singlePlan = plans.length === 1 ? plans[0] : null;
    _bindSplitVideoPlayer(singlePlan);
}

function _formatSplitTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    const ss = s.toFixed(3).padStart(6, "0");
    return `${h}:${String(m).padStart(2, "0")}:${ss}`;
}

function _bindSplitVideoPlayer(plan) {
    const wrap = document.getElementById("episode-split-player-wrap");
    const video = document.getElementById("episode-split-video");
    const timecode = document.getElementById("episode-split-timecode");
    const markTarget = document.getElementById("episode-split-mark-target");
    if (!wrap || !video) return;

    // Show player only when there is exactly one plan with a known episode id
    const episodeId = plan && plan.episode_id && !plan.error ? plan.episode_id : null;
    if (!episodeId) {
        wrap.classList.add("hidden");
        video.src = "";
        return;
    }
    wrap.classList.remove("hidden");
    video.src = `/api/v1/tv/episodes/${encodeURIComponent(episodeId)}/stream`;
    video.load();

    video.ontimeupdate = () => {
        if (timecode) timecode.textContent = _formatSplitTime(video.currentTime);
    };

    // Track which split-time input / episode card is active
    state._splitFocusedInput = null;
    const splitBody = document.getElementById("episode-split-body");
    if (splitBody) {
        splitBody.querySelectorAll(".split-part-card.is-cuttable").forEach((card) => {
            card.addEventListener("click", (event) => {
                selectSplitPartCard(card);
                const input = card.querySelector("[data-split-time]");
                if (input && event.target !== input) {
                    input.focus();
                }
                seekSplitVideo(input);
            });
        });
        splitBody.querySelectorAll("[data-split-time]").forEach((input) => {
            input.addEventListener("focus", () => {
                const card = input.closest(".split-part-card");
                if (card) selectSplitPartCard(card);
            });
            input.addEventListener("change", () => seekSplitVideo(input));
        });
        const firstCuttable = splitBody.querySelector(".split-part-card.is-cuttable");
        if (firstCuttable) {
            selectSplitPartCard(firstCuttable);
            video.addEventListener("loadedmetadata", () => seekSplitVideo(firstCuttable.querySelector("[data-split-time]")), { once: true });
        }
    }
}

// Move the preview to a cut time. A few seconds before it, so the cut itself is seen as it plays.
function seekSplitVideo(input) {
    const video = document.getElementById("episode-split-video");
    if (!video || !input) return;
    const parts = String(input.value || "").trim().split(":").map(Number);
    if (!parts.length || parts.length > 3 || parts.some((part) => !Number.isFinite(part))) return;
    const seconds = parts.reduce((total, part) => total * 60 + part, 0);
    try { video.currentTime = Math.max(0, seconds); } catch (error) { /* metadata not loaded yet */ }
}

function markSplitVideoTime() {
    const video = document.getElementById("episode-split-video");
    if (!video) return;
    const t = _formatSplitTime(video.currentTime);
    const target = state._splitFocusedInput || document.querySelector("#episode-split-body [data-split-time]");
    if (target) {
        target.value = t;
        target.dispatchEvent(new Event("input", { bubbles: true }));
        const card = target.closest(".split-part-card");
        if (card) {
            card.classList.add("mark-pulse");
            setTimeout(() => card.classList.remove("mark-pulse"), 600);
        }
        notify(`Marked ${t}`, "info");
    } else {
        notify("Select an episode to mark its cut time", "warn");
    }
}

function splitJobsFromModal(onlyId) {
    return [...document.querySelectorAll("#episode-split-list [data-split-id], #episode-split-body [data-split-id]")]
        .filter((section) => (!onlyId || section.dataset.splitId === onlyId) && section.querySelector("[data-split-time]"))
        .map((section) => ({
            episode_id: section.dataset.splitId,
            times: [...section.querySelectorAll("[data-split-time]")].map((input) => input.value.trim()),
        }));
}

async function runEpisodeSplit(id) {
    return runEpisodeSplits(splitJobsFromModal(id));
}

async function runAllEpisodeSplits() {
    return runEpisodeSplits(splitJobsFromModal());
}

async function runEpisodeSplits(jobs) {
    if (!jobs.length) return;
    const status = document.getElementById("episode-split-status");
    if (status) status.textContent = "Splitting…";
    document.querySelectorAll("#episode-split-body [data-action='video-split-run'], #episode-split-body [data-action='video-split-all']").forEach((button) => { button.disabled = true; });
    try {
        const started = await api("/api/v1/episodes/split/batch", { method: "POST", body: { jobs } });
        if (started.queued) {
            // Backend queued the split to run after the current scan / file job. Tell the
            // user, close the modal, and leave polling to the watcher - they can reopen the
            // episode later to see the result.
            notify(started.message || "Split episodes added to scan queue", "info");
            const modal = document.getElementById("episode-split-modal");
            if (modal) modal.classList.add("hidden");
            state.splitWatch = { seen: false, until: Date.now() + 30 * 60 * 1000 };
            pollEpisodeSplit();
            document.querySelectorAll("#episode-split-body [data-action='video-split-run'], #episode-split-body [data-action='video-split-all']").forEach((button) => { button.disabled = false; });
            return;
        }
        paintSplitProgress(started.split || { message: started.message });
        state.splitWatch = { seen: true, until: Date.now() + 30 * 60 * 1000 };
        pollEpisodeSplit();
    } catch (error) {
        paintSplitProgress({ error: error.message });
        document.querySelectorAll("#episode-split-body [data-action='video-split-run'], #episode-split-body [data-action='video-split-all']").forEach((button) => { button.disabled = false; });
        throw error;
    }
}

function paintSplitProgress(data) {
    const status = document.getElementById("episode-split-status");
    const text = data.error || data.message || "Splitting…";
    if (status) status.textContent = text;
    else document.getElementById("episode-split-body").innerHTML = `<p class="muted">${escapeHtml(text)}</p>`;
    (data.results || []).forEach(markSplitDone);
}

function markSplitDone(item) {
    const section = document.querySelector(`#episode-split-body [data-split-id="${item.episode_id}"]`);
    if (!section || section.dataset.splitDone === "1") return;
    section.dataset.splitDone = "1";
    if (item.status === "error") {
        section.insertAdjacentHTML("beforeend", `<p>${escapeHtml(item.message || item.error || "The split failed")}</p>`);
        return;
    }
    const parked = String(item.parked || "").split(/[/\\]/).pop();
    section.innerHTML = `<h3>${escapeHtml(section.querySelector("h3") ? section.querySelector("h3").textContent : "File")}</h3>
        <p>${escapeHtml(item.message || "Split finished.")}</p>
        <p class="muted">Source kept as ${escapeHtml(parked)}.</p>
        <p class="job-actions">
            <button type="button" class="btn-ghost" data-action="video-split-restore" data-id="${escapeHtml(item.episode_id)}">Restore original</button>
            <button type="button" class="btn-ghost btn-remove" data-action="video-split-delete-source" data-id="${escapeHtml(item.episode_id)}">Delete source file</button>
        </p>`;
}

function pollEpisodeSplit() {
    stopSplitPoll();
    state.episodeSplitTimer = setTimeout(async () => {
        try {
            const data = await api("/api/v1/episodes/split/status");
            const modal = document.getElementById("episode-split-modal");
            if (modal && !modal.classList.contains("hidden")) paintSplitProgress(data);
            const watch = state.splitWatch || { seen: true };
            if (data.status === "running") {
                watch.seen = true;
                pollEpisodeSplit();
                return;
            }
            if (!watch.seen && Date.now() < (watch.until || 0)) {
                pollEpisodeSplit();  // queued behind another job; it has not started yet
                return;
            }
            if (state.splitWatch) {
                state.splitWatch = null;
                notify(data.error || data.message || "Episodes split.", data.status === "error" ? "fail" : "success");
            }
            document.querySelectorAll("#episode-split-body [data-action='video-split-run'], #episode-split-body [data-action='video-split-all']").forEach((button) => { button.disabled = false; });
            const selected = state.video.tvSel || {};
            if (selected.type === "episode" && (data.results || []).some((item) => item.episode_id === selected.id)) openEpisode(selected.id);
            if (state.media === "tv" && typeof refreshVideoItems === "function") refreshVideoItems("episode");
        } catch (error) {
            paintSplitProgress({ error: error.message });
        }
    }, 1000);
}

async function restoreEpisodeSplit(id) {
    const data = await api(`/api/v1/episodes/${encodeURIComponent(id)}/split/restore`, { method: "POST", body: {} });
    notify(data.message || "The original file is restored.", "success");
    document.getElementById("episode-split-modal").classList.add("hidden");
    stopSplitPoll();
    if (state.media === "tv" && typeof refreshVideoItems === "function") {
        await refreshVideoItems("episode");
    }
    return openEpisode(id);
}

async function deleteSplitSource(id) {
    const data = await api(`/api/v1/episodes/${encodeURIComponent(id)}/split/source`, { method: "POST", body: {} });
    notify(data.message || "The source file was deleted.", "success");
    document.getElementById("episode-split-modal").classList.add("hidden");
    stopSplitPoll();
    if (state.media === "tv" && typeof refreshVideoItems === "function") {
        await refreshVideoItems("episode");
    }
    return openEpisode(id);
}

function episodeSlot(episode) {
    if (episode.display_season == null && episode.display_episode == null) return "";
    const season = episode.display_season == null ? "?" : String(episode.display_season).padStart(2, "0");
    const number = episode.display_episode == null ? "?" : String(episode.display_episode).padStart(2, "0");
    return `S${season}E${number}`;
}

function episodeResume(episode) {
    if (episode.resume_position == null && episode.resume_total == null) return "";
    const position = episode.resume_position == null ? "" : `${episode.resume_position}s`;
    const total = episode.resume_total == null ? "" : `${episode.resume_total}s`;
    return [position, total].filter(Boolean).join(" / ");
}

function episodeBannerArt(episode) {
    const art = (episode && episode.artwork) || {};
    const season = (episode && episode.season_artwork) || {};
    const show = (episode && episode.show_artwork) || {};
    return art.banner || season.banner || show.banner || "";
}

function episodeLandscapeArt(episode) {
    const show = (episode && episode.show_artwork) || {};
    const season = (episode && episode.season_artwork) || {};
    return show.landscape || season.landscape || "";
}

function episodeClearlogoArt(episode) {
    const show = (episode && episode.show_artwork) || {};
    return show.clearlogo || "";
}

function renderEpisodeInfo(episode) {
    const art = episode.artwork || {};
    const shared = (episode.shares_file_with || []).length
        ? `<p class="muted">This file also holds episode ${episode.shares_file_with.join(", ")}.</p>` : "";
    const body = `<p class="muted"><button type="button" class="link" data-action="video-open-show" data-id="${escapeHtml(episode.show_id)}">${escapeHtml(episode.show_title || "")}</button>
            · <button type="button" class="link" data-action="video-open-season" data-id="${escapeHtml(episode.season_id)}" data-show="${escapeHtml(episode.show_id)}">${escapeHtml(episode.season_title || (episode.season_number === 0 ? "Specials" : `Season ${episode.season_number}`))}</button></p>
        ${brandRow(`${infoTitle(`${escapeHtml(episodeHeading(episode, " · "))} ${episode.extra ? alertMark("This episode is not in the TMDB season") : ""} ${multiFlag(episode)}`, { kind: "episode", id: episode.id, locked: episode.locked })}
        <p class="vline">${certBadge(episode)}${[fmtDate(episode.aired), fmtRuntime(episode.runtime_minutes)].filter(Boolean).map(escapeHtml).join(" · ")} ${ratingMarks(episode)}</p>`, episode.network_icons)}
        <div class="vchips vchips-art">${artMarks(episode.artwork, INFO_ART.episode)}${nfoChip("episode.nfo", episode.nfo_path, "episode", episode.id, episode.nfo_stale)}</div>
        <div class="vchips vchips-media">${fileChips(episode.file ? { ...episode.file, audio_main: briefAudio(episode.file) } : null)}${videoStatus(episode, true)}</div>
        ${videoItemActions("episode", episode)}
        ${storyCopy(episode)}
        ${splitButtons(episode)}`;
    document.getElementById("video-center").innerHTML = `<article class="vinfo">
        ${videoHero(art, art.thumb, body, { kind: "episode", id: episode.id, missing: !!episode.missing }, coverActions("episode", episode), {
            banner: episodeBannerArt(episode),
            landscape: episodeLandscapeArt(episode),
            clearlogo: episodeClearlogoArt(episode),
            fallback: [episode.season_artwork || {}, episode.show_artwork || {}],
            actions: videoHeroActions("episode", episode),
            badges: posterFileBadges(episode.file),
        })}
        <section class="vsection">
            ${episode.missing ? "" : filePathBlock(shownPath(episode, "file") || shownPath(episode))}
            ${mediaFlagSection(episode)}
            ${factRows([["Director", clickableFilterLinks(episode.directors), true], ["Writer", clickableFilterLinks(episode.writers), true], ["Guest stars", clickableFilterLinks((episode.guest_stars || []).map((actor) => actor.name)), true], ["Certification", certFact(episode)], ["Country", clickableFilterLinks(episode.show_countries), true], ["User rating", episode.user_rating ?? ""], ["Display", episodeSlot(episode)], ["Resume", episodeResume(episode)], ["Play count", episode.playcount || ""], ["NFO", episode.nfo_path || "None"], ["Media info", (episode.file && episode.file.mediainfo_path) ? pathCell(shownPath(episode.file, "mediainfo_path")) : "None", !!(episode.file && episode.file.mediainfo_path)]])}
            ${shared}
        </section>
        ${episode.missing ? "" : mediaInfoHtml(episode.file, { kind: "episode", id: episode.id })}
        <section class="vsection"><h3>Artwork</h3>${artGallery(art, { kind: "episode", id: episode.id })}</section>
    </article>`;
    releaseCenterScroll();
}

function moveTvSelection(step) {
    const isGrid = typeof videoViewMode === "function" && videoViewMode() === "grid";
    const rows = (state.video.rows || []).filter((node) => node._kind !== "loading" && (!isGrid || node._kind === "show"));
    if (!rows.length) return;
    const sel = state.video.tvSel || {};
    const index = rows.findIndex((node) => node._kind === sel.type && node.id === sel.id);
    const next = rows[Math.max(0, Math.min(rows.length - 1, index < 0 ? 0 : index + step))];
    const host = document.getElementById("video-list");
    if (isGrid) {
        openShow(next.id);
        if (typeof vgridReveal === "function") vgridReveal(host, next.id);
        const card = host && host.querySelector(`.vgrid-card[data-id="${CSS.escape(next.id)}"]`);
        if (card) card.scrollIntoView({ block: "nearest" });
        return;
    }
    const head = host.querySelector(".vm-head");
    scrollRowIntoView(host, state.video.rows.indexOf(next), head ? head.offsetHeight : 0);
    if (next._kind === "show") openShow(next.id);
    else if (next._kind === "season") openSeason(next.id, next._showId);
    else openEpisode(next.id);
}

function expandTvSelection(open) {
    const sel = state.video.tvSel;
    if (!sel || (sel.type !== "show" && sel.type !== "season")) return;
    const key = `${sel.type}:${sel.id}`;
    if (open !== state.video.expanded.has(key)) toggleTvNode(key);
}

async function expandAllVideoRows() {
    if (state.media === "movies") {
        const rows = visibleMovies();
        if (!state.video.openVersions) state.video.openVersions = new Set();
        rows.forEach((row) => {
            if (row._versions && row._versionKey) state.video.openVersions.add(row._versionKey);
        });
        const list = document.getElementById("video-list");
        const scroll = list ? list.scrollTop : 0;
        renderMovieMatrix();
        if (list) {
            list.scrollTop = scroll;
            paintMovieRows();
        }
        return;
    }
    if (state.media !== "tv") return;
    const shows = state.video.shows || [];
    if (!shows.length) return;
    const match = textMatcher(state.video.filter.tv);
    const visibleShows = shows.filter((show) => !match || match(showHaystack(show)));
    const missing = visibleShows.filter((show) => !state.video.showDetails.has(show.id));
    visibleShows.forEach((show) => state.video.expanded.add(`show:${show.id}`));
    renderTvTree();
    const concurrency = 6;
    for (let i = 0; i < missing.length; i += concurrency) {
        const batch = missing.slice(i, i + concurrency);
        await Promise.all(batch.map((show) => showDetail(show.id).catch(() => null)));
    }
    visibleShows.forEach((show) => {
        state.video.expanded.add(`show:${show.id}`);
        const detail = state.video.showDetails.get(show.id);
        (detail && detail.seasons || []).forEach((season) => {
            state.video.expanded.add(`season:${season.id}`);
        });
    });
    renderTvTree();
}

function collapseAllVideoRows() {
    if (state.media === "movies") {
        if (state.video.openVersions) state.video.openVersions.clear();
        const list = document.getElementById("video-list");
        const scroll = list ? list.scrollTop : 0;
        renderMovieMatrix();
        if (list) {
            list.scrollTop = scroll;
            paintMovieRows();
        }
        return;
    }
    if (state.media !== "tv") return;
    state.video.expanded.clear();
    renderTvTree();
}
