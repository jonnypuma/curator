let settingsRequest = null;
let settingsSettled = false;

function loadSettings() {
    const boot = typeof watchBoot === "function" ? watchBoot("settings") : null;
    if ((settingsSettled && state.settings) || state.settings) {
        if (boot) boot.done();
        return Promise.resolve(state.settings);
    }
    if (!settingsRequest) {
        settingsRequest = api("/api/settings").then((cfg) => {
            if (!state.settings && cfg) {
                state.settings = cfg;
                if (cfg.fill_missing_during_scan != null) state.fillMissingDuringScan = cfg.fill_missing_during_scan !== false;
                if (cfg.sort_ignore_the != null) state.sortIgnoreThe = cfg.sort_ignore_the !== false;
            }
            settingsSettled = Boolean(state.settings);
            return state.settings || null;
        }).catch(() => null).finally(() => {
            if (boot) boot.done();
            settingsRequest = null;
        });
    } else if (boot) boot.done();
    return settingsRequest;
}

async function openSettings() {
    const modal = document.getElementById("settings-modal");
    setSettingsStatus("Loading settings…");
    modal.classList.remove("hidden");
    try {
        const [cfg, system] = await Promise.all([api("/api/settings"), api("/api/system")]);
        state.settings = cfg;
        state.mounts = system.mounts || [];
        state.offlinePaths = system.offline_paths || {};
        state.unreadablePaths = system.unreadable_paths || {};
        state.emptyPaths = system.empty_paths || {};
        state.musicPaths = system.music_paths || state.musicPaths;
        state.moviePaths = system.movie_paths || state.moviePaths;
        state.tvPaths = system.tv_paths || state.tvPaths;
        state.clearKeys = {};
        state.cmmApiKey = system.cmm_api_key || "";
        renderSettings();
        if (typeof refreshSavedArrOptions === "function") refreshSavedArrOptions();
        setSettingsStatus("");
    } catch (error) {
        setSettingsStatus(error.message || "Settings could not be loaded.");
        notify(error.message || "Settings could not be loaded.", "error");
    }
}

