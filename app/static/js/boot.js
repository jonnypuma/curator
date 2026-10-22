let bootClient = null;
let bootClosing = false;
let bootLibraryTimer = null;
let bootLibraryEase = 0;
let bootHeartbeatTimer = null;
const bootStartTime = performance.now();

// Everything the loading screen learns is also sent to the server log (docker logs), because the
// browser console is easy to miss and a script that fails to load leaves nothing else behind.
let bootReports = 0;
const bootReported = new Set();

function bootReport(level, message, where) {
    if (bootReports >= 25) return;
    bootReports += 1;
    try {
        fetch("/api/v1/client-log", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ level, message: String(message || ""), where: where || location.pathname }),
            keepalive: true,
        }).catch(() => {});
    } catch (error) { /* reporting must never break the page */ }
}

function bootError(...args) {
    console.error(...args);
    const text = args.map((item) => (item && item.stack) || (item && item.message) || String(item)).join(" ");
    bootReport("error", text);
}

window.addEventListener("error", (event) => {
    const target = event.target;
    if (target && target !== window && (target.src || target.href)) {
        bootReport("error", `could not load ${target.src || target.href}`);
        return;
    }
    const where = event.filename ? `${event.filename.replace(location.origin, "")}:${event.lineno || 0}:${event.colno || 0}` : "";
    bootReport("error", event.message || "script error", where);
}, true);

window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    bootReport("error", `unhandled rejection: ${(reason && (reason.stack || reason.message)) || reason}`);
});

/** A visible line under the loading step once something has taken a while (no devtools needed). */
function showBootDetail(text) {
    let node = document.getElementById("boot-detail");
    if (!node) {
        const step = document.getElementById("boot-step");
        if (!step || !step.parentNode) return;
        node = document.createElement("p");
        node.id = "boot-detail";
        node.className = "boot-step";
        step.parentNode.insertBefore(node, step.nextSibling);
    }
    node.textContent = text || "";
}

function setBootBar(fraction) {
    const fill = document.getElementById("boot-bar-fill");
    const bar = document.getElementById("boot-bar");
    const value = Math.max(0, Math.min(1, Number(fraction) || 0));
    if (fill) fill.style.width = `${Math.round(value * 1000) / 10}%`;
    if (bar) bar.setAttribute("aria-valuenow", String(Math.round(value * 100)));
}

function setBootStep(text) {
    const node = document.getElementById("boot-step");
    if (node) node.textContent = text || "";
}

function bootClientSteps() {
    const media = state.media;
    const steps = [];
    if (media === "movies" || media === "tv" || media === "sets") {
        const name = media === "movies" ? "movies" : media === "tv" ? "TV shows" : "movie sets";
        steps.push({ id: "video", label: `Loading ${name}`, library: true });
    }
    steps.push({ id: "music", label: "Loading the music library", library: true });
    steps.push(
        { id: "settings", label: "Loading settings" },
        { id: "system", label: "Loading status" },
    );
    if (media === "movies" || media === "tv" || media === "sets") {
        steps.push(
            { id: "scan", label: "Checking scans" },
            { id: "files", label: "Checking file jobs" },
        );
    }
    steps.push(
        { id: "totals", label: "Counting libraries" },
        { id: "matches", label: "Restoring matches" },
    );
    if (media === "movies" || media === "tv" || media === "sets") steps.push({ id: "filters", label: "Loading saved filters" });
    return steps;
}

function stopLibraryEase() {
    clearInterval(bootLibraryTimer);
    bootLibraryTimer = null;
    bootLibraryEase = 0;
}

function startLibraryEase() {
    if (bootLibraryTimer) return;
    bootLibraryEase = 0;
    const started = performance.now();
    bootLibraryTimer = setInterval(() => {
        const seconds = (performance.now() - started) / 1000;
        bootLibraryEase = 1 - Math.exp(-seconds / 35);
        paintClientBoot();
    }, 400);
}

