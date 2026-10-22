// Phone layout: below 800 px the three music panes show one at a time, chosen by the tabs above them.

function showPane(name) {
    document.body.dataset.pane = name;
    document.querySelectorAll("[data-pane-tab]").forEach((button) => {
        button.setAttribute("aria-pressed", button.dataset.paneTab === name ? "true" : "false");
    });
    // The lists draw only the rows that fit their height. While a pane is hidden that height is zero, so ask them
    // to redraw once it is back on screen.
    if (name !== "left") return;
    requestAnimationFrame(() => {
        const music = document.body.dataset.media === "music";
        const list = document.getElementById(music ? "tree" : "video-list");
        if (!list || !list.clientHeight) return;
        // A hidden pane loses its scroll position; put it back, then draw the rows that fit.
        const saved = music ? state.treeScroll : state.videoListScroll;
        if (Number.isFinite(saved) && list.scrollTop !== saved) list.scrollTop = saved;
        if (music) {
            if (state.musicViewMode !== "grid" && typeof paintTreeWindow === "function") paintTreeWindow(true);
        } else if (typeof paintVideoRows === "function") {
            paintVideoRows();
        }
    });
}

document.addEventListener("click", (event) => {
    const tab = event.target && event.target.closest ? event.target.closest("[data-pane-tab]") : null;
    if (tab) showPane(tab.dataset.paneTab);
});

// Opening an artist or album moves to the pane that shows it; picking a track moves to its details.
// Movies, shows, seasons, episodes and sets use two panes: the list and the details. A refresh of the open item
// (keepScroll or force) must not pull the phone away from the list.
function followToPane(fn, pane, media, refreshArg) {
    if (typeof window[fn] !== "function") return;
    const original = window[fn];
    window[fn] = function (...args) {
        const music = document.body.dataset.media === "music";
        const refresh = refreshArg !== undefined && args[refreshArg];
        if (window.matchMedia("(max-width: 800px)").matches && music === (media === "music") && !refresh) showPane(pane);
        return original.apply(this, args);
    };
}
document.addEventListener("DOMContentLoaded", () => {
    followToPane("selectArtist", "center", "music");
    followToPane("selectAlbum", "center", "music");
    followToPane("selectTrack", "right", "music");
    followToPane("openMovie", "center", "video", 1);
    followToPane("openShow", "center", "video");
    followToPane("openSeason", "center", "video", 2);
    followToPane("openEpisode", "center", "video", 1);
    followToPane("openSet", "center", "video");
    new MutationObserver(() => showPane("left")).observe(document.body, { attributes: true, attributeFilter: ["data-media"] });
    showPane("left");
});
