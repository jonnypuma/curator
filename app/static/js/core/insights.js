// Library analytics (pure-CSS donuts and bars, an SVG line of scans over time) and list export.

const INSIGHT_COLORS = 10;
const INSIGHT_RANGES = [["week", "This week"], ["month", "This month"], ["year", "This year"], ["all", "All time"]];
const INSIGHT_SERIES = [["music", "Music"], ["movies", "Movies"], ["tv", "TV"]];

state.insights = { media: "all", root: "", range: "month", data: null, scans: null };

function insightPercent(count, total) {
    return total ? `${((count / total) * 100).toFixed(count / total < 0.1 ? 1 : 0)}%` : "0%";
}

function donutHtml(title, items, noun) {
    const total = items.reduce((sum, item) => sum + item.count, 0);
    if (!total) return `<div class="ins-card"><h3>${escapeHtml(title)}</h3><p class="muted">Nothing yet.</p></div>`;
    let at = 0;
    const stops = items.map((item, index) => {
        const from = (at / total) * 100;
        at += item.count;
        return `var(--ins-${index % INSIGHT_COLORS}) ${from.toFixed(3)}% ${((at / total) * 100).toFixed(3)}%`;
    }).join(", ");
    return `<div class="ins-card"><h3>${escapeHtml(title)}</h3>
        <div class="ins-donut-wrap">
            <div class="ins-donut" style="background:conic-gradient(${stops})" role="img" aria-label="${escapeHtml(title)}">
                <span><strong>${total.toLocaleString()}</strong><small>${escapeHtml(noun || "files")}</small></span>
            </div>
            <ul class="ins-legend">${items.map((item, index) => `<li>
                <i style="background:var(--ins-${index % INSIGHT_COLORS})"></i>
                <span>${escapeHtml(item.label)}</span>
                <b>${item.count.toLocaleString()}</b><small>${insightPercent(item.count, total)}</small>
            </li>`).join("")}</ul>
        </div></div>`;
}

function barsHtml(title, items, value, label) {
    const max = Math.max(0, ...items.map(value));
    if (!max) return `<div class="ins-card"><h3>${escapeHtml(title)}</h3><p class="muted">Nothing yet.</p></div>`;
    return `<div class="ins-card ins-wide"><h3>${escapeHtml(title)}</h3><div class="ins-bars">${items.map((item, index) => `
        <div class="ins-bar-row" title="${escapeHtml(item.label)}">
            <span class="ins-bar-label">${escapeHtml(item.label)}</span>
            <span class="ins-bar-track"><span class="ins-bar" style="width:${((value(item) / max) * 100).toFixed(2)}%;background:var(--ins-${index % INSIGHT_COLORS})"></span></span>
            <span class="ins-bar-value">${escapeHtml(label(item))}</span>
        </div>`).join("")}</div></div>`;
}

