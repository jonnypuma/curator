const live = { socket: null, retry: 0, timer: 0, queue: null };

function connectLive() {
    if (!("WebSocket" in window)) return;
    clearTimeout(live.timer);
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    let socket;
    try {
        socket = new WebSocket(`${scheme}://${location.host}/ws/events`);
    } catch (error) {
        scheduleLiveReconnect();
        return;
    }
    live.socket = socket;
    socket.addEventListener("open", () => {
        live.retry = 0;
    });
    socket.addEventListener("message", (event) => {
        let message;
        try {
            message = JSON.parse(event.data);
        } catch (error) {
            return;
        }
        onLiveMessage(message || {});
    });
    socket.addEventListener("close", () => {
        if (live.socket === socket) live.socket = null;
        scheduleLiveReconnect();
    });
}

function scheduleLiveReconnect() {
    live.retry = Math.min(live.retry + 1, 6);
    live.timer = setTimeout(connectLive, 1000 * 2 ** live.retry);
}

function onLiveMessage(message) {
    if (message.type === "QUEUE_TICK") {
        if (typeof queuePanelOpen === "function" && queuePanelOpen()) {
            const nextScans = (message.data && message.data.scans) || [];
            const nextArr = (message.data && message.data.arr) || [];
            const nextLibrary = (message.data && message.data.library) || [];

            const prevScans = state.queuePanel.scans || [];
            const prevArr = state.queuePanel.arr || [];
            const prevLibrary = state.queuePanel.library || [];

            const hasFinishedItem =
                prevLibrary.some((item) => !nextLibrary.some((n) => n.id === item.id)) ||
                prevScans.some((item) => !nextScans.some((n) => n.id === item.id)) ||
                prevArr.some((item) => !nextArr.some((n) => n.id === item.id));

            state.queuePanel.scans = nextScans;
            state.queuePanel.arr = nextArr;
            state.queuePanel.library = nextLibrary;
            paintQueueTabs();
            paintQueueLists();

            if (hasFinishedItem) {
                refreshQueuePanelSoon();
            }
        }
        live.queue = message.data || null;
        paintQueuePill();
        paintQueueRing(live.queue || {});
    } else if (message.type === "SCAN_PROGRESS") {
        onVideoScanLive(message.data);
    } else if (message.type === "SCRAPE_PROGRESS") {
        onVideoScrapeLive(message.data);
    } else if (message.type === "FILES_PROGRESS") {
        onVideoFilesLive(message.data);
    } else if (message.type === "ITEM_ENQUEUED") {
        refreshQueuePanelSoon();
    } else if (message.type === "WORK_EVENT") {
        refreshQueuePanelSoon();
    } else if (message.type === "QUEUE_EVENT") {
        const data = message.data || {};
        notify(webhookReceivedText(data), data.outcome === "unmapped" || data.outcome === "error" ? "warning" : "info");
        refreshQueuePanelSoon();
    } else if (message.type === "QUEUE_FLUSH") {
        const data = message.data || {};
        if (data.state === "finished") notify(`Webhook queue finished. ${data.message || ""}`.trim(), "info");
        refreshQueuePanelSoon();
    }
}

function webhookReceivedText(data) {
    if (String(data.source || "") === "kodi" && data.message) return data.message;
    const source = String(data.source || "webhook");
    const name = source.charAt(0).toUpperCase() + source.slice(1);
    const event = String(data.event || "event");
    if (event === "Test" || data.outcome === "test") return `${name} test received.`;
    const title = data.title ? ` for ${data.title}` : "";
    if (data.outcome === "queued") return `${name} ${event} received${title}. Queued.`;
    if (data.message) return `${name} ${event} received${title}. ${data.message}`;
    return `${name} ${event} received${title}.`;
}

function queueItemCount(queue) {
    const imports = Number(queue.queued_items_count) || 0;
    const runningImports = Number(queue.running_items) || 0;
    const scans = (queue.scans || []).length;
    const arr = (queue.arr || []).length;
    const library = (queue.library || []).length;
    return imports + runningImports + scans + arr + library;
}

function paintQueueBadge(id, buttonId, count) {
    const badge = document.getElementById(id);
    const button = document.getElementById(buttonId);
    if (badge) {
        badge.textContent = count > 99 ? "99+" : String(count);
        badge.classList.toggle("hidden", !count);
    }
    if (button) {
        const label = count ? `Queue, ${count}` : "Queue";
        button.title = label;
        button.setAttribute("aria-label", label);
    }
}

function queueCountdownText(queue) {
    const remaining = Math.max(0, Number(queue.remaining_seconds) || 0);
    const imports = Number(queue.queued_items_count) || 0;
    if (!imports || queue.running) return "";
    if (remaining < 60) return `${Math.round(remaining)}s`;
    return `${Math.round(remaining / 60)}m`;
}

function paintQueuePill() {
    const pill = document.getElementById("queue-pill");
    const queue = live.queue || {};
    const count = queueItemCount(queue);
    paintQueueBadge("dock-queue-count", "dock-queue", count);
    paintQueueBadge("jobs-queue-count", "jobs-queue-btn", count);
    const cd = document.getElementById("dock-queue-countdown");
    if (cd) {
        const cdText = queueCountdownText(queue);
        cd.textContent = cdText;
        cd.classList.toggle("hidden", !cdText);
    }
    if (pill) pill.classList.add("hidden");
    if (typeof syncActivity === "function") syncActivity();
}
