const MEDIA_TYPES = ["music", "movies", "sets", "tv"];
const MEDIA_TITLES = { music: "Music", movies: "Movies", sets: "Movie sets", tv: "TV shows" };

state.media = MEDIA_TYPES.includes(localStorage.getItem("curator.media"))
    ? localStorage.getItem("curator.media")
    : "music";
state.mediaTotals = null;

function initMedia() {
    const nav = document.querySelector(".media-switch");
    if (nav) {
        nav.addEventListener("click", (event) => {
            const tab = event.target.closest(".media-tab");
            if (tab) switchMedia(tab.dataset.media);
        });
        nav.addEventListener("keydown", onMediaKey);
    }
    applyMedia();
    loadMediaTotals();
}

function onMediaKey(event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const step = event.key === "ArrowRight" ? 1 : -1;
    const index = MEDIA_TYPES.indexOf(state.media);
    const next = MEDIA_TYPES[(index + step + MEDIA_TYPES.length) % MEDIA_TYPES.length];
    switchMedia(next);
    const tab = document.querySelector(`.media-tab[data-media="${next}"]`);
    if (tab) tab.focus();
    event.preventDefault();
    event.stopPropagation();
}

function switchMedia(name) {
    if (!MEDIA_TYPES.includes(name) || name === state.media) return;
    state.media = name;
    localStorage.setItem("curator.media", name);
    applyMedia();
    loadMediaTotals();
}

function applyMedia() {
    document.body.dataset.media = state.media;
    document.querySelectorAll(".media-tab").forEach((tab) => {
        const on = tab.dataset.media === state.media;
        tab.setAttribute("aria-selected", on ? "true" : "false");
        tab.tabIndex = on ? 0 : -1;
    });
    const title = document.getElementById("video-stage-title");
    if (title) title.textContent = MEDIA_TITLES[state.media] || "";
    closeScanMenu();
    renderScanButton(state.scan || {});
    if (state.media !== "music") {
        const audio = document.getElementById("player");
        if (audio && !audio.paused) audio.pause();
    }
    if (typeof renderVideoSelectBar === "function") renderVideoSelectBar();
    if (state.media === "music") {
        if (state.scan) pollSystem();
    } else {
        paintVideoScanFooter();
        renderVideo();
    }
    paintMediaTotals();
}

async function loadMediaTotals() {
    const boot = typeof watchBoot === "function" ? watchBoot("totals") : null;
    try {
        state.mediaTotals = await api("/api/v1/totals");
    } catch (error) {
        state.mediaTotals = null;
    } finally {
        if (boot) boot.done();
    }
    paintMediaTotals();
}

function mediaTotalsText(kind) {
    const totals = (state.mediaTotals || {})[kind] || {};
    if (kind === "music") return `${totals.artists || 0} artists · ${totals.albums || 0} albums · ${totals.tracks || 0} tracks`;
    if (kind === "movies") return `${totals.movies || 0} movies`;
    if (kind === "sets") return `${totals.sets || 0} sets`;
    if (kind === "tv") return `${totals.shows || 0} shows · ${totals.seasons || 0} seasons · ${totals.episodes || 0} episodes`;
    return "";
}

function statPill(cls, title, text) {
    return `<span class="pill ${cls}" title="${escapeHtml(title)}">${text}</span>`;
}

function paintMediaTotals() {
    const counts = document.getElementById("video-stage-counts-center");
    if (counts) counts.textContent = mediaTotalsText(state.media);
    const host = document.getElementById("video-library-stats");
    if (!host) return;
    const totals = (state.mediaTotals || {})[state.media] || {};
    const size = totals.bytes && typeof fmtSize === "function" ? fmtSize(totals.bytes) : "";
    const hours = Number(totals.seconds) > 0 ? `${Math.round(Number(totals.seconds) / 3600).toLocaleString()} h` : "";
    let pills = "";
    if (state.media === "movies") {
        pills = [
            statPill("pill-accent", "Movies", `${Number(totals.movies || 0).toLocaleString()} movies`),
            size ? statPill("pill-mauve", "Size", size) : "",
            hours ? statPill("pill-success", "Runtime", hours) : "",
        ].filter(Boolean).join("");
    } else if (state.media === "sets") {
        pills = [
            statPill("pill-accent", "Movie sets", `${Number(totals.sets || 0).toLocaleString()} sets`),
            statPill("pill-mauve", "Movies in sets", `${Number(totals.movies || 0).toLocaleString()} movies`),
        ].filter(Boolean).join("");
    } else if (state.media === "tv") {
        pills = [
            statPill("pill-accent", "TV shows", `${Number(totals.shows || 0).toLocaleString()} shows`),
            statPill("pill-mauve", "Seasons", `${Number(totals.seasons || 0).toLocaleString()} seasons`),
            statPill("pill-success", "Episodes", `${Number(totals.episodes || 0).toLocaleString()} episodes`),
        ].filter(Boolean).join("");
    } else if (state.media === "music") {
        pills = [
            statPill("pill-accent", "Artists", `${Number(totals.artists || 0).toLocaleString()} artists`),
            statPill("pill-mauve", "Albums", `${Number(totals.albums || 0).toLocaleString()} albums`),
            statPill("pill-success", "Tracks", `${Number(totals.tracks || 0).toLocaleString()} tracks`),
        ].filter(Boolean).join("");
    }
    host.innerHTML = pills;
}
