// IMDb's free datasets, kept as a local copy for ratings, episode ids and basic title facts.
// The server does the downloading. This file draws the Settings section and follows its progress.

const IMDB_TERMS_URL = "https://developer.imdb.com/non-commercial-datasets";
const IMDB_LICENSE_URL = "https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX";
let imdbDataTimer = null;

function imdbDataSection() {
    const cfg = videoCfg();
    const days = Math.max(7, Math.min(365, Number(cfg.imdb_refresh_days) || 30));
    return `<section class="settings-section" id="imdb-datasets" data-tab="integrations">
            <h3>IMDb ratings from IMDb's own data files</h3>
            <label class="choice"><input type="checkbox" id="imdb-data" ${cfg.imdb_data ? "checked" : ""}> Use IMDb's free datasets for ratings and episode details</label>
            <p class="muted">Off by default. When on, Curator downloads three of IMDb's data files (ratings, episodes and basic title facts) straight from datasets.imdbws.com, builds a searchable copy of about 270 MB in the cache folder and deletes the download afterwards. Episodes then get their own IMDb id and score from that copy, so OMDb is not asked for each one. For movies and shows the copy fills what OMDb and the other sources leave empty: the IMDb score, the title, year, runtime and genres.</p>
            <p class="muted">IMDb offers these files for personal and non-commercial use only. Turn this on only if that describes how you use Curator. Read <a href="${IMDB_TERMS_URL}" target="_blank" rel="noopener noreferrer">IMDb's terms for the datasets</a> and its <a href="${IMDB_LICENSE_URL}" target="_blank" rel="noopener noreferrer">licensing article</a>. Data from IMDb's non-commercial datasets, for personal use only.</p>
            <label class="field">Refresh every <input id="imdb-days" type="number" min="7" max="365" value="${days}"> days</label>
            <p class="muted">IMDb publishes new files every day, but ratings move slowly. Curator checks quietly in the background and downloads again only when the copy is older than this.</p>
            <label class="field">User agent
                <span class="path-field">
                    <input id="imdb-user-agent" class="mono" type="text" autocomplete="off" spellcheck="false" maxlength="200" value="${escapeHtml(cfg.imdb_user_agent || "")}" placeholder="Mozilla/5.0 (Windows NT 10.0; Win64; x64) …">
                    <button type="button" class="btn-ghost" id="imdb-user-agent-reset" data-action="imdb-user-agent-reset" title="Clear the saved name and send the default" ${cfg.imdb_user_agent ? "" : "disabled"}>Use default</button>
                </span>
            </label>
            <p class="muted">Sent with every request to IMDb. The default is a common Mozilla browser name. You can enter anything here, for example the name your own agreement or licence with IMDb asks for, and it is sent instead. Leave it empty to use the default, which is shown in the box.</p>
            <div id="imdb-data-status" class="muted" aria-live="polite">Checking…</div>
            <p><button type="button" class="btn-ghost key-test" id="imdb-data-refresh" data-action="imdb-data-refresh">Refresh now</button>
               <button type="button" class="btn-ghost key-test" id="imdb-data-remove" data-action="imdb-data-remove">Remove local copy</button></p>
        </section>`;
}

// The IMDb options live under Integrations. General and Schedules point there, since that is where people look.
function imdbPointer() {
    return `<p class="muted">IMDb's free data files for ratings (the switch, the refresh interval and the user agent) are under
            <button type="button" class="link" data-action="settings-goto" data-tab="integrations" data-target="imdb-datasets">Integrations, IMDb ratings from IMDb's own data files</button>.</p>`;
}

function imdbScheduleSection() {
    return `<section class="settings-section" data-tab="sync">
        <h3>IMDb datasets</h3>
        <p class="muted">The local copy of IMDb's data files is checked quietly in the background and downloaded again when it is older than the interval you set. It is not a cron schedule.</p>
        ${imdbPointer()}
    </section>`;
}

function imdbCount(value) {
    return Number(value || 0).toLocaleString();
}