function renderSettings() {
    const body = document.getElementById("settings-body");
    const scroll = body ? body.scrollTop : 0;
    const cfg = state.settings || {};
    cfg.assets = cfg.assets || {};
    cfg.sources_enabled = cfg.sources_enabled || {};
    const mounts = state.mounts || [];
    const assets = ASSET_GROUPS.map(([title, items]) => {
        const boxes = items.map(([key, label]) =>
            `<label class="choice"><input type="checkbox" data-asset="${key}" ${cfg.assets[key] ? "checked" : ""}> ${escapeHtml(label)}</label>`
        ).join("");
        return `<div class="asset-group">
            <div class="asset-group-head">
                <h4>${escapeHtml(title)}</h4>
                <span>
                    <button type="button" class="btn-ghost" data-action="asset-all" data-checked="true">Select all</button>
                    <button type="button" class="btn-ghost" data-action="asset-all" data-checked="false">Deselect all</button>
                </span>
            </div>
            ${boxes}
        </div>`;
    }).join("");
    const priority = orderedSources(cfg.source_priority, cfg.sources_enabled).map((source) => `<div class="priority-item${cfg.sources_enabled[source] === false ? " is-off" : ""}" draggable="true" data-source="${escapeHtml(source)}">
        ${priorityGrip()}
        <label class="choice"><input type="checkbox" data-source-enabled="${escapeHtml(source)}" ${cfg.sources_enabled[source] === false ? "" : "checked"}> ${escapeHtml(sourceLabel(source))}</label>
        ${priorityNudge(source)}
    </div>`).join("");
    const preset = presetFor(cfg.min_resolution);
    const embedPreset = presetFor(cfg.embed_max_px);
    const presetOptions = RESOLUTION_PRESETS.map(([value, label]) =>
        `<option value="${value}" ${preset === value ? "selected" : ""}>${escapeHtml(label)}</option>`
    ).join("");
    const embedOptions = RESOLUTION_PRESETS.map(([value, label]) =>
        `<option value="${value}" ${embedPreset === value ? "selected" : ""}>${escapeHtml(label)}</option>`
    ).join("");
    const cmmKey = state.cmmApiKey || "";
    document.getElementById("settings-body").innerHTML = `
        <section class="settings-section" data-tab="general"><h3>CMM API key</h3>
            <label>CMM API key
                <span class="path-field">
                    <input id="cmm-api-key" class="mono" readonly spellcheck="false" value="${escapeHtml(cmmKey)}" placeholder="Not set in docker-compose" aria-label="CMM API key">
                    <button type="button" class="icon-btn" data-action="copy-cmm-key" title="Copy API key" aria-label="Copy API key" ${cmmKey ? "" : "disabled"}>${typeof clipboardIcon === "function" ? clipboardIcon() : "Copy"}</button>
                </span>
            </label>
            <p class="muted">This is CMM_API_KEY from docker-compose. Paste it where a webhook address says YOUR_KEY. Changing it here does not save a new key.</p>
        </section>
        <section class="settings-section" data-tab="general"><h3>Logging</h3>
            <label class="choice"><input type="checkbox" id="verbose-logging" ${cfg.verbose_logging ? "checked" : ""}> Verbose logging</label>
            <p class="muted">Writes scan albums, artwork downloads, metadata lookups, match apply, and batch jobs to the container log (docker compose logs -f). Turn this on while troubleshooting, then save settings. The scan engine checkbox still turns the same album detail on for one scan.</p>
        </section>
        <section class="settings-section" data-tab="general"><h3>Library behaviour</h3>
            <label>Probe workers
                <input id="probe-workers" type="number" min="1" max="20" value="${Math.max(1, Math.min(20, Number((typeof videoCfg === "function" ? videoCfg() : {}).probe_workers) || 8))}">
            </label>
            <p class="muted">CMM_PROBE_WORKERS. How many movie and TV files are probed at once during a scan, from 1 to 8. Saving settings stores this number and it overrides docker-compose. Raise it for a fast local disk.</p>
        </section>
        <section class="settings-section" data-tab="general"><h3>Trailer download quality</h3>
            <label class="field">Highest quality ${typeof videoSelect === "function" ? videoSelect("video-trailer-resolution", (typeof videoCfg === "function" ? videoCfg() : {}).trailer_resolution || "1080p", [["2160p", "2160p"], ["1080p", "1080p"], ["720p", "720p"]]) : ""}</label>
            <p class="muted">The tallest picture to search for when a trailer is downloaded, by hand or after an import. A trailer already on disk is only replaced when it is shorter than this and YouTube has a taller copy.</p>
        </section>
        <section class="settings-section" data-tab="general"><h3>Prune safety</h3>
            <label class="choice"><input type="checkbox" id="prune-safety" ${cfg.prune_safety !== false ? "checked" : ""}> Hold back removals when too much is missing</label>
            <p class="muted">On: a scan does not remove missing items from the database when more than 20 % of a mount, or of one library path, cannot be found (a drive that came back half-empty). They stay in the library marked Not found, and you can remove them with Remove all not found. Off: the scan removes whatever it cannot find, whatever the share. A library path that is readable but completely empty is always left alone. Applies to music, movies and TV shows. No file is ever touched.</p>
        </section>
        <section class="settings-section" data-tab="music"><h3>Library</h3>
            <label class="choice"><input type="checkbox" id="sort-ignore-the" data-sort-ignore-the ${cfg.sort_ignore_the !== false ? "checked" : ""}> Ignore a leading The, A, or An when sorting the library</label>
            <p class="muted">The Beatles is listed under B. Turn this off to list that name under T. The same choice is on the Movies and TV tabs and applies to every library.</p>
            <h3>UI Elements</h3>
            <label class="choice"><input type="checkbox" id="video-ui-music-poster-badges" ${(typeof videoCfg === "function" ? videoCfg() : {}).ui_music_poster_badges !== false ? "checked" : ""}> Show format and quality badges on the album cover</label>
            <label class="choice"><input type="checkbox" id="video-ui-music-art-badges" ${(typeof videoCfg === "function" ? videoCfg() : {}).ui_music_art_badges !== false ? "checked" : ""}> Show resolution and aspect ratio badges on artwork</label>
            <label class="choice"><input type="checkbox" id="video-ui-music-edition-badge" ${(typeof videoCfg === "function" ? videoCfg() : {}).ui_music_edition_badge !== false ? "checked" : ""}> Show the edition badge (Original studio album, Deluxe edition, EP, Single&hellip;) on album rows</label>
            <label class="choice"><input type="checkbox" id="video-ui-music-date-added" ${(typeof videoCfg === "function" ? videoCfg() : {}).ui_music_date_added !== false ? "checked" : ""}> Show date added</label>
            <label class="choice"><input type="checkbox" id="video-ui-music-processed" ${(typeof videoCfg === "function" ? videoCfg() : {}).ui_music_processed !== false ? "checked" : ""}> Show processed/unprocessed checkmark</label>
            <label class="field">Export format ${typeof videoSelect === "function" ? videoSelect("video-export-format-music", (typeof videoCfg === "function" ? videoCfg() : {}).export_format_music || "csv", [["csv", "CSV (spreadsheets)"], ["xml", "XML"]]) : ""}</label>
        </section>
        ${libraryFoldersSection(cfg, mounts)}
        ${pathMappingsSection()}
        <section class="settings-section" data-tab="music"><h3>Storage and structure</h3>
            <label class="choice"><input type="radio" name="nfo" value="kodi" ${cfg.nfo_profile === "kodi" ? "checked" : ""}> Kodi/Jellyfin (artist.nfo and album.nfo)</label>
            <label class="choice"><input type="radio" name="nfo" value="emby" ${cfg.nfo_profile === "emby" ? "checked" : ""}> Emby (folder.nfo)</label>
            <label class="field">.nfo dialect ${typeof videoSelect === "function" ? videoSelect("music-nfo-dialect", cfg.nfo_dialect || "kodi", [["kodi", "Kodi"], ["emby", "Emby / Jellyfin (adds lockdata)"], ["plex", "Plex (adds musicbrainz guid)"]]) : ""}</label>
            <p class="muted">Kodi writes the plain Kodi artist and album .nfo. Emby / Jellyfin adds a lockdata tag so the server keeps the saved values. Plex adds a guid tag built from the MusicBrainz id. The file names are set by the choice above.</p>
            <label class="choice"><input type="checkbox" id="music-nfo-backup" ${cfg.nfo_backup !== false ? "checked" : ""}> Keep a .nfo.bak when a rewrite replaces a file</label>
            <label class="choice"><input type="checkbox" id="allmusic-enabled" ${cfg.allmusic_enabled !== false ? "checked" : ""}> Look up AllMusic when finding metadata</label>
            <p class="muted">Find metadata can read AllMusic for the artist biography, the album review, and styles, moods, and themes. Album reviews and descriptors use the first checked source that has text. Requests are spaced a few seconds apart. The user average under the album cover comes from AllMusic when this lookup is on.</p>
            ${metaPriorityList(cfg, "biography", "Biography")}
            <label class="choice"><input type="checkbox" id="biography-longest" ${cfg.biography_longest !== false ? "checked" : ""}> Use the longest biography</label>
            <p class="muted">Every checked biography source is read. The longest text is kept, and a scan replaces a shorter biography you did not edit yourself. The list above still decides which sources are used, and it breaks a tie. Turn this off to keep the first source in that list that has a biography, and to leave a stored biography as it is.</p>
            ${metaPriorityList(cfg, "review", "Album review")}
            ${metaPriorityList(cfg, "descriptors", "Styles, moods, and themes")}
            <label class="choice"><input type="checkbox" id="nfo-on-bio-save" ${cfg.nfo_on_bio_save !== false ? "checked" : ""}> Update artist.nfo when a biography is saved</label>
            <p class="muted">Saving a biography also rewrites the artist .nfo in that artist’s folder. Emby writes folder.nfo. Turn this off to keep the file until you press Write artist.nfo.</p>
            <p class="muted">Choose which release types are written at the end of the album title. Album is off, because a normal album title usually stays as it is. A selected type is written as (single), (EP), (live), (compilation), or (album). A title that already ends with one of those is updated instead of repeated. Folder names that use the album title include it too. The release type is always stored as its own tag either way.</p>
            <div class="suffix-types" role="group" aria-label="Release types to append">${suffixTypeButtons(cfg)}</div>
            <p class="muted">Apply match writes the categories that are on. Artwork stays a manual choice. Batch Find metadata only loads a release into the library tree. Tags also marks the album processed.</p>
            <div class="suffix-types" role="group" aria-label="What Apply match writes">${applyWriteButtons(cfg)}</div>
            <p class="section-label">Choose MB release during</p>
            <p class="muted">The scan pauses after each album’s MusicBrainz lookup. Pick a release or skip it. Apply match in that window saves the Tags, .nfo, and Lyrics categories that are on. Forced also pauses when the Force checkbox is on.</p>
            <div class="suffix-types" role="group" aria-label="Scan types that pause to choose a MusicBrainz release">${scanModeButtons(cfg, "choose_release_modes")}</div>
            <p class="section-label">Artwork lookup during</p>
            <p class="muted">After the release step, the scan pauses so you can choose artwork for that album before the next one starts. Forced also pauses when the Force checkbox is on.</p>
            <div class="suffix-types" role="group" aria-label="Scan types that pause to choose artwork">${scanModeButtons(cfg, "artwork_lookup_modes")}</div>
            <label class="choice"><input type="checkbox" id="refresh-discography-during-scan" ${cfg.refresh_discography_during_scan !== false ? "checked" : ""}> Update MusicBrainz discography during a scan</label>
            <p class="muted">An incremental deep scan checks only artists that gained a new album or had an album's files change, and only when that artist's catalog is missing or older than 7 days. A full or deep scan checks every artist in the scanned folders on that same 7 day rule. A catalog newer than that is left as it is.</p>
            <label class="choice"><input type="checkbox" id="fill-mb-metadata-during-incremental" ${cfg.fill_mb_metadata_during_incremental !== false ? "checked" : ""}> Fill in missing MusicBrainz metadata during an incremental deep scan</label>
            <p class="muted">A full or deep scan copies blank MusicBrainz fields onto an album that already has a release id. Titles, artist names, and track numbers that are already stored stay as they are. An incremental deep scan does this only when this is on, and only for albums that are new or changed. An album with no release id is left for Find metadata.</p>
            <label class="choice"><input type="checkbox" id="fill-missing-during-scan" ${cfg.fill_missing_during_scan !== false ? "checked" : ""}> Download missing metadata and artwork during a scan</label>
            <p class="muted">After the sidecar audit, a scan fills a blank biography or album review and downloads artwork that is still missing. It looks for every type checked under Artwork to fetch. An incremental deep scan only does this for albums that are new or changed, and for their artists. A full or deep scan still checks the whole library. A shorter biography is replaced when Use the longest biography is on, unless you edited that biography yourself. Turn this off to leave those steps out of the scan.</p>
            <label class="choice"><input type="checkbox" id="limited-artwork-during-scan" ${cfg.limited_artwork_during_scan ? "checked" : ""}> Limited artwork search during scan</label>
            <p class="muted">When this is on, the artwork step only looks for a missing artist thumb or album cover. When it is off, that step looks for every artwork type that is checked under Artwork to fetch and is still missing from the folder.</p>
            <label class="choice"><input type="checkbox" id="scan-rewrite-nfo" ${cfg.scan_rewrite_nfo ? "checked" : ""}> Rewrite .nfo files at the end of a scan</label>
            <p class="muted">The last stage writes an album.nfo that is missing, and it rewrites album.nfo for a new or changed album that already has a MusicBrainz id. The file is written after reviews, countries, and original years are stored. When this is on, that stage also replaces every artist.nfo and album.nfo in the scanned folders. A full or deep scan without this box still writes files that are missing.</p>
            <label>Skip a metadata miss for
                <input id="metadata-miss-days" type="number" min="0" max="3650" value="${Math.max(0, Math.min(3650, Number(cfg.metadata_miss_days) || 0))}"> days
            </label>
            <p class="muted">A biography or review lookup that finds nothing waits this many days before the next scan tries it again. 0 tries again on every scan. Saving a biography or review yourself clears the wait.</p>
        </section>
        <section class="settings-section" data-tab="files"><h3>Purge folders</h3>
            <h4>Data folder</h4>
            <p class="muted">Holds what Curator cannot download or rebuild: images you uploaded and copies kept when an image was replaced, for music, movies, TV shows and sets (<span class="mono">/data/artwork/additional/music</span>, <span class="mono">movie</span>, <span class="mono">tv</span>, <span class="mono">sets</span>). They are listed as options in the artwork windows. Back this folder up.</p>
            <p class="muted" id="storage-info-data">Checking…</p>
            <p><button type="button" class="btn-danger" data-action="purge-storage" data-folder="data">Purge uploaded and replaced artwork</button></p>
            <h4>Cache</h4>
            <p class="muted">Thumbnails, artwork options downloaded from the internet, video previews and recognised subtitle text. Everything in it is rebuilt when needed, and it also trims itself, so purging only frees space sooner.</p>
            <p class="muted" id="storage-info-cache">Checking…</p>
            <p><button type="button" class="btn-ghost" data-action="purge-storage" data-folder="cache">Purge cache</button></p>
        </section>
        <section class="settings-section" data-tab="files"><h3>Missing logos</h3>
            <p class="muted">Networks and studios in your library that have no logo yet, busiest first. Upload a PNG or any image for a name and it is used from then on. Your logos are kept in the data folder (<span class="mono">/data/brands</span>) and win over the ones shipped with Curator.</p>
            <p>
                <button type="button" class="btn-ghost" data-action="logos-load" data-media="tv">TV networks</button>
                <button type="button" class="btn-ghost" data-action="logos-load" data-media="movies">Movie studios</button>
            </p>
            <div id="logos-list" class="muted"></div>
        </section>
        <section class="settings-section" data-tab="music"><h3>Artwork to fetch</h3>
            <p class="muted">Names match Kodi 22. Clearlogo is the logo artwork. Fanart is the full-screen artist image. Discart replaces the older cdart.png name. A multi-disc album also saves discart1.png, discart2.png, and so on, plus a discart.png inside each CD folder. Cover Art Archive types are mapped onto those files.</p>
            <label>Maximum edge
                <select id="resolution-preset">${presetOptions}</select>
            </label>
            <p class="muted">Small is 500 px, medium 700 px, large 1,000 px, and very large 1,300 px. Curator keeps the largest image that fits that edge. A thumbnail under 500 px is not suggested when a larger cover is available. Unlimited has no maximum. Custom sets the number yourself. A larger image is used only when nothing that fits is large enough.</p>
            <label id="min-resolution-wrap" class="${preset === "custom" ? "" : "hidden"}">Custom maximum edge
                <input id="min-resolution" type="number" min="0" max="10000" value="${Number(cfg.min_resolution) || 0}"> px. 0 means no maximum.
            </label>
            <label>Fanart images
                <input id="fanart-count" type="number" min="1" max="20" value="${Number(cfg.fanart_count) || 5}">
            </label>
            <p class="muted">How many artist fanart images a scan downloads on its own. The first is saved as fanart.jpg or fanart.png, then fanart1, fanart2, and so on. Fanart has to be enabled below. Choosing another image from the artwork tab keeps going past this number.</p>
            <div class="section-label">Source priority</div>
            <div class="priority-list">${priority}</div>
            ${assets}
        </section>
        <section class="settings-section" data-tab="general"><h3>API credentials</h3>
            <p class="muted">A saved key is shown as ••••••••. Leave the field blank to keep it, or type a new key to replace it. A key from docker-compose is kept when the field is blank. Test checks the typed key, or the saved one when the field is blank.</p>
            <div class="section-label">Movies and TV</div>
            ${videoKeyFields()}
            <div class="section-label">Music and artwork</div>
            <p class="muted">MusicBrainz, Cover Art Archive, Deezer, LRCLIB, TheAudioDB, and Wikipedia do not need keys. AcoustID also needs fpcalc, which is included in the image. Last.fm is on the Integrations tab.</p>
            <label>MusicBrainz contact <input id="mb-contact" value="${escapeHtml(cfg.musicbrainz_contact || "")}"></label>
            ${keyField("fanart_key", "fanart-key", "Fanart.tv key", "FANART_API_KEY")}
            <p class="muted">Fanart.tv is used for music, movie, set and TV artwork.</p>
            ${keyField("acoustid_key", "acoustid-key", "AcoustID key", "ACOUSTID_API_KEY")}
            <p class="muted">The Trakt client id is on the Integrations tab.</p>
        </section>
        <section class="settings-section" data-tab="music"><h3>Lyrics</h3>
            <label class="choice"><input type="radio" name="lyrics" value="lrc" ${cfg.lyrics_mode === "lrc" ? "checked" : ""}> Synced karaoke (.lrc)</label>
            <label class="choice"><input type="radio" name="lyrics" value="txt" ${cfg.lyrics_mode === "txt" ? "checked" : ""}> Plain text (.txt)</label>
        </section>
        <section class="settings-section" data-tab="music"><h3>Artwork in the audio file</h3>
            <label class="choice"><input type="checkbox" id="embed-artwork" ${cfg.embed_artwork ? "checked" : ""}> Embed folder.jpg into audio on save</label>
            <label>Embedded image maximum edge
                <select id="embed-preset">${embedOptions}</select>
            </label>
            <p class="muted">This resizes the picture stored inside the audio file. The folder.jpg next to the music stays full size. Unlimited embeds the full image.</p>
            <label id="embed-max-wrap" class="${embedPreset === "custom" ? "" : "hidden"}">Custom embedded edge
                <input id="embed-max-px" type="number" min="0" max="10000" value="${Number(cfg.embed_max_px) || 0}"> px. 0 means no maximum.
            </label>
        </section>
        <section class="settings-section" data-tab="music"><h3>On Lidarr import</h3>
            <label class="choice"><input type="checkbox" id="scrape-music" ${((state.settings.automation || {}).music !== false) ? "checked" : ""}> Scrape music found by a webhook scan</label>
            <p class="muted">Off leaves Lidarr import webhooks out of the music scan. The same switch is on Automation.</p>
        </section>
        <section class="settings-section" data-tab="integrations">${integrationHeading("last.fm", "Last.fm")}
            <p class="muted">Last.fm supplies artist biographies, album reviews, and tags. Album lookup uses the API key. The shared secret is stored for signed requests. Last.fm does not publish an album score, so the album line shows AllMusic and the Kodi rating written from it.</p>
            ${keyField("lastfm_key", "lastfm-key", "API key", "LASTFM_API_KEY")}
            ${secretField("lastfm_secret", "lastfm-secret", "Shared secret", "LASTFM_API_SECRET")}
        </section>
        <section class="settings-section" data-tab="integrations">${integrationHeading("lidarr", "Lidarr")}
            <p class="muted">Lidarr sends a webhook after it imports a release. In Lidarr open Settings, Connect, and add a Webhook. Paste the address below. Turn on On Grab, On Import, On Upgrade, On Download Failure, and On Import Failure. On Grab reports that a release was sent for download. On Download Failure and On Import Failure report a failed download. Test should succeed. An older Lidarr webhook that already uses a token on /api/webhooks/lidarr keeps working.</p>
            ${arrSwitches("lidarr", "Scan a release when Lidarr reports it imported")}
            <label class="choice"><input type="checkbox" id="lidarr-monitor-new" ${cfg.lidarr_monitor_new !== false ? "checked" : ""}> Monitor albums when adding a new artist to Lidarr</label>
            <p class="muted">When this is on, Lidarr marks that artist’s albums as monitored. It does not start a download search for every album. When it is off, the artist is added and only a release you search later is monitored.</p>
            <p class="muted">The scan covers that album only. It reads new or changed files, looks the album up on MusicBrainz, and fills missing metadata and artwork the same way an incremental deep scan does. Grab and failure notices still arrive when scan on import is off.</p>
            ${arrWebhookLine()}
            <div class="section-label">Path prefixes</div>
            <p class="muted">Use these when Lidarr and Curator do not see the same folder. The longest Lidarr prefix is replaced with the Curator path. Leave this empty when both sides use the same path.</p>
            ${lidarrPathRows(cfg.lidarr_paths)}
            <p><button type="button" class="btn-ghost" data-action="add-lidarr-path">Add path prefix</button></p>
            <label>Lidarr address
                <input id="lidarr-api-url" value="${escapeHtml(cfg.lidarr_url || "")}" placeholder="http://lidarr:8686" spellcheck="false">
            </label>
            ${videoKeyField("lidarr_api_key", "lidarr-api-key", "Lidarr API key", "LIDARR_API_KEY", "")}
            ${arrTest("auto-lidarr-test")}
            <p><button type="button" class="btn-ghost" data-action="auto-lidarr-load">Load folders and profiles</button></p>
            <label class="field">Root folder <select id="lidarr-root">
                <option value="">Lidarr's first root folder</option>
                ${(cfg.lidarr && cfg.lidarr.root_folder) ? `<option value="${escapeHtml(cfg.lidarr.root_folder)}" selected>${escapeHtml(cfg.lidarr.root_folder)}</option>` : ""}
            </select></label>
            <label class="field">Quality profile <select id="lidarr-profile">
                <option value="0">Lidarr's first quality profile</option>
                ${savedProfileOptions(cfg.lidarr && cfg.lidarr.quality_profiles, cfg.lidarr && cfg.lidarr.quality_profile, cfg.lidarr && cfg.lidarr.quality_profile_name).map((item) => `<option value="${item.id}" ${Number(item.id) === Number(cfg.lidarr.quality_profile) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}
            </select></label>
            <label class="field">Metadata profile <select id="lidarr-metadata">
                <option value="0">Lidarr's first metadata profile</option>
                ${savedProfileOptions(cfg.lidarr && cfg.lidarr.metadata_profiles, cfg.lidarr && cfg.lidarr.metadata_profile, cfg.lidarr && cfg.lidarr.metadata_profile_name).map((item) => `<option value="${item.id}" ${Number(item.id) === Number(cfg.lidarr.metadata_profile) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}
            </select></label>
            <p class="muted">Right-click a discography cover and choose Look up in Lidarr, or use Search missing in Lidarr for every studio album that is not on disk. The search is a job, so Jobs shows it while Lidarr works. An album already on disk is searched again. A missing album is added, and the artist is added too when Lidarr does not have them yet, using the root folder and profiles above. Lossless is a quality profile you create in Lidarr, then pick here. LIDARR_URL and LIDARR_API_KEY in docker-compose are used when these fields are empty.</p>
        </section>
        ${scheduleSection(cfg, "schedule")}
        ${scheduleSection(cfg, "backup")}
        ${restoreSectionHtml()}
        ${videoSettingsSections()}`;
    applySettingsTab({ keepScroll: true });
    if (typeof paintConnectionErrors === "function") paintConnectionErrors((state.system || {}).connections);
    if (body) {
        body.scrollTop = scroll;
        requestAnimationFrame(() => { body.scrollTop = scroll; });
    }
    queueSchedulePreview();
    syncBackupButton();
    paintStorage();
    bindGeneralRuntime();
}

function bindGeneralRuntime() {
    const scrapeMusic = document.getElementById("scrape-music");
    const autoMusic = document.getElementById("auto-music");
    if (scrapeMusic && autoMusic && !scrapeMusic.dataset.bound) {
        scrapeMusic.dataset.bound = "1";
        scrapeMusic.addEventListener("change", () => { autoMusic.checked = scrapeMusic.checked; });
        autoMusic.addEventListener("change", () => { scrapeMusic.checked = autoMusic.checked; });
    }
}

function showSchedulePanel(group, mode) {
    const root = document.querySelector(`[data-schedule-group="${group}"]`);
    if (!root) return;
    root.querySelectorAll("[data-schedule-panel]").forEach((panel) => {
        panel.classList.toggle("hidden", panel.dataset.schedulePanel !== mode);
    });
}

function scheduleSection(cfg, group) {
    const prefix = group === "backup" ? "backup" : "schedule";
    const modeValue = cfg[`${prefix}_mode`];
    const mode = ["preset", "daily", "weekly", "monthly", "custom"].includes(modeValue) ? modeValue : "preset";
    const presets = Array.isArray(cfg.schedule_presets) ? cfg.schedule_presets : [];
    const summary = cfg[`${prefix}_summary`] || {};
    const weekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    const weekday = Number.isInteger(Number(cfg[`${prefix}_weekday`])) ? Number(cfg[`${prefix}_weekday`]) : 0;
    const monthDay = Math.min(31, Math.max(1, Number(cfg[`${prefix}_day`]) || 1));
    const fallbackTime = prefix === "backup" ? "04:00" : "03:00";
    const time = /^\d{2}:\d{2}/.test(cfg[`${prefix}_time`] || "") ? String(cfg[`${prefix}_time`]).slice(0, 5) : fallbackTime;
    const scanMode = cfg.schedule_scan_mode === "deep" || cfg.schedule_scan_mode === "full" ? cfg.schedule_scan_mode : "incremental";
    const groups = [];
    presets.forEach((preset) => {
        const name = preset.group || "Presets";
        let bucket = groups.find((item) => item.name === name);
        if (!bucket) {
            bucket = { name, items: [] };
            groups.push(bucket);
        }
        bucket.items.push(preset);
    });
    const presetOptions = groups.map((bucket) => {
        const options = bucket.items.map((preset) =>
            `<option value="${escapeHtml(preset.id)}" ${cfg[`${prefix}_preset`] === preset.id ? "selected" : ""}>${escapeHtml(preset.name)}</option>`
        ).join("");
        return `<optgroup label="${escapeHtml(bucket.name)}">${options}</optgroup>`;
    }).join("");
    const dayOptions = weekdays.map((name, index) =>
        `<option value="${index}" ${weekday === index ? "selected" : ""}>${name}</option>`
    ).join("");
    const monthOptions = Array.from({ length: 31 }, (_, index) => {
        const day = index + 1;
        return `<option value="${day}" ${monthDay === day ? "selected" : ""}>${day}</option>`;
    }).join("");
    const modes = [
        ["preset", "Preset"],
        ["daily", "Daily"],
        ["weekly", "Weekly"],
        ["monthly", "Monthly"],
        ["custom", "Crontab"],
    ].map(([value, label]) =>
        `<label class="choice"><input type="radio" name="${prefix}-mode" value="${value}" ${mode === value ? "checked" : ""}> ${label}</label>`
    ).join("");
    const next = summary.is_valid === false
        ? "That expression needs five fields: minute hour day month weekday."
        : summary.next_run_display
            ? (summary.enabled ? `Next run ${summary.next_run_display}.` : `Scheduler is off. Next run would be ${summary.next_run_display}.`)
            : "";
    const title = prefix === "backup" ? "Backup schedule" : "Scan schedule";
    const enabledLabel = prefix === "backup" ? "Dump the database on a schedule" : "Run a library pass on a schedule";
    const writableMounts = (state.mounts || []).filter((mount) => mount.writable);
    const extra = prefix === "backup"
        ? `<label>Backup folder
                <span class="path-field"><input id="backup-folder" spellcheck="false" value="${escapeHtml(cfg.backup_folder || "")}" placeholder="${escapeHtml(backupDefaultFolder())}"><button type="button" class="btn-ghost" data-action="browse-backup-folder">Browse</button></span>
            </label>
            <datalist id="backup-folder-mounts">${writableMounts.map((mount) => `<option value="${escapeHtml(mount.path)}">`).join("")}</datalist>
            <p class="muted">Any folder on a mount marked rw in the container. Leave it empty to use ${escapeHtml(backupDefaultFolder())} (BACKUP_DIR in docker-compose). Writable mounts: ${writableMounts.length ? writableMounts.map((mount) => `<span class="mono">${escapeHtml(mount.path)}</span>`).join(", ") : "none detected"}.</p>
            <label>Dumps to keep
                <input id="backup-keep" data-schedule-preview="1" type="number" min="1" max="100" value="${Number(cfg.backup_keep) || 14}">
            </label>
            <label class="choice"><input id="backup-snapshot" type="checkbox" ${cfg.backup_snapshot_before_bulk ? "checked" : ""}> Snapshot the database before large writes</label>
            <p class="muted">Before removing, deleting, batch editing or running a file job on 5 or more items, a dump named before-bulk-… is written to the backup folder. Only the last 2 are kept, and each is about the size of the database, so leave this off unless you want the safety net.</p>
            <p class="muted">Each run writes a custom-format dump to the backup folder. Older dumps beyond this count are removed. A scheduled dump waits if a scan is already running, then starts. Backup now stays off during a scan. The live database stays in the database volume. A Resonance dump placed in the Curator folder is listed below for a music import. Times follow the container timezone.</p>
            <p><button type="button" id="backup-now" data-action="backup-now">Backup now</button></p>
            <p class="muted" id="backup-now-note"></p>`
        : `            <label>Library
                <select id="schedule-media">
                    ${[["music", "Music"], ["movies", "Movies"], ["tv", "TV shows"], ["sets", "Movie sets"]].map(([value, label]) =>
                        `<option value="${value}" ${(cfg.schedule_media || "music") === value ? "selected" : ""}>${label}</option>`
                    ).join("")}
                </select>
            </label>
            <div class="schedule-scan-type">
                <label class="choice"><input type="radio" name="schedule-scan" value="incremental" data-schedule-preview="1" ${scanMode === "incremental" ? "checked" : ""}> Incremental deep scan</label>
                <label class="choice"><input type="radio" name="schedule-scan" value="full" data-schedule-preview="1" ${scanMode === "full" ? "checked" : ""}> Full scan</label>
                <label class="choice"><input type="radio" name="schedule-scan" value="deep" data-schedule-preview="1" ${scanMode === "deep" ? "checked" : ""}> Deep scan</label>
            </div>
            <label>Scan logs to keep
                <input id="scan-log-keep" type="number" min="1" max="100" value="${Math.min(100, Math.max(1, Number(cfg.scan_log_keep) || 30))}">
            </label>
            <p class="muted">Each finished scan writes config/logs/YYYY-MM-DD-HHMMSS_&lt;media&gt;_scan.log. When a scan finishes with more logs than this, the oldest log is deleted. The previous single scan.log file is left as it is.</p>
            <p class="muted">Each saved schedule runs on its own. Choose Music, Movies, TV shows, or Movie sets. A movie set pass scrapes metadata and artwork for every set. A pass waits if another library scan is already running, then starts. A music pass also fingerprints unmatched albums and fetches missing lyrics.</p>
            <p><button type="button" id="save-scan-schedule" data-action="save-scan-schedule">Save schedule</button></p>`;
    const preview = prefix === "backup"
        ? `<div class="schedule-preview-card" id="backup-preview">
                <div class="schedule-preview-header">
                    <span id="backup-description">${escapeHtml(summary.description || "")}</span>
                    <span class="mono" id="backup-cron-label">${escapeHtml(summary.effective_cron || "")}</span>
                </div>
                <p class="muted" id="backup-next">${escapeHtml(next)}</p>
                <p class="muted" id="backup-zone">${summary.timezone ? `Times use ${escapeHtml(summary.timezone)}.` : ""}</p>
            </div>`
        : `<div class="schedule-preview-card" id="schedule-preview">
                <div id="schedule-saved">${savedScheduleHtml(cfg)}</div>
            </div>`;
    return `<section class="settings-section" data-schedule-group="${prefix}" data-tab="${prefix === "backup" ? "backup" : "sync"}"><h3>${title}</h3>
            <label class="choice"><input type="checkbox" id="${prefix}-enabled" data-schedule-preview="1" ${cfg[`${prefix}_enabled`] ? "checked" : ""}> ${enabledLabel}</label>
            <div class="schedule-mode-tabs">${modes}</div>
            <div class="schedule-panel ${mode === "preset" ? "" : "hidden"}" data-schedule-panel="preset">
                <label>Preset
                    <select id="${prefix}-preset" data-schedule-preview="1">${presetOptions}</select>
                </label>
            </div>
            <div class="schedule-panel ${mode === "daily" ? "" : "hidden"}" data-schedule-panel="daily">
                <label>Time
                    <input id="${prefix}-time-daily" data-schedule-preview="1" data-schedule-time="1" type="time" value="${escapeHtml(time)}">
                </label>
            </div>
            <div class="schedule-panel ${mode === "weekly" ? "" : "hidden"}" data-schedule-panel="weekly">
                <div class="schedule-grid">
                    <label>Day
                        <select id="${prefix}-weekday" data-schedule-preview="1">${dayOptions}</select>
                    </label>
                    <label>Time
                        <input id="${prefix}-time-weekly" data-schedule-preview="1" data-schedule-time="1" type="time" value="${escapeHtml(time)}">
                    </label>
                </div>
            </div>
            <div class="schedule-panel ${mode === "monthly" ? "" : "hidden"}" data-schedule-panel="monthly">
                <div class="schedule-grid">
                    <label>Day of the month
                        <select id="${prefix}-day" data-schedule-preview="1">${monthOptions}</select>
                    </label>
                    <label>Time
                        <input id="${prefix}-time-monthly" data-schedule-preview="1" data-schedule-time="1" type="time" value="${escapeHtml(time)}">
                    </label>
                </div>
                <p class="muted">A day the month does not have, such as the 31st in February, waits until the next month that includes it.</p>
            </div>
            <div class="schedule-panel ${mode === "custom" ? "" : "hidden"}" data-schedule-panel="custom">
                <label>Crontab
                    <input id="${prefix}-cron" data-schedule-preview="1" value="${escapeHtml(cfg[`${prefix}_cron`] || (prefix === "backup" ? "0 4 * * *" : "0 3 * * *"))}" placeholder="0 3 * * *" spellcheck="false">
                </label>
                <p class="muted">Five fields: minute, hour, day of month, month, day of week. Sunday is 0. <span class="mono">0 3 * * 1</span> is every Monday at 03:00.</p>
            </div>
            ${extra}
            ${preview}
        </section>`;
}

function scheduleNextSentence(summary, enabled) {
    if (!summary || summary.is_valid === false) return "That expression needs five fields: minute hour day month weekday.";
    if (!summary.next_run_display) return "";
    if (enabled) return `Next run ${summary.next_run_display}.`;
    return `Scheduler is off. Next run would be ${summary.next_run_display}.`;
}

function savedSchedulesEnabled(cfg) {
    const box = document.getElementById("schedule-enabled");
    if (box) return box.checked;
    return !!(cfg && cfg.schedule_enabled);
}

function savedScheduleHtml(cfg) {
    const items = Array.isArray(cfg && cfg.scan_schedule_summaries) ? cfg.scan_schedule_summaries : [];
    const enabled = savedSchedulesEnabled(cfg);
    if (!items.length) {
        return `<p class="muted">No schedules saved. Choose a scan and a time, then press Save schedule.</p>`;
    }
    return items.map((summary, index) => {
        const title = `Schedule #${index + 1}: ${summary.media_label || "Music"} · ${summary.scan_label || "Incremental deep scan"}`;
        const zone = summary.timezone ? `Times use ${summary.timezone}.` : "";
        return `<article class="schedule-saved-item">
            <div class="schedule-preview-header">
                <span>${escapeHtml(title)}</span>
                <button type="button" class="btn-ghost btn-remove" data-action="remove-scan-schedule" data-index="${index}">Remove</button>
            </div>
            <p>${escapeHtml(summary.description || "")}</p>
            <p class="mono">${escapeHtml(summary.effective_cron || "")}</p>
            <p class="muted">${escapeHtml(scheduleNextSentence(summary, enabled))}</p>
            <p class="muted schedule-zone">${escapeHtml(zone)}</p>
        </article>`;
    }).join("");
}

function paintSavedSchedules(cfg) {
    const box = document.getElementById("schedule-saved");
    if (!box || !cfg) return;
    box.innerHTML = savedScheduleHtml(cfg);
}

function readScheduleTime(group) {
    const root = document.querySelector(`[data-schedule-group="${group}"]`);
    const fallback = (state.settings && state.settings[`${group}_time`]) || (group === "backup" ? "04:00" : "03:00");
    if (!root) return fallback;
    const active = root.querySelector("[data-schedule-panel]:not(.hidden) input[data-schedule-time]");
    if (active && active.value) return active.value.slice(0, 5);
    const any = root.querySelector("input[data-schedule-time]");
    if (any && any.value) return any.value.slice(0, 5);
    return fallback;
}

function readScheduleGroup(group) {
    const root = document.querySelector(`[data-schedule-group="${group}"]`);
    const prefix = group === "backup" ? "backup" : "schedule";
    if (!root) return {};
    const mode = root.querySelector(`input[name='${prefix}-mode']:checked`);
    const preset = root.querySelector(`#${prefix}-preset`);
    const weekday = root.querySelector(`#${prefix}-weekday`);
    const day = root.querySelector(`#${prefix}-day`);
    const cron = root.querySelector(`#${prefix}-cron`);
    const enabled = root.querySelector(`#${prefix}-enabled`);
    const fields = {
        [`${prefix}_enabled`]: !!(enabled && enabled.checked),
        [`${prefix}_mode`]: mode ? mode.value : "preset",
        [`${prefix}_preset`]: preset ? preset.value : "",
        [`${prefix}_time`]: readScheduleTime(prefix),
        [`${prefix}_weekday`]: weekday ? Number(weekday.value) : 0,
        [`${prefix}_day`]: day ? Number(day.value) : 1,
        [`${prefix}_cron`]: cron ? cron.value.trim() : "",
    };
    if (prefix === "schedule") {
        const scan = root.querySelector("input[name='schedule-scan']:checked");
        fields.schedule_scan_mode = scan ? scan.value : "incremental";
        const library = root.querySelector("#schedule-media");
        fields.schedule_media = library ? library.value : "music";
        const logs = root.querySelector("#scan-log-keep");
        fields.scan_log_keep = logs ? Number(logs.value) : 30;
    } else {
        const keep = root.querySelector("#backup-keep");
        fields.backup_keep = keep ? Number(keep.value) : 14;
        const snapshot = root.querySelector("#backup-snapshot");
        if (snapshot) fields.backup_snapshot_before_bulk = snapshot.checked;
        const folder = root.querySelector("#backup-folder");
        if (folder) fields.backup_folder = folder.value.trim();
    }
    return fields;
}

function paintSchedulePreview(group, summary) {
    const prefix = group === "backup" ? "backup" : "schedule";
    const description = document.getElementById(`${prefix}-description`);
    const cronLabel = document.getElementById(`${prefix}-cron-label`);
    const next = document.getElementById(`${prefix}-next`);
    const zone = document.getElementById(`${prefix}-zone`);
    if (!description || !summary) return;
    description.textContent = summary.description || "";
    if (cronLabel) cronLabel.textContent = summary.effective_cron || "";
    if (next) {
        if (summary.is_valid === false) next.textContent = "That expression needs five fields: minute hour day month weekday.";
        else if (!summary.next_run_display) next.textContent = "";
        else if (summary.enabled) next.textContent = `Next run ${summary.next_run_display}.`;
        else next.textContent = `Scheduler is off. Next run would be ${summary.next_run_display}.`;
    }
    if (zone) zone.textContent = summary.timezone ? `Times use ${summary.timezone}.` : "";
    if (state.settings) state.settings[`${prefix}_summary`] = summary;
}

let schedulePreviewToken = 0;

function queueSchedulePreview() {
    clearTimeout(queueSchedulePreview.timer);
    queueSchedulePreview.timer = setTimeout(refreshSchedulePreview, 250);
}

async function refreshSchedulePreview() {
    if (!document.getElementById("schedule-preview") && !document.getElementById("backup-preview")) return;
    const token = ++schedulePreviewToken;
    if (document.getElementById("schedule-saved") && state.settings) paintSavedSchedules(state.settings);
    if (!document.getElementById("backup-preview")) return;
    try {
        const backup = await api("/api/schedule/preview", { method: "POST", body: { ...readScheduleGroup("backup"), kind: "backup" } });
        if (token !== schedulePreviewToken) return;
        paintSchedulePreview("backup", backup);
    } catch (error) {
        if (token !== schedulePreviewToken) return;
        const next = document.getElementById("backup-next");
        if (next && !next.textContent) next.textContent = "Next run shows after the settings are saved.";
    }
}

async function saveScanSchedule() {
    if (!rememberSettingsForm()) return;
    const fields = readScheduleGroup("schedule");
    let summary;
    try {
        summary = await api("/api/schedule/preview", { method: "POST", body: { ...fields, kind: "schedule" } });
    } catch (error) {
        notify(error.message || "That schedule could not be read.", "error");
        return;
    }
    if (!summary || summary.is_valid === false || !summary.effective_cron) {
        notify("That expression needs five fields: minute hour day month weekday.", "warning");
        return;
    }
    const entry = {
        scan_mode: fields.schedule_scan_mode || "incremental",
        cron: summary.effective_cron,
        media: fields.schedule_media || "music",
    };
    const list = Array.isArray(state.settings.scan_schedules) ? state.settings.scan_schedules.slice() : [];
    if (list.some((item) => item.cron === entry.cron && item.scan_mode === entry.scan_mode && (item.media || "music") === entry.media)) {
        notify("That schedule is already in the list.", "info");
        return;
    }
    if (list.length >= 20) {
        notify("Twenty schedules is the limit.", "warning");
        return;
    }
    state.settings.scan_schedules = list.concat([entry]);
    const saved = await saveSettings({ keepOpen: true, message: "Schedule saved." });
    if (!saved) state.settings.scan_schedules = list;
}

async function removeScanSchedule(index) {
    if (!rememberSettingsForm()) return;
    const list = Array.isArray(state.settings.scan_schedules) ? state.settings.scan_schedules.slice() : [];
    const at = Number(index);
    if (!Number.isInteger(at) || at < 0 || at >= list.length) return;
    const previous = list.slice();
    list.splice(at, 1);
    state.settings.scan_schedules = list;
    const saved = await saveSettings({ keepOpen: true, message: "Schedule removed." });
    if (!saved) state.settings.scan_schedules = previous;
}

function showPlayerCleanPanel(mode) {
    document.querySelectorAll("[data-player-clean-panel]").forEach((panel) => {
        panel.classList.toggle("hidden", panel.dataset.playerCleanPanel !== mode);
    });
}

function _readPlayerCleanCron() {
    const mode = (document.querySelector('[name="player-clean-mode"]:checked') || {}).value || "preset";
    if (mode === "preset") return (document.getElementById("player-clean-preset") || {}).value || "";
    if (mode === "daily") {
        const t = (document.getElementById("player-clean-time-daily") || {}).value || "04:00";
        const [h, m] = t.split(":").map(Number);
        return `${m || 0} ${h || 4} * * *`;
    }
    if (mode === "weekly") {
        const day = (document.getElementById("player-clean-weekday") || {}).value || "0";
        const t = (document.getElementById("player-clean-time-weekly") || {}).value || "04:00";
        const [h, m] = t.split(":").map(Number);
        return `${m || 0} ${h || 4} * * ${day}`;
    }
    return (document.getElementById("player-clean-cron") || {}).value || "";
}

async function savePlayerCleanSchedule() {
    const player = (document.getElementById("player-clean-player") || {}).value || "kodi";
    const media = (document.getElementById("player-clean-media") || {}).value || "video";
    // Clean is only offered by players that have a separate clean call; anything else updates.
    const wantedKind = (document.getElementById("player-clean-kind") || {}).value || "update";
    const kind = PLAYER_CLEAN_SUPPORT[player] && wantedKind === "clean" ? "clean" : "update";
    const cron = _readPlayerCleanCron().trim();
    if (!cron) { notify("Choose a schedule first.", "warning"); return; }
    let summary;
    try {
        summary = await api("/api/schedule/preview", { method: "POST", body: { schedule_cron: cron, kind: "schedule" } });
    } catch (error) {
        notify(error.message || "That schedule could not be read.", "error");
        return;
    }
    if (!summary || summary.is_valid === false || !summary.effective_cron) {
        notify("That expression needs five fields: minute hour day month weekday.", "warning");
        return;
    }
    const entry = { player, kind, media, cron: summary.effective_cron };
    const list = Array.isArray((state.settings || {}).player_clean_schedules) ? state.settings.player_clean_schedules.slice() : [];
    if (list.some((item) => item.cron === entry.cron && item.player === entry.player && item.media === entry.media && (item.kind || "update") === entry.kind)) {
        notify("That schedule is already in the list.", "info");
        return;
    }
    if (list.length >= 20) { notify("Twenty schedules is the limit.", "warning"); return; }
    state.settings.player_clean_schedules = list.concat([entry]);
    const saved = await saveSettings({ keepOpen: true, message: "Player schedule saved." });
    if (!saved) state.settings.player_clean_schedules = list;
    else if (typeof paintPlayerCleanSchedules === "function") paintPlayerCleanSchedules();
}

async function removePlayerCleanSchedule(index) {
    const list = Array.isArray((state.settings || {}).player_clean_schedules) ? state.settings.player_clean_schedules.slice() : [];
    const at = Number(index);
    if (!Number.isInteger(at) || at < 0 || at >= list.length) return;
    const previous = list.slice();
    list.splice(at, 1);
    state.settings.player_clean_schedules = list;
    const saved = await saveSettings({ keepOpen: true, message: "Player schedule removed." });
    if (!saved) state.settings.player_clean_schedules = previous;
    else if (typeof paintPlayerCleanSchedules === "function") paintPlayerCleanSchedules();
}

function normalizeClientPath(path) {
    const value = String(path || "").trim().replace(/\\/g, "/");
    if (value.length > 1) return value.replace(/\/+$/, "");
    return value;
}

function addMusicPath(path, role, kind) {
    addLibraryPath(path, "music", role, kind);
}

const APPLY_WRITES = [
    ["tags", "Tags", "Write MusicBrainz tags into the audio files, and mark the album processed"],
    ["nfo", ".nfo", "Write artist.nfo and album.nfo"],
    ["lyrics", "Lyrics", "Fetch lyrics from LRCLIB"],
];

const SUFFIX_TYPES = [
    ["album", "Album"],
    ["single", "Single"],
    ["ep", "EP"],
    ["live", "Live"],
    ["compilation", "Compilation"],
];

const SCAN_MODE_FLAGS = [
    ["incremental", "Incremental deep scan"],
    ["full", "Full"],
    ["deep", "Deep"],
    ["forced", "Forced"],
];

function scanModeButtons(cfg, key) {
    const chosen = (cfg && cfg[key]) || {};
    return SCAN_MODE_FLAGS.map(([mode, label]) => {
        const on = !!chosen[mode];
        return `<button type="button" class="suffix-type${on ? " is-on" : ""}" data-action="scan-mode-flag" data-scan-flag="${key}" data-scan-mode="${mode}" aria-pressed="${on ? "true" : "false"}">${label}</button>`;
    }).join("");
}

function toggleScanModeFlag(key, mode) {
    if (!rememberSettingsForm()) return;
    const blank = { incremental: false, full: false, deep: false, forced: false };
    const chosen = { ...blank, ...(state.settings[key] || {}) };
    chosen[mode] = !chosen[mode];
    state.settings[key] = chosen;
    renderSettings();
}

function applyWriteButtons(cfg) {
    const chosen = (cfg && cfg.apply_writes) || { tags: true, nfo: true, lyrics: true };
    return APPLY_WRITES.map(([key, label, title]) => {
        const on = chosen[key] !== false;
        return `<button type="button" class="suffix-type${on ? " is-on" : ""}" data-action="apply-write" data-apply-write="${key}" aria-pressed="${on ? "true" : "false"}" title="${escapeHtml(title)}">${label}</button>`;
    }).join("");
}

function toggleApplyWrite(kind) {
    if (!rememberSettingsForm()) return;
    const writes = { tags: true, nfo: true, lyrics: true, ...(state.settings.apply_writes || {}) };
    delete writes.art;
    writes[kind] = !writes[kind];
    state.settings.apply_writes = writes;
    renderSettings();
}

function suffixTypeButtons(cfg) {
    const chosen = (cfg && cfg.title_suffix_types) || {};
    return SUFFIX_TYPES.map(([key, label]) => {
        const on = !!chosen[key];
        return `<button type="button" class="suffix-type${on ? " is-on" : ""}" data-action="suffix-type" data-suffix-type="${key}" aria-pressed="${on ? "true" : "false"}">${label}</button>`;
    }).join("");
}

function toggleSuffixType(kind) {
    if (!rememberSettingsForm()) return;
    const types = { ...(state.settings.title_suffix_types || {}) };
    types[kind] = !types[kind];
    state.settings.title_suffix_types = types;
    renderSettings();
}

function suffixEnabled(albumType) {
    const types = (state.settings && state.settings.title_suffix_types) || {};
    const key = String(albumType || "").trim().toLowerCase();
    return !!types[key];
}

const META_LABELS = { allmusic: "AllMusic", theaudiodb: "TheAudioDB", lastfm: "Last.fm", wikipedia: "Wikipedia" };

function orderedSources(order, enabled) {
    const on = [];
    const off = [];
    const seen = new Set();
    (order || []).forEach((source) => {
        if (!source || seen.has(source)) return;
        seen.add(source);
        if (enabled && enabled[source] === false) off.push(source);
        else on.push(source);
    });
    return on.concat(off);
}

function metaPriorityList(cfg, purpose, title) {
    const enabledFor = (cfg.metadata_enabled && cfg.metadata_enabled[purpose]) || {};
    const order = orderedSources((cfg.metadata_priority && cfg.metadata_priority[purpose]) || [], enabledFor);
    const enabled = (cfg.metadata_enabled && cfg.metadata_enabled[purpose]) || {};
    const rows = order.map((source) => `<div class="priority-item${enabled[source] === false ? " is-off" : ""}" draggable="true" data-meta-source="${escapeHtml(source)}">
        ${priorityGrip()}
        <label class="choice"><input type="checkbox" ${enabled[source] === false ? "" : "checked"}> ${escapeHtml(META_LABELS[source] || source)}</label>
        ${priorityNudge(source, purpose)}
    </div>`).join("");
    return `<div class="section-label">${escapeHtml(title)}</div><div class="priority-list" data-meta-list="${escapeHtml(purpose)}">${rows}</div>`;
}

function priorityArrow(direction) {
    const path = direction === "up" ? "M6 14l6-8 6 8" : "M6 10l6 8 6-8";
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
}

function priorityGrip() {
    return `<span class="priority-grip" title="Drag to reorder" aria-hidden="true"></span>`;
}

function priorityNudge(source, purpose) {
    const purposeAttr = purpose ? ` data-purpose="${escapeHtml(purpose)}"` : "";
    const up = purpose ? "meta-priority-up" : "priority-up";
    const down = purpose ? "meta-priority-down" : "priority-down";
    return `<span class="priority-nudges">
        <button type="button" class="icon-btn" data-action="${up}" data-source="${escapeHtml(source)}"${purposeAttr} title="Move up" aria-label="Move up">${priorityArrow("up")}</button>
        <button type="button" class="icon-btn" data-action="${down}" data-source="${escapeHtml(source)}"${purposeAttr} title="Move down" aria-label="Move down">${priorityArrow("down")}</button>
    </span>`;
}

let priorityDragRow = null;

function onPriorityDragStart(event) {
    const row = event.target.closest(".priority-item");
    if (!row || !row.closest(".priority-list")) return;
    if (event.target.closest("button, input")) {
        event.preventDefault();
        return;
    }
    priorityDragRow = row;
    row.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", row.dataset.metaSource || row.dataset.source || "");
}

function clearPriorityDropMarks() {
    document.querySelectorAll(".priority-item.drop-before, .priority-item.drop-after").forEach((row) => {
        row.classList.remove("drop-before", "drop-after");
    });
}

function onPriorityDragOver(event) {
    const row = event.target.closest(".priority-item");
    if (!priorityDragRow || !row || row === priorityDragRow) return;
    if (row.parentElement !== priorityDragRow.parentElement) return;
    event.preventDefault();
    const box = row.getBoundingClientRect();
    const after = event.clientY > box.top + box.height / 2;
    clearPriorityDropMarks();
    row.classList.add(after ? "drop-after" : "drop-before");
}

function onPriorityDrop(event) {
    const row = event.target.closest(".priority-item");
    if (!priorityDragRow || !row || row === priorityDragRow) return;
    const list = priorityDragRow.parentElement;
    if (!list || row.parentElement !== list) return;
    event.preventDefault();
    const after = row.classList.contains("drop-after");
    list.insertBefore(priorityDragRow, after ? row.nextSibling : row);
    clearPriorityDropMarks();
    if (list.dataset.videoChain) return;
    const rows = [...list.querySelectorAll(":scope > .priority-item")];
    rememberSettingsForm();
    if (!list.dataset.metaList) {
        state.settings.source_priority = rows.map((item) => item.dataset.source).filter(Boolean);
    }
    renderSettings();
}

function onPriorityDragEnd() {
    if (priorityDragRow) priorityDragRow.classList.remove("is-dragging");
    priorityDragRow = null;
    clearPriorityDropMarks();
}

function moveMetaPriority(purpose, source, direction) {
    rememberSettingsForm();
    const order = state.settings.metadata_priority && state.settings.metadata_priority[purpose];
    if (!order) return;
    const index = order.indexOf(source);
    const next = index + direction;
    if (index < 0 || next < 0 || next >= order.length) return;
    [order[index], order[next]] = [order[next], order[index]];
    renderSettings();
}

function readMetaPriority(root) {
    const priority = {};
    const enabled = {};
    root.querySelectorAll("[data-meta-list]").forEach((list) => {
        const purpose = list.dataset.metaList;
        priority[purpose] = [];
        enabled[purpose] = {};
        list.querySelectorAll("[data-meta-source]").forEach((row) => {
            const source = row.dataset.metaSource;
            priority[purpose].push(source);
            const box = row.querySelector("input[type='checkbox']");
            enabled[purpose][source] = box ? box.checked : true;
        });
    });
    if (Object.keys(priority).length) {
        state.settings.metadata_priority = priority;
        state.settings.metadata_enabled = enabled;
    }
}

function movePriority(source, direction) {
    rememberSettingsForm();
    const list = state.settings.source_priority || [];
    const index = list.indexOf(source);
    const next = index + direction;
    if (index < 0 || next < 0 || next >= list.length) return;
    [list[index], list[next]] = [list[next], list[index]];
    renderSettings();
}

function rememberSettingsForm() {
    if (typeof rememberOutbound === "function") rememberOutbound();
    const root = document.getElementById("settings-body");
    if (!root || !state.settings || !document.getElementById("resolution-preset")) return false;
    const nfo = document.querySelector("input[name='nfo']:checked");
    const lyrics = document.querySelector("input[name='lyrics']:checked");
    if (nfo) state.settings.nfo_profile = nfo.value;
    const nfoBackup = document.getElementById("music-nfo-backup");
    if (nfoBackup) state.settings.nfo_backup = nfoBackup.checked;
    const nfoDialect = document.getElementById("music-nfo-dialect");
    if (nfoDialect) state.settings.nfo_dialect = nfoDialect.value;
    const allmusicEnabled = document.getElementById("allmusic-enabled");
    if (allmusicEnabled) state.settings.allmusic_enabled = allmusicEnabled.checked;
    readMetaPriority(root);
    const nfoOnBio = document.getElementById("nfo-on-bio-save");
    if (nfoOnBio) state.settings.nfo_on_bio_save = nfoOnBio.checked;
    const scanRewriteNfo = document.getElementById("scan-rewrite-nfo");
    if (scanRewriteNfo) state.settings.scan_rewrite_nfo = scanRewriteNfo.checked;
    const longestBio = document.getElementById("biography-longest");
    if (longestBio) state.settings.biography_longest = longestBio.checked;
    const musicFolder = document.getElementById("music-rename-folder");
    const musicFile = document.getElementById("music-rename-file");
    if (musicFolder) state.settings.rename_folder_pattern = musicFolder.value.trim();
    if (musicFile) state.settings.rename_file_pattern = musicFile.value.trim();
    const verboseLogging = document.getElementById("verbose-logging");
    if (verboseLogging) state.settings.verbose_logging = verboseLogging.checked;
    const pruneSafety = document.getElementById("prune-safety");
    if (pruneSafety) state.settings.prune_safety = pruneSafety.checked;
    if (lyrics) state.settings.lyrics_mode = lyrics.value;
    const preset = document.getElementById("resolution-preset").value;
    const presetRow = RESOLUTION_PRESETS.find((item) => item[0] === preset);
    const custom = document.getElementById("min-resolution");
    state.settings.min_resolution = preset !== "custom" && presetRow
        ? presetRow[2]
        : Number(custom ? custom.value : 0);
    const suffixTypes = {};
    document.querySelectorAll("[data-suffix-type]").forEach((button) => {
        suffixTypes[button.dataset.suffixType] = button.classList.contains("is-on");
    });
    if (Object.keys(suffixTypes).length) state.settings.title_suffix_types = suffixTypes;
    const applyWrites = {};
    document.querySelectorAll("[data-apply-write]").forEach((button) => {
        applyWrites[button.dataset.applyWrite] = button.classList.contains("is-on");
    });
    if (Object.keys(applyWrites).length) state.settings.apply_writes = applyWrites;
    const fillMb = document.getElementById("fill-mb-metadata-during-incremental");
    const fillMissing = document.getElementById("fill-missing-during-scan");
    const limitedArtwork = document.getElementById("limited-artwork-during-scan");
    const refreshDiscography = document.getElementById("refresh-discography-during-scan");
    if (fillMb) state.settings.fill_mb_metadata_during_incremental = fillMb.checked;
    if (fillMissing) state.settings.fill_missing_during_scan = fillMissing.checked;
    if (limitedArtwork) state.settings.limited_artwork_during_scan = limitedArtwork.checked;
    const missDays = document.getElementById("metadata-miss-days");
    if (missDays) state.settings.metadata_miss_days = Math.max(0, Math.min(3650, Number(missDays.value) || 0));
    if (refreshDiscography) state.settings.refresh_discography_during_scan = refreshDiscography.checked;
    ["choose_release_modes", "artwork_lookup_modes"].forEach((key) => {
        const chosen = { incremental: false, full: false, deep: false, forced: false };
        root.querySelectorAll(`[data-scan-flag="${key}"]`).forEach((button) => {
            chosen[button.dataset.scanMode] = button.classList.contains("is-on");
        });
        if (root.querySelector(`[data-scan-flag="${key}"]`)) state.settings[key] = chosen;
    });
    const fanartCount = document.getElementById("fanart-count");
    if (fanartCount) state.settings.fanart_count = Number(fanartCount.value || 5);
    state.settings.musicbrainz_contact = document.getElementById("mb-contact").value;
    ["lastfm-key", "lastfm-secret", "fanart-key", "acoustid-key", "lidarr-api-key", "lidarr-token"].forEach((id) => {
        const input = document.getElementById(id);
        const field = { "lastfm-key": "lastfm_key", "lastfm-secret": "lastfm_secret", "fanart-key": "fanart_key", "acoustid-key": "acoustid_key", "lidarr-api-key": "lidarr_api_key", "lidarr-token": "lidarr_token" }[id];
        if (input && input.value.trim() && field) state.settings[field] = input.value;
    });
    const embed = document.getElementById("embed-artwork");
    if (embed) state.settings.embed_artwork = embed.checked;
    const embedPresetEl = document.getElementById("embed-preset");
    const embedPresetRow = embedPresetEl
        ? RESOLUTION_PRESETS.find((item) => item[0] === embedPresetEl.value)
        : null;
    const embedPx = document.getElementById("embed-max-px");
    if (embedPresetEl) {
        state.settings.embed_max_px = embedPresetEl.value !== "custom" && embedPresetRow
            ? embedPresetRow[2]
            : Number(embedPx ? embedPx.value : 0);
    }
    ["jellyfin", "navidrome", "plex", "emby"].forEach((name) => {
        const input = document.getElementById(`webhook-${name}-url`);
        if (input) state.settings[`webhook_${name}`] = input.value.trim();
        const enabled = document.getElementById(`webhook-${name}-enabled`);
        if (enabled) state.settings[`webhook_${name}_enabled`] = enabled.checked;
    });
    const lidarrEnabled = document.getElementById("lidarr-enabled");
    if (lidarrEnabled) state.settings.lidarr_enabled = lidarrEnabled.checked;
    const lidarrImportScan = document.getElementById("lidarr-import-scan");
    if (lidarrImportScan) state.settings.lidarr_import_scan = lidarrImportScan.checked;
    const lidarrMonitorNew = document.getElementById("lidarr-monitor-new");
    if (lidarrMonitorNew) state.settings.lidarr_monitor_new = lidarrMonitorNew.checked;
    const sortIgnoreThe = visibleControl(root, "[data-sort-ignore-the]");
    if (sortIgnoreThe) state.settings.sort_ignore_the = sortIgnoreThe.checked;
    const lidarrUrl = document.getElementById("lidarr-api-url");
    if (lidarrUrl) state.settings.lidarr_url = lidarrUrl.value.trim();
    const lidarrRoot = document.getElementById("lidarr-root");
    if (lidarrRoot) {
        const quality = chosenProfiles("lidarr-profile");
        const metadata = chosenProfiles("lidarr-metadata");
        const previous = state.settings.lidarr || {};
        state.settings.lidarr = {
            root_folder: lidarrRoot.value,
            quality_profile: quality.id,
            quality_profile_name: quality.name || previous.quality_profile_name || "",
            quality_profiles: quality.list.length ? quality.list : (previous.quality_profiles || []),
            metadata_profile: metadata.id,
            metadata_profile_name: metadata.name || previous.metadata_profile_name || "",
            metadata_profiles: metadata.list.length ? metadata.list : (previous.metadata_profiles || []),
        };
    }
    if (root.querySelector("[data-lidarr-row]")) state.settings.lidarr_paths = readLidarrPaths(root);
    Object.assign(state.settings, readScheduleGroup("schedule"), readScheduleGroup("backup"));
    state.settings.assets = {};
    root.querySelectorAll("[data-asset]").forEach((input) => { state.settings.assets[input.dataset.asset] = input.checked; });
    state.settings.sources_enabled = { ...(state.settings.sources_enabled || {}) };
    root.querySelectorAll("[data-source-enabled]").forEach((input) => {
        state.settings.sources_enabled[input.dataset.sourceEnabled] = input.checked;
    });
    root.querySelectorAll(".priority-list:not([data-meta-list]):not([data-video-chain])").forEach((list) => {
        const seen = new Set();
        const order = [];
        list.querySelectorAll(":scope > .priority-item").forEach((item) => {
            const source = item.dataset.source;
            if (!source || seen.has(source)) return;
            seen.add(source);
            order.push(source);
        });
        if (order.length) state.settings.source_priority = order;
    });
    state.settings.music_path_roles = { ...(state.settings.music_path_roles || {}) };
    root.querySelectorAll("[data-path-role]").forEach((input) => {
        state.settings.music_path_roles[input.dataset.pathRole] = input.value;
    });
    state.settings.music_path_kinds = { ...(state.settings.music_path_kinds || {}) };
    root.querySelectorAll("[data-path-kind]").forEach((input) => {
        state.settings.music_path_kinds[input.dataset.pathKind] = input.value;
    });
    state.settings.scan_excluded = [];
    root.querySelectorAll("[data-scan-exclude]").forEach((input) => {
        if (input.checked) state.settings.scan_excluded.push(input.dataset.scanExclude);
    });
    readVideoSettings(root);
    readAutomationSettings(root);
    return true;
}

function setSettingsStatus(message, kind) {
    const line = document.getElementById("settings-status");
    if (!line) return;
    line.textContent = message || "";
    line.className = `settings-status ${kind || ""}`.trim();
}

async function copyCmmApiKey() {
    const text = state.cmmApiKey || "";
    if (!text) {
        notify("CMM_API_KEY is not set in docker-compose.", "warning");
        return;
    }
    try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
        else copyPlainText(text);
        notify("API key copied.", "info");
    } catch (error) {
        try {
            copyPlainText(text);
            notify("API key copied.", "info");
        } catch (again) {
            notify("Could not copy the API key.", "warning");
        }
    }
}

async function saveSettings(options) {
    const keepOpen = !!(options && options.keepOpen);
    const button = document.getElementById("save-settings");
    const scheduleButton = document.getElementById("save-scan-schedule");
    if (!rememberSettingsForm()) {
        setSettingsStatus("The settings form is not ready.", "error");
        notify("The settings form is not ready.", "error");
        return;
    }
    const body = { ...state.settings };
    delete body.key_sources;
    delete body.key_status;
    delete body.schedule_summary;
    delete body.schedule_presets;
    delete body.backup_summary;
    delete body.backup_default;
    delete body.scan_schedule_summaries;
    delete body.outbound_catalog;
    const clear = Object.keys(state.clearKeys || {}).filter((key) => state.clearKeys[key]);
    ["lastfm_key", "lastfm_secret", "fanart_key", "acoustid_key", "lidarr_api_key", "radarr_api_key", "sonarr_api_key", "bazarr_api_key", "tmdb_key", "tvdb_key", "omdb_key", "crawlbase_token", "opensubtitles_key", "opensubtitles_password",
        "kodi_password", "kodi_library_password", "jellyfin_token", "plex_token", "emby_token",
        "webhook_emby_key", "webhook_jellyfin_key", "webhook_navidrome_key", "webhook_plex_key"].forEach((field) => {
        if (String(body[field] || "").trim()) {
            const index = clear.indexOf(field);
            if (index >= 0) clear.splice(index, 1);
        }
    });
    body.clear_keys = clear;
    if (button) button.disabled = true;
    if (scheduleButton) scheduleButton.disabled = true;
    setSettingsStatus("Saving settings…", "info");
    try {
        state.settings = await api("/api/settings", { method: "PUT", body });
        state.fillMissingDuringScan = state.settings.fill_missing_during_scan !== false;
        applyScanSteps();
        state.clearKeys = {};
        state.musicPaths = state.settings.music_paths || state.musicPaths;
        if (keepOpen) {
            paintSavedSchedules(state.settings);
            setSettingsStatus("");
            notify((options && options.message) || "Schedule saved.", "info");
            pollSystem();
            return true;
        }
        document.getElementById("path-modal").classList.add("hidden");
        document.getElementById("settings-modal").classList.add("hidden");
        setSettingsStatus("");
        state.sortIgnoreThe = state.settings.sort_ignore_the !== false;
        renderTree();
        if (state.media !== "music" && typeof renderVideo === "function") renderVideo();
        notify("Settings saved.", "info");
        pollSystem();
        return true;
    } catch (error) {
        setSettingsStatus(error.message || "Settings were not saved.", "error");
        notify(error.message || "Settings were not saved.", "error");
        return false;
    } finally {
        if (button) button.disabled = false;
        if (scheduleButton) scheduleButton.disabled = false;
    }
}

function presetFor(value) {
    const match = RESOLUTION_PRESETS.find((item) => item[2] !== null && Number(item[2]) === Number(value));
    return match ? match[0] : "custom";
}

function lidarrWebhookUrl(token) {
    const value = String(token || "").trim();
    return value ? `/api/webhooks/lidarr?token=${encodeURIComponent(value)}` : "/api/webhooks/lidarr?token=…";
}

function lidarrPathRows(rows) {
    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) return "";
    return items.map((row, index) => `<div class="lidarr-map" data-lidarr-row>
        <input data-lidarr-from type="text" spellcheck="false" value="${escapeHtml(row.lidarr || "")}" placeholder="Lidarr path" aria-label="Lidarr path">
        <input data-lidarr-to type="text" spellcheck="false" value="${escapeHtml(row.resonance || "")}" placeholder="Curator path" aria-label="Curator path">
        <button type="button" class="btn-ghost btn-remove" data-action="remove-lidarr-path" data-index="${index}">Delete</button>
    </div>`).join("");
}

