function paletteActions() {
    return [
        { id: "scan", label: "Scan active library" },
        { id: "video-movies", label: "Go to Movies" },
        { id: "video-tv", label: "Go to TV Shows" },
        { id: "video-sets", label: "Go to Movie Sets" },
        { id: "music", label: "Go to Music" },
        { id: "queue", label: "Open Webhook Queue" },
        { id: "insights", label: "Open Library Analytics" },
        { id: "tags", label: "Open Tag Manager" },
        { id: "languages", label: "Open Language Defaults" },
        { id: "duplicates", label: "Open Duplicates & Copies" },
        { id: "settings", label: "Open Settings" },
        { id: "about", label: "About Curator and library health" },
        { id: "shortcuts", label: "Keyboard shortcuts" },
        { id: "rename", label: "Rename selection" },
        { id: "artwork", label: "Artwork harvester" },
        { id: "gold", label: "Gold filter" },
        { id: "theme-mocha", label: "Theme: Catppuccin Mocha" },
        { id: "theme-macchiato", label: "Theme: Catppuccin Macchiato" },
        { id: "theme-nord", label: "Theme: Nord" },
        { id: "theme-dracula", label: "Theme: Dracula" },
        { id: "theme-oled", label: "Theme: Dark OLED" },
        { id: "theme-olive", label: "Theme: Olive Garden" },
        { id: "theme-sunset", label: "Theme: Ocean Sunset" },
        { id: "theme-deepsea", label: "Theme: Deep Sea" },
        { id: "theme-nightfall", label: "Theme: Vivid Nightfall" },
        { id: "theme-coastal", label: "Theme: Coastal Blues" },
        { id: "theme-lavender", label: "Theme: Soft Lavender" },
        { id: "theme-candle", label: "Theme: Candlelit Library" },
    ];
}

// A small cached copy of the poster, so a long result list stays light.
function paletteArt(path) {
    return typeof path === "string" && path && typeof artUrl === "function" ? artUrl(path, 160) : "";
}

function paletteItems(query, actions, artists) {
    const text = String(query || "").trim();
    const actionRows = actions.map((item) => ({ kind: "action", id: item.id, label: item.label }));
    if (!text || text === ">") return actionRows;
    if (text.startsWith(">")) {
        const needle = text.slice(1).trim().toLowerCase();
        if (!needle) return actionRows;
        return actionRows.filter((row) => row.label.toLowerCase().includes(needle) || row.id.toLowerCase().includes(needle));
    }
    const needle = text.toLowerCase();
    const rows = [];

    // Search movies
    if (state.video && Array.isArray(state.video.movies)) {
        state.video.movies.forEach((m) => {
            const title = m.title || "";
            const year = m.year ? ` (${m.year})` : "";
            if (title.toLowerCase().includes(needle)) {
                rows.push({ kind: "movie", id: String(m.id), label: `${title}${year}`, hint: "Movie", thumb: paletteArt(m.poster) });
            }
        });
    }

    // Search TV shows
    if (state.video && Array.isArray(state.video.shows)) {
        state.video.shows.forEach((s) => {
            const title = s.title || "";
            const year = s.year ? ` (${s.year})` : "";
            if (title.toLowerCase().includes(needle)) {
                rows.push({ kind: "show", id: String(s.id), label: `${title}${year}`, hint: "TV Show", thumb: paletteArt(s.poster) });
            }
        });
    }

    // Search Movie sets
    if (state.video && Array.isArray(state.video.sets)) {
        state.video.sets.forEach((set) => {
            const title = set.name || set.title || "";
            if (title.toLowerCase().includes(needle)) {
                rows.push({ kind: "set", id: String(set.id), label: title, hint: "Movie Set", thumb: paletteArt(set.artwork && set.artwork.poster) });
            }
        });
    }

    // Search artists and albums
    (artists || []).forEach((artist) => {
        const name = artist.name || "";
        if (name.toLowerCase().includes(needle)) rows.push({ kind: "artist", id: String(artist.id || ""), label: name, hint: "Artist" });
        (artist.albums || []).forEach((album) => {
            const title = album.title || "";
            if (title.toLowerCase().includes(needle) || name.toLowerCase().includes(needle)) {
                rows.push({ kind: "album", id: String(album.id || ""), label: title, hint: name, thumb: album.id ? `/api/albums/${encodeURIComponent(album.id)}/cover?w=160` : "" });
            }
        });
    });

    // Also match actions
    actionRows.forEach((act) => {
        if (act.label.toLowerCase().includes(needle) || act.id.toLowerCase().includes(needle)) {
            rows.push(act);
        }
    });

    return rows;
}