function paintClientBoot() {
    if (!bootClient) return;
    const libraries = bootClient.filter((step) => step.library);
    const quick = bootClient.filter((step) => !step.library);
    const libraryDone = libraries.filter((step) => step.done).length;
    const quickDone = quick.filter((step) => step.done).length;
    const librarySpan = 0.4;
    const quickSpan = 0.1;
    const slice = libraries.length ? librarySpan / libraries.length : librarySpan;
    let value = 0.5 + slice * libraryDone;
    const libraryRunning = libraries.some((step) => step.started && !step.done);
    if (libraryRunning) value += slice * 0.85 * bootLibraryEase;
    else value += libraries.length ? 0 : librarySpan;
    value += quick.length ? quickSpan * (quickDone / quick.length) : quickSpan;
    setBootBar(Math.min(value, libraryRunning ? 0.9 : 1));
    if (bootClient.every((step) => step.done)) {
        stopLibraryEase();
        stopBootHeartbeat();
        setBootStep("Opening…");
        completeBootBar();
        return;
    }
    const running = libraries.filter((step) => step.started && !step.done);
    if (libraries.some((step) => !step.done)) {
        setBootStep("Loading libraries");
        return;
    }
    const active = running[0] || bootClient.find((step) => step.started && !step.done) || bootClient.find((step) => !step.done);
    setBootStep(active ? active.label : "Opening…");
}

function startBootHeartbeat() {
    if (bootHeartbeatTimer) clearInterval(bootHeartbeatTimer);
    bootHeartbeatTimer = setInterval(() => {
        if (bootClosing || !bootClient) {
            stopBootHeartbeat();
            return;
        }
        const pending = bootClient.filter((s) => !s.done);
        if (pending.length === 0) {
            stopBootHeartbeat();
            return;
        }
        const totalSec = ((performance.now() - bootStartTime) / 1000).toFixed(1);
        const details = pending.map((s) => {
            const status = s.started
                ? `running for ${((performance.now() - (s.startedAt || performance.now())) / 1000).toFixed(1)}s`
                : "not started yet";
            return `"${s.id}" (${s.label}: ${status})`;
        });
        console.log(`[boot heartbeat +${totalSec}s] Waiting for ${pending.length} step(s): ${details.join("; ")}`);
        if (performance.now() - bootStartTime > 10000) {
            showBootDetail(`Still waiting for: ${pending.map((s) => s.id).join(", ")} (${totalSec}s)`);
            // Steps queued behind a library load are waiting their turn, not stuck: say nothing
            // about them until the libraries are in.
            const librariesBusy = bootClient.some((item) => item.library && !item.done);
            for (const s of pending) {
                if (!s.started && librariesBusy) continue;
                const key = `${s.id}:${s.started ? "running" : "idle"}`;
                if (bootReported.has(key)) continue;
                bootReported.add(key);
                bootReport("warn", `boot step "${s.id}" (${s.label}) ${s.started ? "still running" : "has not started"} after ${totalSec}s`);
            }
        }
    }, 2500);
}

function stopBootHeartbeat() {
    if (bootHeartbeatTimer) {
        clearInterval(bootHeartbeatTimer);
        bootHeartbeatTimer = null;
    }
}

function beginClientBoot() {
    bootClient = bootClientSteps().map((step) => ({ ...step, started: false, done: false, startedAt: 0 }));
    console.log(`[boot] Client boot sequence registered ${bootClient.length} step(s) for media="${state.media}":`,
        bootClient.map((s) => `${s.id} ("${s.label}")`).join(", "));
    const label = document.getElementById("boot-label");
    if (label) label.textContent = "Loading…";
    setBootBar(0.5);
    paintClientBoot();
    startBootHeartbeat();
}