function readLidarrPaths(root) {
    const rows = [];
    root.querySelectorAll("[data-lidarr-row]").forEach((row) => {
        const from = row.querySelector("[data-lidarr-from]");
        const to = row.querySelector("[data-lidarr-to]");
        rows.push({
            lidarr: from ? from.value.trim() : "",
            resonance: to ? to.value.trim() : "",
        });
    });
    return rows;
}

function addLidarrPath() {
    if (!rememberSettingsForm()) return;
    state.settings.lidarr_paths = readLidarrPaths(document.getElementById("settings-body"));
    state.settings.lidarr_paths.push({ lidarr: "", resonance: "" });
    renderSettings();
}

function removeLidarrPath(index) {
    if (!rememberSettingsForm()) return;
    const rows = readLidarrPaths(document.getElementById("settings-body"));
    const at = Number(index);
    if (Number.isInteger(at)) rows.splice(at, 1);
    state.settings.lidarr_paths = rows;
    renderSettings();
}

function newLidarrToken() {
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    let binary = "";
    bytes.forEach((value) => { binary += String.fromCharCode(value); });
    const token = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const input = document.getElementById("lidarr-token");
    if (input) input.value = token;
    if (state.settings) state.settings.lidarr_token = token;
    const url = document.getElementById("lidarr-url");
    if (url) url.textContent = lidarrWebhookUrl(token);
}

