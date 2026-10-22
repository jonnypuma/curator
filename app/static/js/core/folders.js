const FOLDER_TYPES = ["music", "movies", "tv"];
const FOLDER_TYPE_LABELS = { music: "Music", movies: "Movies", tv: "TV shows" };
const FOLDER_KEYS = { music: "music_paths", movies: "movie_paths", tv: "tv_paths" };

state.videoScanRoots = { movies: "", tv: "" };

function scanKind() {
    if (state.media === "sets") return "movies";
    return FOLDER_TYPES.includes(state.media) ? state.media : "music";
}

function scanPaths(kind) {
    if (kind === "movies") return state.moviePaths || [];
    if (kind === "tv") return state.tvPaths || [];
    return state.musicPaths || [];
}

function currentScanRoot() {
    const kind = scanKind();
    return kind === "music" ? (state.scanRoot || "") : (state.videoScanRoots[kind] || "");
}

function ownScanRunning() {
    const kind = scanKind();
    if (kind === "music") return !!(state.scan && state.scan.status === "running");
    const scan = typeof videoScanFor === "function" ? videoScanFor(kind) : (state.videoScan || {});
    if (scan.interrupt) return false;
    return (scan.status === "running" || scan.status === "paused") && scan.media === kind;
}

function otherScanActive() {
    if (ownScanRunning()) return false;
    const music = state.scan && state.scan.status === "running";
    const video = (state.videoScan || {}).status === "running";
    return !!(music || video || (state.scanQueue || []).length);
}

function scanBusy() {
    return ownScanRunning();
}

function guessFolderType(path) {
    const name = String(path || "").toLowerCase();
    if (/(^|[\/_\-\s])(tv|shows?|series|television)([\/_\-\s]|$)/.test(name)) return "tv";
    if (/(^|[\/_\-\s])(movies?|films?|cinema)([\/_\-\s]|$)/.test(name)) return "movies";
    return "music";
}

function pathExcluded(path) {
    const wanted = normalizeClientPath(path);
    return ((state.settings || {}).scan_excluded || []).some((item) => normalizeClientPath(item) === wanted);
}

function folderTypeOf(cfg, path) {
    return FOLDER_TYPES.find((type) => (cfg[FOLDER_KEYS[type]] || []).includes(path)) || "music";
}

function folderTypeSelect(attr, path, selected) {
    return `<select ${attr}="${escapeHtml(path)}" title="Media type of this folder">
        ${FOLDER_TYPES.map((type) => `<option value="${type}" ${type === selected ? "selected" : ""}>${FOLDER_TYPE_LABELS[type]}</option>`).join("")}
    </select>`;
}

function pathOffline(path) {
    const groups = state.offlinePaths || {};
    return ["music", "movies", "tv"].some((kind) => (groups[kind] || []).includes(path));
}

function pathEmpty(path) {
    const groups = state.emptyPaths || {};
    return ["music", "movies", "tv"].some((kind) => (groups[kind] || []).includes(path));
}

function pathUnreadable(path) {
    const groups = state.unreadablePaths || {};
    return ["music", "movies", "tv"].some((kind) => (groups[kind] || []).includes(path));
}

function libraryFolderRow(cfg, mounts, path, type) {
    const mount = mounts.find((item) => path === item.path || path.startsWith(`${item.path}/`));
    const mode = mount ? (mount.writable ? "rw" : "ro") : "";
    let music = `<span class="folder-kind"></span>`;
    if (type === "music") {
        const kind = (cfg.music_path_kinds || {})[path] === "artist" ? "artist" : "artists";
        music = `<select data-path-kind="${escapeHtml(path)}" title="What this folder contains">
                <option value="artists" ${kind === "artists" ? "selected" : ""}>Many artists</option>
                <option value="artist" ${kind === "artist" ? "selected" : ""}>One artist</option>
            </select>`;
    }
    const excluded = pathExcluded(path);
    const offline = pathOffline(path);
    const offlineTag = offline
        ? `<span class="folder-mode is-offline" title="This folder cannot be read right now. Scans skip it and nothing indexed under it is removed.">offline</span>`
        : "";
    const unreadable = !offline && pathUnreadable(path);
    const unreadableTag = unreadable
        ? `<span class="folder-mode is-unreadable" title="This folder exists but cannot be listed - check permissions or the mount. Scans skip it and nothing indexed under it is removed.">unreadable</span>`
        : "";
    const empty = !offline && !unreadable && pathEmpty(path);
    const emptyTag = empty
        ? `<span class="folder-mode is-empty" title="This folder is readable but holds nothing. Nothing indexed under it is removed. If it is finished with, remove the path and scan again.">empty</span>`
        : "";
    return `<div class="path-row folder-row${mount ? " is-mounted" : " is-unmounted"}${excluded ? " is-excluded" : ""}${offline ? " is-offline" : ""}${unreadable ? " is-unreadable" : ""}" data-folder-type="${type}">
        <span class="mono" title="${escapeHtml(path)}">${escapeHtml(path)} ${mode ? `<span class="folder-mode">${mode}</span>` : `<span class="folder-mode is-off">not mounted</span>`}${offlineTag}${unreadableTag}${emptyTag}</span>
        ${folderTypeSelect("data-path-media", path, type)}
        ${music}
        <label class="choice folder-exclude" title="Leave this folder out of library scans"><input type="checkbox" data-scan-exclude="${escapeHtml(path)}" ${excluded ? "checked" : ""}> Exclude</label>
        <button type="button" class="btn-ghost btn-remove" data-action="remove-path" data-path="${escapeHtml(path)}" data-media="${type}">Delete</button>
    </div>`;
}

