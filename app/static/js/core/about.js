// About Curator: the version number and what this install is running on.

const PROJECT_URL = "https://github.com/jonnypuma/curator";

function aboutUptime(seconds) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return [days ? `${days} d` : "", hours ? `${hours} h` : "", `${minutes} min`].filter(Boolean).join(" ");
}

function ytdlpCell(tool) {
    const age = tool.age_days === null || tool.age_days === undefined ? "" : `${tool.age_days} days old`;
    const origin = tool.updated ? "updated in Curator" : "";
    const detail = [age, origin].filter(Boolean).join(", ");
    return `<span id="about-ytdlp-version">${tool.version ? escapeHtml(tool.version) : "not installed"}</span>
        <span class="${tool.stale ? "about-ytdlp-old" : "muted"}" id="about-ytdlp-age">${detail ? `(${escapeHtml(detail)})` : ""}</span>
        <div class="about-ytdlp">
            <button type="button" id="about-ytdlp-button" data-action="about-ytdlp-update">Update yt-dlp</button>
            <span class="muted" id="about-ytdlp-note">Checking for a newer release…</span>
        </div>`;
}

function setYtdlpDue(due) {
    const button = document.getElementById("about-ytdlp-button");
    if (button) button.classList.toggle("is-due", !!due);
}

function setYtdlpNote(text, kind) {
    const note = document.getElementById("about-ytdlp-note");
    if (!note) return;
    note.className = kind || "muted";
    note.textContent = text;
}

async function checkYtdlp() {
    try {
        const info = await api("/api/v1/ytdlp?check=1");
        setYtdlpDue(!info.check_error && info.update_available);
        if (info.check_error) setYtdlpNote(`Could not look for a newer release: ${info.check_error}`);
        else if (info.update_available) setYtdlpNote(`${info.latest} is available`, "about-ytdlp-new");
        else setYtdlpNote("This is the newest release");
    } catch (error) {
        setYtdlpNote("Could not look for a newer release");
    }
}

async function updateYtdlp() {
    const button = document.getElementById("about-ytdlp-button");
    if (!button || button.disabled) return;
    button.disabled = true;
    button.textContent = "Updating…";
    setYtdlpNote("Downloading the release and checking it…");
    try {
        const info = await api("/api/v1/ytdlp/update", { method: "POST", body: {} });
        const version = document.getElementById("about-ytdlp-version");
        const age = document.getElementById("about-ytdlp-age");
        if (version) version.textContent = info.version || "";
        if (age) {
            const detail = [info.age_days === null || info.age_days === undefined ? "" : `${info.age_days} days old`, info.updated ? "updated in Curator" : ""].filter(Boolean).join(", ");
            age.className = info.stale ? "about-ytdlp-old" : "muted";
            age.textContent = detail ? `(${detail})` : "";
        }
        setYtdlpDue(false);
        setYtdlpNote(info.message || "Updated", "about-ytdlp-new");
        paintAboutHealth();
    } catch (error) {
        setYtdlpNote((error && error.message) || "The update failed", "about-ytdlp-error");
    } finally {
        button.disabled = false;
        button.textContent = "Update yt-dlp";
    }
}

function paintAboutHealth() {
    return api("/api/v1/about/health").then((health) => {
        const mark = { ok: "✓", warn: "!", bad: "✗" };
        const holder = document.getElementById("about-health");
        if (!holder) return;
        holder.outerHTML = `<table class="about-table" id="about-health"><tbody>${(health.checks || []).map((c) => `<tr class="health-${escapeHtml(c.state)}"><td>${mark[c.state] || ""} ${escapeHtml(c.name)}</td><td>${escapeHtml(c.detail)}</td></tr>`).join("")}</tbody></table>`;
    }).catch(() => {
        const holder = document.getElementById("about-health");
        if (holder) holder.textContent = "Could not run the health checks";
    });
}

// Requests that took two seconds or more since Curator started, newest first: which window was slow, and how slow.
function paintAboutSlow() {
    return api("/api/v1/about/slow").then((data) => {
        const holder = document.getElementById("about-slow");
        if (!holder) return;
        const rows = data.requests || [];
        if (!rows.length) {
            holder.textContent = `No request has taken ${data.threshold_seconds || 2} seconds or more since Curator started.`;
            return;
        }
        holder.outerHTML = `<table class="about-table" id="about-slow"><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.at.replace("T", " "))}</td><td><span class="mono">${escapeHtml(row.method)} ${escapeHtml(row.path)}</span>${row.status >= 400 ? ` <span class="muted">(${escapeHtml(String(row.status))})</span>` : ""}</td><td>${escapeHtml(row.seconds.toFixed(1))} s</td></tr>`).join("")}</tbody></table>`;
    }).catch(() => {
        const holder = document.getElementById("about-slow");
        if (holder) holder.textContent = "Could not read the slow requests";
    });
}

async function openAbout() {
    const modal = document.getElementById("about-modal");
    const body = document.getElementById("about-body");
    if (!modal || !body) return;
    body.innerHTML = `<p class="muted">Loading…</p>`;
    modal.classList.remove("hidden");
    try {
        const data = await api("/api/v1/about");
        const loaded = (document.querySelector(".version-pill") || {}).textContent || "";
        const stale = loaded && data.version && loaded.replace(/^v/, "") !== data.version;
        const rows = [
            ["Version", `v${escapeHtml(data.version)}${stale ? ` <span class="muted">(this page was loaded as ${escapeHtml(loaded)}; reload to update)</span>` : ""}`],
            ["Project", `<a href="${PROJECT_URL}" target="_blank" rel="noopener noreferrer">github.com/jonnypuma/curator</a>`],
            ["Running for", escapeHtml(aboutUptime(data.uptime_seconds || 0))],
            ["Database", escapeHtml(data.database ? `PostgreSQL ${data.database}` : "PostgreSQL")],
            ["Python", escapeHtml(data.python || "")],
            ...(data.tools || []).map((tool) => [
                escapeHtml(tool.name),
                tool.name === "yt-dlp" ? ytdlpCell(tool) : tool.version ? escapeHtml(tool.version) : `<span class="muted">not installed</span>`,
            ]),
        ];
        body.innerHTML = `<table class="about-table"><tbody>${rows.map(([name, value]) => `<tr><td>${name}</td><td>${value}</td></tr>`).join("")}</tbody></table>`;
        body.insertAdjacentHTML("beforeend", `<h3 class="about-health-title">Health</h3><p class="muted" id="about-health">Checking…</p>`);
        paintAboutHealth();
        body.insertAdjacentHTML("beforeend", `<h3 class="about-health-title">Slow requests</h3><p class="muted" id="about-slow">Loading…</p>`);
        paintAboutSlow();
        if (document.getElementById("about-ytdlp-note")) checkYtdlp();
    } catch (error) {
        body.innerHTML = `<p class="muted">${escapeHtml((error && error.message) || "Could not load this information")}</p>`;
    }
}

document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (target && target.matches && target.matches(".brand[data-action='about-open']") && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        openAbout();
    }
});
