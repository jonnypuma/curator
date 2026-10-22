/**
 * Keeps layout choices on the server as well as in the browser.
 *
 * Columns, their order and widths, pane widths, sort and a few view options were only in
 * localStorage, so another address, another browser or cleared site data reset them. This script
 * runs first: it asks the server for the saved copy and writes it into localStorage before the other
 * scripts read it, then mirrors every later change back. The first time (nothing saved on the
 * server yet) the browser's own values are uploaded, so nothing is lost.
 */
(function () {
    const KEYS = [
        "resonance.columns", "resonance.columnWidths", "resonance.panes", "resonance.librarySort",
        "resonance.density", "resonance.theme", "resonance.reviewCollapsed", "resonance.bioCollapsed",
        "curator.movieColumns", "curator.tvColumns", "curator.movieWidths", "curator.tvWidths",
        "curator.movieSort", "curator.tvSort", "curator.setSort", "curator.videoLeft", "curator.videoRight",
    ];
    const watched = new Set(KEYS);
    const nativeSet = Storage.prototype.setItem;
    const nativeRemove = Storage.prototype.removeItem;
    const URL = "/api/v1/ui-state";
    let pending = {};
    let timer = null;

    function flush() {
        timer = null;
        const values = pending;
        pending = {};
        if (!Object.keys(values).length) return;
        try {
            fetch(URL, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ values }),
                keepalive: true,
            }).catch(() => {});
        } catch (error) { /* saving must never break the page */ }
    }

    function queue(values) {
        Object.assign(pending, values);
        if (!timer) timer = setTimeout(flush, 500);
    }

    // Load: a synchronous request, because the scripts that follow read localStorage right away.
    let saved = null;
    try {
        const request = new XMLHttpRequest();
        request.open("GET", URL, false);
        request.send();
        if (request.status === 200) saved = (JSON.parse(request.responseText) || {}).state || {};
    } catch (error) { saved = null; }

    if (saved !== null) {
        const upload = {};
        for (const key of KEYS) {
            if (typeof saved[key] === "string") {
                if (localStorage.getItem(key) !== saved[key]) nativeSet.call(localStorage, key, saved[key]);
            } else {
                const local = localStorage.getItem(key);
                if (local !== null) upload[key] = local;
            }
        }
        if (Object.keys(upload).length) queue(upload);
    }

    Storage.prototype.setItem = function (key, value) {
        nativeSet.call(this, key, value);
        if (this === window.localStorage && watched.has(key)) queue({ [key]: String(value) });
    };
    Storage.prototype.removeItem = function (key) {
        nativeRemove.call(this, key);
        if (this === window.localStorage && watched.has(key)) queue({ [key]: null });
    };
    window.addEventListener("pagehide", flush);
})();
