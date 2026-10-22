async function api(path, options = {}) {
    const response = await fetch(path, {
        cache: "no-store",
        ...options,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(data.error || response.statusText);
        error.status = response.status;
        error.body = data;
        throw error;
    }
    return data;
}

function setPending(id, proposal) {
    if (!id) return;
    if (proposal) state.pending[id] = proposal;
    else delete state.pending[id];
    const path = `/api/matches/${id}`;
    const call = proposal
        ? api(path, { method: "PUT", body: proposal })
        : api(path, { method: "DELETE", body: {} });
    call.catch((error) => notify(error.message || "The loaded match could not be saved.", "warning"));
}

async function loadStoredMatches() {
    const boot = typeof watchBoot === "function" ? watchBoot("matches") : null;
    try {
        const data = await api("/api/matches");
        state.pending = data.matches || {};
        if (state.album && state.pending[state.album.album.id]) {
            state.proposal = state.pending[state.album.album.id];
            renderCenter();
        }
        renderTree();
        renderBatchBar();
    } catch (error) {
        notify(error.message || "Loaded matches could not be restored.", "warning");
    } finally {
        if (boot) boot.done();
    }
}