function togglePalette() {
    const palette = document.getElementById("palette");
    if (palette.classList.contains("hidden")) {
        palette.classList.remove("hidden");
        const input = document.getElementById("palette-input");
        input.value = "";
        state.paletteIndex = 0;
        renderPalette();
        input.focus();
        return;
    }
    closePalette();
}

function closePalette() {
    document.getElementById("palette").classList.add("hidden");
}

function renderPalette() {
    const input = document.getElementById("palette-input");
    const host = document.getElementById("palette-list");
    const rows = paletteItems(input.value, paletteActions(), state.artists);
    if (state.paletteIndex >= rows.length) state.paletteIndex = 0;
    host.innerHTML = rows.map((row, index) => `<button type="button" class="palette-row${index === state.paletteIndex ? " active" : ""}" data-action="palette-pick" data-kind="${escapeHtml(row.kind)}" data-id="${escapeHtml(row.id)}">
        ${row.thumb ? `<img class="palette-thumb" src="${escapeHtml(row.thumb)}" alt="" loading="lazy" onerror="this.remove()">` : ""}<span class="palette-label">${escapeHtml(row.label)}</span><span class="muted">${escapeHtml(row.hint || row.kind)}</span>
    </button>`).join("") || `<p class="muted">No matches in the loaded library.</p>`;
}

function movePalette(key) {
    const rows = [...document.querySelectorAll("#palette-list .palette-row")];
    if (!rows.length) return;
    if (key === "ArrowDown") state.paletteIndex = (state.paletteIndex + 1) % rows.length;
    if (key === "ArrowUp") state.paletteIndex = (state.paletteIndex - 1 + rows.length) % rows.length;
    if (key === "Enter") {
        const row = rows[state.paletteIndex];
        if (row) runPalette(row.dataset.kind, row.dataset.id);
        return;
    }
    renderPalette();
}

function runPalette(kind, id) {
    closePalette();
    if (kind === "artist") {
        if (state.media !== "music") switchMedia("music");
        return selectArtist(id);
    }
    if (kind === "album") {
        if (state.media !== "music") switchMedia("music");
        return selectAlbum(id);
    }
    if (kind === "movie") {
        if (state.media !== "movies") switchMedia("movies");
        if (typeof openMovie === "function") return openMovie(id);
        return;
    }
    if (kind === "show") {
        if (state.media !== "tv") switchMedia("tv");
        if (typeof openShow === "function") return openShow(id);
        return;
    }
    if (kind === "set") {
        if (state.media !== "sets") switchMedia("sets");
        if (typeof openSet === "function") return openSet(id);
        return;
    }
    if (id === "video-movies") return switchMedia("movies");
    if (id === "video-tv") return switchMedia("tv");
    if (id === "video-sets") return switchMedia("sets");
    if (id === "music") return switchMedia("music");
    if (id === "about") return typeof openAbout === "function" ? openAbout() : null;
    if (id === "shortcuts") {
        const sheet = document.getElementById("shortcuts-modal");
        return sheet ? sheet.classList.remove("hidden") : null;
    }
    if (id === "queue") return typeof openQueuePanel === "function" ? openQueuePanel() : null;
    if (id === "insights") return typeof openInsights === "function" ? openInsights() : null;
    if (id === "tags") return typeof openTagManager === "function" ? openTagManager(null) : null;
    if (id === "languages") return typeof openLanguageDefaults === "function" ? openLanguageDefaults() : null;
    if (id === "duplicates") return typeof openDuplicates === "function" ? openDuplicates() : null;
    if (id === "settings") return typeof openSettings === "function" ? openSettings() : null;
    if (id === "scan") {
        if (state.media === "music") return runAction(() => scan(false, "incremental"));
        if (typeof openVideoScanModal === "function") return openVideoScanModal(state.media);
        return;
    }
    if (id === "rename") {
        if (state.media === "music") {
            if (!state.album && !state.selected.size) {
                notify("Open an album or select albums before renaming.", "info");
                return;
            }
            return openRenameModal();
        }
        if (typeof openSelectionRename === "function") return openSelectionRename();
        return;
    }
    if (id === "artwork") {
        if (state.media === "music") return openArtwork();
        if (typeof openVideoArtPicker === "function") {
            if (state.media === "movies" && state.video.movieId) return openVideoArtPicker("movie", state.video.movieId, "");
            if (state.media === "sets" && state.video.setId) return openVideoArtPicker("set", state.video.setId, "");
            if (state.media === "tv" && state.video.tvSel && state.video.tvSel.id) return openVideoArtPicker(state.video.tvSel.type, state.video.tvSel.id, "");
        }
        notify("Pick an item first.", "info");
        return;
    }
    if (id === "gold") {
        state.filter = "gold";
        sessionStorage.setItem("resonance.filter", "gold");
        const filter = document.getElementById("library-filter");
        if (filter) filter.value = "gold";
        if (typeof syncLibraryFilterButton === "function") syncLibraryFilterButton();
        return loadLibrary();
    }
    if (id && id.startsWith("theme-")) return applyTheme(id.slice(6));
}