function backupDefaultFolder() {
    return (state.settings || {}).backup_default || "/backups";
}

function libraryMounts(cfg, mounts) {
    const backups = [backupDefaultFolder(), cfg.backup_folder].filter(Boolean).map(normalizeClientPath);
    return mounts.filter((mount) => !backups.includes(normalizeClientPath(mount.path)));
}

function libraryFoldersSection(cfg, allMounts) {
    const mounts = libraryMounts(cfg, allMounts);
    const loose = [];
    const rows = FOLDER_TYPES.map((type) => {
        const list = cfg[FOLDER_KEYS[type]] || [];
        const mounted = [];
        list.forEach((path) => {
            const onVolume = mounts.some((item) => path === item.path || path.startsWith(`${item.path}/`));
            const row = libraryFolderRow(cfg, mounts, path, type);
            if (onVolume) mounted.push(row);
            else loose.push(row);
        });
        const body = mounted.length
            ? mounted.join("")
            : list.length
                ? `<p class="muted">No mounted ${FOLDER_TYPE_LABELS[type].toLowerCase()} folders. The saved folders are listed under Not mounted.</p>`
                : `<p class="muted">No ${FOLDER_TYPE_LABELS[type].toLowerCase()} folders yet.</p>`;
        return `<h4 class="folder-group-title">${FOLDER_TYPE_LABELS[type]}</h4>${body}`;
    }).join("");
    const looseBlock = loose.length
        ? `<h4 class="folder-group-title folder-group-unmounted">Not mounted</h4>
            <p class="muted">These folders are saved, but no volume in the container currently contains them.</p>
            ${loose.join("")}`
        : "";
    const used = FOLDER_TYPES.flatMap((type) => (cfg[FOLDER_KEYS[type]] || []).map((path) => [path, type]));
    const available = mounts.filter((mount) => !used.some(([path]) => normalizeClientPath(path) === normalizeClientPath(mount.path)));
    const offers = available.length
        ? available.map((mount) => `<div class="path-row folder-row is-available"><span class="mono" title="${escapeHtml(mount.path)}">${escapeHtml(mount.path)} <span class="folder-mode">${mount.writable ? "rw" : "ro"}</span></span>
            ${folderTypeSelect("data-mount-media", mount.path, guessFolderType(mount.path))}
            <span class="folder-kind"></span>
            <button type="button" class="btn-ghost" data-action="add-mount" data-path="${escapeHtml(mount.path)}">Add mount</button></div>`).join("")
        : `<p class="muted">Every detected mount is already in the list. Add path can still open a folder inside one of them.</p>`;
    return `<section class="settings-section" data-tab="general"><h3>Library folders</h3>
        <p class="muted">These are directories inside the container. Mount a host folder in docker-compose, recreate the container, then add the folder here and save settings.</p>
        <p class="muted">Each folder has one media type. The Scan button only scans folders of the library that is open: Music scans music folders, Movies and Movie sets scan movie folders, and TV shows scans TV folders. A folder can not sit inside a folder of another type. Exclude leaves the folder in the library and skips it on scans.</p>
        <p class="muted">For music folders, Many artists treats each subfolder as an artist and One artist treats the folder itself as the artist. Collection is music you keep and it counts as owned. Inbox is a drop folder for new arrivals: those albums show an Inbox tag and stay out of the owned count.</p>
        <p class="muted">${mounts.length ? `Detected mounts: ${mounts.map((mount) => escapeHtml(mount.path)).join(", ")}` : "No mounts were detected yet. Add a volume in docker-compose and recreate the container."}</p>
        <p class="settings-warning hidden" data-offline-paths></p>
        <p class="settings-warning hidden" data-unreadable-paths></p>
        <p class="settings-warning hidden" data-empty-paths></p>
        <p class="muted">An offline folder is skipped by scans and nothing indexed under it is removed, so a mount that is away cannot wipe your library. To remove a folder's items, take the path out here and scan again.</p>
        <div id="music-path-list">${rows}${looseBlock}</div>
        <h4 class="folder-group-title">Volumes not in a library</h4>
        ${offers}
        <p><button type="button" class="btn-ghost" data-action="add-path">Add path</button></p>
    </section>`;
}

