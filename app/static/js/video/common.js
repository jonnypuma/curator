function libraryRibbonKey() {
    if (state.media === "tv" || state.media === "sets") return state.media;
    return "movies";
}

function libraryRibbons() {
    const video = state.video || (state.video = {});
    const stored = video.ribbons;
    if (!stored || stored instanceof Set) {
        const carried = stored instanceof Set ? [...stored] : [];
        video.ribbons = {
            movies: new Set(libraryRibbonKey() === "movies" ? carried : []),
            sets: new Set(libraryRibbonKey() === "sets" ? carried : []),
            tv: new Set(libraryRibbonKey() === "tv" ? carried : []),
        };
    }
    const key = libraryRibbonKey();
    if (!(video.ribbons[key] instanceof Set)) video.ribbons[key] = new Set(video.ribbons[key] || []);
    return video.ribbons[key];
}

const VIDEO_ROW = 34;
const VIDEO_OVERSCAN = 12;

const artVersions = new Map();

function noteArtVersion(path) {
    if (path) artVersions.set(path, Date.now());
}

function infoBanner(urls, actions) {
    const banner = (urls && urls.banner) || "";
    const landscape = (urls && urls.landscape) || "";
    const logo = (urls && urls.clearlogo) || "";
    let art = "";
    if (banner) {
        art = `<img class="backdrop is-banner" alt="" src="${escapeHtml(banner)}" data-step="banner" onerror="infoBannerFallback(this)">`;
    } else if (landscape) {
        art = `<img class="backdrop is-banner" alt="" src="${escapeHtml(landscape)}" data-step="landscape" onerror="infoBannerFallback(this)">`;
        if (logo) {
            art += `<img class="clearlogo" alt="" src="${escapeHtml(logo)}" onerror="this.remove()">`;
        }
    } else if (logo) {
        art = `<img class="clearlogo" alt="" src="${escapeHtml(logo)}" onerror="this.remove()">`;
    }
    return `<div class="info-banner" data-landscape="${escapeHtml(landscape)}" data-logo="${escapeHtml(logo)}">${art}<div class="hero-actions">${actions || ""}</div></div>`;
}

function infoBannerFallback(image) {
    const hero = image.closest(".info-banner");
    if (!hero) {
        image.remove();
        return;
    }
    const landscape = hero.dataset.landscape || "";
    const logo = hero.dataset.logo || "";
    if (image.dataset.step === "banner" && landscape) {
        image.dataset.step = "landscape";
        image.src = landscape;
        if (logo && !hero.querySelector(".clearlogo")) {
            const logoEl = document.createElement("img");
            logoEl.className = "clearlogo";
            logoEl.alt = "";
            logoEl.src = logo;
            logoEl.onerror = () => logoEl.remove();
            hero.appendChild(logoEl);
        }
        return;
    }
    if (logo && !hero.querySelector(".clearlogo")) {
        image.outerHTML = `<img class="clearlogo" alt="" src="${escapeHtml(logo)}" onerror="this.remove()">`;
        return;
    }
    image.remove();
}