function showUndo(message) {
    const bar = document.getElementById("snackbar");
    if (!bar) return;
    bar.classList.remove("hidden");
    bar.innerHTML = `<span>${escapeHtml(message)}</span><button type="button" data-action="undo-snack">Undo</button>`;
}

function hideUndo() {
    const bar = document.getElementById("snackbar");
    if (bar) bar.classList.add("hidden");
}

let waveGraph = null;
function ensureWave(audio) {
    if (waveGraph) return waveGraph;
    try {
        const context = new AudioContext();
        const source = context.createMediaElementSource(audio);
        const analyser = context.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        analyser.connect(context.destination);
        waveGraph = { context, analyser, peaks: [] };
        return waveGraph;
    } catch (error) {
        return null;
    }
}

function drawWave() {
    const audio = document.getElementById("player");
    const canvas = document.getElementById("player-wave");
    if (!waveGraph || !canvas || !audio) return;
    const data = new Uint8Array(waveGraph.analyser.fftSize);
    waveGraph.analyser.getByteTimeDomainData(data);
    let peak = 0;
    for (let index = 0; index < data.length; index += 1) peak = Math.max(peak, Math.abs(data[index] - 128));
    waveGraph.peaks.push(peak);
    if (waveGraph.peaks.length > canvas.width) waveGraph.peaks.shift();
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#89b4fa";
    waveGraph.peaks.forEach((level, index) => {
        const height = Math.max(1, (level / 128) * canvas.height);
        ctx.fillRect(index, (canvas.height - height) / 2, 1, height);
    });
    if (!audio.paused) requestAnimationFrame(drawWave);
}

function syncSeek() {
    const audio = document.getElementById("player");
    const clock = document.getElementById("player-clock");
    if (!audio || !clock) return;
    const playing = Boolean(audio.currentSrc) && !audio.paused && !audio.ended;
    clock.disabled = !playing;
}

function setPlayerVolume(audio, level) {
    const value = Math.min(1, Math.max(0, Number(level) || 0));
    audio.volume = value;
    localStorage.setItem("resonance.volume", String(value));
    const mark = document.getElementById("player-knob-mark");
    if (mark) mark.setAttribute("transform", `rotate(${(-140 + value * 280).toFixed(1)} 32 30)`);
    const knob = document.getElementById("player-volume");
    if (knob) {
        knob.setAttribute("aria-valuenow", String(Math.round(value * 100)));
        knob.setAttribute("aria-valuetext", `${Math.round(value * 100)} percent`);
    }
}

function seekFromClock(event) {
    const audio = document.getElementById("player");
    const clock = document.getElementById("player-clock");
    if (!audio || !clock || clock.disabled || !audio.currentSrc) return;
    const rect = clock.getBoundingClientRect();
    if (!rect.width) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    audio.currentTime = ratio * (playbackCap(audio) || 15);
    paintPlayerClock(audio);
}

function bindPlayer() {
    const audio = document.getElementById("player");
    const volume = document.getElementById("player-volume");
    const clock = document.getElementById("player-clock");
    const stored = localStorage.getItem("resonance.volume");
    const initial = stored !== null ? Number(stored) : 0.9;
    setPlayerVolume(audio, Number.isFinite(initial) ? initial : 0.9);
    volume.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        const startX = event.clientX;
        const start = audio.volume;
        volume.setPointerCapture(event.pointerId);
        const move = (next) => setPlayerVolume(audio, start + (next.clientX - startX) / 120);
        const end = () => {
            volume.removeEventListener("pointermove", move);
            volume.removeEventListener("pointerup", end);
            volume.removeEventListener("pointercancel", end);
        };
        volume.addEventListener("pointermove", move);
        volume.addEventListener("pointerup", end);
        volume.addEventListener("pointercancel", end);
    });
    volume.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const step = event.shiftKey ? 0.1 : 0.05;
        setPlayerVolume(audio, audio.volume + (event.key === "ArrowRight" ? step : -step));
    });
    clock.addEventListener("pointerdown", seekFromClock);
    clock.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const step = event.shiftKey ? 5 : 1;
        const cap = playbackCap(audio) || 15;
        audio.currentTime = Math.min(cap, Math.max(0, (Number(audio.currentTime) || 0) + (event.key === "ArrowRight" ? step : -step)));
        paintPlayerClock(audio);
    });
    ["play", "pause", "ended", "emptied"].forEach((name) => audio.addEventListener(name, () => {
        syncSeek();
        paintPlayerStatus(audio);
        paintPlayerClock(audio);
        if (name === "play") drawWave();
    }));
    syncSeek();
    paintPlayerClock(audio);
    paintPlayerIdentity();
}