function watchBoot(id) {
    const step = bootClient && bootClient.find((item) => item.id === id);
    if (!step) {
        console.warn(`[boot] watchBoot("${id}") called, but "${id}" is not in registered boot steps`);
        return { done() {} };
    }
    if (step.started) {
        console.log(`[boot] watchBoot("${id}") called again, but step is already marked started (done=${step.done})`);
        return { done() {} };
    }
    step.started = true;
    step.startedAt = performance.now();
    const elapsedSinceBoot = ((performance.now() - bootStartTime) / 1000).toFixed(2);
    console.log(`[boot] Step started: "${id}" ("${step.label}") at +${elapsedSinceBoot}s`);
    paintClientBoot();
    let closed = false;
    return {
        done() {
            if (closed || step.done) return;
            closed = true;
            step.done = true;
            const stepDuration = Math.round(performance.now() - (step.startedAt || performance.now()));
            step.ms = stepDuration;
            const remaining = bootClient.filter((s) => !s.done);
            console.log(`[boot] Step completed: "${id}" in ${stepDuration}ms. (${remaining.length} step(s) remaining: ${remaining.map((s) => s.id).join(", ") || "none"})`);
            if (step.library && bootClient.some((item) => item.library && !item.done)) {
                stopLibraryEase();
                startLibraryEase();
            }
            paintClientBoot();
        },
    };
}

function completeBootBar(force = false) {
    if (bootClosing) return;
    if (!force && bootClient && bootClient.some((step) => !step.done)) return;
    bootClosing = true;
    stopBootHeartbeat();
    const totalBootDuration = ((performance.now() - bootStartTime) / 1000).toFixed(2);
    console.log(`[boot] All steps completed! Dismissing boot screen after ${totalBootDuration}s.`);
    if (bootClient) {
        const parts = bootClient.map((step) => `${step.id} ${step.ms === undefined ? "n/a" : step.ms + "ms"}`);
        bootReport("info", `boot finished in ${totalBootDuration}s: ${parts.join(", ")}`);
    }
    showBootDetail("");
    setBootBar(1);
    const boot = document.getElementById("boot-screen");
    if (!boot) {
        preloadOtherLibraries();
        return;
    }
    setTimeout(() => {
        boot.classList.add("hidden");
        console.log(`[boot] Boot screen hidden. Application interactive.`);
        preloadOtherLibraries();
    }, 160);
}

function preloadOtherLibraries() {
    if (typeof loadVideo !== "function") return;
    ["movies", "sets", "tv"].forEach((media) => {
        if (media === state.media) return;
        const have = media === "sets" ? state.video.sets : media === "tv" ? state.video.shows : state.video.movies;
        if (have || (state.video.loading && state.video.loading[media])) return;
        try {
            console.log(`[boot] Preloading library for inactive media: "${media}"`);
            loadVideo(media, { quiet: true });
        } catch (err) {
            console.error(`[boot] preloadVideo error for "${media}":`, err);
        }
    });
}

async function waitForCurator() {
    const label = document.getElementById("boot-label");
    let shown = 0.02;
    setBootBar(shown);
    setBootStep("Waiting for the database…");
    console.log("[boot] Polling /api/boot for database & backend readiness...");
    while (true) {
        try {
            const data = await api("/api/boot");
            if (data.error) {
                bootError("[boot] /api/boot error:", data.error);
                if (label) label.textContent = data.error;
                setBootStep(data.error);
                return null;
            }
            const server = Number(data.progress);
            if (Number.isFinite(server)) {
                shown = Math.max(shown, (Math.min(Math.max(server, 0), 0.8) / 0.8) * 0.5);
                setBootBar(shown);
                setBootStep(server < 0.46 ? "Waiting for the database…" : "Starting workers…");
            }
            if (data.ready) {
                console.log("[boot] /api/boot is ready!");
                setBootBar(0.5);
                return 0.5;
            }
        } catch (error) {
            console.warn("[boot] Waiting for Curator /api/boot to respond:", error.message || error);
            shown = Math.min(0.08, shown + 0.004);
            setBootBar(shown);
            setBootStep("Waiting for Curator…");
        }
        await new Promise((resolve) => setTimeout(resolve, 400));
    }
}