function secretField(field, id, label, envName) {
    const status = state.clearKeys[field] ? "cleared" : (((state.settings || {}).key_status || {})[field] || "");
    const set = status === "saved" || status === "environment";
    const cue = status === "cleared"
        ? `<span class="muted">This secret will be cleared on save.</span>`
        : set
            ? `<span class="key-set">•••••••• Secret is set${status === "environment" ? ` from ${escapeHtml(envName)}` : ""}.</span>`
            : `<span class="muted">Not set. You can also set ${escapeHtml(envName)} in docker-compose.</span>`;
    const clear = status === "saved"
        ? `<button type="button" class="btn-ghost" data-action="clear-key" data-field="${field}">Clear</button>`
        : "";
    return `<label>${escapeHtml(label)}
        <input id="${id}" type="password" autocomplete="new-password" value="" placeholder="${set && status !== "cleared" ? "••••••••" : "Paste a secret"}">
    </label>
    ${cue} ${clear}`;
}

function keyField(field, id, label, envName) {
    const status = state.clearKeys[field] ? "cleared" : (((state.settings || {}).key_status || {})[field] || "");
    const set = status === "saved" || status === "environment";
    const cue = status === "cleared"
        ? `<span class="muted">This key will be cleared on save.</span>`
        : set
            ? `<span class="key-set">•••••••• Key is set${status === "environment" ? ` from ${escapeHtml(envName)}` : ""}.</span>`
            : `<span class="muted">Not set. You can also set ${escapeHtml(envName)} in docker-compose.</span>`;
    const clear = status === "saved"
        ? `<button type="button" class="btn-ghost" data-action="clear-key" data-field="${field}">Clear</button>`
        : "";
    const service = { lastfm_key: "lastfm", fanart_key: "fanart", acoustid_key: "acoustid" }[field];
    const toast = { lastfm_key: "Last.fm", fanart_key: "Fanart.tv", acoustid_key: "AcoustID" }[field];
    return `<div class="key-row"><label>${escapeHtml(label)}
        <input id="${id}" type="password" autocomplete="new-password" value="" placeholder="${set && status !== "cleared" ? "••••••••" : "Paste a key"}">
    </label>
    <button type="button" class="btn-ghost key-test" data-action="test-key" data-service="${service}" data-input="${id}" data-field="${field}" data-label="${escapeHtml(toast)}">Test</button></div>
    ${cue} ${clear}${service ? connectionErrorHtml(service) : ""}`;
}