function syncPreviewControls() {
    const play = document.getElementById("player-toggle");
    const span = document.getElementById("player-span");
    const audio = document.getElementById("player");
    if (play) play.textContent = state.fullPlayback ? "Full song" : "Preview";
    if (span) {
        span.classList.toggle("is-full", !!state.fullPlayback);
        span.setAttribute("aria-pressed", state.fullPlayback ? "true" : "false");
        span.title = state.fullPlayback
            ? "Whole file. Click for a 15 second preview."
            : "15 second preview. Click for the whole file.";
        span.setAttribute("aria-label", state.fullPlayback ? "Full song" : "Preview");
    }
    paintPlayerStatus(audio);
    paintPlayerIdentity();
    paintPlayerClock(audio);
}

function togglePlaybackSpan() {
    state.fullPlayback = !state.fullPlayback;
    const audio = document.getElementById("player");
    if (audio && audio.currentSrc) {
        audio.dataset.mode = state.fullPlayback ? "full" : "preview";
        if (!state.fullPlayback && audio.currentTime >= 15) audio.pause();
        applySeekLimit(audio);
    }
    syncPreviewControls();
}

function bindLoupe() {
    const body = document.getElementById("artwork-body");
    body.addEventListener("mousemove", (event) => {
        const card = event.target.closest(".art-card");
        const loupe = document.getElementById("loupe");
        if (!card) {
            loupe.classList.add("hidden");
            return;
        }
        const image = card.querySelector("img");
        if (!image) return;
        const rect = image.getBoundingClientRect();
        const x = rect.width ? (event.clientX - rect.left) / rect.width : 0.5;
        const y = rect.height ? (event.clientY - rect.top) / rect.height : 0.5;
        loupe.classList.remove("hidden");
        loupe.style.backgroundImage = `url("${image.src}")`;
        loupe.style.backgroundPosition = `${Math.min(100, Math.max(0, x * 100))}% ${Math.min(100, Math.max(0, y * 100))}%`;
        loupe.style.left = `${Math.min(window.innerWidth - 160, event.clientX + 18)}px`;
        loupe.style.top = `${Math.min(window.innerHeight - 160, event.clientY + 18)}px`;
    });
    body.addEventListener("mouseleave", () => document.getElementById("loupe").classList.add("hidden"));
    bindCompareSlider("compare-slider", "compare-candidate");
    bindCompareSlider("video-compare-slider", "video-compare-candidate");
}

function bindCompareSlider(sliderId, imageId) {
    const slider = document.getElementById(sliderId);
    const image = document.getElementById(imageId);
    if (!slider || !image) return;
    slider.addEventListener("input", () => {
        image.style.clipPath = `inset(0 ${100 - Number(slider.value)}% 0 0)`;
    });
}

function sizeCompareFrame(frame, image) {
    const box = frame && frame.querySelector(".art-compare-frame");
    const stage = frame && frame.querySelector(".art-compare-stage");
    if (!box || !image || !image.naturalWidth || !image.naturalHeight) return;
    const workspace = frame.parentElement;
    const availableH = workspace && workspace.clientHeight ? workspace.clientHeight : Math.round(window.innerHeight * 0.62);
    const maxH = Math.max(96, availableH - 72);
    const chosen = Number(frame.dataset.compareWidth);
    const paneW = chosen || frame.clientWidth || 320;
    if (chosen) frame.style.width = `${Math.round(paneW)}px`;
    const maxW = Math.max(120, (frame.clientWidth || paneW) - 24);
    const ratio = image.naturalWidth / image.naturalHeight;
    let width = maxW;
    let height = width / ratio;
    if (height > maxH) {
        height = maxH;
        width = height * ratio;
    }
    if (stage) stage.style.width = `${Math.round(width)}px`;
    box.style.width = stage ? "100%" : `${Math.round(width)}px`;
    box.style.height = `${Math.round(height)}px`;
}

