const LOSSY_FORMATS = new Set(["mp3", "aac", "ogg", "opus", "m4a", "wma"]);
const LOSSLESS_FORMATS = new Set(["flac", "wav", "aiff", "aif", "alac"]);

function formatLabel(track) {
    const format = String(track.file_format || "").toLowerCase();
    let name = format ? format.toUpperCase() : "AUDIO";
    if (format === "dsf" || format === "dff") name = "DSD";
    else if (format === "alac") name = "ALAC";
    if (LOSSY_FORMATS.has(format) && track.bitrate) return `${name} ${track.bitrate}`;
    if (track.bit_depth && track.sample_rate && (LOSSLESS_FORMATS.has(format) || format === "dsf" || format === "dff")) {
        return `${name} ${track.bit_depth}·${Math.round(Number(track.sample_rate) / 1000)}`;
    }
    return name;
}

function isHires(track) {
    const format = String(track.file_format || "").toLowerCase();
    if (!LOSSLESS_FORMATS.has(format)) return false;
    return Number(track.bit_depth || 0) > 16 || Number(track.sample_rate || 0) > 48000;
}

function fidelityPill(track, text) {
    const label = text || formatLabel(track);
    return `<span class="fidelity${isHires(track) ? " hires" : ""}">${escapeHtml(label)}</span>`;
}

function fidelitySummary(tracks) {
    if (!tracks || !tracks.length) return "";
    const labels = [...new Set(tracks.map((track) => formatLabel(track)))];
    const sample = tracks.find((track) => formatLabel(track) === labels[0]) || tracks[0];
    const text = labels.length === 1 ? labels[0] : `${labels[0]} +${labels.length - 1}`;
    return fidelityPill(sample, text);
}

function replayPill(track) {
    const gain = (track.tags || {}).replaygain_track_gain;
    if (!gain) return "";
    return `<span class="tag-pill tabular">${escapeHtml(gain)}</span>`;
}

function explicitPill(track) {
    const tags = track.tags || {};
    const flag = String(tags.itunesadvisory || tags.explicit || "").trim().toLowerCase();
    if (flag === "1" || flag === "explicit" || flag === "true") return `<span class="tag-pill bad">Explicit</span>`;
    return "";
}

function trackBadges(track) {
    return `${fidelityPill(track)} ${replayPill(track)} ${explicitPill(track)} ${audioBadge(track)}`;
}

function earthIcon() {
    return `<svg class="earth-icon" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.2"/><ellipse cx="8" cy="8" rx="2.7" ry="6.2" fill="none" stroke="currentColor" stroke-width="1"/><path d="M2.1 8h11.8M3.1 5.3h9.8M3.1 10.7h9.8" fill="none" stroke="currentColor" stroke-width="1"/></svg>`;
}

function countryIcon(code) {
    const value = String(code || "").trim().toUpperCase();
    if (!value) return "";
    if (value === "XW") return earthIcon();
    const file = value === "XE" ? "eu" : value.toLowerCase();
    if (!/^[a-z]{2}$/.test(file)) return "";
    return `<img class="country-flag-img" alt="" width="18" height="13" src="https://flagcdn.com/w40/${file}.png" data-code="${file}" onerror="this.replaceWith(document.createTextNode(this.dataset.code.toUpperCase()))">`;
}

function countryPill(country) {
    const value = String(country || "").trim().toUpperCase();
    const name = countryName(value);
    if (!name) return "";
    const icon = countryIcon(value);
    return `<span class="tag-pill country-pill" title="${escapeHtml(name)}">${icon}<span>${escapeHtml(name)}</span></span>`;
}

function countryFlag(country) {
    const value = String(country || "").trim().toUpperCase();
    if (!value) return "";
    const name = countryName(value);
    const icon = countryIcon(value);
    if (!icon && !name) return "";
    return `<span class="country-flag" title="${escapeHtml(name || value)}">${icon || escapeHtml(value)}</span>`;
}

const COUNTRY_ALIASES = {
    "united states of america": "US", "united states": "US", usa: "US", "u.s.a": "US", "u.s": "US",
    uk: "GB", "great britain": "GB", england: "GB", "northern ireland": "GB", scotland: "GB", wales: "GB",
    "czech republic": "CZ", czechoslovakia: "CZ", guadaloupe: "GP", guadeloupe: "GP",
    "hong kong sar china": "HK", macedonia: "MK", "republic of macedonia": "MK", "north macedonia": "MK",
    "netherlands antilles": "NL", "soviet union": "RU", ussr: "RU", "russian federation": "RU", russia: "RU",
    turkey: "TR", "türkiye": "TR", vietnam: "VN", "viet nam": "VN",
    "south korea": "KR", "republic of korea": "KR", korea: "KR", "north korea": "KP",
    iran: "IR", syria: "SY", laos: "LA", bolivia: "BO", venezuela: "VE", tanzania: "TZ", moldova: "MD",
    palestine: "PS", "ivory coast": "CI", "cote d'ivoire": "CI", "côte d'ivoire": "CI",
    burma: "MM", myanmar: "MM", swaziland: "SZ", eswatini: "SZ", yugoslavia: "RS",
    "east germany": "DE", "west germany": "DE",
};