function testApiKey(button) {
    const label = button.dataset.label || "the service";
    const input = document.getElementById(button.dataset.input);
    const field = button.dataset.field;
    button.dataset.testLabel = "Test";
    beginConnectionTest(button);
    const finish = (ok) => {
        paintConnectionTest(button, ok);
        notify(ok ? `Connection to ${label} successful!` : `Connection to ${label} failed!`, ok ? "success" : "fail");
    };
    api("/api/settings/test-key", {
        method: "POST",
        body: {
            service: button.dataset.service,
            key: input ? input.value : "",
            cleared: !!(field && state.clearKeys[field]),
        },
    }).then((data) => finish(!!data.ok)).catch(() => finish(false));
}

function clearKey(field) {
    if (!field) return;
    state.clearKeys[field] = true;
    rememberSettingsForm();
    renderSettings();
    setSettingsStatus("The key will be removed when you save.", "info");
}

async function openPathBrowser(purpose) {
    state.pathPick = purpose === "set-folder" || purpose === "backup-folder" || purpose === "map-local" ? purpose : "library";
    rememberSettingsForm();
    const mounts = purpose === "backup-folder"
        ? (state.mounts || []).filter((mount) => mount.writable)
        : libraryMounts(state.settings || {}, state.mounts || []);
    if (!mounts.length) {
        notify("No mounts were detected. Add a volume in docker-compose and recreate the container.", "warning");
        return;
    }
    const select = document.getElementById("path-mount");
    select.innerHTML = mounts.map((mount) => `<option value="${escapeHtml(mount.path)}">${escapeHtml(mount.path)} (${mount.writable ? "rw" : "ro"})</option>`).join("");
    const media = document.getElementById("path-media");
    if (media && state.pathPick !== "set-folder") media.value = scanKind();
    syncPathModalMedia();
    document.getElementById("path-modal").classList.remove("hidden");
    try {
        await browsePath("");
    } catch (error) {
        notify(error.message, "error");
    }
}