function bindArtSplit() {
    document.querySelectorAll("[data-art-split]").forEach((handle) => {
        if (handle.dataset.bound) return;
        handle.dataset.bound = "1";
        handle.addEventListener("pointerdown", (event) => {
            const modal = handle.closest(".modal-content");
            const frame = modal && modal.querySelector(".art-compare");
            const box = frame && frame.querySelector(".art-compare-frame");
            if (!frame || !box) return;
            const startX = event.clientX;
            const startW = frame.getBoundingClientRect().width;
            const move = (ev) => {
                const workspace = frame.parentElement;
                const limit = workspace ? workspace.clientWidth * 0.72 : window.innerWidth * 0.6;
                const next = Math.max(180, Math.min(limit, startW + (ev.clientX - startX)));
                frame.dataset.compareWidth = String(Math.round(next));
                frame.style.width = `${Math.round(next)}px`;
                const image = frame.querySelector("#compare-current, #video-compare-current");
                sizeCompareFrame(frame, image && image.naturalWidth ? image : frame.querySelector("img"));
            };
            const stop = () => {
                window.removeEventListener("pointermove", move);
                window.removeEventListener("pointerup", stop);
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", stop);
            event.preventDefault();
        });
    });
}

function watchCompareSize(frame, current, candidate) {
    const fit = () => sizeCompareFrame(frame, current && current.naturalWidth ? current : candidate);
    [current, candidate].forEach((image) => {
        if (image) image.onload = fit;
    });
    fit();
}

// No current image, or one that cannot be loaded, is shown as a dark half with a label, not a broken picture.
function markNoCurrent(frame, current, missing) {
    if (missing) {
        frame.dataset.noCurrent = "1";
        if (current) current.removeAttribute("src");
    } else {
        delete frame.dataset.noCurrent;
    }
}

function revealCompare(frame, current, candidate, label, currentUrl, candidateUrl, caption) {
    if (!frame) return;
    frame.classList.remove("hidden");
    markNoCurrent(frame, current, !currentUrl);
    if (current) current.onerror = () => markNoCurrent(frame, current, true);
    if (label) label.textContent = caption || "Compare";
    const slider = frame.querySelector("input[type=range]");
    if (candidate) {
        if (candidateUrl) candidate.src = candidateUrl;
        else candidate.removeAttribute("src");
    }
    if (!currentUrl) {
        if (slider) slider.value = "50";
        if (candidate) candidate.style.clipPath = "inset(0 50% 0 0)";
        watchCompareSize(frame, null, candidate);
        return;
    }
    if (current) current.src = currentUrl;
    if (slider) slider.value = "50";
    if (candidate) candidate.style.clipPath = "inset(0 50% 0 0)";
    watchCompareSize(frame, current, candidate);
}

function currentArtUrl(asset, artistMode) {
    if (artistMode) {
        const id = (state.artworkTarget && state.artworkTarget.artistId) || state.artistId;
        return id ? `/api/artists/${id}/art/${encodeURIComponent(asset)}` : "";
    }
    const album = state.album && state.album.album;
    const id = (state.artworkTarget && state.artworkTarget.albumId) || (album && album.id);
    return id ? `/api/albums/${id}/art/${encodeURIComponent(asset)}` : "";
}

// Gallery cards show a small cached copy (?w=); comparing quality needs the original.
function fullImageUrl(src) {
    if (!src) return "";
    try {
        const url = new URL(src, window.location.href);
        if (url.origin !== window.location.origin) return src;
        url.searchParams.delete("w");
        return url.pathname + url.search;
    } catch (error) {
        return src;
    }
}

function showCompare(card) {
    const frame = document.getElementById("art-compare");
    const label = document.getElementById("compare-label");
    const current = document.getElementById("compare-current");
    const candidateImage = document.getElementById("compare-candidate");
    if (!frame || !card || !current || !candidateImage) return;
    const asset = card.dataset.asset || "front";
    const artistMode = !!(state.artworkTarget && state.artworkTarget.subject === "artist");
    const image = card.querySelector("img");
    const url = currentArtUrl(asset, artistMode);
    frame.dataset.asset = asset;
    const suggested = card.dataset.suggested === "1" && card.dataset.selected !== "1";
    const caption = !url
        ? `Preview ${assetLabel(asset)} · no artwork saved yet`
        : (suggested ? `Compare ${assetLabel(asset)} · suggested` : `Compare ${assetLabel(asset)}`);
    revealCompare(frame, current, candidateImage, label, url ? `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}` : "", image ? fullImageUrl(image.src) : "", caption);
}