let countryByName = null;

function countryCode(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const upper = text.toUpperCase();
    if (/^[A-Z]{2}$/.test(upper)) return upper;
    const key = text.toLowerCase().replace(/\./g, "").replace(/\s+/g, " ");
    if (COUNTRY_ALIASES[key]) return COUNTRY_ALIASES[key];
    if (!countryByName) {
        countryByName = new Map();
        try {
            const names = new Intl.DisplayNames(["en"], { type: "region" });
            for (let i = 65; i <= 90; i += 1) {
                for (let j = 65; j <= 90; j += 1) {
                    const code = String.fromCharCode(i, j);
                    const name = names.of(code);
                    if (name && name.toUpperCase() !== code) countryByName.set(name.toLowerCase(), code);
                }
            }
        } catch (error) {
            countryByName = new Map();
        }
    }
    return countryByName.get(key) || "";
}

function countryFlags(list) {
    const items = Array.isArray(list) ? list : [];
    const flags = items.map((item) => {
        const label = String(item || "").trim();
        if (!label) return "";
        const code = countryCode(label);
        const icon = code ? countryIcon(code) : "";
        if (!icon) return `<span class="country-flag" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`;
        return `<span class="country-flag" title="${escapeHtml(label)}">${icon}</span>`;
    }).filter(Boolean);
    return flags.length ? `<span class="country-flags">${flags.join("")}</span>` : "";
}

function nfoLink(subject, row) {
    const label = subject === "artist" ? "artist.nfo" : "album.nfo";
    if (!row || !row.has_nfo) return `<span class="bad">– ${label}</span>`;
    const stale = !!row.nfo_stale;
    const title = stale ? "Database has changes that are not in this file" : "Show this file";
    return `<button type="button" class="nfo-link ${stale ? "stale" : "ok"}" data-action="view-nfo" data-subject="${subject}" title="${escapeHtml(title)}">✓ ${label}</button>`;
}

function lyricsIcon() {
    // Document with text lines + music double-note. No pencil: the pencil variant is the
    // synced-lyrics editor button in the player bar only.
    return `<svg class="lyrics-icon" viewBox="0 0 24 26" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <!-- Document body: rounded-bottom, folded top-right corner -->
      <path d="M2 2h15.5L23 7.5V22.5a1.5 1.5 0 0 1-1.5 1.5H2A1.5 1.5 0 0 1 .5 22.5V3.5A1.5 1.5 0 0 1 2 2z"/>
      <!-- Folded corner -->
      <path d="M17.5 2.2V7.5H23" stroke-width="1.2"/>
      <!-- Text lines on document -->
      <line x1="3.5" y1="10" x2="13.5" y2="10" stroke-width="1.2"/>
      <line x1="3.5" y1="13" x2="13.5" y2="13" stroke-width="1.2"/>
      <line x1="3.5" y1="16" x2="9" y2="16" stroke-width="1.2"/>
      <!-- Double music note (overlapping lower-right area of doc) -->
      <ellipse cx="11" cy="22" rx="1.9" ry="1.25" transform="rotate(-18 11 22)" fill="currentColor" stroke="none"/>
      <ellipse cx="17" cy="21" rx="1.9" ry="1.25" transform="rotate(-18 17 21)" fill="currentColor" stroke="none"/>
      <line x1="12.7" y1="21.2" x2="12.7" y2="15.2" stroke-width="1.35"/>
      <line x1="18.7" y1="20.2" x2="18.7" y2="14.2" stroke-width="1.35"/>
      <path d="M12.7 15.2 L18.7 14.2 L18.7 15.8 L12.7 16.8 Z" fill="currentColor" stroke="none"/>
    </svg>`;
}

function lyricsMark(have, total) {
    const count = Number(have) || 0;
    const all = Number(total) || 0;
    const tone = !all || !count ? "missing" : (count >= all ? "ok" : "partial");
    const title = `${count} of ${all} tracks have lyrics`;
    return `<span class="lyrics-mark ${tone}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">${lyricsIcon()}<span class="lyrics-count">${count}/${all}</span></span>`;
}