async function browsePath(relative) {
    const root = document.getElementById("path-mount").value;
    const data = await api(`/api/browse?${new URLSearchParams({ root, path: relative || "" })}`);
    state.pathBrowser = { root: data.root, path: data.path || "", current: data.current };
    document.getElementById("path-current").textContent = data.current || data.root || "";
    const dirs = data.dirs || [];
    renderPathIndex(dirs);
    const seen = new Set();
    document.getElementById("path-dirs").innerHTML = dirs.length
        ? dirs.map((name) => {
            const next = data.path ? `${data.path}/${name}` : name;
            const letter = folderInitial(name);
            const mark = seen.has(letter) ? "" : ` data-letter="${escapeHtml(letter)}"`;
            seen.add(letter);
            return `<div class="path-row"${mark}><span>${escapeHtml(name)}</span><button type="button" class="btn-ghost" data-action="path-open" data-path="${escapeHtml(next)}">Open</button></div>`;
        }).join("")
        : `<p class="muted">No subfolders. Use this folder to add it.</p>`;
}

function folderInitial(name) {
    const first = Array.from(String(name || "").trim())[0] || "";
    if (!first) return "#";
    if (/[0-9]/.test(first)) return first;
    const upper = first.toLocaleUpperCase();
    let base = upper;
    try {
        base = upper.normalize("NFD").replace(/\p{M}/gu, "");
    } catch (error) {
        base = upper;
    }
    if (/^[A-Z]$/.test(base)) return base;
    return upper;
}