function imdbDataText(info) {
    if (info.running) return `Updating: ${info.step || "working"}…`;
    if (info.queued) return "Starting…";
    const lines = [];
    if (info.ready) {
        const built = info.built_at ? new Date(info.built_at * 1000).toLocaleDateString() : "";
        const origin = { "data folder": "files in your data folder", mixed: "files in your data folder and a download" }[info.source] || "a download";
        const age = info.age_days ? `, ${info.age_days} day${info.age_days === 1 ? "" : "s"} ago` : "";
        const counts = info.counts || {};
        const size = info.size ? `${Math.round(info.size / 1000000)} MB on disk` : "";
        lines.push(`Local copy ready (built ${built}${age} from ${origin}). ${imdbCount(counts.ratings)} ratings, ${imdbCount(counts.episodes)} episodes and ${imdbCount(counts.titles)} titles${size ? `, ${size}` : ""}.`);
        lines.push(info.enabled
            ? `Next refresh in ${info.next_in_days === 0 ? "a moment" : `${info.next_in_days} day${info.next_in_days === 1 ? "" : "s"}`}.`
            : "The copy is not used while this is off. Remove it below to free the space.");
    } else if (info.enabled) {
        lines.push("No copy yet. It is built in the background shortly after you save.");
        if ((info.data_folder_files || []).length === 3) lines.push("The files you placed in the data folder are used for the first build, so nothing is downloaded.");
    } else {
        lines.push("Off. Nothing is downloaded while this is off.");
    }
    if (info.error) lines.push(`The last update failed: ${info.error}`);
    return lines.join(" ");
}

function syncImdbAgentReset() {
    const input = document.getElementById("imdb-user-agent");
    const button = document.getElementById("imdb-user-agent-reset");
    if (input && button) button.disabled = !input.value.trim();
}

function resetImdbAgent() {
    const input = document.getElementById("imdb-user-agent");
    if (!input) return;
    input.value = "";
    syncImdbAgentReset();
    setSettingsStatus("User agent cleared. After you save, the default is sent.");
    input.focus();
}

function paintImdbData(info) {
    const box = document.getElementById("imdb-data-status");
    if (!box) return;
    const agent = document.getElementById("imdb-user-agent");
    if (agent && info.default_user_agent) agent.placeholder = info.default_user_agent;
    box.textContent = imdbDataText(info);
    const busy = !!(info.running || info.queued);
    const refresh = document.getElementById("imdb-data-refresh");
    const remove = document.getElementById("imdb-data-remove");
    if (refresh) {
        refresh.disabled = busy || !info.enabled;
        refresh.title = info.enabled ? "" : "Turn this on and save the settings first";
    }
    if (remove) {
        remove.disabled = busy || info.enabled || !(info.ready || info.size);
        remove.title = info.enabled ? "Turn this off and save the settings first" : "";
    }
}

async function loadImdbDataStatus() {
    const box = document.getElementById("imdb-data-status");
    clearTimeout(imdbDataTimer);
    if (!box) return;
    try {
        const info = await api("/api/v1/imdb-data");
        paintImdbData(info);
        if (info.running || info.queued) imdbDataTimer = setTimeout(loadImdbDataStatus, 3000);
    } catch (error) {
        box.textContent = "The status could not be read.";
    }
}

async function refreshImdbData() {
    try {
        const info = await api("/api/v1/imdb-data/refresh", { method: "POST", body: {} });
        paintImdbData({ ...info, queued: true });
        clearTimeout(imdbDataTimer);
        imdbDataTimer = setTimeout(loadImdbDataStatus, 1500);
    } catch (error) {
        notify((error && error.message) || "The update could not be started.", "error");
    }
}

async function removeImdbData() {
    try {
        paintImdbData(await api("/api/v1/imdb-data", { method: "DELETE" }));
        notify("The local IMDb copy was removed.", "info");
    } catch (error) {
        notify((error && error.message) || "The local copy could not be removed.", "error");
    }
}