function libraryPathOwner(value) {
    const cfg = state.settings || {};
    for (const type of FOLDER_TYPES) {
        for (const path of cfg[FOLDER_KEYS[type]] || []) {
            const other = normalizeClientPath(path);
            if (other === value || value.startsWith(`${other}/`) || other.startsWith(`${value}/`)) return [type, other];
        }
    }
    return null;
}

function addLibraryPath(path, media, role, kind) {
    rememberSettingsForm();
    const type = FOLDER_TYPES.includes(media) ? media : "music";
    const value = normalizeClientPath(path);
    if (!value) {
        notify("Choose a detected mount, or type a container path such as /movies.", "warning");
        return;
    }
    if (!value.startsWith("/")) {
        notify("Use the path inside the container. It needs to start with /.", "warning");
        return;
    }
    const clash = libraryPathOwner(value);
    if (clash && clash[1] === value) {
        notify(`${value} is already a ${FOLDER_TYPE_LABELS[clash[0]].toLowerCase()} folder.`, "info");
        return;
    }
    if (clash && clash[0] !== type) {
        notify(`${value} overlaps the ${FOLDER_TYPE_LABELS[clash[0]].toLowerCase()} folder ${clash[1]}. Each folder can have only one media type.`, "warning");
        return;
    }
    const key = FOLDER_KEYS[type];
    state.settings[key] = [...(state.settings[key] || []), value];
    if (type === "music") {
        state.settings.music_path_kinds = state.settings.music_path_kinds || {};
        state.settings.music_path_kinds[value] = kind === "artist" ? "artist" : "artists";
    }
    renderSettings();
    notify(`Added ${value} as a ${FOLDER_TYPE_LABELS[type].toLowerCase()} folder. Save settings to keep it.`, "info");
}

function dropLibraryPath(path, type) {
    const key = FOLDER_KEYS[type];
    const next = (state.settings[key] || []).filter((item) => item !== path);
    if (type === "music" && !next.length) {
        notify("Keep at least one music folder.", "warning");
        return false;
    }
    state.settings[key] = next;
    if (type === "music") {
        if (state.settings.music_path_roles) delete state.settings.music_path_roles[path];
        if (state.settings.music_path_kinds) delete state.settings.music_path_kinds[path];
    }
    if (state.settings.scan_excluded) {
        state.settings.scan_excluded = state.settings.scan_excluded.filter((item) => normalizeClientPath(item) !== normalizeClientPath(path));
    }
    return true;
}

function removeLibraryPath(path, media) {
    rememberSettingsForm();
    const type = FOLDER_TYPES.includes(media) ? media : folderTypeOf(state.settings, path);
    if (dropLibraryPath(path, type)) renderSettings();
}

function retypeLibraryPath(path, media) {
    rememberSettingsForm();
    const from = folderTypeOf(state.settings, path);
    if (!FOLDER_TYPES.includes(media) || from === media) return;
    if (!dropLibraryPath(path, from)) {
        renderSettings();
        return;
    }
    const key = FOLDER_KEYS[media];
    state.settings[key] = [...(state.settings[key] || []), path];
    if (media === "music") {
        state.settings.music_path_roles = { ...(state.settings.music_path_roles || {}), [path]: "library" };
        state.settings.music_path_kinds = { ...(state.settings.music_path_kinds || {}), [path]: "artists" };
    }
    renderSettings();
    notify(`${path} is now a ${FOLDER_TYPE_LABELS[media].toLowerCase()} folder. Save settings to keep it.`, "info");
}

function syncPathModalMedia() {
    const picking = state.pathPick === "set-folder" || state.pathPick === "backup-folder" || state.pathPick === "map-local";
    const select = document.getElementById("path-media");
    const music = document.getElementById("path-music-options");
    const mediaRow = document.getElementById("path-media-row");
    if (mediaRow) mediaRow.classList.toggle("hidden", picking);
    if (select && music) music.classList.toggle("hidden", picking || select.value !== "music");
    const title = document.getElementById("path-title");
    if (title) {
        const titles = { "backup-folder": "Backup folder", "set-folder": "Movie set information folder", "map-local": "Local path" };
        title.textContent = titles[state.pathPick] || `Add a ${(FOLDER_TYPE_LABELS[(select || {}).value] || "library").toLowerCase()} folder`;
    }
}