function renderPathIndex(dirs) {
    const box = document.getElementById("path-index");
    if (!box) return;
    const present = new Set((dirs || []).map(folderInitial));
    const extras = [...present].filter((key) => !/^[0-9A-Z]$/.test(key)).sort((a, b) => a.localeCompare(b));
    const keys = [..."0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", ...extras];
    box.innerHTML = keys.map((key) => {
        const ready = present.has(key);
        return `<button type="button" class="btn-ghost" data-action="path-jump" data-letter="${escapeHtml(key)}" ${ready ? "" : "disabled"}>${escapeHtml(key)}</button>`;
    }).join("");
}

function jumpToFolder(letter) {
    const rows = document.querySelectorAll("#path-dirs [data-letter]");
    const row = [...rows].find((item) => item.dataset.letter === letter);
    if (!row) return false;
    row.scrollIntoView({ block: "start", inline: "nearest" });
    row.classList.add("is-jump");
    window.setTimeout(() => row.classList.remove("is-jump"), 700);
    return true;
}

function setAssetGroup(action, checked) {
    const group = action.closest(".asset-group");
    if (!group) return;
    group.querySelectorAll("[data-asset]").forEach((input) => { input.checked = checked; });
}

async function pathUp() {
    const parts = String(state.pathBrowser.path || "").split("/").filter(Boolean);
    parts.pop();
    await browsePath(parts.join("/"));
}