function scanLabel(label, unit) {
    if (unit === "day") {
        const day = new Date(`${label}T00:00:00`);
        return day.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    }
    const [year, month] = label.split("-").map(Number);
    return new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

function scanLineHtml(scans, title, rangesOn) {
    const heading = title || "Scans over time";
    const ranges = rangesOn === false ? "" : INSIGHT_RANGES.map(([key, text]) => `<button type="button" class="vribbon${state.insights.range === key ? " is-on" : ""}" data-action="insights-range" data-range="${key}" aria-pressed="${state.insights.range === key}">${text}</button>`).join("");
    const head = `<div class="ins-line-head"><h3>${escapeHtml(heading)}</h3>${ranges ? `<span class="ins-ranges">${ranges}</span>` : ""}</div>`;
    if (!scans) return `<div class="ins-card ins-wide">${head}<p class="muted">Loading…</p></div>`;
    const labels = scans.labels || [];
    const width = 640;
    const height = 180;
    const pad = { left: 30, right: 10, top: 10, bottom: 24 };
    const max = Math.max(1, ...INSIGHT_SERIES.flatMap(([key]) => scans.series[key] || []));
    const x = (index) => pad.left + (labels.length > 1 ? (index / (labels.length - 1)) * (width - pad.left - pad.right) : (width - pad.left - pad.right) / 2);
    const y = (count) => pad.top + (1 - count / max) * (height - pad.top - pad.bottom);
    const grid = [0, 0.5, 1].map((part) => {
        const value = Math.round(max * part);
        return `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(value)}" y2="${y(value)}" class="ins-gridline"/><text x="${pad.left - 6}" y="${y(value) + 4}" text-anchor="end">${value}</text>`;
    }).join("");
    const step = Math.max(1, Math.ceil(labels.length / 8));
    const chosen = [];
    labels.forEach((label, index) => {
        if (index % step !== 0 && index !== labels.length - 1) return;
        const at = x(index);
        if (chosen.length && at - chosen[chosen.length - 1].at < 72) {
            if (index !== labels.length - 1) return;
            chosen.pop();
        }
        chosen.push({ label, at });
    });
    const ticks = chosen.map((tick, order) => {
        const anchor = order === 0 ? "start" : order === chosen.length - 1 ? "end" : "middle";
        return `<text x="${tick.at}" y="${height - 6}" text-anchor="${anchor}">${escapeHtml(scanLabel(tick.label, scans.unit))}</text>`;
    }).join("");
    const lines = INSIGHT_SERIES.map(([key], index) => {
        const values = scans.series[key] || [];
        if (!values.some(Boolean)) return "";
        const points = values.map((count, at) => `${x(at).toFixed(1)},${y(count).toFixed(1)}`).join(" ");
        const dots = values.map((count, at) => count ? `<circle cx="${x(at).toFixed(1)}" cy="${y(count).toFixed(1)}" r="3"><title>${escapeHtml(scanLabel(labels[at], scans.unit))}: ${count}</title></circle>` : "").join("");
        return `<g class="ins-series" style="--line:var(--ins-${index})"><polyline points="${points}"/>${dots}</g>`;
    }).join("");
    const legend = INSIGHT_SERIES.map(([key, text], index) => {
        const count = (scans.series[key] || []).reduce((sum, value) => sum + value, 0);
        return `<li><i style="background:var(--ins-${index})"></i><span>${text}</span><b>${count}</b></li>`;
    }).join("");
    const body = scans.total
        ? `<svg class="ins-line" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(heading)}">${grid}${ticks}${lines}</svg>`
        : `<p class="muted">${heading === "Items added" ? "Nothing added in this period." : "No scans in this period."}</p>`;
    return `<div class="ins-card ins-wide">${head}${body}<ul class="ins-legend ins-legend-row">${legend}</ul></div>`;
}

function artworkHtml(art, coverage) {
    if (!art) return "";
    const count = Number(art.count) || 0;
    const pending = art.size_bytes == null;
    const size = pending ? "counting sizes…" : (fmtSize(art.size_bytes) || "0 B");
    const items = art.media || [];
    const types = art.types || [];
    const missing = (coverage && coverage.missing_art) || [];
    const charts = [];
    if (count && !pending) {
        charts.push(`<div class="ins-grid">
            ${barsHtml("Artwork size", items, (item) => item.size_bytes, (item) => fmtSize(item.size_bytes) || "0 B")}
            ${barsHtml("Artwork files", items, (item) => item.count, (item) => item.count.toLocaleString())}
        </div>`);
    } else if (count) {
        charts.push(`<div class="ins-grid">${barsHtml("Artwork files", items, (item) => item.count, (item) => item.count.toLocaleString())}</div>`);
    }
    const breakdown = [];
    if (types.length) {
        if (!pending) breakdown.push(barsHtml("Artwork size by type", types, (item) => item.size_bytes, (item) => fmtSize(item.size_bytes) || "0 B"));
        breakdown.push(barsHtml("Artwork by type", types, (item) => item.count, (item) => item.count.toLocaleString()));
    }
    if (missing.length) {
        breakdown.push(barsHtml("Missing artwork", missing, (item) => item.missing, (item) => `${item.missing.toLocaleString()} of ${item.total.toLocaleString()}`));
    }
    if (breakdown.length) charts.push(`<div class="ins-grid">${breakdown.join("")}</div>`);
    const body = charts.length ? charts.join("") : `<p class="muted">No artwork files recorded yet.</p>`;
    return `<h3 class="ins-heading">Artwork · ${count.toLocaleString()} images · ${size}</h3>${body}`;
}

function tallySum(items) {
    return (items || []).reduce((sum, item) => sum + (Number(item.count) || 0), 0);
}

function tallyNote(items) {
    return (items || []).map((item) => `${(Number(item.count) || 0).toLocaleString()} ${String(item.label || "").toLowerCase()}`).join(" · ");
}

function coverageHtml(coverage) {
    if (!coverage) return "";
    const trailers = coverage.trailers || {};
    const subs = coverage.subtitles || {};
    const cards = [];
    if (trailers.files || trailers.missing || trailers.linked || trailers.files == null) {
        const counted = trailers.files == null;
        cards.push(statCard(
            "Trailers",
            counted ? "…" : (trailers.files || 0).toLocaleString(),
            counted
                ? `${(trailers.linked || 0).toLocaleString()} linked · counting files…`
                : `${(trailers.missing || 0).toLocaleString()} missing · ${fmtSize(trailers.size_bytes) || "0 B"} · ${(trailers.linked || 0).toLocaleString()} linked`,
        ));
    }
    if (subs.videos) {
        cards.push(statCard(
            "No subtitles",
            (subs.none || 0).toLocaleString(),
            `of ${(subs.videos || 0).toLocaleString()} videos · ${(subs.external_files || 0).toLocaleString()} files · ${subs.external_bytes == null ? "counting sizes…" : (fmtSize(subs.external_bytes) || "0 B")}`,
        ));
    }
    const probe = tallySum(coverage.probe_failed);
    const duplicates = tallySum(coverage.duplicates);
    const upgrades = tallySum(coverage.upgrades);
    if (probe) cards.push(statCard("Probe failed", probe.toLocaleString(), tallyNote(coverage.probe_failed)));
    if (duplicates) cards.push(statCard("Duplicates", duplicates.toLocaleString(), tallyNote(coverage.duplicates)));
    if (upgrades) cards.push(statCard("Upgrades available", upgrades.toLocaleString(), tallyNote(coverage.upgrades)));
    if (!cards.length) return "";
    return `<h3 class="ins-heading">Library health</h3><div class="ins-stats">${cards.join("")}</div>`;
}

function disksHtml(disks, pending) {
    const rows = disks || [];
    if (!rows.length) {
        const note = pending ? "Checking free space…" : "No library folders are configured.";
        return `<div class="ins-card ins-wide"><h3>Storage</h3><p class="muted">${note}</p></div>`;
    }
    return `<div class="ins-card ins-wide"><h3>Storage</h3><div class="ins-bars ins-disks">${rows.map((disk) => {
        const total = Number(disk.total) || 0;
        const used = Number(disk.used) || 0;
        const free = Number(disk.free) || 0;
        const pct = total ? Math.min(100, (used / total) * 100) : 0;
        const span = pct > 0 ? (100 / (pct / 100)).toFixed(2) : "100";
        const libraries = (disk.libraries || []).join(", ");
        const value = disk.mounted
            ? `${libraries ? `${libraries} · ` : ""}${fmtSize(used) || "0 B"} used · ${fmtSize(free) || "0 B"} free · ${fmtSize(total) || "0 B"}`
            : `${libraries ? `${libraries} · ` : ""}Not mounted`;
        return `<div class="ins-bar-row">
            <span class="ins-bar-label" title="${escapeHtml(disk.label)}">${escapeHtml(disk.label)}</span>
            <span class="ins-bar-track"><span class="ins-bar ins-disk" style="width:${pct.toFixed(2)}%;--disk-span:${span}%"></span></span>
            <span class="ins-bar-value">${escapeHtml(value)}</span>
        </div>`;
    }).join("")}</div></div>`;
}

function musicHtml(music) {
    if (!music) return "";
    const totals = music.totals || {};
    if (!totals.tracks) {
        if (state.insights.media !== "music" && state.insights.root) return "";
        return `<div class="ins-card ins-wide"><h3>Music</h3><p class="muted">No tracks here yet. Scan a music folder first.</p></div>`;
    }
    const hours = Math.round((totals.duration_seconds || 0) / 3600);
    return `<h3 class="ins-heading">Music · ${totals.artists.toLocaleString()} artists · ${totals.albums.toLocaleString()} albums · ${totals.tracks.toLocaleString()} tracks · ${fmtSize(totals.size_bytes) || "0 B"} · ${hours.toLocaleString()} hours</h3>
        <div class="ins-grid">
            ${donutHtml("Audio format", music.formats, "tracks")}
            ${donutHtml("Bit depth", music.depths, "tracks")}
            ${donutHtml("Sample rate", music.rates, "tracks")}
            ${donutHtml("Lyrics", music.lyrics, "tracks")}
            ${donutHtml("Album match", music.matches, "albums")}
            ${barsHtml("Genres", music.genres, (item) => item.count, (item) => item.count.toLocaleString())}
            ${barsHtml("Music by path", music.roots, (item) => item.size_bytes, (item) => `${item.count.toLocaleString()} · ${fmtSize(item.size_bytes)}`)}
        </div>`;
}

function statCard(label, value, note) {
    return `<div class="ins-stat"><span>${escapeHtml(label)}</span>${note ? `<small>${escapeHtml(note)}</small>` : ""}<strong>${escapeHtml(value)}</strong></div>`;
}

function ratioText(watched, total) {
    return `${(watched || 0).toLocaleString()} / ${(total || 0).toLocaleString()}`;
}

function videoCharts(block) {
    if (!(block.totals || {}).files) return "";
    return `${donutHtml("HDR format", block.formats)}
        ${donutHtml("Secondary HDR (Dolby Vision)", block.secondary)}
        ${donutHtml("Resolution", block.resolutions)}
        ${donutHtml("Video codec", block.codecs)}
        ${donutHtml("Container", block.containers || [])}
        ${barsHtml("By path", block.roots, (item) => item.count, (item) => `${item.count.toLocaleString()} · ${fmtSize(item.size_bytes)}`)}
        ${barsHtml("Main audio codec", block.audio, (item) => item.count, (item) => item.count.toLocaleString())}
        ${barsHtml("Source", block.sources, (item) => item.count, (item) => item.count.toLocaleString())}`;
}

function movieHtml(block) {
    if (!block) return "";
    const lib = block.library || {};
    const counts = `<div class="ins-stats">
        ${statCard("Movies", ratioText(lib.watched, lib.total), `Watched / Total · ${watchedHours(lib.watched_seconds)}`)}
    </div>`;
    const stats = `<h3 class="ins-heading">Movie Stats</h3><div class="ins-stats">
        ${statCard("Size on disk", fmtSize(lib.size_bytes) || "0 B")}
        ${statCard("Average size per movie", fmtSize(lib.average_bytes) || "0 B")}
    </div>`;
    const charts = (block.totals || {}).files
        ? `<div class="ins-grid">${videoCharts(block)}</div>`
        : `<p class="muted">No movie files here yet. Scan a Movies folder first.</p>`;
    return `<h3 class="ins-heading">Movies</h3>${counts}${stats}${charts}`;
}

function tvHtml(block) {
    if (!block) return "";
    const lib = block.library || {};
    const counts = `<div class="ins-stats">
        ${statCard("Shows", ratioText(lib.series_watched, lib.series_total), "Watched / Total")}
        ${statCard("By status", `${(lib.continuing || 0).toLocaleString()} | ${(lib.ended || 0).toLocaleString()}`, "Continuing | Ended/Cancelled")}
        ${statCard("Seasons", `${(lib.seasons_watched || 0).toLocaleString()} | ${(lib.seasons_total || 0).toLocaleString()}`, "Watched | Total")}
        ${statCard("Episodes", `${(lib.episodes_watched || 0).toLocaleString()} | ${(lib.episodes_missing || 0).toLocaleString()} | ${(lib.episodes_total || 0).toLocaleString()}`, `Watched | Missing | Total · ${watchedHours(lib.watched_seconds)}`)}
    </div>`;
    const stats = `<h3 class="ins-heading">TV Stats</h3><div class="ins-stats">
        ${statCard("Size on disk", fmtSize(lib.size_bytes) || "0 B")}
        ${statCard("Average size per episode", fmtSize(lib.average_bytes) || "0 B")}
    </div>`;
    const charts = (block.totals || {}).files
        ? `<div class="ins-grid">${videoCharts(block)}</div>`
        : `<p class="muted">No episode files here yet. Scan a TV folder first.</p>`;
    return `<h3 class="ins-heading">TV shows</h3>${counts}${stats}${charts}`;
}

function fmtRam(bytes) {
    const gb = Number(bytes) / 1e9;
    if (!Number.isFinite(gb) || gb <= 0) return "";
    return `${gb.toFixed(gb < 10 ? 1 : 2)} GB`;
}

function insightsRamText() {
    const memory = state.system && state.system.memory;
    if (!memory) return "";
    const used = fmtRam(memory.app_bytes);
    const free = fmtRam(memory.available_bytes);
    if (used && free) return ` · RAM: ${used} / ${free}`;
    if (used) return ` · RAM: ${used}`;
    if (free) return ` · RAM: ${free} free`;
    return "";
}

function insightsTotalsText(data) {
    if (data.media === "music") {
        const totals = data.totals || {};
        const hours = Math.round((totals.duration_seconds || 0) / 3600);
        return `${(totals.artists || 0).toLocaleString()} artists · ${(totals.albums || 0).toLocaleString()} albums · ${(totals.tracks || 0).toLocaleString()} tracks · ${fmtSize(totals.size_bytes || 0) || "0 B"} · ${hours.toLocaleString()} hours${insightsDbText(data)}${insightsRamText()}`;
    }
    const parts = [];
    const movies = data.movies && data.movies.library;
    const tv = data.tv && data.tv.library;
    if (movies) parts.push(`${(movies.total || 0).toLocaleString()} movies`);
    if (tv) {
        parts.push(`${(tv.series_total || 0).toLocaleString()} shows`);
        parts.push(`${(tv.seasons_total || 0).toLocaleString()} seasons`);
        parts.push(`${(tv.episodes_total || 0).toLocaleString()} episodes`);
    }
    let size = 0;
    let duration = 0;
    [data.movies, data.tv].forEach((block) => {
        if (!block) return;
        size += Number((block.library && block.library.size_bytes) || 0);
        duration += Number((block.totals && block.totals.duration_seconds) || 0);
    });
    const music = data.music && data.music.totals;
    if (music && music.tracks) parts.push(`${music.tracks.toLocaleString()} tracks`);
    parts.push(fmtSize(size) || "0 B");
    parts.push(`${Math.round(duration / 3600).toLocaleString()} video hours`);
    if (music) parts.push(`${Math.round((Number(music.duration_seconds) || 0) / 3600).toLocaleString()} audio hours`);
    return `${parts.join(" · ")}${insightsDbText(data)}${insightsRamText()}`;
}

function watchedHours(seconds) {
    return `${Math.round((Number(seconds) || 0) / 3600).toLocaleString()} h watched`;
}

function insightsDbText(data) {
    const bytes = Number(data && data.database_bytes) || 0;
    if (!bytes) return "";
    return ` · DB: ${fmtSize(bytes) || "0 B"}`;
}

function refreshInsightsMemory() {
    const modal = document.getElementById("insights-modal");
    const data = state.insights && state.insights.data;
    if (!modal || modal.classList.contains("hidden") || !data) return;
    const totals = document.getElementById("insights-totals");
    if (totals) totals.textContent = insightsTotalsText(data);
}

function renderInsights() {
    const body = document.getElementById("insights-body");
    const data = state.insights.data;
    const rootSelect = document.getElementById("insights-root");
    const roots = state.insights.media === "movies" ? (state.moviePaths || [])
        : state.insights.media === "tv" ? (state.tvPaths || [])
            : state.insights.media === "music" ? (state.musicPaths || [])
                : (state.musicPaths || []).concat(state.moviePaths || [], state.tvPaths || []);
    rootSelect.innerHTML = `<option value="">All paths</option>${roots.map((root) => `<option value="${escapeHtml(root)}" ${root === state.insights.root ? "selected" : ""}>${escapeHtml(root)}</option>`).join("")}`;
    document.getElementById("insights-media").value = state.insights.media;
    if (!data) {
        body.innerHTML = `<p class="muted">Loading…</p>`;
        return;
    }
    const totals = document.getElementById("insights-totals");
    totals.textContent = insightsTotalsText(data);
    const musicOnly = data.media === "music";
    const pending = data.filesystem_error
        ? `<p class="muted">File sizes could not be counted. The charts below are from the library database.</p>`
        : data.filesystem_pending ? `<p class="muted">Checking files on the library folders…</p>` : "";
    body.innerHTML = `${pending}${artworkHtml(data.artwork, data.coverage)}${coverageHtml(data.coverage)}${disksHtml(data.disks, data.filesystem_pending)}${musicOnly ? musicHtml(data) : `${musicHtml(data.music)}${movieHtml(data.movies)}${tvHtml(data.tv)}`}
        ${scanLineHtml(state.insights.scans)}
        ${scanLineHtml(state.insights.scans && state.insights.scans.added, "Items added", false)}`;
}

async function loadInsights() {
    const ticket = (state.insights.ticket = (state.insights.ticket || 0) + 1);
    const { media, root } = state.insights;
    state.insights.data = null;
    renderInsights();
    const query = new URLSearchParams({ media, root });
    const [data, scans] = await Promise.all([
        api(`/api/v1/analytics?${query}`),
        api(`/api/v1/analytics/scans?range=${state.insights.range}`),
    ]);
    if (state.insights.ticket !== ticket) return;
    state.insights.data = data;
    state.insights.scans = scans;
    renderInsights();
    if (data.filesystem_pending) pollInsightFiles(ticket);
}

async function pollInsightFiles(ticket) {
    const modal = document.getElementById("insights-modal");
    for (let attempt = 0; attempt < 45; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        if (state.insights.ticket !== ticket || !modal || modal.classList.contains("hidden")) return;
        const { media, root } = state.insights;
        const query = new URLSearchParams({ media, root });
        try {
            const data = await api(`/api/v1/analytics?${query}`);
            if (state.insights.ticket !== ticket) return;
            state.insights.data = data;
            renderInsights();
            if (!data.filesystem_pending) return;
        } catch (error) {
            if (state.insights.ticket !== ticket) return;
            notify((error && error.message) || "Library analytics could not finish counting files.", "warning");
            return;
        }
    }
}

async function loadInsightScans(range) {
    state.insights.range = range;
    state.insights.scans = null;
    renderInsights();
    state.insights.scans = await api(`/api/v1/analytics/scans?range=${range}`);
    renderInsights();
}

function openInsights() {
    state.insights.media = state.media === "music" ? "music" : state.media === "movies" || state.media === "sets" ? "movies" : state.media === "tv" ? "tv" : "all";
    state.insights.root = "";
    document.getElementById("insights-totals").textContent = "";
    document.getElementById("insights-modal").classList.remove("hidden");
    return loadInsights();
}

function bindInsights() {
    const media = document.getElementById("insights-media");
    const root = document.getElementById("insights-root");
    if (!media || !root) return;
    media.addEventListener("change", () => {
        state.insights.media = media.value;
        state.insights.root = "";
        runAction(loadInsights);
    });
    root.addEventListener("change", () => {
        state.insights.root = root.value;
        runAction(loadInsights);
    });
}

// Export of the shown list.

function exportIds(media) {
    if (media === "movies") return visibleMovies().map((movie) => movie.id);
    if (media === "sets") return visibleSets().map((set) => set.id);
    if (media === "music") {
        const artists = typeof pendingArtists === "function" && typeof orderedArtists === "function"
            ? pendingArtists(orderedArtists(state.artists || []))
            : (state.artists || []);
        return artists.flatMap((artist) => (artist.albums || []).map((album) => album.id));
    }
    return tvNodes().filter((node) => node.type === "show").map((node) => node.id);
}

async function exportVideoList() {
    const media = state.media === "tv" ? "tv" : state.media === "sets" ? "sets" : state.media === "music" ? "music" : "movies";
    const ids = exportIds(media);
    if (!ids.length) {
        notify("Nothing to export. Clear the filter or the ribbons first.", "warning");
        return;
    }
    const root = (media === "movies" || media === "tv") ? (state.videoScanRoots[media] || "") : "";
    const exportKey = media === "music" ? "export_format_music" : "export_format";
    const format = videoCfg()[exportKey] === "xml" ? "xml" : "csv";
    const response = await fetch("/api/v1/export", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ media, ids, format, roots: root ? [root] : [] }),
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || response.statusText);
    }
    const blob = await response.blob();
    const match = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = match ? match[1] : `curator-${media}.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    const count = Number(response.headers.get("X-Export-Count")) || 0;
    const noun = { tv: "episode", sets: "set", music: "album", movies: "movie" }[media] || "item";
    notify(`Exported ${count.toLocaleString()} ${noun}${count === 1 ? "" : "s"} as ${format.toUpperCase()}${root ? ` from ${root}` : ""}.`, "info");
}

function onInsightsAction(name, action) {
    if (name === "insights-open") return runAction(openInsights, "Counting…");
    if (name === "insights-range") return runAction(() => loadInsightScans(action.dataset.range));
    if (name === "insights-export") return runAction(exportVideoList, "Exporting…");
    return false;
}