function infoFanart(url) {
    if (!url) return "";
    const safe = String(url).replace(/\\/g, "\\\\").replace(/'/g, "%27");
    return `<div class="info-fanart" style="background-image:url('${safe}')"></div>`;
}

function artUrl(path, width) {
    if (!path) return "";
    const params = new URLSearchParams({ path });
    if (width) params.set("w", String(width));
    const version = artVersions.get(path);
    if (version) params.set("v", String(version));
    return `/api/v1/artwork?${params}`;
}

function pathMount(path) {
    const value = String(path || "");
    const roots = []
        .concat(state.mounts || [])
        .map((item) => (item && item.path) || "")
        .concat(state.musicPaths || [], state.moviePaths || [], state.tvPaths || [])
        .filter(Boolean);
    let best = "";
    roots.forEach((root) => {
        const base = String(root).replace(/\/+$/, "");
        if ((value === base || value.startsWith(`${base}/`)) && base.length > best.length) best = base;
    });
    return best;
}

function splitMount(path) {
    const value = String(path || "");
    const mount = pathMount(value);
    if (!mount) return { mount: "", rest: value };
    return { mount, rest: value.slice(mount.length).replace(/^\//, "") };
}

function shownPath(item, key) {
    if (!item) return "";
    if (isWanted(item) && (!key || key === "path" || key === "folder")) return "";
    if (String(item.path || "").indexOf("missing://") === 0 && (!key || key === "path")) return "";
    if (key === "file") {
        const file = item.file || {};
        return file.display_path || file.path || "";
    }
    const field = key || "path";
    const display = field === "path" ? "display_path" : `display_${field}`;
    return item[display] || item[field] || "";
}

function filePathBlock(path) {
    if (!path) return "";
    const parts = splitMount(path);
    const mount = parts.mount ? `<p class="mono vpath"><span class="muted">Mount</span> ${escapeHtml(parts.mount)}</p>` : "";
    return `<div class="vfilepath"><h3>Filepath</h3>${mount}<p class="mono vpath">${escapeHtml(path)}</p></div>`;
}

function fmtRuntime(minutes) {
    const value = Number(minutes) || 0;
    if (!value) return "";
    const hours = Math.floor(value / 60);
    return hours ? `${hours}h ${String(value % 60).padStart(2, "0")}m` : `${value}m`;
}

function fmtDuration(seconds) {
    const value = Number(seconds) || 0;
    if (!value) return "";
    const h = Math.floor(value / 3600);
    const m = Math.floor((value % 3600) / 60);
    const s = value % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

function fmtSize(bytes) {
    const value = Number(bytes) || 0;
    if (!value) return "";
    if (value >= 1e12) return `${(value / 1e12).toFixed(2)} TB`;
    if (value >= 1e9) return `${(value / 1e9).toFixed(2)} GB`;
    return `${Math.round(value / 1e6)} MB`;
}

function fmtDate(value) {
    if (!value) return "";
    const number = Number(value);
    if (number > 1e9 && number < 1e12) return new Date(number * 1000).toISOString().slice(0, 10);
    const text = String(value);
    return text.length >= 10 ? text.slice(0, 10) : text;
}

function titleFacts(row) {
    if (!row || row._kind === "loading" || row._kind === "missing" || row._version) return "";
    const kind = row._kind || "movie";
    const cfg = typeof videoCfg === "function" ? videoCfg() : {};
    const bits = [];
    if (kind === "show") {
        if (cfg.ui_tv_seasons !== false) {
            const count = Number(row.season_count) || 0;
            const title = count === 1 ? "1 season" : `${count} seasons`;
            bits.push(`<span class="album-count" title="${escapeHtml(title)}">${count}</span>`);
        }
    } else if (kind === "season") {
        if (cfg.ui_tv_episodes !== false) {
            const count = Number(row.episode_count) || 0;
            const title = count === 1 ? "1 episode" : `${count} episodes`;
            bits.push(`<span class="album-count" title="${escapeHtml(title)}">${count}</span>`);
        }
    }
    const showDate = kind === "movie" ? (cfg.ui_movie_date_added !== false) : (cfg.ui_tv_date_added !== false);
    const added = fmtDate(row.date_added || row.created_at);
    if (showDate && added && (kind === "show" || kind === "season" || kind === "episode" || kind === "movie")) {
        bits.push(`<span class="added-date" title="Added to the library">${escapeHtml(added)}</span>`);
    }
    const showProcessed = kind === "movie" ? (cfg.ui_movie_processed !== false) : kind === "set" ? (cfg.ui_set_processed !== false) : (cfg.ui_tv_processed !== false);
    if (showProcessed && (kind === "show" || kind === "season" || kind === "movie" || kind === "set")) {
        bits.push(row.status === "PROCESSED"
            ? `<span class="process-mark ok" title="Processed">✓</span>`
            : `<span class="process-mark bad" title="Not processed">✕</span>`);
    }
    const noMatch = (kind === "movie" || kind === "show") && !row.tmdb_id && !row.imdb_id && !row.tvdb_id;
    if (noMatch) bits.push(`<span class="process-mark unmatched" title="Not matched to any database">⚠️</span>`);
    return bits.length ? `<span class="vl-facts">${bits.join("")}</span>` : "";
}

function mediaBadge(file, title, pane) {
    const src = String(file).split("/").map((part) => encodeURIComponent(part)).join("/");
    return `<img class="vbadge${pane ? " vbadge-pane" : ""}" src="/media/${src}" alt="" title="${escapeHtml(title || "")}">`;
}

function toneBadge(text, cls) {
    if (!text) return "";
    return `<span class="vhdr ${cls}">${escapeHtml(text)}</span>`;
}

function resolutionBadge(value) {
    const file = { "8K": "8k.png", "4K": "4k.png", "1080p": "1080p.png", "720p": "720p.png", SD: "SD.png" }[value];
    return file ? mediaBadge(`resolution/${file}`, value, true) : (value ? escapeHtml(value) : "");
}

function resolutionText(value) {
    const cls = { "8K": "badge-8k", "4K": "badge-4k", "1080p": "badge-1080", "720p": "badge-720", SD: "badge-sd" }[value] || "badge-sdr";
    return value ? toneBadge(value, cls) : "";
}

function aspectText(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (text.includes(":")) return toneBadge(text, "badge-aspect");
    const number = Number(text);
    const label = Number.isFinite(number) && number > 0 ? `${number.toFixed(2)}:1` : text;
    return toneBadge(label, "badge-aspect");
}

function videoCodecFile(value) {
    const key = String(value || "").toLowerCase();
    if (key.includes("hevc") || key.includes("h265") || key.includes("h.265")) return "hevc.png";
    if (key.includes("264") || key.includes("avc")) return "h264.png";
    if (key.includes("av1")) return "av1.png";
    if (key.includes("vp9")) return "vp9.png";
    if (key.includes("mpeg2") || key.includes("mpeg-2")) return "mpeg2.png";
    if (key.includes("vc-1") || key === "vc1") return "vc1.png";
    return "";
}

function videoCodecClass(value) {
    const key = String(value || "").toLowerCase();
    if (key.includes("hevc") || key.includes("265")) return "badge-hevc";
    if (key.includes("264") || key.includes("avc")) return "badge-h264";
    if (key.includes("av1")) return "badge-av1";
    if (key.includes("vp9")) return "badge-vp9";
    if (key.includes("mpeg2") || key.includes("mpeg-2")) return "badge-mpeg2";
    if (key.includes("vc-1") || key === "vc1") return "badge-vc1";
    return "badge-sdr";
}

function videoCodecBadge(value) {
    const text = String(value || "");
    const file = videoCodecFile(text);
    return file ? mediaBadge(`videocodec/${file}`, text, true) : escapeHtml(text);
}

function videoCodecText(value) {
    return value ? toneBadge(value, videoCodecClass(value)) : "";
}

function audioCodecBadge(value) {
    const key = String(value || "").toLowerCase();
    if (!key) return "";
    const pairs = [
        ["truehd atmos", "dolby_atmos.svg"], ["atmos", "dolby_atmos.svg"], ["dts:x", "dts_x.jpg"], ["dts-x", "dts_x.jpg"],
        ["dts-hd ma", "dtshd_ma.png"], ["dts-hd hra", "dtshd_hra.png"], ["dts-hd", "dts-hd.png"],
        ["truehd", "dolbytruehd.png"], ["e-ac-3", "eac3.png"], ["eac3", "eac3.png"], ["ac-3", "dolbydigital.png"],
        ["ac3", "dolbydigital.png"], ["aac", "AAC_original.png"], ["flac", "flac_white.png"], ["opus", "opus.png"],
        ["vorbis", "vorbis.png"], ["mp3", "mp3.jpg"], ["pcm", "pcm.png"], ["dts", "dts.png"],
    ];
    const found = pairs.find(([name]) => key.includes(name));
    return found ? mediaBadge(`audiocodec/${found[1]}`, value, true) : escapeHtml(value);
}

function audioCodecClass(value) {
    const key = String(value || "").toLowerCase();
    if (key.includes("atmos") || key.includes("truehd")) return "badge-atmos";
    if (key.includes("dts")) return "badge-dts";
    if (key.includes("ac-3") || key.includes("ac3") || key.includes("eac3") || key.includes("e-ac")) return "badge-dd";
    if (key.includes("flac") || key.includes("pcm")) return "badge-lossless";
    return "badge-audio";
}

function audioCodecText(value) {
    return value ? toneBadge(value, audioCodecClass(value)) : "";
}

function channelBadge(value) {
    const text = String(value || "");
    const match = text.match(/^(\d+)\.(\d+)/);
    const count = match ? Number(match[1]) + Number(match[2]) : (/^\d+$/.test(text) ? Number(text) : 0);
    const known = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10];
    return known.includes(count) && text ? mediaBadge(`audiochannels/${count}.png`, text, true) : escapeHtml(text);
}

function channelText(value) {
    return value ? toneBadge(value, "badge-channels") : "";
}

function sourceClass(value) {
    const key = String(value || "").toLowerCase();
    if (key.includes("uhd")) return "badge-uhd";
    if (key.includes("bd-rip") || key.includes("bdrip") || key.includes("brrip")) return "badge-bdrip";
    if (key.includes("bluray") || key.includes("blu-ray")) return "badge-bluray";
    if (key.includes("hd") && key.includes("dvd")) return "badge-hddvd";
    if (key.includes("dvd")) return "badge-dvd";
    if (key.includes("web-dl") || key.includes("webdl")) return "badge-webdl";
    if (key.includes("web")) return "badge-webrip";
    if (key.includes("hdtv")) return "badge-hdtv";
    return "badge-sdr";
}

function sourceText(value) {
    return value ? toneBadge(value, sourceClass(value)) : "";
}

const RATING_SOURCES = [
    ["themoviedb", "tmdb.png", "TMDB"],
    ["tmdb", "tmdb.png", "TMDB"],
    ["imdb", "imdb.png", "IMDb"],
    ["tomatometerallcritics", "rottentomatoes.png", "Tomatometer"],
    ["tomatometeravgcritics", "rottentomatoes.png", "Tomatometer average"],
    ["tomatometer", "rottentomatoes.png", "Tomatometer"],
    ["rottentomatoes", "rottentomatoes.png", "Rotten Tomatoes"],
    ["tomatometerallaudience", "rottentomatoes_audience.png", "RT audience"],
    ["tomatometeravguseraudience", "rottentomatoes_audience.png", "RT audience"],
    ["tomatometeravgaudience", "rottentomatoes_audience.png", "RT audience average"],
    ["metacritic", "metacritic.png", "Metascore"],
    ["metacriticuser", "metacritic.png", "Metacritic user"],
    ["trakt", "trakt.png", "Trakt"],
    ["anilist", "", "AniList"],
    ["ofdb", "", "OFDb"],
    ["tvdb", "tvdb.png", "TheTVDB"],
    ["thetvdb", "tvdb.png", "TheTVDB"],
    ["tvmaze", "tvmaze.png", "TVMaze"],
];

function rottenTomatoesMark(key) {
    const name = String(key || "").toLowerCase();
    const audience = name.includes("audience") || name.includes("popcorn");
    const tomato = name.includes("tomato") || name.includes("rotten") || name.includes("tomatometer");
    if (!tomato && !audience) return null;
    if (audience) {
        const label = name.includes("avg") ? "RT audience average" : "RT audience";
        return ["rottentomatoes_audience.png", label];
    }
    const label = name.includes("avg") ? "Tomatometer average" : "Tomatometer";
    return ["rottentomatoes.png", label];
}

function brandMark(icons) {
    const items = (icons || []).filter((item) => item && item.src);
    if (!items.length) return "";
    const marks = items.map((item) => {
        const name = item.name || "";
        return `<img src="${escapeHtml(item.src)}" alt="${escapeHtml(name)}" title="${escapeHtml(name)}">`;
    }).join("");
    return `<div class="vbrand">${marks}</div>`;
}

function brandRow(copy, icons) {
    const mark = brandMark(icons);
    if (!mark) return copy;
    return `<div class="vbrand-row"><div class="vbrand-copy">${copy}</div>${mark}</div>`;
}

function ratingPage(key, item) {
    const ids = { ...((item && item.ids) || {}) };
    if (item && item.imdb_id) ids.imdb = item.imdb_id;
    if (item && item.tmdb_id) ids.tmdb = item.tmdb_id;
    if (item && item.tvdb_id) ids.tvdb = item.tvdb_id;
    if (item && item.trakt_id) ids.trakt = item.trakt_id;
    if (item && item.show_imdb_id && !ids.imdb) ids.imdb = item.show_imdb_id;
    if (item && item.show_tmdb_id && !ids.tmdb) ids.tmdb = item.show_tmdb_id;
    if (item && item.show_tvdb_id && !ids.tvdb) ids.tvdb = item.show_tvdb_id;
    if (item && item.show_trakt_id && !ids.trakt) ids.trakt = item.show_trakt_id;
    const tv = !!(item && (item.show_title || item.show_status !== undefined || item.show_tmdb_id || item.tvdb_id));
    const title = (item && (item.show_title || item.title)) || "";
    const dashed = siteSlug(title, "-");
    const underscored = siteSlug(title, "_");
    const lower = String(key || "").toLowerCase();
    if (lower === "imdb" && ids.imdb) return `https://www.imdb.com/title/${encodeURIComponent(ids.imdb)}/`;
    if ((lower === "tmdb" || lower === "themoviedb") && ids.tmdb) {
        if (tv && item.episode_number != null && item.season_number != null && item.show_title) {
            return `https://www.themoviedb.org/tv/${encodeURIComponent(ids.tmdb)}/season/${encodeURIComponent(item.season_number)}/episode/${encodeURIComponent(item.episode_number)}`;
        }
        return `https://www.themoviedb.org/${tv ? "tv" : "movie"}/${encodeURIComponent(ids.tmdb)}`;
    }
    if ((lower === "tvdb" || lower === "thetvdb") && ids.tvdb) return `https://thetvdb.com/dereferrer/series/${encodeURIComponent(ids.tvdb)}`;
    if (lower === "tvmaze" && ids.tvmaze) return `https://www.tvmaze.com/shows/${encodeURIComponent(ids.tvmaze)}`;
    if (lower === "trakt") {
        if (ids.trakt && !/^\d+$/.test(String(ids.trakt))) return `https://trakt.tv/${tv ? "shows" : "movies"}/${encodeURIComponent(ids.trakt)}`;
        if (ids.imdb) return `https://trakt.tv/search?query=${encodeURIComponent(ids.imdb)}`;
    }
    if ((lower.includes("tomato") || lower.includes("rotten")) && underscored) return `https://www.rottentomatoes.com/${tv ? "tv" : "m"}/${encodeURIComponent(underscored)}`;
    if (lower.includes("metacritic") && dashed) return `https://www.metacritic.com/${tv ? "tv" : "movie"}/${encodeURIComponent(dashed)}/`;
    return "";
}

function siteSlug(title, sep) {
    return String(title || "").toLowerCase().replace(/[^a-z0-9]+/g, sep).replace(new RegExp(`^\\${sep}+|\\${sep}+$`, "g"), "");
}

function ratingMarks(item) {
    const ratings = (item && item.ratings) || {};
    const used = new Set();
    const marks = [];
    const add = (key, file, label, row, star) => {
        const mark = `${file}:${label}`;
        if (!row || row.value == null || row.value === "" || used.has(mark)) return;
        used.add(mark);
        const max = Number(row.max || 10);
        const text = max > 10 ? String(Math.round(Number(row.value))) : Number(row.value).toFixed(1);
        const votes = row.votes ? ` · ${Number(row.votes).toLocaleString()} votes` : "";
        const logo = star
            ? `<svg class="vrating-star" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2.6 14.7 8.1l6.1.9-4.4 4.3 1 6.1L12 16.8 6.6 19.4l1-6.1L3.2 9l6.1-.9L12 2.6z"/></svg>`
            : file
                ? `<img src="/media/providers/${file}" alt="${escapeHtml(label)}">`
                : `<span>${escapeHtml(label)}</span>`;
        const href = ratingPage(key, item);
        const tag = href ? "a" : "span";
        const link = href ? ` href="${escapeHtml(href)}" target="_blank" rel="noopener"` : "";
        marks.push(`<${tag} class="vrating-item"${link} title="${escapeHtml(label + votes)}">${logo}<span>${escapeHtml(text)}</span></${tag}>`);
    };
    RATING_SOURCES.forEach(([key, file, label]) => add(key, file, label, ratings[key]));
    Object.keys(ratings).forEach((key) => {
        if (RATING_SOURCES.some(([name]) => name === key)) return;
        const tomato = rottenTomatoesMark(key);
        if (tomato) {
            add(key, tomato[0], tomato[1], ratings[key]);
            return;
        }
        const fromNfo = key === "default" || key === "nfo";
        add(key, "", fromNfo ? "Rating from the .nfo" : key, ratings[key], fromNfo);
    });
    if (!marks.length && item && item.rating) {
        return `<span class="vrating">★ ${Number(item.rating).toFixed(1)}${item.votes ? ` <small>${Number(item.votes).toLocaleString()} votes</small>` : ""}</span>`;
    }
    return marks.length ? `<span class="vratings">${marks.join("")}</span>` : "";
}

function sourceFormatText(value) {
    const text = String(value || "");
    if (!text) return "";
    const key = text.toLowerCase();
    const cls = key.includes("remux") ? "badge-remux" : key.includes("complete") || key.includes("disk") ? "badge-brdisk" : sourceClass(text);
    return toneBadge(text, cls);
}

function sourceKey(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function sourceChips(row) {
    if (!row) return "";
    const format = row.source_format || "";
    const group = row.video_source || "";
    const chips = [];
    if (group && sourceKey(group) !== sourceKey(format)) chips.push(sourceText(group));
    if (format) chips.push(sourceFormatText(format));
    return chips.join("");
}

function sourceFact(row) {
    if (!row) return "";
    const format = row.source_format || "";
    const group = row.video_source || "";
    if (format && sourceKey(format) === sourceKey(group)) return format;
    return [group, format].filter(Boolean).join(" ");
}

function formatIcons(row) {
    if (!row) return "";
    const source = String(row.video_source || "");
    const key = source.toLowerCase();
    const edition = String(row.edition || "");
    const icons = [];
    const disc = key.includes("bluray") || key.includes("blu-ray") || key.includes("uhd");
    if (row.is_3d && disc) icons.push(["format/3d_bluray.png", "3D Blu-ray"]);
    if (key.includes("uhd")) icons.push(["format/UHDBluray.png", source || "UHD Blu-ray"]);
    else if (!row.is_3d && (key.includes("bluray") || key.includes("blu-ray"))) icons.push(["format/bluray.png", source || "Blu-ray"]);
    else if (key.includes("bd-rip") || key.includes("bdrip") || key.includes("brrip")) icons.push(["format/bluray_rip.png", source || "Blu-ray rip"]);
    else if (key.includes("hd") && key.includes("dvd")) icons.push(["format/hddvd.png", source || "HD DVD"]);
    else if (key.includes("dvd")) icons.push(["format/dvd.png", source || "DVD"]);
    if (/imax\s*enhanced/i.test(edition)) icons.push(["format/imax_enhanced.png", "IMAX Enhanced"]);
    else if (/\bimax\b/i.test(edition)) icons.push(["format/imax.png", "IMAX"]);
    return icons.map(([file, title]) => mediaBadge(file, title, true)).join("");
}

function hdrBadge(text, cls) {
    return toneBadge(text, cls);
}

function hdrIconFile(format) {
    const file = { dovi: "dolbyvision.png", hdr10plus: "HDR10+.png", hdr10: "hdr10.png", hlg: "hlg.png" }[format];
    return file ? `hdr/${file}` : (format && format !== "sdr" ? "hdr/hdr.png" : "");
}

function hdrSecondaryFile(text) {
    const key = String(text || "").toLowerCase().replace(/\+/g, "plus").replace(/\s/g, "");
    const file = { hdr10plus: "HDR10+.png", hdr10: "hdr10.png", hlg: "hlg.png", dolbyvision: "dolbyvision.png", dv: "dolbyvision.png" }[key];
    return file ? `hdr/${file}` : "";
}

function hdrPane(row) {
    if (!row || !row.hdr_format) return "";
    if (row.hdr_format === "sdr") return toneBadge("SDR", "badge-sdr");
    const parts = [];
    const main = hdrIconFile(row.hdr_format);
    if (main) parts.push(mediaBadge(main, hdrLabel(row), true));
    const secondary = hdrSecondaryFile(row.hdr_secondary);
    if (secondary && secondary !== main) parts.push(mediaBadge(secondary, row.hdr_secondary, true));
    if (row.hdr_format === "dovi") {
        const profile = row.dovi_profile ? String(row.dovi_profile) : "";
        const layer = String(row.dovi_el_type || "").toUpperCase();
        if (profile) parts.push(toneBadge(`P${profile}`, doviProfileClass(profile)));
        if (layer === "FEL" || layer === "MEL") parts.push(toneBadge(layer, layer === "FEL" ? "badge-el-fel" : "badge-el-mel"));
    }
    return parts.join("");
}

function doviProfileClass(profile) {
    const value = String(profile || "");
    if (value === "5") return "badge-p5";
    if (value === "8.1" || value === "8") return "badge-p8";
    if (value === "8.4") return "badge-p84";
    if (value === "10") return "badge-p10";
    if (value === "10.1") return "badge-p101";
    if (value === "10.4") return "badge-p104";
    if (value === "20") return "badge-p20";
    return "badge-p7";
}

function hdrLabel(row) {
    const format = row && row.hdr_format;
    if (!format) return "";
    if (format === "dovi") {
        const profile = row.dovi_profile ? ` P${row.dovi_profile}` : "";
        const el = row.dovi_el_type ? ` ${row.dovi_el_type}` : "";
        return `DV${profile}${el}`;
    }
    return { hdr10plus: "HDR10+", hdr10: "HDR10", hlg: "HLG", sdr: "SDR" }[format] || String(format).toUpperCase();
}

function hdrFull(row) {
    const main = hdrLabel(row);
    return row && row.hdr_secondary && main ? `${main} · ${row.hdr_secondary}` : main;
}

function hdrMainHtml(row) {
    if (!row || !row.hdr_format) return "";
    if (row.hdr_format === "dovi") {
        const profile = row.dovi_profile ? String(row.dovi_profile) : "";
        const layer = String(row.dovi_el_type || "").toUpperCase();
        return [
            hdrBadge("Dolby Vision", "badge-dovi"),
            profile ? hdrBadge(`P${profile}`, doviProfileClass(profile)) : "",
            layer === "FEL" || layer === "MEL" ? hdrBadge(layer, layer === "FEL" ? "badge-el-fel" : "badge-el-mel") : "",
        ].join("");
    }
    const known = { hdr10plus: ["HDR10+", "badge-hdr10plus"], hdr10: ["HDR10", "badge-hdr10"], hlg: ["HLG", "badge-hlg"], sdr: ["SDR", "badge-sdr"] };
    const item = known[row.hdr_format] || [String(row.hdr_format).toUpperCase(), "badge-sdr"];
    return hdrBadge(item[0], item[1]);
}

function hdrSecondaryHtml(row) {
    const text = String((row && row.hdr_secondary) || "");
    if (!text) return "";
    const key = text.toLowerCase().replace(/\+/g, "plus").replace(/\s/g, "");
    const cls = { hdr10plus: "badge-hdr10plus", hdr10: "badge-hdr10", hlg: "badge-hlg" }[key] || "badge-hdr10";
    return hdrBadge(key === "hdr10plus" ? "HDR10+" : text, cls);
}

function hdrClass(row) {
    const format = row && row.hdr_format;
    if (format === "dovi") return "is-dv";
    if (format === "hdr10plus" || format === "hdr10") return "is-hdr";
    if (format === "hlg") return "is-hlg";
    return "";
}

function chip(text, cls, title) {
    if (!text) return "";
    return `<span class="vchip${cls ? ` ${cls}` : ""}"${title ? ` title="${escapeHtml(title)}"` : ""}>${escapeHtml(text)}</span>`;
}

function listText(values, limit) {
    const list = (values || []).filter(Boolean);
    if (!limit || list.length <= limit) return list.join(", ");
    return `${list.slice(0, limit).join(", ")} +${list.length - limit}`;
}

function langText(values) {
    return (values || []).map((item) => String(item).toUpperCase()).join(" ");
}

function isWanted(item) {
    return !!(item && (item.wanted || String(item.path || "").indexOf("wanted://") === 0));
}

function statusChip(status, skipNew) {
    if (status === "NEW" && !skipNew) return chip("NEW", "is-new");
    if (status === "IGNORED") return chip("Ignored", "is-muted");
    if (status === "PROCESSED") return chip("Processed", "is-muted");
    return "";
}

function newEpisodesChip(row) {
    if (!row || row._kind !== "show") return "";
    const count = Number(row.new_count) || 0;
    if (!count) return "";
    const label = count === 1 ? "1 new episode" : `${count.toLocaleString()} new episodes`;
    return chip(label, "is-new");
}

function catalogueMarks(row) {
    if (!row) return "";
    const kind = row._kind === "episode" ? "episode" : (!row._kind ? "movie" : "");
    const duplicateId = row._duplicateId || row.id;
    const duplicate = row.duplicate_release && duplicateId && (kind === "movie" || kind === "episode")
        ? `<button type="button" class="tag-pill duplicate-pill" data-action="open-duplicates" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(duplicateId)}" title="Another copy of this is in the library">Duplicate</button>`
        : "";
    if (!kind || !row.id) {
        const upgrade = row.upgrade ? `<span class="tag-pill upgrade-pill">Upgrade available</span>` : "";
        return `${upgrade}${duplicate}`;
    }
    const where = row.upgrade_path ? `A higher-quality copy is at ${row.upgrade_path}` : "A higher-quality copy is in the library";
    const upgrade = row.upgrade ? `<button type="button" class="tag-pill upgrade-pill" data-action="video-upgrade" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(row.id)}" title="${escapeHtml(where)}">Upgrade available</button>` : "";
    return `${upgrade}${duplicate}`;
}

function artBadgeAllowed(ownerKind) {
    const cfg = typeof videoCfg === "function" ? videoCfg() : {};
    if (ownerKind === "set") return cfg.ui_set_art_badges !== false;
    if (ownerKind === "show" || ownerKind === "season" || ownerKind === "episode") return cfg.ui_tv_art_badges !== false;
    if (ownerKind === "music" || ownerKind === "artist" || ownerKind === "album" || ownerKind === "track") return cfg.ui_music_art_badges !== false;
    return cfg.ui_movie_art_badges !== false;
}

function gcdNum(a, b) {
    let x = Math.abs(Math.round(a)) || 0;
    let y = Math.abs(Math.round(b)) || 0;
    while (y) {
        const t = y;
        y = x % y;
        x = t;
    }
    return x || 1;
}

function formatArtAspect(w, h) {
    if (!w || !h) return "";
    const ratio = w / h;
    const common = [
        [2, 3, 2 / 3],
        [16, 9, 16 / 9],
        [1, 1, 1],
        [4, 3, 4 / 3],
        [21, 9, 21 / 9],
        [5, 1, 5],
        [54, 10, 5.4],
    ];
    for (const [rw, rh, target] of common) {
        if (Math.abs(ratio - target) / target < 0.035) return `${rw}:${rh}`;
    }
    const g = gcdNum(w, h);
    const sw = Math.round(w / g);
    const sh = Math.round(h / g);
    if (sw <= 32 && sh <= 32) return `${sw}:${sh}`;
    return `${ratio.toFixed(2)}:1`;
}

function updateArtBadgeOnLoad(img) {
    if (!img || !img.naturalWidth || !img.naturalHeight) return;
    const wrap = img.closest(".vposter-wrap, .vart-frame, .cover-frame, .artist-photo-frame, .vgrid-poster-wrap, .artist-thumb-wrap, .album-art-wrap");
    if (!wrap) return;
    let badge = wrap.querySelector(".art-dim-badge");
    if (!badge) return;
    const fullSrc = img.dataset.fullSrc || img.getAttribute("src") || "";
    const applyDim = (w, h) => {
        const aspect = formatArtAspect(w, h);
        const dims = `${w}×${h}${aspect ? ` · ${aspect}` : ""}`;
        badge.textContent = dims;
        badge.classList.remove("hidden");
        const bar = wrap.querySelector(".art-swap-bar");
        if (bar) bar.textContent = `Swap · ${dims}`;
    };
    if (fullSrc && fullSrc.includes("w=")) {
        const clean = fullSrc.replace(/([?&])w=\d+&?/, "$1").replace(/[?&]$/, "");
        const probe = new Image();
        probe.onload = () => applyDim(probe.naturalWidth, probe.naturalHeight);
        probe.src = clean;
    } else {
        applyDim(img.naturalWidth, img.naturalHeight);
    }
}

function clickableFilterLinks(values, limit, actionName) {
    const list = (values || []).filter(Boolean);
    if (!list.length) return "";
    const shown = limit && list.length > limit ? list.slice(0, limit) : list;
    const act = actionName || "video-filter-query";
    const html = shown.map((item) => `<button type="button" class="vlink-chip" data-action="${act}" data-query="${escapeHtml(String(item))}" title="Filter by ${escapeHtml(String(item))}">${escapeHtml(String(item))}</button>`).join(", ");
    return limit && list.length > limit ? `${html} <span class="muted">+${list.length - limit}</span>` : html;
}

function tvProgressBarHtml(have, total, hasMissing) {
    const cfg = typeof videoCfg === "function" ? videoCfg() : {};
    if (cfg.ui_tv_progress === false) return "";
    const h = Math.max(0, Number(have) || 0);
    const t = Math.max(h, Number(total) || 0);
    if (t === 0 && h === 0) return "";
    const pct = t > 0 ? Math.min(100, Math.round((h / t) * 100)) : 0;
    const tone = h === 0 ? "is-empty" : (h >= t && !hasMissing ? "is-complete" : "is-partial");
    const fillPct = h === 0 ? 100 : pct;
    const label = `${h} / ${t}`;
    return `<div class="tv-progress-wrap ${tone}" title="Episodes on disk: ${label}${hasMissing ? " (missing seasons or episodes)" : ""}">
        <div class="tv-progress-track"><div class="tv-progress-fill ${tone}" style="width:${fillPct}%"></div></div>
        <span class="tv-progress-label">${escapeHtml(label)}</span>
    </div>`;
}

function posterBadgesAllowed(ownerKind) {
    const cfg = typeof videoCfg === "function" ? videoCfg() : {};
    if (ownerKind === "set") return cfg.ui_set_poster_badges !== false;
    if (ownerKind === "show" || ownerKind === "season" || ownerKind === "episode") return cfg.ui_tv_poster_badges !== false;
    return cfg.ui_movie_poster_badges !== false;
}

function posterFileBadges(file) {
    if (!file) return "";
    const tracks = file.audio_tracks || [];
    const track = tracks.find((item) => item.default) || tracks[0] || {};
    const codec = file.audio_codec || track.codec || "";
    const channels = file.audio_channels || track.channels || "";
    return {
        top: `${resolutionText(file.resolution)}${hdrMainHtml(file)}`,
        bottom: `${sourceChips(file)}${codec ? `${audioCodecText(codec)}${channelText(channels)}` : ""}`,
    };
}

function artFrame(imageHtml, owner, zoomSrc, caption, mark, progressHtml, badgesHtml) {
    const wide = caption === "thumb" ? " vthumb-wrap" : "";
    const sash = mark ? " has-sash" : "";
    const swapData = `data-action="video-art-swap"${owner ? ` data-kind="${escapeHtml(owner.kind)}" data-id="${escapeHtml(owner.id)}"` : ""}`;
    const zoomData = zoomSrc ? `data-action="video-art-zoom" data-src="${escapeHtml(zoomSrc)}" data-caption="${escapeHtml(caption || "artwork")}"` : "";
    const parts = typeof badgesHtml === "string" ? { top: badgesHtml, bottom: "" } : (badgesHtml || {});
    const badges = owner && posterBadgesAllowed(owner.kind)
        ? `${parts.top ? `<div class="poster-badges poster-badges-top">${parts.top}</div>` : ""}${parts.bottom ? `<div class="poster-badges poster-badges-bottom">${parts.bottom}</div>` : ""}`
        : "";
    const showBadge = artBadgeAllowed(owner && owner.kind);
    const dimBadge = showBadge ? `<span class="art-dim-badge hidden"></span>` : "";
    const enhancedImg = showBadge
        ? String(imageHtml).replace(/<img\b/, `<img onload="updateArtBadgeOnLoad(this)" data-full-src="${escapeHtml(zoomSrc || "")}"`)
        : imageHtml;
    return `<div class="vposter-col"><div class="vposter-wrap${wide}${sash}">
        <button type="button" class="vposter-swap${zoomSrc ? " has-swap-bar" : ""}" ${zoomSrc ? zoomData : swapData} title="${zoomSrc ? "Enlarge artwork" : "Swap artwork"}" aria-label="${zoomSrc ? "Enlarge artwork" : "Swap artwork"}">${enhancedImg}</button>
        ${mark || ""}
        ${badges}
        ${dimBadge}
        ${zoomSrc ? `<button type="button" class="art-swap-bar" ${swapData} title="Swap artwork" aria-label="Swap artwork">Swap</button>` : ""}
    </div>${progressHtml || ""}</div>`;
}

function failPill(kind, text) {
    if (!text) return "";
    const label = kind === "scrape" ? "Scrape failed" : "Probe failed";
    return `<button type="button" class="tag-pill probe-fail-pill" data-action="video-copy-probe" data-fail="${kind}" title="${escapeHtml(String(text))}">${label}</button>`;
}

const HEALTH_LABELS = {
    no_size: "Empty file",
    no_video: "No video stream",
    no_audio: "No audio",
    audio_lang: "Unknown audio language",
    short: "Shorter than expected",
};

function healthWords(row) {
    return ((row && row.health) || []).map((code) => HEALTH_LABELS[code]).filter(Boolean);
}

function healthPill(row) {
    const words = healthWords(row);
    if (!words.length) return "";
    return `<span class="tag-pill health-warn-pill" title="${escapeHtml(words.join(", "))}">⚠ ${escapeHtml(words.length === 1 ? words[0] : `${words.length} warnings`)}</span>`;
}

function probeFailPill(row) {
    if (!row) return "";
    const probe = row._groupProbeError || row.probe_error || "";
    const scrape = row._groupScrapeError || row.scrape_error || "";
    return `${failPill("probe", probe)}${failPill("scrape", scrape)}`;
}

function markedRow(row) {
    if (!row || !row._versions) return row;
    return {
        ...row,
        id: row._markId || row.id,
        _duplicateId: row._groupDuplicateId || row.id,
        duplicate_release: !!row._groupDuplicate,
        upgrade: !!row._groupUpgrade,
        upgrade_path: row._groupUpgradePath || "",
    };
}

function nfoChangePill(row) {
    if (!row || (!row.nfo_stale && !row.nfo_family_stale)) return "";
    const title = row.nfo_stale
        ? "The database has changes that are not in the stored NFO"
        : "A season or episode .nfo has changes that are not in the file";
    const clickable = row.id && row._kind !== "missing" && (row.nfo_stale || (row._kind === "show" && row.nfo_family_stale));
    if (clickable) {
        const kind = row._kind || "movie";
        return `<button type="button" class="tag-pill changes-pill" data-action="video-view-nfo" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(row.id)}" title="${escapeHtml(title)}">NFO changes</button>`;
    }
    return `<span class="tag-pill changes-pill" title="${escapeHtml(title)}">NFO changes</span>`;
}

function videoStatus(row, skipNew) {
    const wanted = isWanted(row) ? chip("Wanted", "is-muted") : "";
    const held = row && row.prune_held ? `<span class="tag-pill prune-held-pill" title="Not found at the last scan, but kept because removing it would break a prune safety limit. Remove it from the library if it is really gone.">Not found</span>` : "";
    return `${wanted}${held}${statusChip(row && row.status, skipNew)}${newEpisodesChip(row)}${nfoChangePill(row)}${probeFailPill(row)}${healthPill(row)}${catalogueMarks(markedRow(row))}`;
}

function fileChips(row) {
    if (!row) return "";
    const tracks = row.audio_tracks || [];
    const track = tracks.find((item) => item.default) || tracks[0] || {};
    const codec = row.audio_codec || track.codec || "";
    const channels = row.audio_channels || track.channels || "";
    const imax = /imax\s*enhanced/i.test(row.edition || "") ? toneBadge("IMAX Enhanced", "badge-uhd")
        : /\bimax\b/i.test(row.edition || "") ? toneBadge("IMAX", "badge-uhd") : "";
    return [
        resolutionText(row.resolution),
        aspectText(row.aspect_ratio),
        hdrMainHtml(row),
        hdrSecondaryHtml(row),
        sourceChips(row),
        imax,
        videoCodecText(row.video_codec),
        `${audioCodecText(codec)}${channelText(channels)}`,
        row.stereo_mode ? toneBadge(row.stereo_mode, "badge-3d") : (row.is_3d ? toneBadge("3D", "badge-3d") : ""),
    ].join("");
}

function containerName(value) {
    const text = String(value || "").split(",")[0].trim();
    if (text.toLowerCase() === "matroska" || text.toLowerCase() === "mkv") return "MKV";
    return text;
}

function factRows(rows) {
    const body = rows.filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== "")
        .map(([label, value, raw]) => `<dt>${escapeHtml(label)}</dt><dd>${raw ? value : escapeHtml(value)}</dd>`).join("");
    return body ? `<dl class="vfacts">${body}</dl>` : "";
}

function idLinks(item) {
    const ids = { ...((item && item.ids) || {}) };
    if (item && item.imdb_id) ids.imdb = item.imdb_id;
    if (item && item.tmdb_id) ids.tmdb = item.tmdb_id;
    if (item && item.tvdb_id) ids.tvdb = item.tvdb_id;
    const tv = !!(item && (item.tvdb_id || item.show_status !== undefined));
    const links = [];
    if (ids.imdb) links.push(`<a href="https://www.imdb.com/title/${encodeURIComponent(ids.imdb)}/" target="_blank" rel="noopener">IMDb ${escapeHtml(ids.imdb)}</a>`);
    if (ids.tmdb) links.push(`<a href="https://www.themoviedb.org/${tv ? "tv" : "movie"}/${encodeURIComponent(ids.tmdb)}" target="_blank" rel="noopener">TMDB ${escapeHtml(ids.tmdb)}</a>`);
    if (ids.tvdb) links.push(`<a href="https://thetvdb.com/dereferrer/series/${encodeURIComponent(ids.tvdb)}" target="_blank" rel="noopener">TVDB ${escapeHtml(ids.tvdb)}</a>`);
    if (ids.tvmaze) links.push(`<a href="https://www.tvmaze.com/shows/${encodeURIComponent(ids.tvmaze)}" target="_blank" rel="noopener">TVMaze ${escapeHtml(ids.tvmaze)}</a>`);
    return links.join(" · ");
}

function actorPhoto(thumb) {
    const value = String(thumb || "").trim();
    if (!value) return "";
    if (/^https?:\/\//i.test(value)) return value;
    return artUrl(value);
}

function scoreText(value, digits) {
    if (value === null || value === undefined || value === "") return "";
    const number = Number(value);
    if (!Number.isFinite(number)) return "";
    const places = digits === undefined ? (number > 10 ? 0 : 1) : digits;
    return places ? number.toFixed(places) : String(Math.round(number));
}

function pathCell(path) {
    if (!path) return "";
    const parts = splitMount(path);
    if (!parts.mount) return escapeHtml(path);
    return `<span class="vpath-cell"><b>${escapeHtml(parts.mount)}</b><span>${escapeHtml(parts.rest || path)}</span></span>`;
}

function nfoMatrixChip(row) {
    if (!row || !row.has_nfo) return "—";
    const kind = row._kind || "movie";
    if (!row.id || kind === "missing") return "✓";
    return `<button type="button" class="chip ok" data-action="video-view-nfo" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(row.id)}" title="Show the .nfo">✓</button>`;
}

function nfoIcon() {
    return `<svg class="nfo-icon" viewBox="0 0 36 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path class="nfo-page" d="M5 2.4h16.2L31.2 12.2V20.6a1.6 1.6 0 0 1-1.6 1.6H5A1.6 1.6 0 0 1 3.4 20.6V4A1.6 1.6 0 0 1 5 2.4z"/><path class="nfo-fold" d="M21 2.6V12h10"/><text class="nfo-letters" x="15.6" y="16.7" text-anchor="middle" fill="currentColor" stroke="none" font-size="7.4" font-weight="700" font-family="ui-sans-serif, system-ui, sans-serif">NFO</text></svg>`;
}

function nfoMark(label, present, stale, attrs) {
    const tone = present ? (stale ? "stale" : "ok") : "missing";
    const title = !present
        ? `No ${label}`
        : (stale ? `${label}: the database has changes that are not in this file` : label);
    const clickable = present && attrs;
    const tag = clickable ? "button" : "span";
    const extra = clickable ? ` type="button" ${attrs}` : "";
    return `<${tag} class="nfo-mark ${tone}"${extra} title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">${nfoIcon()}</${tag}>`;
}

function nfoChip(label, path, kind, id, stale) {
    const attrs = path && kind && id
        ? `data-action="video-view-nfo" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(id)}"`
        : "";
    return nfoMark(label, !!path, !!stale, attrs);
}

async function showVideoNfo(kind, id) {
    const data = await api(`/api/v1/nfo/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
    openNfoModal(data, { kind, id });
    if (kind === "show" && data.file_stale === false) clearShowFileStale(id);
}

function clearShowFileStale(id) {
    const show = (state.video.shows || []).find((item) => String(item.id) === String(id));
    if (show) show.nfo_stale = false;
    const detail = state.video.showDetails && state.video.showDetails.get(id);
    if (detail) detail.nfo_stale = false;
    if (state.media === "tv" && typeof renderTvTree === "function") renderTvTree();
}

const CERT_BOARDS = { US: "MPAA", DE: "FSK", GB: "BBFC", AU: "ACB", CA: "CHVRS", FR: "CNC", NL: "Kijkwijzer" };

function certificationText(item) {
    const items = (item && item.certifications) || {};
    return Object.keys(items).sort().map((code) => `${CERT_BOARDS[code] || code} ${items[code]}`).join(" · ");
}

function certView(item) {
    const own = item && item.certifications && Object.keys(item.certifications).length ? item.certifications : null;
    return {
        mpaa: (item && item.mpaa) || (!own && item && item.show_mpaa) || "",
        certifications: own || (item && item.show_certifications) || {},
    };
}

function certShort(item) {
    const view = certView(item);
    const mpaa = String(view.mpaa || "").replace(/^rated\s+/i, "").trim();
    if (mpaa) return mpaa;
    const certs = view.certifications || {};
    return certs.US || certs.GB || certs.DE || Object.values(certs)[0] || "";
}

function certBadge(item) {
    const short = certShort(item);
    if (!short) return "";
    const full = certificationText(certView(item));
    const title = full || String((certView(item).mpaa) || short);
    return `<span class="cert-badge" title="${escapeHtml(title)}">${escapeHtml(short)}</span>`;
}

function certFact(item) {
    const view = certView(item);
    return certificationText(view) || String(view.mpaa || "").trim();
}

function castHtml(actors, limit) {
    const list = (actors || []).slice(0, limit || 18);
    if (!list.length) return "";
    return `<h3>Cast</h3><div class="vcast">${list.map((actor) => {
        const photo = actorPhoto(actor.thumb);
        const face = photo
            ? `<img class="vcast-photo" src="${escapeHtml(photo)}" alt="" loading="lazy">`
            : `<span class="vcast-photo is-empty" aria-hidden="true"></span>`;
        const role = actor.role ? `<small>${escapeHtml(actor.role)}</small>` : `<small></small>`;
        const name = actor.name || "";
        return `<button type="button" class="vcast-item is-clickable" data-action="video-filter-query" data-query="${escapeHtml(name)}" title="Filter library by ${escapeHtml(name)}">${face}<strong>${escapeHtml(name)}</strong>${role}</button>`;
    }).join("")}</div>`;
}

function youtubeId(value) {
    const text = String(value || "");
    const patterns = [
        /[?&](?:video_?id|v)=([A-Za-z0-9_-]{11})/,
        /youtu\.be\/([A-Za-z0-9_-]{11})/,
        /youtube(?:-nocookie)?\.com\/(?:embed|shorts|v|live)\/([A-Za-z0-9_-]{11})/,
    ];
    for (const pattern of patterns) {
        const match = text.match(pattern);
        if (match) return match[1];
    }
    return /^[A-Za-z0-9_-]{11}$/.test(text) ? text : "";
}

function trailerSection(item, owner) {
    const file = item && item.trailer_file;
    const youtube = youtubeId(item && item.trailer);
    const title = (item && (item.title || item.show_title)) || "Trailer";
    const player = file
        ? `<video class="vtrailer" controls preload="metadata" src="/api/v1/media?path=${encodeURIComponent(file)}"></video>`
        : youtube
            ? `<iframe class="vtrailer" title="Trailer" src="https://www.youtube.com/embed/${youtube}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`
            : `<p class="muted">No trailer yet. Scrape this item so the YouTube link is saved, then download it.</p>`;
    const local = file ? `<p class="muted mono vpath">${escapeHtml(String(file).split("/").slice(-2).join("/"))}</p>` : "";
    const buttons = [];
    if (file || youtube) {
        buttons.push(`<button type="button" class="btn-ghost" data-action="video-trailer-popout" data-title="${escapeHtml(title)}" data-file="${escapeHtml(file || "")}" data-youtube="${escapeHtml(youtube || "")}" title="Open in a floating mini-player so it keeps playing while browsing">Pop out player</button>`);
    }
    if (file && typeof document !== "undefined" && document.pictureInPictureEnabled) {
        buttons.push(`<button type="button" class="btn-ghost" data-action="video-trailer-pip" title="Open in browser Picture-in-Picture">Picture-in-Picture</button>`);
    }
    if (owner) {
        buttons.push(`<button type="button" class="btn-ghost" data-action="video-trailer-download" data-kind="${escapeHtml(owner.kind)}" data-id="${escapeHtml(owner.id)}">Download trailer</button>`);
    }
    const actions = buttons.length ? `<div class="vtrailer-actions">${buttons.join("")}</div>` : "";
    const hasTheme = owner && (owner.kind === "movie" || owner.kind === "show");
    const themeHtml = hasTheme ? themeSongSubsection(item, owner) : "";
    const heading = hasTheme ? "Trailer &amp; Theme Song" : "Trailer";
    return `<section class="vsection"><h3>${heading}</h3>${player}${local}${actions}${themeHtml}</section>`;
}

function themeSongSubsection(item, owner) {
    const themeFile = item && item.theme_file;
    const dlBtn = owner
        ? `<button type="button" class="btn-ghost" data-action="video-files-run" data-op="themes" data-kind="${escapeHtml(owner.kind)}" data-id="${escapeHtml(owner.id)}">${themeFile ? "Re-download theme.mp3" : "Download theme.mp3"}</button>`
        : "";
    if (!themeFile) {
        return `<div class="vtheme-box"><h4>Theme song</h4><p class="muted">No local <code>theme.mp3</code> found.</p><div class="vtrailer-actions">${dlBtn}</div></div>`;
    }
    const shortPath = String(themeFile).split(/[\\/]/).slice(-2).join("/");
    return `<div class="vtheme-box">
        <h4>Theme song <span class="tag-pill ok">theme.mp3</span></h4>
        <audio class="vtheme-audio" controls preload="none" src="/api/v1/media?path=${encodeURIComponent(themeFile)}"></audio>
        <p class="muted mono vpath">${escapeHtml(shortPath)}</p>
        <div class="vtrailer-actions">${dlBtn}</div>
    </div>`;
}

function bindTrailerPopoutDrag() {
    const head = document.getElementById("trailer-popout-head");
    const box = document.getElementById("trailer-popout");
    if (!head || !box || head.dataset.bound) return;
    head.dataset.bound = "1";
    head.addEventListener("pointerdown", (event) => {
        if (event.target.closest("button")) return;
        const rect = box.getBoundingClientRect();
        const offsetX = event.clientX - rect.left;
        const offsetY = event.clientY - rect.top;
        const move = (ev) => {
            const left = Math.max(8, Math.min(window.innerWidth - rect.width - 8, ev.clientX - offsetX));
            const top = Math.max(8, Math.min(window.innerHeight - rect.height - 8, ev.clientY - offsetY));
            box.style.left = `${Math.round(left)}px`;
            box.style.top = `${Math.round(top)}px`;
            box.style.right = "auto";
            box.style.bottom = "auto";
        };
        const stop = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", stop);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", stop);
        event.preventDefault();
    });
}

function openTrailerPopout(action) {
    const box = document.getElementById("trailer-popout");
    const stage = document.getElementById("trailer-popout-stage");
    const titleNode = document.getElementById("trailer-popout-title");
    const pipBtn = document.getElementById("trailer-popout-pip");
    if (!box || !stage) return;
    bindTrailerPopoutDrag();
    const file = action.dataset.file || "";
    const youtube = action.dataset.youtube || "";
    const title = action.dataset.title || "Trailer";
    if (titleNode) titleNode.textContent = title;
    const inlineVideo = document.querySelector("#video-center video.vtrailer");
    let resumeTime = 0;
    if (inlineVideo) {
        resumeTime = Number(inlineVideo.currentTime) || 0;
        try {
            inlineVideo.pause();
        } catch (err) {}
    }
    if (file) {
        stage.innerHTML = `<video id="trailer-popout-video" controls autoplay preload="metadata" src="/api/v1/media?path=${encodeURIComponent(file)}"></video>`;
        const popVideo = document.getElementById("trailer-popout-video");
        if (popVideo && resumeTime > 0) {
            popVideo.addEventListener("loadedmetadata", () => {
                try {
                    popVideo.currentTime = resumeTime;
                } catch (err) {}
            }, { once: true });
        }
        if (pipBtn) pipBtn.classList.toggle("hidden", !document.pictureInPictureEnabled);
    } else if (youtube) {
        stage.innerHTML = `<iframe title="${escapeHtml(title)}" src="https://www.youtube.com/embed/${encodeURIComponent(youtube)}?autoplay=1" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
        if (pipBtn) pipBtn.classList.add("hidden");
    } else {
        return;
    }
    box.classList.remove("hidden");
}

function closeTrailerPopout() {
    const box = document.getElementById("trailer-popout");
    const stage = document.getElementById("trailer-popout-stage");
    if (stage) stage.innerHTML = "";
    if (box) box.classList.add("hidden");
}

function toggleTrailerPopoutSize() {
    const box = document.getElementById("trailer-popout");
    const btn = document.getElementById("trailer-popout-size");
    if (!box) return;
    const large = box.classList.toggle("is-large");
    if (btn) btn.textContent = large ? "Compact" : "Large";
}

async function requestTrailerPip(videoEl) {
    const video = videoEl || document.querySelector("#video-center video.vtrailer") || document.getElementById("trailer-popout-video");
    if (!video || typeof video.requestPictureInPicture !== "function") {
        notify("Picture-in-Picture is only available for local trailer video files in supported browsers.", "info");
        return;
    }
    try {
        if (document.pictureInPictureElement === video) {
            await document.exitPictureInPicture();
        } else {
            if (video.readyState < 1) {
                await new Promise((resolve) => {
                    video.addEventListener("loadedmetadata", resolve, { once: true });
                    video.load();
                });
            }
            await video.requestPictureInPicture();
        }
    } catch (error) {
        notify((error && error.message) || "Could not start Picture-in-Picture.", "warning");
    }
}

function artGallery(art, owner) {
    const entries = Object.entries(art || {}).filter(([, path]) => typeof path === "string" && path);
    const fetch = owner && owner.kind !== "set"
        ? `<p><button type="button" class="btn-ghost" data-action="video-art-fetch" data-kind="${escapeHtml(owner.kind)}" data-id="${escapeHtml(owner.id)}">Download missing artwork</button></p>`
        : "";
    if (!entries.length) return `<div id="video-artwork">${fetch}<p class="muted">No local artwork was found.</p></div>`;
    const showBadge = artBadgeAllowed(owner && owner.kind);
    return `<div id="video-artwork">${fetch}<div class="vart-grid">${entries.map(([kind, path]) => {
        const fullUrl = artUrl(path);
        const dimBadge = showBadge ? `<span class="art-dim-badge hidden"></span>` : "";
        const onloadAttr = showBadge ? ` onload="updateArtBadgeOnLoad(this)" data-full-src="${escapeHtml(fullUrl)}"` : "";
        return `<figure class="vart-item">
        <div class="vart-frame">
            <img loading="lazy" src="${artUrl(path, 342)}" alt="${escapeHtml(kind)}"${onloadAttr}>
            ${dimBadge}
            ${zoomButton("video-art-zoom", `data-src="${escapeHtml(fullUrl)}" data-caption="${escapeHtml(kind)}"`)}
        </div>
        <figcaption>${escapeHtml(kind)}${owner ? ` <button type="button" class="art-delete" data-action="video-art-delete" data-kind="${escapeHtml(owner.kind)}" data-id="${escapeHtml(owner.id)}" data-art-kind="${escapeHtml(kind)}" title="Delete this artwork file" aria-label="Delete ${escapeHtml(kind)} artwork">${trashIcon()}</button>` : ""}</figcaption>
    </figure>`;
    }).join("")}</div></div>`;
}

function trackTable(head, rows) {
    if (!rows.length) return `<p class="muted">None.</p>`;
    const cell = (value) => (value && typeof value === "object" && value.html != null)
        ? `<td>${value.html}</td>`
        : `<td>${escapeHtml(value ?? "")}</td>`;
    return `<table class="vtracks"><thead><tr>${head.map((name) => `<th>${escapeHtml(name)}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((row) => `<tr>${row.map(cell).join("")}</tr>`).join("")}</tbody></table>`;
}

function isMkvFile(file) {
    return String((file && file.path) || "").toLowerCase().endsWith(".mkv");
}

const NO_TRACK_LANGUAGE = new Set(["", "und", "unk", "unknown", "zxx", "mis", "mul"]);

// The one language list for every place a track's language is chosen. Nothing is typed by hand. With preselect the
// current language is the chosen entry (a code that is not in the list is added so it is not lost); without it the
// list starts on a prompt, for a Set button that writes only when something was picked.
function trackLanguageSelect(current, attributes, preselect, prompt) {
    const code = String(current || "").trim().toLowerCase();
    const listed = typeof TRACK_LANGUAGES !== "undefined" ? TRACK_LANGUAGES : [["eng", "English"]];
    const extra = preselect && !NO_TRACK_LANGUAGE.has(code) && !listed.some(([key]) => key === code) ? [[code, code.toUpperCase()]] : [];
    const chosen = preselect && !NO_TRACK_LANGUAGE.has(code) ? code : "";
    const items = [...extra, ...listed].map(([key, label]) =>
        `<option value="${escapeHtml(key)}"${key === chosen ? " selected" : ""}>${escapeHtml(label)}</option>`).join("");
    return `<select ${attributes || ""} aria-label="Language"><option value="">${escapeHtml(prompt || "Language…")}</option>${items}</select>`;
}

// The language as a person reads it, for the confirmation window.
function trackLanguageName(code) {
    const key = String(code || "").trim().toLowerCase();
    if (NO_TRACK_LANGUAGE.has(key)) return "unknown";
    const listed = typeof TRACK_LANGUAGES !== "undefined" ? TRACK_LANGUAGES : [];
    const found = listed.find(([value]) => value === key);
    return found ? found[1] : key.toUpperCase();
}

// An embedded track's language: the current code, a list to pick another, and a button that writes it into the
// file. Audio and subtitle tracks both use it. The list is always shown; outside an MKV it is locked, with the
// reason, because those containers cannot be changed in place.
function trackLanguageCell(owner, trackKind, index, lang, mkv, starred) {
    const shown = `${String(lang || "").toUpperCase()}${starred ? " ★" : ""}`;
    if (!owner) return shown;
    if (!mkv) {
        const why = "Only the tracks of an MKV can be changed in place. Remux the file to MKV first.";
        return { html: `<span class="track-lang is-locked" title="${escapeHtml(why)}">${escapeHtml(shown)} ${trackLanguageSelect(lang, "disabled", false)} <button type="button" class="btn-ghost" disabled>Set</button></span>` };
    }
    return { html: `<span class="track-lang">${escapeHtml(shown)} ${trackLanguageSelect(lang, "", false)} <button type="button" class="btn-ghost" data-action="video-track-lang" data-kind="${escapeHtml(owner.kind)}" data-id="${escapeHtml(owner.id)}" data-track="${trackKind}" data-index="${index}" data-current="${escapeHtml(String(lang || ""))}" title="Write this language into the file">Set</button></span>` };
}

function defaultTrackCell(owner, trackKind, index, on, mkv) {
    if (!mkv || !owner) return on ? "Default" : "";
    if (on) return { html: `<span class="tag-pill">Default</span>` };
    const label = trackKind === "audio" ? "Set as the default audio track" : "Set as the default subtitle track";
    return { html: `<button type="button" class="btn-ghost" data-action="video-default-track" data-kind="${escapeHtml(owner.kind)}" data-id="${escapeHtml(owner.id)}" data-track="${trackKind}" data-index="${index}" title="${escapeHtml(label)}">Default</button>` };
}



const SUB_SYNC_EXTS = new Set(["srt", "vtt", "ass", "ssa", "idx", "sup"]);
const SUB_SYNC_SVG = `<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none" aria-hidden="true">
    <path d="M4.5 4.5h15a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5H10.6l-3.1 3.5a.6.6 0 0 1-1 -.4V16.5H4.5A1.5 1.5 0 0 1 3 15V6a1.5 1.5 0 0 1 1.5-1.5z"/>
    <rect x="6.3" y="9.3" width="11" height="1.8" rx="0.9" fill="var(--bg-surface)"/>
    <rect x="6.3" y="12.1" width="8.5" height="1.8" rx="0.9" fill="var(--bg-surface)"/>
</svg>`;

function syncedBadge(when) {
    return when ? ` <span class="sub-synced" title="Marked as synced ${escapeHtml(String(when))}">&#10003; Synced</span>` : "";
}

function subSyncIconCell(file, folder, track) {
    let name = String(track && track.file || "");
    if (!name) return "";
    let ext = name.split(".").pop().toLowerCase();
    if (ext === "sub") {
        // A VobSub is a pair; the .idx row carries the timing, so the .sub row opens it too.
        const sibling = name.replace(/\.sub$/i, ".idx").toLowerCase();
        const match = ((file && file.external_subtitles) || []).find((row) => String(row.file || "").toLowerCase() === sibling);
        if (match) { name = match.file; ext = "idx"; }
    }
    if (!SUB_SYNC_EXTS.has(ext)) {
        return { html: `<span class="muted" title="${ext.toUpperCase()} subtitles cannot be synced">—</span>` };
    }
    const picture = ext === "idx" || ext === "sup";
    const path = folder ? `${folder}/${name}` : name;
    const videoPath = String((file && file.path) || "");
    const label = picture ? "Sync this picture subtitle to the video (its text is read with OCR first)" : "Sync this subtitle to the video";
    return { html: `<button type="button" class="icon-btn sub-sync-btn" data-action="sub-sync-open"
        data-sub-path="${escapeHtml(path)}" data-video-path="${escapeHtml(videoPath)}"
        title="${label}" aria-label="${label}">${SUB_SYNC_SVG}</button>${syncedBadge(track && track.synced)}` };
}

// A VobSub is an .idx + .sub pair that only works together, so it is listed once, under the
// .sub name. Renaming that row renames both files (see subtitles.retag).
function externalSubtitleRows(file) {
    const rows = (file && file.external_subtitles) || [];
    const names = new Set(rows.map((row) => String(row.file || "").toLowerCase()));
    return rows.filter((row) => {
        const name = String(row.file || "").toLowerCase();
        return !(name.endsWith(".idx") && names.has(`${name.slice(0, -4)}.sub`));
    });
}

function subtitleEditors(file, owner) {
    const rows = externalSubtitleRows(file);
    if (!owner || !rows.length) return "";
    return `<div class="vsub-edits">${rows.map((track) => {
        const flags = new Set(track.flags || []);
        const box = (flag, label) => `<label class="choice"><input type="checkbox" data-sub-flag="${flag}" ${flags.has(flag) ? "checked" : ""}> ${label}</label>`;
        return `<div class="vsub-edit" data-sub-file="${escapeHtml(track.file)}" data-sub-current="${escapeHtml(String(track.lang || "").toLowerCase())}">
            <span class="mono">${escapeHtml(track.file)}</span>
            ${trackLanguageSelect(track.lang, "data-sub-lang", true, "Choose a language…")}
            ${box("forced", "Forced")}${box("sdh", "SDH")}${box("hi", "HI")}
            <button type="button" class="btn-ghost" data-action="video-sub-save" data-kind="${escapeHtml(owner.kind)}" data-id="${escapeHtml(owner.id)}">Save</button>
        </div>`;
    }).join("")}</div>`;
}

// Says what the Default and Language buttons do, or why a file has none: they are written into the file itself, and
// that can be done in place for MKV only.
function trackNote(file, owner, mkv) {
    if (!owner || !((file.audio_tracks || []).length || (file.subtitle_tracks || []).length)) return "";
    if (mkv) {
        return `<p class="muted">On the embedded tracks of an MKV, Default sets which track a player starts with and Language writes the chosen language into the file, for example when it shows as unknown. Subtitle files next to the video are changed in the list under Subtitles.</p>`;
    }
    const container = containerName(file.container);
    return `<p class="muted">Only the embedded tracks of an MKV can be changed in place, so the Language lists are locked and there is no Default button for this ${container ? `${escapeHtml(container)} ` : ""}file. Remux it to MKV first to edit them.</p>`;
}

function mediaInfoHtml(file, owner) {
    if (!file) return `<section class="vsection"><h3>Media info</h3><p class="muted">This item has no probed video file.</p></section>`;
    const size = file.width && file.height ? `<span class="muted">${file.width}×${file.height}</span>` : "";
    const profile = file.video_profile ? `<span class="muted">${escapeHtml(file.video_profile)}</span>` : "";
    const video = factRows([
        ["Resolution", `${resolutionText(file.resolution)} ${size}`.trim(), true],
        ["Codec", `${videoCodecText(file.video_codec)} ${profile}`.trim(), true],
        ["HDR", `${hdrMainHtml(file)}${hdrSecondaryHtml(file)}`, true],
        ["Dolby Vision", file.hdr_format === "dovi" ? [
            file.dovi_profile ? `Profile ${file.dovi_profile}` : "",
            file.dovi_el_type ? `${file.dovi_el_type} enhancement layer` : "",
            file.dovi_bl_compat ? `BL compatibility ${file.dovi_bl_compat}` : "",
        ].filter(Boolean).join(" · ") : ""],
        ["MaxCLL / MaxFALL", file.max_cll || file.max_fall ? `${file.max_cll || "—"} / ${file.max_fall || "—"} nits` : "—"],
        ["Bit depth", file.bit_depth ? `${file.bit_depth}-bit` : ""],
        ["Frame rate", file.fps ? `${file.fps} fps` : ""],
        ["Aspect ratio", file.aspect_ratio],
        ["Video bitrate", file.video_bitrate_mbps ? `${file.video_bitrate_mbps} Mb/s` : ""],
        ["3D", file.stereo_mode ? toneBadge(file.stereo_mode, "badge-3d") : (file.is_3d ? toneBadge("3D", "badge-3d") : ""), true],
    ]);
    const container = factRows([
        ["Container", containerName(file.container)],
        ["Duration", fmtDuration(file.duration_seconds)],
        ["Size", fmtSize(file.size_bytes)],
        ["Overall bitrate", file.bitrate_mbps ? `${file.bitrate_mbps} Mb/s` : ""],
        ["Source", sourceChips(file), true],
        ["Edition", file.edition],
        ["Chapters", file.chapters || ""],
        ["Probed", fmtDate(file.probed_at)],
    ]);
    const mkv = isMkvFile(file);
    const audioHead = ["#", "Language", "Codec", "Channels", "Bitrate", "Title"];
    if (mkv) audioHead.push("Default");
    const audio = trackTable(audioHead,
        (file.audio_tracks || []).map((track, index) => {
            const row = [
                `${index + 1}${track.default ? " ★" : ""}`, trackLanguageCell(owner, "audio", index, track.lang, mkv), track.codec, track.channels,
                track.bitrate_kbps ? `${track.bitrate_kbps} kb/s` : "", track.title,
            ];
            if (mkv) row.push(defaultTrackCell(owner, "audio", index, !!track.default, true));
            return row;
        }));
    const subHead = ["Language", "Format", "Flags", "Where", "Title"];
    if (mkv) subHead.push("Default");
    subHead.push("Sync");
    const videoFolder = (file && file.path) ? String(file.path).replace(/[\\\/][^\\\/]*$/, "") : "";
    const subtitles = trackTable(subHead, [
        ...(file.subtitle_tracks || []).map((track, index) => {
            const row = [
                trackLanguageCell(owner, "subtitle", index, track.lang, mkv, !!track.default), track.codec, (track.flags || []).join(", "), "Embedded", track.title,
            ];
            if (mkv) row.push(defaultTrackCell(owner, "subtitle", index, !!track.default, true));
            row.push("");  // embedded tracks can't be synced as sidecars
            return row;
        }),
        ...externalSubtitleRows(file).map((track) => {
            const row = [
                String(track.lang || "").toUpperCase(), track.format, (track.flags || []).join(", "), "External", track.file,
            ];
            if (mkv) row.push("");
            row.push(subSyncIconCell(file, videoFolder, track));
            return row;
        }),
    ]);
    const error = file.probe_error
        ? `<p class="scan-status is-failed">${escapeHtml(file.probe_error)} <button type="button" class="btn-ghost" data-action="video-copy-probe" data-fail="probe" title="${escapeHtml(file.probe_error)}">Copy</button></p>`
        : "";
    return `<section class="vsection"><h3>Media info</h3>${error}
        <div class="vmedia-cols"><div><h4>Video</h4>${video || `<p class="muted">Not probed.</p>`}</div><div><h4>File</h4>${container}</div></div>
        ${trackNote(file, owner, mkv)}
        <h4>Audio</h4>${audio}
        <h4>Subtitles</h4>${subtitles}
        ${subtitleEditors(file, owner)}
    </section>`;
}

function statusButtons(kind, item) {
    const status = item.status || "NEW";
    const ignored = status === "IGNORED";
    const processed = status === "PROCESSED";
    const fresh = status === "NEW" ? `<span class="badge-new">NEW</span>` : "";
    const button = (value, label, on) => `<button type="button" class="btn-ghost${on ? " is-on" : ""}" data-action="video-status" data-kind="${kind}" data-id="${escapeHtml(item.id)}" data-status="${value}">${label}</button>`;
    const process = processed
        ? button("NEW", "Set to unprocessed", true)
        : `<button type="button" class="btn-process" data-action="video-status" data-kind="${kind}" data-id="${escapeHtml(item.id)}" data-status="PROCESSED">Mark processed</button>`;
    const ignore = ignored
        ? button("NEW", "Stop ignoring", true)
        : button("IGNORED", "Ignore", false);
    const lock = typeof lockButton === "function" ? lockButton(kind, item) : "";
    return `<div class="vstatus">${fresh}${process}${ignore}${lock}</div>`;
}

function videoTrashButton(kind, id) {
    return `<button type="button" class="title-delete" data-action="video-delete-one" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(id)}" title="Remove…" aria-label="Remove…">${typeof trashSvg === "function" ? trashSvg() : ""}</button>`;
}

function videoHeroActions(kind, item) {
    return `${statusButtons(kind, item)}${videoTrashButton(kind, item.id)}`;
}

function infoTitle(text, edit) {
    const pencil = edit
        ? `<button type="button" class="icon-btn" data-action="video-edit" data-kind="${escapeHtml(edit.kind)}" data-id="${escapeHtml(edit.id)}" ${edit.locked ? "disabled title=\"Unlock to edit\"" : ""} title="Edit" aria-label="Edit">${typeof pencilIcon === "function" ? pencilIcon() : ""}</button>`
        : "";
    return `<div class="info-name"><h2>${text}</h2>${pencil}</div>`;
}

function holdCenterScroll() {
    const node = document.getElementById("video-center");
    state.video.centerScroll = node ? node.scrollTop : 0;
    state.video.keepCenterScroll = true;
}

function releaseCenterScroll() {
    if (!state.video || !state.video.keepCenterScroll) return;
    const top = state.video.centerScroll || 0;
    state.video.keepCenterScroll = false;
    const node = document.getElementById("video-center");
    if (!node) return;
    const apply = () => { if (node.isConnected) node.scrollTop = top; };
    apply();
    requestAnimationFrame(apply);
}

function textMatcher(query) {
    const tokens = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (!tokens.length) return null;
    return (haystack) => tokens.every((token) => haystack.includes(token));
}

function pinnedListScroll(host) {
    const saved = state.videoListScroll;
    if (Number.isFinite(saved)) return saved;
    return host ? host.scrollTop : 0;
}

function pinListScroll(host, top) {
    if (!host) return;
    state.videoListScroll = top;
    state.videoScrollPin = true;
    state.videoScrollAt = performance.now();
    let frames = 0;
    const apply = () => {
        if (!host.isConnected) return true;
        placeListScroll(host, top);
        const max = Math.max(0, host.scrollHeight - host.clientHeight);
        return top <= 0 || max + 1 >= top;
    };
    const step = () => {
        frames += 1;
        if (apply() || frames > 30) {
            state.videoScrollPin = false;
            return;
        }
        requestAnimationFrame(step);
    };
    apply();
    requestAnimationFrame(step);
}

function placeListScroll(host, scroll) {
    const body = host.querySelector(".vwin-rows");
    if (body) body.style.height = `${(state.video.rows || []).length * VIDEO_ROW}px`;
    const max = Math.max(0, host.scrollHeight - host.clientHeight);
    const next = Math.min(Math.max(0, scroll), max);
    if (host.scrollTop !== next) host.scrollTop = next;
    return next;
}

function paintWindow(host, rows, renderRow, extraHeight) {
    const body = host.querySelector(".vwin-rows");
    if (!body) return;
    const total = rows.length;
    body.style.height = `${total * VIDEO_ROW}px`;
    const top = Math.max(0, host.scrollTop - (extraHeight || 0));
    const first = Math.max(0, Math.floor(top / VIDEO_ROW) - VIDEO_OVERSCAN);
    const last = Math.min(total, Math.ceil((top + host.clientHeight) / VIDEO_ROW) + VIDEO_OVERSCAN);
    const key = `${first}:${last}:${total}:${state.video.paintToken}`;
    if (body.dataset.window === key) return;
    body.dataset.window = key;
    let html = "";
    for (let index = first; index < last; index += 1) html += renderRow(rows[index], index);
    body.innerHTML = html;
}

function scrollRowIntoView(host, index, extraHeight) {
    const top = index * VIDEO_ROW + (extraHeight || 0);
    const view = host.clientHeight;
    if (top < host.scrollTop + (extraHeight || 0)) host.scrollTop = top - (extraHeight || 0);
    else if (top + VIDEO_ROW > host.scrollTop + view) host.scrollTop = top + VIDEO_ROW - view;
}