function useBrowsedPath() {
    const current = state.pathBrowser.current || "";
    if (state.pathPick === "set-folder" || state.pathPick === "backup-folder" || state.pathPick === "map-local") {
        if (!current) {
            notify("Choose a folder first.", "warning");
            return;
        }
        const input = state.pathPick === "map-local"
            ? state.pathMapInput
            : document.getElementById(state.pathPick === "backup-folder" ? "backup-folder" : "video-set-folder");
        if (input) input.value = current;
        document.getElementById("path-modal").classList.add("hidden");
        const note = state.pathPick === "backup-folder"
            ? "Backup folder selected. Save settings to keep it."
            : state.pathPick === "map-local"
                ? "Local path selected. Save settings to keep it."
                : "Movie set folder selected. Save settings to keep it.";
        notify(note, "info");
        return;
    }
    const kind = document.getElementById("path-kind").value;
    const media = document.getElementById("path-media").value;
    if (!current) {
        notify("Choose a folder first.", "warning");
        return;
    }
    addLibraryPath(current, media, "library", kind);
    document.getElementById("path-modal").classList.add("hidden");
}

function formatArtBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(value / 1024))} KB`;
}

const STORAGE_LABELS = { data: "uploaded and replaced artwork", cache: "the cache" };

async function paintStorage() {
    const data = document.getElementById("storage-info-data");
    const cache = document.getElementById("storage-info-cache");
    if (!data && !cache) return;
    try {
        const info = await api("/api/storage");
        const describe = (part, hint) => {
            if (!part.files) return "Nothing is stored.";
            const folders = (part.folders || []).filter((item) => item.bytes).map((item) => `${item.name} ${formatArtBytes(item.bytes)}`).join(", ");
            const warn = part.mounted ? "" : ` This folder is not a mounted volume: add ${hint} to the compose file.`;
            return `${part.files} file${part.files === 1 ? "" : "s"}, ${formatArtBytes(part.bytes)}${folders ? ` (${folders})` : ""}.${warn}`;
        };
        if (data) data.textContent = describe(info.data, "./data:/data");
        if (cache) cache.textContent = describe(info.cache, "./cache:/cache");
    } catch (error) {
        if (data) data.textContent = "Could not read the folder.";
        if (cache) cache.textContent = "Could not read the folder.";
    }
}

async function purgeStorage(folder) {
    const label = STORAGE_LABELS[folder];
    if (!label) return;
    const warning = folder === "data"
        ? "Delete every uploaded and replaced artwork file? They are removed from the artwork windows and cannot be brought back."
        : "Delete everything in the cache? Thumbnails and downloaded artwork are made again when needed.";
    if (!confirm(warning)) return;
    const data = await api(`/api/storage/purge/${encodeURIComponent(folder)}`, { method: "POST" });
    notify(`Deleted ${data.removed} file${data.removed === 1 ? "" : "s"}, ${formatArtBytes(data.bytes)}.`, "success");
    paintStorage();
}

async function loadMissingLogos(media) {
    const host = document.getElementById("logos-list");
    if (!host) return;
    host.textContent = "Checking…";
    const data = await api(`/api/v1/brands/missing?media=${encodeURIComponent(media)}`);
    const rows = (data.networks || []).slice(0, 100);
    if (!rows.length) {
        host.textContent = "Every name has a logo.";
        return;
    }
    host.dataset.media = media;
    host.innerHTML = `<p class="muted">${data.count} without a logo${data.count > rows.length ? `, showing the first ${rows.length}` : ""}.</p>` + rows.map((row) =>
        `<div class="logo-row"><span>${escapeHtml(row.name)} <span class="muted">· ${row.shows} item${row.shows === 1 ? "" : "s"}</span></span> <button type="button" class="btn-ghost" data-action="logo-upload" data-media="${escapeHtml(media)}" data-name="${escapeHtml(row.name)}">Upload logo</button></div>`
    ).join("");
}

function pickLogo(media, name) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.addEventListener("change", async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        try {
            if (file.size > 5 * 1024 * 1024) throw new Error("Logos must be 5 MB or smaller");
            const form = new FormData();
            form.append("kind", media === "tv" ? "network" : "studios");
            form.append("name", name);
            form.append("file", file);
            const response = await fetch("/api/v1/brands/upload", { method: "POST", body: form });
            const saved = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(saved.error || saved.detail || response.statusText);
            notify(`Logo added for ${name}.`, "success");
            await loadMissingLogos(media);
        } catch (error) {
            notify(error.message || "Could not add the logo.", "fail");
        }
    });
    input.click();
}