async function startCurator() {
    console.log(`[boot] startCurator starting. state.media="${state.media}"`);
    const opened = await waitForCurator();
    if (opened == null) return;
    beginClientBoot();
    try {
        const filterEl = document.getElementById("library-filter");
        if (filterEl) filterEl.value = state.filter;
        if (typeof syncLibraryFilterButton === "function") syncLibraryFilterButton();
        if (typeof renderColumnMenu === "function") renderColumnMenu();
        if (typeof bindEvents === "function") bindEvents();
        if (typeof renderCenter === "function") renderCenter();
    } catch (err) {
        bootError("[boot] Early UI setup error:", err);
    }

    const libraries = [];
    if (typeof loadLibrary === "function") {
        console.log("[boot] Queueing music library load...");
        libraries.push(loadLibrary());
    }
    if (state.media === "movies" || state.media === "tv" || state.media === "sets") {
        if (typeof loadVideo === "function") {
            console.log(`[boot] Queueing video library load for "${state.media}"...`);
            libraries.push(loadVideo(state.media, { quiet: true }));
        }
    }
    // The other video libraries start loading now, in parallel, so switching to them is instant.
    // The loading screen does not wait for them: only the library on screen and the music library.
    preloadOtherLibraries();
    startLibraryEase();
    console.log(`[boot] Awaiting ${libraries.length} primary library load(s)...`);
    await Promise.all(libraries.map((job) => Promise.resolve(job).catch((err) => {
        bootError("[boot] Primary library load rejected:", err);
    })));
    stopLibraryEase();
    console.log("[boot] Primary libraries finished. Initializing secondary services...");
    paintClientBoot();

    try {
        if (typeof loadSettings === "function") loadSettings();
    } catch (e) {
        bootError("[boot] loadSettings call error:", e);
    }
    try {
        if (typeof loadStoredMatches === "function") loadStoredMatches();
    } catch (e) {
        bootError("[boot] loadStoredMatches call error:", e);
    }
    try {
        if (typeof pollSystem === "function") pollSystem();
    } catch (e) {
        bootError("[boot] pollSystem call error:", e);
    }
    try {
        if (typeof initVideo === "function") initVideo();
    } catch (e) {
        bootError("[boot] initVideo call error:", e);
    }
    try {
        if (typeof initMedia === "function") initMedia();
    } catch (e) {
        bootError("[boot] initMedia call error:", e);
    }
    if (state.media === "movies" || state.media === "tv") {
        try {
            if (typeof loadSavedFilters === "function") loadSavedFilters(state.media).catch((e) => bootError("[boot] loadSavedFilters async error:", e));
        } catch (e) {
            bootError("[boot] loadSavedFilters call error:", e);
        }
    }
    if (state.media === "movies" || state.media === "tv" || state.media === "sets") {
        try {
            if (typeof pollVideoFiles === "function") pollVideoFiles();
        } catch (e) {
            bootError("[boot] pollVideoFiles call error:", e);
        }
        try {
            if (typeof pollVideoScan === "function") pollVideoScan();
        } catch (e) {
            bootError("[boot] pollVideoScan call error:", e);
        }
    }
    try {
        if (typeof bindSettingsTabs === "function") bindSettingsTabs();
    } catch (e) {
        bootError("[boot] bindSettingsTabs call error:", e);
    }
    try {
        if (typeof noteTraktReturn === "function") noteTraktReturn();
    } catch (e) {
        bootError("[boot] noteTraktReturn call error:", e);
    }
    try {
        if (typeof connectLive === "function") connectLive();
    } catch (e) {
        bootError("[boot] connectLive call error:", e);
    }
}

startCurator();