function presentChip(key, label, subject, stale) {
    if (key === "lyrics") return `<span class="chip ok">✓ ${escapeHtml(label)}</span>`;
    if (key === "nfo") {
        const title = stale ? "Database has changes that are not in this file" : "Show this file";
        return `<button type="button" class="chip ${stale ? "stale" : "ok"}" data-action="view-nfo" data-subject="${subject}" title="${escapeHtml(title)}">✓ ${escapeHtml(label)}</button>`;
    }
    return `<button type="button" class="chip ok" data-action="view-chip" data-subject="${subject}" data-focus="${key}" title="Show this artwork">✓ ${escapeHtml(label)}</button>`;
}

function artistChips(artist) {
    const assets = (artist && artist.assets) || {};
    const present = ["artistthumb", "fanart", "clearlogo", "landscape", "banner"].filter((kind) => assets[kind]);
    const nfo = assets.has_nfo || (artist && artist.has_nfo);
    const link = nfoMark("artist.nfo", !!nfo, !!(artist && artist.nfo_stale), nfo ? `data-action="view-nfo" data-subject="artist"` : "");
    return `<div class="chip-row">${artMarks(present, INFO_ART.artist)}${link}</div>`;
}

function albumChips(album, tracks) {
    const assets = new Set(state.album.assets || []);
    if (album.has_artwork) assets.add("front");
    const rows = tracks || [];
    const lyrics = rows.filter((track) => track.lyrics_type && track.lyrics_type !== "none").length;
    const link = nfoMark("album.nfo", !!album.has_nfo, !!album.nfo_stale, album.has_nfo ? `data-action="view-nfo" data-subject="album"` : "");
    return `<div class="chip-row">${artMarks([...assets], INFO_ART.album)}${link}${lyricsMark(lyrics, rows.length)}</div>`;
}

function durationTone(localSeconds, remoteSeconds) {
    const remote = Number(remoteSeconds || 0);
    if (!remote) return "";
    const local = Number(localSeconds || 0);
    if (Math.abs(local - remote) > 3) return "danger";
    return "ok";
}

function renderAligner(host) {
    const rows = state.album.tracks.map((track) => {
        const proposal = proposalFor(track.id);
        const remote = proposal ? Number(proposal.duration_seconds || 0) : 0;
        const local = Number(track.duration_seconds || 0);
        const tone = durationTone(local, remote);
        const delta = remote ? Math.round(local - remote) : 0;
        const sign = delta > 0 ? `+${delta}` : String(delta);
        return { track, proposal, tone, sign, remote };
    });
    const local = rows.map((row) => `<div class="aligner-row" data-side="local" data-track="${escapeHtml(row.track.id)}" data-tone="${row.tone}" draggable="true">
        <span>${escapeHtml(String(row.track.track_number || 0).padStart(2, "0"))} ${escapeHtml(row.track.title || "")}</span>
        <span class="tabular">${formatDuration(row.track.duration_seconds)}</span>
    </div>`).join("");
    const used = new Set(rows.map((row) => String(row.proposal && row.proposal.title || "").toLowerCase()).filter(Boolean));
    const extras = (state.proposal.expected || []).filter((item) => !used.has(String(item.title || "").toLowerCase()));
    const remote = rows.map((row) => `<div class="aligner-row" data-side="remote" data-track="${escapeHtml(row.track.id)}">
        <span>${escapeHtml(row.proposal ? (row.proposal.title || "") : "Unmatched")}</span>
        <span class="delta tabular ${row.tone}">${row.remote ? `${row.sign}s` : "—"}</span>
    </div>`).join("") + extras.map((item) => `<div class="aligner-row">
        <span>${escapeHtml(item.title || "")}</span>
        <span class="delta tabular">${item.duration_seconds ? formatDuration(item.duration_seconds) : "—"}</span>
    </div>`).join("");
    host.innerHTML = `<div class="aligner" id="aligner"><svg class="aligner-svg" id="aligner-svg"></svg><div>${local}</div><div>${remote}</div></div>`;
    bindTrackDrag();
    requestAnimationFrame(drawAlignerLines);
}

function drawAlignerLines() {
    const box = document.getElementById("aligner");
    const svg = document.getElementById("aligner-svg");
    if (!box || !svg) return;
    const rect = box.getBoundingClientRect();
    svg.setAttribute("viewBox", `0 0 ${rect.width} ${rect.height}`);
    const lines = [];
    box.querySelectorAll("[data-side='local']").forEach((row) => {
        const remote = box.querySelector(`[data-side='remote'][data-track="${row.dataset.track}"]`);
        if (!remote) return;
        const from = row.getBoundingClientRect();
        const to = remote.getBoundingClientRect();
        const x1 = from.right - rect.left;
        const y1 = from.top + from.height / 2 - rect.top;
        const x2 = to.left - rect.left;
        const y2 = to.top + to.height / 2 - rect.top;
        lines.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="${row.dataset.tone === "danger" ? "danger" : ""}"></line>`);
    });
    svg.innerHTML = lines.join("");
}
