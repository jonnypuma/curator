<img width="2037" height="1097" alt="Screenshot 2026-10-22 214231" src="https://github.com/user-attachments/assets/c407fc72-de25-4e5c-8a36-16922e34957d" />
<img width="2038" height="1117" alt="Screenshot 2026-10-20 231004" src="https://github.com/user-attachments/assets/6912f40a-7ac4-4834-b5b0-d43a9d2b53ca" />
<img width="2046" height="1111" alt="Screenshot 2026-10-20 231044" src="https://github.com/user-attachments/assets/f96319d1-5574-4df4-91c5-7e660b4cff95" />

# Curator

Curator is a media manager built for Kodi. It covers the whole path from a finished download in
Lidarr, Radarr, Sonarr to a Kodi library update. When one of those apps reports an
import, Curator indexes the music, movie, movie set, or TV folder, reads and writes Kodi `.nfo`
files and artwork, trailers and theme songs, probes every video for codec, HDR and audio details, and then asks Kodi to
scan the folder that changed. Recent changes are listed in `CHANGELOG.md`.

## Summary

The most important things Curator does:

1. **Metadata and artwork lookup from several sources at once** (TMDB, TheTVDB, TVmaze, OMDb, Trakt, fanart.tv for video; MusicBrainz, AcoustID, Last.fm, AllMusic, TheAudioDB and fanart.tv for music), with per-library source order and overwrite rules.
2. **Advanced media probing and HDR detection** with ffprobe, MediaInfo and dovi_tool: resolution, Dolby Vision profile and FEL/MEL layer, HDR10+, HDR10, HLG, audio and subtitle tracks.
3. **Dolby Vision conversion from Profile 7 to Profile 8.1.**
4. **Episode splitting** for files that hold more than one episode, with automatic renaming and scanning of the split files and a way to restore the original.
5. **Subtitle syncing tool** with live preview, automatic sync (alass), and OCR for picture subtitles (VobSub and PGS), plus subtitle search and download from OpenSubtitles.
6. **Synced-lyrics editor** for music, with LRCLIB lyrics lookup.
7. **Radarr, Sonarr, Lidarr and Bazarr integration**: the whole path from a finished download to a Kodi, Jellyfin, Plex, Emby or Navidrome library update.
8. **Missing and upgrade lookups** through Radarr, Sonarr and Lidarr for missing media or better quality.
9. **Advanced duplicate tools** for movies, TV and music.
10. **Default audio and subtitle track selection** tools.
11. **Scan scheduling** for music, movies, TV and player library cleans.
12. **Trakt watched sync.**
13. **Library analytics and statistics**, with export.
14. **Powerful filtering and sorting**: column filters, ribbons, saved filters and a command palette.

And more:

- **Kodi first**: reads and writes Kodi `.nfo` files and artwork, with Jellyfin, Emby and Plex naming options.
- **Movie sets, multi-version movies and trailers**: collections, several copies of one movie, trailer and extras download.
- **File renaming and moving** with patterns and a pattern builder for movies, TV and music.
- **Music tools**: tag writing, ReplayGain, cue splitting, gap check, compilation handling and batch edit.
- **Safety nets**: undo for locks and batch edits, an automatic database snapshot before large changes, scheduled backups with restore, prune limits, and offline-folder protection.
- **Notifications to other apps**: Discord, Slack, Telegram, Pushover, ntfy, Gotify, Apprise and webhooks.
- **File health warnings** for files that look empty, short or without audio.
- **Poster grid view and poster badges**, a phone-friendly layout, and keyboard shortcuts.

## One FastAPI app

The process is a single FastAPI application, `app/main.py`. It serves the web page, the static
files, and every HTTP route. Flask is not part of the stack. On startup the app opens the database,
loads settings, and starts the music scheduler, backups, and the webhook queue. API docs are at
`/api/v1/docs`.

Music and video share that app. They keep separate URL prefixes:

- Movie, movie set, and TV routes are mounted at `/api/v1`.
- Music routes are mounted at `/api`. They call the Resonance library functions.

`app/resonance/` is the music library. The package name remains from Curator's music-only
predecessor. It holds the music scanner, the MusicBrainz, AcoustID, Last.fm, AllMusic, and fanart.tv
lookups, the tag and `.nfo` writers, and the settings store.

The rest of the Python code lives under `app/curator/`:

- `scrapers/` looks up movies and TV: TMDB, TheTVDB, OMDb, Trakt, and fanart.tv.
- `video/` reads movie and TV folders: file and episode naming, `.nfo` reading, local artwork, and
  the ffprobe, MediaInfo, and dovi_tool probe that records resolution, HDR format, Dolby Vision
  profile and enhancement layer, and audio and subtitle tracks.
- `routes/` holds the FastAPI routers for both `/api/v1` and `/api`.

## Running

1. Copy `docker-compose.yml.example` to `docker-compose.yml`, and `.env.example` to `.env`. Set `MUSIC_PATH`, `MOVIES_PATH`, and `TV_PATH` to the host folders.
   The folders must already exist. Compose does not create missing library folders, because Docker
   cannot `chown` a folder it creates on a network share.
2. `python scripts/pack-media.py` once, when building from source. It packs the shipped badge images in `app/media/`
   (logos of studios, networks, record labels, codecs and providers, thousands of small files) into one file,
   `app/media.zip`, which the image takes instead of the folder. Run it again after adding or changing an image there.
3. `docker compose up -d`
4. Open `http://<host>:4455`. On a new install the setup wizard opens by itself (see below).

### Setup wizard

A step-by-step window that takes a new install from nothing to its first scan. It opens by itself the first time the
page loads on a fresh install (nothing configured and nothing scanned yet), and **Settings → About → Run setup wizard**
opens it any time. Each step has **Back**, **Skip** and **Save and continue**, and the dots at the top show where you
are; a tick means that step was saved. Skip saves nothing. Every step saves the same settings the Settings window does,
so anything here can be changed there later.

1. **Library folders**: one card each for music, movies, TV shows and music videos. Add a folder by typing its path
   inside the container, with **Browse**, or with one click on a mounted volume Curator found. Each folder is checked
   at once: it must exist, Curator must be able to list it, and it must be on a mounted volume. A read-only mount is
   marked *Read only*: scans work, but `.nfo` files, artwork, renames and deletes need write access.
2. **Metadata and artwork**: keys for TMDB, TheTVDB, OMDb, Fanart.tv, Last.fm and AcoustID, each with **Test** and a
   link to where the key is made; the MusicBrainz contact; a **Test** for MusicBrainz and TheAudioDB, which need no
   key; and Trakt sign-in.
3. **Download apps**: Radarr, Sonarr, Lidarr and Bazarr address and API key with **Test connection**; the webhook
   address with your `CMM_API_KEY` already in it and a copy button (Bazarr gets its Apprise address); and path mapping
   rows for when the app sees the library under another path. **Save and test paths** checks that each Curator path
   exists and that the app's root folders under the row land on folders that exist here.
4. **Players**: Kodi, Plex, Emby, Jellyfin and Navidrome address and credentials with **Test connection**, one box for
   the video library and one for the music library, and Curator path → player path rows. **Save and test paths**
   asks Kodi to open each folder, and compares the rows with the library folders Plex, Emby and Jellyfin report.
5. **Finish**: what is set up and what is not, and one box per library to start its first scan.

The container runs with umask 002, so the folders and files Curator creates are 775 and 664: the owner and the group can write and everyone can read, which keeps Kodi working. Set `UMASK` in the environment for another value. Existing folders and files keep what they have, so run `find <library> -type d -exec chmod 775 {} +` and `find <library> -type f -exec chmod 664 {} +` once to match them.

Three folders hold what Curator writes. `config` has settings, logs, Trakt tokens and the undo files (`config/undo`).
`data` (mounted as `/data`, set by `DATA_DIR`) has the artwork that cannot be fetched again: files you uploaded and
replaced ones, in one folder per media type (`data/artwork/additional/music`, `movie`, `tv`, `sets`). Back it up; Logos you add in Settings → Files → Missing logos are kept there too (`data/brands`). Settings → Files → Purge folders shows its size
and can purge it. `cache`
(mounted as `/cache`, set by `CACHE_DIR`) has only what Curator can rebuild: thumbnails, artwork downloaded from
a web address, smaller copies of music and video artwork for lists and grids (`cache/music`, `cache/video`), the video copies the subtitle editor plays, and recognised subtitle text. The cache keeps itself small: a downloaded artwork option is
removed a week after it was last used (or sooner when the folder passes 1 GB), and the downloaded original of an
image you choose is removed as soon as the image is saved with the music. You can delete
`cache` at any time and it fills again as you use the app. If you upgrade from a version without it, add
`- ./cache:/cache` and `CACHE_DIR: /cache` to `docker-compose.yml`. On the first start Curator moves the old files
into place and updates the paths it had saved. Files it cannot move are left where they are and keep working.

The image includes ffmpeg, ffprobe, MediaInfo, dovi_tool, mkvtoolnix, yt-dlp, tesseract, and alass (automatic subtitle sync; the alass release is x86-64 only, so on other CPUs the image builds without it and the Automatic button is hidden). yt-dlp is downloaded when the image is built, newest release, and Deno is included because yt-dlp needs a JavaScript runtime to read YouTube. YouTube changes often, so an old yt-dlp stops working. If trailer or theme song downloads start failing (the log line names the yt-dlp version and says when it is old), open **About** (click the Curator name at the top left) and press **Update yt-dlp** next to the yt-dlp row (the button glows while GitHub lists a newer release). Curator downloads the newest release from GitHub, checks it against the SHA-256 list published with that release, starts it once to make sure it runs, and keeps it in `cache/bin/`. From then on it runs whichever of that copy and the image's yt-dlp is newer, so a later image rebuild is not held back by it. About links to the project page, <https://github.com/jonnypuma/curator>, and also says how old the installed version is and whether GitHub lists a newer release (it asks GitHub when the window opens, at most once every six hours, and sends nothing from your install); the Health list there warns when the version is more than four months old. Below it, **Slow requests** lists every request that took two seconds or more since Curator started (the newest 50), with when it ran and how long it took. The update is only ever started by pressing the button. Purging the cache folder removes the updated copy and the image's yt-dlp is used again. Rebuilding the image also works: `docker compose build --build-arg YTDLP_REFRESH=$(date +%s)`. `YTDLP_VERSION` fixes a particular release instead. Tesseract reads picture subtitles (see Syncing external subtitles). It ships with English, Norwegian, Swedish, Danish, Finnish, German, French, Spanish, Italian, Dutch, Portuguese, and Polish. To change the list, set the `TESSERACT_LANGS` build argument (for example `"eng nor"`) under `build:` in `docker-compose.yml` and rebuild (`docker-compose.yml.example` has the commented line).

## Library folders and media types

Every library folder has one media type: **Music**, **Movies**, or **TV shows**. Set them in
Settings, General, Library folders. A folder can not sit inside a folder of another type. Curator's own `config`,
`cache` and `data` folders are never offered as a library folder, and a new library folder can not be one of them,
hold one, or sit inside one.

The Scan button follows the library that is open. In Music it scans music folders only. In Movies
and Movie sets it scans movie folders, and in TV shows it scans TV folders. This applies both to
"All" and to a single folder picked in the Scan drop-down. The label is `Scan |` and that folder, or `Scan | All music`, `Scan | All movies`, or `Scan | All tv shows`. While another scan is running, the same button says `Queue |` and still shows that selection. At least one music folder is required.

### Offline folders

A library folder whose mount has gone away is shown with an **offline** badge in Settings,
General, Library folders, and a warning names the offline folders. Reachability is probed by
listing the folder, not just by `isdir`, because an NFS or CIFS mount that has gone away can
still look like a directory while every read fails.

An offline folder is skipped by scans, and nothing indexed under it is removed. A mount that is
away therefore cannot empty your library, and the items reappear once the mount is back.

The same applies to a folder that is readable but turns up empty, which is what a mount that
remounts empty looks like: the scan leaves its items alone and says so in the scan log.

An **unreadable** badge marks a folder that exists but cannot be listed, which is a permission
problem or a mount that is still attached while every read fails. It is treated exactly as
carefully as an away mount: skipped, and nothing under it is removed.

An **empty** badge marks a folder that is readable but holds nothing, which is both what a
mount that remounted empty looks like and what a folder you emptied looks like. A warning names
them, because the scan will not prune an empty folder: if the folder really is finished with,
the path should come out of Settings.

**To remove a folder's items, take the path out in Settings, General, Library folders, then
scan again.** That is the only thing that removes them, so removal is always something you
asked for rather than a side effect of a mount being down. Only database rows are removed; no
file is ever deleted by a scan.

Removal is recorded when you save, and is limited to what sits under the path you removed:

- Remove one path on a mount and the other paths on that mount keep their items.
- Remove every path on a mount and the whole mount's items go.
- A path that merely stopped being configured - an offline mount, an excluded folder, a config
  edited by hand - is never treated as a removal, and nothing under it is removed.
- A removal is cleared by the next scan of that library, so a removed path's items go whether
  or not its mount is back.
- Wanted titles rooted at the removed path are removed too. A wanted title has no file yet and
  holds the root its file was meant to land in, so once that path is gone it has nowhere to
  land. Radarr or Sonarr still holds the request.

A scan also refuses to drop more than a fifth of the items in one pass once more than ten are
held, for music and video alike, and says so in the scan log. This is checked twice:

- **Per mount.** A mount can hold several library paths, of more than one media type, so the
  whole mount is judged at once: if it would lose more than a fifth across all of its paths,
  no path on that mount is pruned. Each path on its own could otherwise stay under the limit
  while the mount lost a great deal.
- **Per library path**, for a single path losing a lot on its own.

A mount that comes back partly populated looks exactly like a large removal, so it is held
back until you confirm with a full scan.

Database backups are not a library folder. They go to `/backups` by default; pick any other writable
mounted folder on the Backup settings tab.

Movie and TV scans have three modes. The button label for the first is **Incremental deep scan**. On an empty library the scan dialog offers Deep only. On a library that already has items, Incremental deep scan is the one selected when the dialog opens.

- **Incremental deep scan** walks the library once and builds the list of files that need work. The walk compares size, modification time, the `.nfo`, and the folder time. A match is left alone. Probe workers start only after that walk has finished, and they read the finished list. The walk does not run while those workers are busy.
- **Full** uses that same order. The walk reads every file. A file that already has every enabled field and image, and has not changed, is left alone. A file that is new, changed, or whose last probe failed or never finished is put on the list. Probe workers start when the walk is finished. After probing, anything still missing an enabled field or image is looked up.
- **Deep** counts folders and video files first. That pass lists names only. It does not read `.nfo` files or open the videos. The log records the count, and the progress bar keeps that file total for the rest of the probe. Every file is then probed. The workers stay full: with 8 workers, 8 files are open at once, and the next file is handed over when a worker is free. Every item in the file or mount is looked up again.

While **Folders and files** is running, the folder walk is the first 15% of that stage's bar. Probing the files that need work is the rest. On the scan bar, the folder walk is about 10%, probing about 45%, and the metadata and artwork lookup about 40%. Trailers and writing `.nfo` files share what remains.

A show or season folder with no episode files is not probed for episodes. A new or changed `tvshow.nfo` or `season.nfo` in that folder is still read. Each empty folder is written to the scan log as `Empty folder: …`, and the scan report counts them. A video file that is on disk and has no episode row is stored as a new episode, including when an earlier probe already recorded the file.

**Prefer clean fanart and character art** (Settings, Movies, under Artwork languages; on by default) picks fanart and character art with no title or logo on them before any language, and uses a picture with text only when no clean one exists; the artwork window suggests and lists the clean ones first. Posters, landscape and the other types keep the language order, so landscape art keeps its title.

**Artwork shape.** Every artwork type has a shape: posters and key art tall, fanart, landscape and episode thumbs wide, banners a long strip, disc and square art square (logos, clear art and character art are not judged). A picture of the wrong shape (a fanart a site listed among the posters) is never chosen by a scrape, Download missing artwork or Clean artwork, and every downloaded picture is checked before it is saved; the artwork window marks it **Wrong shape** and never suggests it. **Replace artwork with the wrong shape during a scan** (Settings, Movies and TV shows, under During a scan; on by default) checks the files of the scanned items on disk and gives each wrong one the suggested picture of its type, and Clean artwork has the same as **Any artwork with the wrong shape**. For a show, season artwork and episode thumbs are checked too. The width and height of every artwork file are kept in the database with its path (read again only when the file changes), so these checks do not open the files; artwork from before 4.1.0 is read once and its size stored. **Download missing artwork** takes the picture the artwork window marks Suggested for each missing type, so fanart is clean when a clean one exists.

**Clean artwork during a scan** (Settings, Movies and TV shows, under During a scan; off by default) runs Clean artwork as a scan stage, after the metadata and artwork lookup and before the .nfo files, for the ticked types (Fanart; Character art for shows; Extra fanart), with *Only pictures with a title or logo on them*. An incremental scan does the items it added or read again, a full or deep scan every item in the scanned folders; an item whose fanart was already picked or cleaned is skipped unless Extra fanart is ticked. The scan's progress shows a Clean artwork step, and the players get the new pictures through *Update client libraries for items with updated artwork*, which now also makes Kodi drop its cached copy of a changed picture.

**Jobs, Recent.** Under Running and Waiting, the Jobs panel lists the last 30 finished jobs of every kind (file jobs such as Clean artwork, rename and integrity checks, scans, scrapes and background jobs), newest first, with Done, Failed or Stopped, when it ended, the movies, shows or episodes it worked on (the first 25 are kept, with the count) and its summary. A Kodi library update names what it scanned in its last line. **Log** opens the full log of a file job, a background job or a music scan, with Copy; movie and TV scans and scrapes keep theirs in Scan history. The last 300 file jobs are kept.

**After an update** an open Curator page keeps running the scripts it was loaded with. When the page sees that the running Curator is a newer build, it shows *Curator was updated while this page was open* with **Reload** (and **Later**).

**Clean artwork…** (select movies, shows or movie sets, Metadata menu at the bottom; a set offers Fanart, Extra fanart and Any artwork with the wrong shape, saved in its folder inside the central set folder) is for the artwork that should carry no title or logo: **Fanart** (ticked by default), for shows **Character art**, and **Extra fanart**. For extra fanart, a picture that is in `extrafanart/` more than once (the same shot at another size, framed tighter or wider, or from another site) keeps its largest copy, and one that matches an online picture listed with a language is swapped for a clean picture that is not there yet, or taken out when there is none; every file taken out goes to the recycle bin. **Also download missing clean pictures** (on by default, remembered) gives an item without fanart or character art the suggested clean one, and tops extra fanart up to the Maximum extra fanart in Settings with clean pictures that are not there yet; untick it to only clean what is there. A replaced picture becomes the one the artwork window marks Suggested for that type, and an item without that type gets it. **Replace** has three choices: only pictures with a title or logo on them (Curator matches the file with the online pictures by size, or by comparing it with small previews, and replaces one that matches a picture listed with a language), that and pictures that match nothing online, or any picture that is not the suggested one, also when it is listed as clean (TMDB lists many backdrops with the title on them without a language). Pictures you picked or uploaded in the artwork window and locked items are never touched, and a replaced file stays in the artwork window to be picked again. The job reuses the artwork window's own code, so it saves exactly the card marked Suggested, and its log names the Curator version and each picture it saved. When it ends, the open page loads the new pictures at once (no reload), and the artwork window marks the picture each file came from **In use**; scans keep that note as long as the file stays the same. Below that is one box per player switched on for the library (*Update library in Kodi after artwork download* and so on). The usual Overwrite artwork setting only replaces a picture with a larger one, so it cannot do this.

**New artwork reaches the players without a rescan.** Kodi keeps a cached copy of every picture it has shown, so a new `fanart.jpg` under the same name stays hidden behind the old one. After Clean fanart, and whenever a picture is chosen or uploaded in the artwork window, Curator queues an artwork refresh of that movie or show (Queue window, Library updates) on the players whose box is ticked (the artwork window has the same boxes in its title bar, *Update library in Kodi after artwork download*): Kodi drops its cached copy of the changed pictures and, when the file name changed, points the item at the new file. Kodi then reads the new picture the next time it shows the item; nothing is rescanned or wiped, the .nfo is not read again and the watched state is untouched. Plex, Emby and Jellyfin refresh the item. For pictures changed earlier, select the movies or shows and choose **Update artwork in players…** in the Metadata menu, tick the players and press Start.

**Two different entries in the right-click menu.** *Update player library…* asks Kodi, Emby, Jellyfin or Plex to scan
the item's folder (you pick the players) and shows up under Library updates in the Queue. *Rescan in Sonarr* (or
Radarr, Lidarr) only asks that app to rescan; no player is told. After a Sonarr rescan Curator scans the show as
well, because Sonarr only reports files it adds or removes.

**A failed player update is kept.** When a player cannot take an update, it stays in the Queue under Library updates,
in a Failed list with what went wrong. Curator queues it again by itself the first time that player answers again,
and **Retry failed**, **Retry**, **Remove** and **Clear failed** do the rest by hand.

**Every library update says what triggered it.** Rows under Library updates in the Queue, the finished row in Recent
library updates, and the Kodi alerts for a scan that was sent or is waiting all end with *Triggered by*, for example a
Radarr webhook and its event, a schedule, the manual update button, a retry, a file job or a bulk cleanup. Requests that
were folded into one job list each trigger. An update that was running when Curator stopped is run again on start and
says *Curator restarted while this update was running*. A full scan that Kodi, Emby, Jellyfin or Plex is still running at that
moment is not sent a second time: Curator waits for it to finish and removes the job.

Curator sends a Kodi one request at a time and waits for each answer before the next, whichever part of Curator sends it (library updates, watched sync, the Kodi report, connection tests), so a large job takes longer but never floods Kodi.

Local artwork is stored during **Folders and files**: poster, fanart, banner, clearlogo, clearart, discart, landscape, keyart, squareart, characterart on shows, season poster, banner, fanart, and landscape, episode thumbs, and images in `extrafanart/` and `extrathumbs/`. At the end of that stage the log lists the `.nfo` files and every artwork type that was stored (`Saved artwork: …`).

In the video artwork window each artwork type has an **Upload** button for an image (up to 25 MB) from your computer. It is saved with the same Kodi file name as a picked candidate and replaces the current file of that type. The **Extra fanart** section (movies, shows and sets) shows the files in `extrafanart/` as they are on disk when the window opens and offers every fanart candidate, marking **In use** the ones already there (the picture a file was added from, or the same picture at another size); choosing one, or uploading, adds it as the next `fanartN` and replaces nothing. The **Extrathumbs (legacy)** section (movies and shows) works the same way for `extrathumbs/`: it offers the landscape pictures and adds the next `thumbN`. Extra thumbs are legacy (Kodi dropped them and few players read them), so they are off by default under Settings, Movies and TV shows; while they are off the window shows no Extrathumbs section and does not read the files in `extrathumbs/`, which stay on disk. Every card says its size in pixels and its file type, and a file on disk also its file size. The bin on a file deletes exactly that file (into the recycle bin, so it can be restored), here and in the artwork strip of an item. An online picture you never want can be banned with the crossed-circle button next to its details: it is never suggested, never picked by Clean artwork, a scrape or Download missing artwork, and stays in the window greyed out with an Unban button. A ban is kept by the picture's address, so the same shot on another site needs its own ban. When a picture of the open item was replaced and is still kept, **Undo last artwork** in the window's header puts it back, and pressing it again brings the newer one back. Each card has a tick box in its top left corner; while something is ticked, a bar above the cards offers **Download** (every ticked online picture; the first ticked one of a type that holds one file, such as the poster, becomes that file, and the others are saved next to it as `poster1.jpg`, `poster2.jpg`…, which the players ignore and the window lists with a **Use** button to make one the main file; extra fanart and extrathumbs take every ticked picture), **Ban** (the ticked online pictures), **Delete** (the ticked files on disk, into the recycle bin, after one confirmation) and **Clear ticks**.

The movie and TV stepper is **Folders and files**, **Metadata and artwork**, **Trailers and subtitles**, then **Write .nfo**. Music keeps Directory walk, Changed files, and separate Metadata and Artwork steps.

A matching `<video>.cmm_mediainfo.xml` is used on an incremental or full scan when the file name and size are the same, and the file is not opened again. A deep scan ignores that file and probes the video, then writes the XML again. `<streamdetails>` in an `.nfo` are written from the stored probe. They are not read back.

When **Download missing metadata and artwork during a scan** is on, a movie or show is looked up once. That title's sources are asked together, the metadata is written, and that title's missing images are downloaded before the next title starts. **Limited artwork search** on that same pass downloads a missing poster only. When artwork download is off, the pass still writes metadata and the log says images were skipped. An incremental scan does this for items that are new or changed. A full scan does it for anything still missing. A deep scan looks up every item again. Locked items and locked fields stay as they are. Movie sets stay a separate set scrape. Music still looks up biographies and reviews first, then missing covers.

Trailer download, when that scan option is on, runs during the lookup. Several trailers download at once, up to the scrape concurrency (1 to 12, default 4). A trailer is downloaded when none is on disk, or when the file is below the quality set under General and YouTube has a taller copy. A file that already meets the setting is left alone, and so is a file when YouTube has nothing taller. The new file is still capped at the setting. When the lookup is off, the trailer step runs on its own. An incremental scan does this for items that are new or changed. A full or deep scan does it for every movie, show, or season that already has a trailer link. A title whose YouTube link is saved during the lookup starts its download then.

**Update client libraries after a scan.** Under During a scan on the Movies, TV and Music settings, three switches
(off by default) make the last step of any scan, incremental, full or deep, refresh the items it changed on your players:
*Update client libraries for items with updated metadata*, *…updated artwork* and, for Movies and TV, *…updated
ratings*. An item counts when the scan filled in a missing value, replaced one because overwrite is on, or added the
item. A folder scan does not make a player read an item it already has again, so Kodi and Plex refresh each changed
movie, show or episode (Kodi reads the .nfo again), and Emby and Jellyfin get the item folders marked as changed. An
item a player does not have yet gets a scan of its folder. The refresh shows up in Library updates. For music, Kodi and
Navidrome already get a library scan after every music scan; Kodi cannot refresh one album's album.nfo or artwork.
Path rows under Integrations are needed. Try it on one movie in Kodi first: a refresh rebuilds the entry from the .nfo.

**Scan .iso files** is on by default, on the Movies settings under During a scan. A movie scan opens each `.iso` and stores the streams inside. Turn it off to read the disc name only. That read seeks through the disc image, so a scan of Blu-ray and UHD folders takes longer while it is on. A TV scan always reads the disc file name.

Items are only removed for a folder that was read to the end. A folder that comes back empty or is
not mounted keeps its items. Removal waits until that walk has finished and the probe workers have drained. Set `CMM_PROBE_WORKERS` (1 to 20, default 8) for how many files are probed at once. The database connection pool is sized automatically to `max(16, probe_workers + 6)`.

A scan will not prune more than 20% of the known items for a root in one run, and the same check is applied across a whole mount. If the walk would remove more, the prune is skipped and the anomaly is logged. This prevents mass removals from the database when a mount is temporarily offline or returns fewer items than expected.

**Environment variables** (set in `.env` or the compose environment block):

| Variable | Default | Description |
|---|---|---|
| `CMM_PROBE_WORKERS` | `8` | Number of parallel video probe workers (1–20). More workers keep more NAS reads in flight; useful for deep scans on multi-core machines. |
| `CMM_ARTIST_WORKERS` | `4` | Parallel music artist scan threads (local metadata only; online lookups remain serial). |
| `CMM_SKIP_PATTERNS` | *(empty)* | Comma-separated glob patterns excluded from all directory walks, e.g. `*.tmp,__pycache__`. Added to the built-in skip list. Patterns can also be managed through the Settings UI. |
| `CMM_WRITE_SIDECARS` | `1` | Starting value of the **Write a .cmm_mediainfo.xml media info file** boxes under Settings, Movies and Settings, TV. Set to `0` to start with both off. Once you save those settings, the boxes decide, one for movies and one for TV. |
| `CMM_ALLOWED_ORIGINS` | *(any)* | Comma-separated list of allowed WebSocket origins, e.g. `http://192.168.1.50:4455`. When not set, any origin is accepted. |
| `CMM_TIMEZONE` | *(system)* | IANA timezone name for scheduled scans, library cleans and backups, e.g. `Europe/Amsterdam`. Takes precedence over `TZ`. A zone saved under Settings, General, Time zone wins over both and needs no restart; leave that box empty, or press Reset next to it, to use this one. |

## Scraping movies and TV

Add a TMDB key under Settings, General, API credentials, or set `TMDB_API_KEY` (and optionally `OMDB_API_KEY`
and `TVDB_API_KEY`) in `.env`. Every key there has a **Test** button. Then press **Scrape** in the Movies or TV list, or right-click rows.
A click or the arrow keys opens an item. The checkbox, Space, and the check at the top of the list select items. The same checks are used for movies, movie sets, shows, seasons, episodes, and albums.

The scrape window keeps its progress bar, status line and **Start scrape** button in a row at the bottom, so the button is in view however many source options are listed above it. Only the options and the log scroll. The button becomes **Stop scrape** while a scrape runs. Each finished scrape saves its log under `config/logs` (`…_<media>_scrape.log`), and **Saved scrapes** in the window opens the list, newest first, with Copy and Export. The newest *scan_log_keep* logs per media are kept.

- TMDB is the default source for TV shows, because a TheTVDB key is a paid subscription. DVD and
  absolute episode order come from TMDB episode groups. When a show has no such group and a
  TheTVDB key is set, TheTVDB's order is used instead. TheTVDB can be made the first TV source on
  the TV settings tab.

- Every source is asked in parallel. For each field, the first source in the order set on the
  Movies and TV settings tabs wins. Ratings and ids from all sources are kept.
- Trakt (needs the client ID) supplies English movie and TV show details and ratings, with no artwork. A show's seasons and episodes still come from TMDB, TheTVDB, and TVMaze. When TMDB and TheTVDB have no entry for a show, the show's own details come from Trakt and its seasons and episodes keep what is stored.
- OMDb adds IMDb, Rotten Tomatoes, and Metacritic ratings, and English movie details (plot, release date, runtime, genres, countries, languages, cast, directors, writers) from the same request. TMDB wins where it has a value unless OMDb is first in the order or chosen as the metadata provider. A free key allows 1,000 lookups a day. When OMDb reports that limit, Curator stops asking until the next UTC day. Turn on **OMDb Patron** under the key when the key is a patron key. Curator then keeps asking after that stop.
- On the Movies tab, **Collapse versions of the same movie into one row** groups copies of the same title. Ticking a collapsed row selects every version in it (the count and every action include them all); expand the row to tick one version. On the TV tab it does the same for an episode that has a second video file. The movie page shows the studio, and the show page shows the network.
- Overwrite is two switches for each of Movies, TV, and Movie sets: **Overwrite metadata** and **Overwrite artwork**. On replaces a value when the lookup has one. Off fills a value that is empty. An image is replaced only when the new file is larger. `CMM_OVERWRITE_ALL` turns both switches on until Settings are saved. The scrape dialog has the same two switches for that run, starting from the saved ones. **Rewrite .nfo files this time** starts from the scan's rewrite setting. On replaces the `.nfo` and keeps a `.nfo.bak` when backup is on. Off writes an `.nfo` only when one is missing.
- `.nfo` files follow Kodi 22: `movie.nfo` or `<video>.nfo`, `tvshow.nfo`, and `season.nfo` in season
  folders. A video that holds one episode uses `<video>.nfo`. A video that holds several episodes
  uses a separate file per episode, `<video>-S01E01.nfo` and `<video>-S01E02.nfo`. Each of those
  files contains one `<episodedetails>` block. Movie and episode NFOs include
  `<fileinfo><streamdetails>` (video, audio, and subtitle), with `<hdrtype>` and `<hdrdetail>`
  (for example `7FEL` or `8.1`). Each movie file keeps its own NFO. Copies that share a TMDB id,
  an IMDb id, or the same title and year are marked with Kodi’s version tags: `<videoassettitle>`
  (the edition, or Standard Edition), `<videoassettype>0</videoassettype>`, `<hasvideoversions>`,
  and `<isdefaultvideoversion>`. The highest-resolution copy is the default. A built-in Kodi cut
  name also gets its `<videoassetid>`. A custom cut name does not, because that id belongs to one
  Kodi library. Kodi still attaches the copies in its version manager. The Emby/Jellyfin dialect
  adds `<lockdata>` and flat ratings.
  The Plex dialect adds `<guid>` lines.
- Artwork is saved with Kodi names (`poster.jpg`, `clearlogo.png`, `season01-poster.jpg`,
  `<video>-thumb.jpg`). A multi-episode file uses `<video>-S01E01-thumb.jpg` for each episode.
  A scan that still finds the older shared `<video>.nfo` writes one `.nfo` per episode and retires the
  shared file. A scrape saves a separate thumbnail for each episode. Until that scrape runs, every
  episode in the file shows the shared thumbnail.
- **Split episodes** is experimental. It cuts a multi-episode Matroska file without re-encoding, using
  chapters when they sit near the expected join, otherwise a black frame together with silence. The
  file name can list more episodes than the video contains, so check every cut. The source is renamed
  and kept until you delete it. Restore puts that source back and removes the parts.
  Images narrower than the minimum width set for their type are skipped.
- **Fix Match** searches TMDB or TheTVDB, or takes a pasted id, and rescrapes with that id. A title, plot or year you
  had edited by hand on the old match is replaced too (only edition, set, tags, your rating, watched state and episode
  order keep their locks), and so are locked season names and episode titles of a show. The job's log under Jobs,
  Recent says what became of the title. For seven days afterwards the
  movie or show page has **Undo Fix Match**, which puts back the metadata, seasons, episodes, artwork and .nfo files from
  just before it (artwork and .nfo files the Fix Match added go to the recycle bin; video files are not touched).
- TheTVDB can supply movie metadata and artwork when it is selected for that movie. The movie's identity stays its TMDB id. A TheTVDB release date from another year is not used as the premiere.
- **Custom scrapers** on a movie, show, season, episode, or album saves a source order for that item. An empty choice follows the global order. A season or episode does not inherit the show's choice.
- The padlock locks an item. Scans, scrapes, and edits leave a locked item alone, and locking a show
  locks its seasons and episodes. **Edit** changes fields inline. Each edited field is locked on its
  own so scrapes keep your value, and the field's padlock in the edit form unlocks it again.
- **Remove…** asks whether to remove rows from the library only or to delete from disk. Removing
  from the library keeps the files, and the next scan adds them back. Deleting from disk works the
  way it does for music. The item must sit inside a mounted library folder, the library folder
  itself is never deleted, and an item whose folder holds other library items is refused. A movie
  or show in its own folder is deleted with the folder. A movie that shares a folder is deleted with
  its sidecar files (`.nfo`, artwork, subtitles) and nothing else. Seasons and episodes take their
  season artwork and episode sidecars with them. Deleting or removing a copy also rewrites Duplicate, Upgrade, and Not duplicates on the copies that remain. A lone survivor loses all three. Two or more copies that still match each other keep theirs. The open library updates those pills when the delete finishes.

### Provider ids

The info pane for a movie, show or episode ends with a row of every provider id the item has (icon, provider, number, separated by bullets). The Edit window has a **Provider ids** field written like `tmdb=1022, tvdb=2405`. Edited ids are locked, so scrapes keep them.

Season and episode numbers can also be set by hand in the Edit windows. The season window can renumber its episodes at the same time. Numbers set by hand are locked, so a scan keeps them.

### Episode numbers and Sonarr

With Sonarr set up, a TV scan stores each episode under the season and episode number Sonarr gives its file, which can differ from the file name (a file named S04E01 that Sonarr numbers S03E01). The library, the .nfo files and scraping use those numbers. Without Sonarr the file name decides.

### ARR versions and Sonarr 5

**Test connection** for Radarr, Sonarr, Lidarr and Bazarr logs the version the app reports and saves it in
`config/arr_versions.json`. The version, the API used and the time of the test are shown under the button.

Sonarr 3 and 4 are used through `/api/v3`, as before. When the test finds Sonarr 5 or newer and `/api/v5` answers,
Curator switches to `/api/v5`; an endpoint that v5 does not have is tried again on `/api/v3`. Sonarr 5 can find a
show by its TMDB id as well as its TVDB id, so **Look up in Sonarr** and the Sonarr searches are then also offered
for shows that only have a TMDB id, and **Add show** can add a show Sonarr only knows by its TMDB id (it waits in the
library as wanted until the files arrive). Below Sonarr 5 they stay greyed out for those shows. Run Test connection again
after upgrading Sonarr so Curator picks up the new version.

### Where ratings come from

Every score is stored under the name of the service it came from, and **Default rating** on the Movies and TV settings tabs picks the one shown as the main score and written to the `.nfo`.

| Rating | Where it comes from |
|---|---|
| TMDB | TMDB, in the movie, show and episode lookup. |
| IMDb | OMDb, with a key. Or IMDb's own data files, when you turn on **IMDb ratings from IMDb's own data files** (see below). |
| Rotten Tomatoes and Metacritic | OMDb, with a key. Or the title's page on rottentomatoes.com and metacritic.com, when those two are in the source list. |
| Trakt | Trakt, with a client ID. |
| TheTVDB, TVmaze, AniList, OFDb | The service of that name, when it is in the source list. OFDb (ofdb.de) is off by default, as it is mostly German. |

**Open Film Database (ofdb.cc).** A free, open (ODbL) movie and TV database with an API and no key, available as a
metadata source in the Movies and TV source lists. It is not the German OFDb at ofdb.de and it has no scores. It is
asked by id only (IMDb, then TMDB, then TheTVDB for shows), never by title, so it cannot attach a wrong title. It fills
what the sources above it left empty: title, original title, plot, tagline, release date and year, genres, runtime for
movies, and status and network for shows. Put it last in the list for that. New installs have it last in the source list. An install with a saved list gets it only when you add it under Settings, Movies or TV.

#### IMDb's own data files (optional)

IMDb publishes free data files for personal and non-commercial use at <https://datasets.imdbws.com/>. Under Settings, Integrations, IMDb ratings from IMDb's own data files (General and Schedules link there), the switch **Use IMDb's free datasets for ratings and episode details** lets Curator use three of them: ratings, episodes and basic title facts. Read [IMDb's terms for the datasets](https://developer.imdb.com/non-commercial-datasets) and its [licensing article](https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX) first, and turn it on only if you use Curator for personal, non-commercial purposes.

- **Off by default.** While it is off nothing is downloaded, and no lookup uses the data.
- **Each install downloads for itself**, straight from `datasets.imdbws.com`, with a common Mozilla browser user agent by default. The **User agent** box under the switch replaces it with anything you type, for example the name your own agreement or licence with IMDb asks for. **Use default** clears it. It is a single line of plain ASCII, at most 200 characters. The files are never part of the image or the repository, and Curator has no route that serves them. `.gitignore` and `.dockerignore` keep them out of both.
- **What stays on disk.** About 290 MB are downloaded into the cache folder, turned into one searchable index of about 270 MB (`<cache>/imdb/imdb.sqlite`), and the downloaded files are deleted right after. Building takes a minute or two. The index only covers what Curator reads: ratings, the id of each episode, and the title, year, runtime and genres of movies and shows. A failed or interrupted build leaves the old index in place. **Remove local copy** deletes it, once the switch is off.
- **Your own downloads are used first.** Files named `title.ratings.tsv.gz`, `title.episode.tsv.gz` and `title.basics.tsv.gz` in `<data>/imdb` (the `data` folder next to `config` and `cache`) are read for the build when they are newer than the refresh interval, so nothing is downloaded. Curator never changes or deletes them.
- **Refresh every 30 days** by default (7 to 365). IMDb updates the files daily, but ratings move slowly. Curator checks quietly in the background and downloads again only when the index is older than the interval, or when you press **Refresh now**. A refresh asks IMDb whether it has published anything new first, and the progress shows in the Jobs panel as *IMDb data*. After a failed update Curator waits a day before it tries again by itself.
- **What it fills in.** A show scrape gives every episode its own IMDb id and score, so OMDb is not asked for each episode. For movies and shows a scrape puts the copy last in the source order: it supplies the IMDb score when OMDb gave none (no key, the daily limit, or an unknown title) and the title, year, runtime and genres that no other source had, and a value from another source is never replaced by it. **Update ratings** is different: it uses the copy first (next point).
- **Update ratings, on one item or many.** Right-click a movie, show or episode (or a selection of them) and choose **Update ratings** (with the count when several are picked), or press **Update ratings** in the batch footer, which always runs as a job. Either way a window opens first with a tick box for every source: the local IMDb data (when it is built and switched on), TMDB, OMDb, Trakt, Rotten Tomatoes, Metacritic, AniList and OFDb. A **Select / deselect all** box above them ticks or clears every source that can be used. A source that is not set up (no key, switched off, not built) is greyed out with the reason, and your ticks are remembered for next time. Only the ticked sources are asked. The IMDb score comes from the local copy first and replaces the one OMDb has cached; TMDB, Trakt and the Rotten Tomatoes and Metacritic page scrapers (when they are on) are still asked for their own scores, and OMDb for the rest. One item updates on the spot. Several run as one job, shown in the Jobs panel as *Movie ratings*, *TV ratings* or *Episode ratings* with a Stop button, queued behind a running scan. To spare the OMDb daily limit, a batch skips OMDb for an item when the copy has its IMDb score and the item already has its Rotten Tomatoes or Metacritic score; an item that lacks those still asks OMDb. Locked items are skipped. Under the sources the window has an **Only update items where the score stored for a ticked source has…** box with *a rating below N*, *fewer than N votes*, *more than N votes* and *no score yet*, which narrows a big run to the items that most need it (a rating below 1 usually means no or very few votes). Nothing ticked updates every item; ticking several updates an item that meets any of them, checked per ticked source against the score already stored, and only the sources that qualify are asked. A missing score counts as a low rating and as few votes. The job ends with a line such as *28 updated, 26 with the IMDb score from the local data, 2 skipped, 0 failed*, and the lists and the open item reload by themselves. Without the local copy (switch off or not built yet) it works as before, from the online sources only. In a multi-episode file (for example `S02E21E22`) IMDb usually lists only the first episode, so every other episode in the file that has no IMDb score of its own takes the first episode's score and votes, in a scrape and in Update ratings. Trakt answers "429 too many requests" when asked for hundreds of episodes at once; Curator waits that out (following Trakt's Retry-After) instead of failing the items, so a big run with only Trakt ticked is slow. Tick the local IMDb data and leave Trakt out for speed.

Data from IMDb's non-commercial datasets, for personal use only.

### Movie sets

Set a **central set folder** on the Movie sets settings tab (Browse picks a folder the container can see, for example `/movies/_Sets`) or with `CMM_SET_FOLDER`. A saved setting overrides the variable. Point
Kodi's "Movie set information folder" at the same place. Each set gets a subfolder named after the
set, with characters Windows can't use replaced by `_`. It holds `poster.jpg`, `fanart.jpg`,
`clearlogo.png`, `discart.png`, the other chosen artwork, and `set.nfo`. The folder is filled when a movie
in the set is scraped, or with **Scrape set** on the Movie sets tab. Art comes from TMDB
collections and fanart.tv. Each movie's `.nfo` includes a `<set>` block with the collection name and overview, so Kodi can group the movies without assigning the set by hand.

Scraping also stores every movie of the TMDB collection. The Movie sets list shows how many of them
you own, and a set's page lists the missing ones with their release state. Movie titles on that page wrap, so the full title stays visible. The set list has filter ribbons: New, Movies missing, Artwork missing, Not scraped, Scrape failed, and No NFO. **Search in Radarr** adds
a missing movie to Radarr (monitored, with the root folder, quality profile and minimum availability
from Settings, Integrations, Radarr) and starts a search. A movie Radarr already has is set to
monitored and searched. Set the Radarr address and key there or with `RADARR_URL` and
`RADARR_API_KEY`.

## Renaming, subtitles, extras, and trailers

Music rename uses the folder and file patterns on Settings, Files. The same patterns are used by a batch rename. A one-disc album is `<album artist>/[<year>] <album>/Disc 1 - 01 - <title>`. A multi-disc album adds `CD<disc>` under the album, so disc 2 track 1 is `<album artist>/[<year>] <album>/CD2/Disc 2 - 01 - <title>`. `%multidisc%` is filled in only when the release has more than one disc, and `$if(%multidisc%,/CD%discnumber%)` adds that folder. A saved pattern that is still the previous default is updated to this one. A pattern you edited is left as it is. The album page shows the record label and catalog number when they are known, under the artist and year.

Music artwork uses Kodi names. A one-disc album keeps `discart.png`. A multi-disc album also saves `discart1.png`, `discart2.png`, and so on, with no leading zero, and puts `discart.png` inside each `CD` folder when that disc has art. `discart.png` stays in the album folder as well, so a skin that looks at the album still finds a disc image. Cover Art Archive medium images are the per-disc source. A disc with no image is left blank rather than copied from another disc. Disc art is saved as a transparent PNG. `back.jpg`, `spine.jpg`, and `booklet.pdf` stay in the album folder.

Every disc of a release keeps the same album tag. A trailing `(CD 1)` or `(Disc 2)` is removed, so Kodi does not split the release. `DISCNUMBER` and `TOTALDISCS` are plain integers, with no leading zero. A MusicBrainz disc title is written as `DISCSUBTITLE` (`TSST` on MP3). The release id and release-group id are the same on every track. Several artists in one tag are written as separate artist values. A compilation is tagged `COMPILATION=1`.

`album.nfo` is written once, in the album folder. A copy inside `CD1` or `Disc 2` is removed. Each `<track>` includes `<disc>` and, when the disc has a title, `<discsubtitle>`.

On an MKV, the audio and embedded subtitle tables have a **Default** button and a **Language** list with a **Set** button. Default sets the track the player starts with. Language writes the chosen language into the track, for example when it shows as unknown. Both go through mkvpropedit, in place. Changing a language asks you to confirm first. Other containers (MP4 and so on) cannot be changed in place, so the language list is greyed out and the file has to be remuxed to MKV first. Languages are always chosen from a list and never typed. External subtitle language and flags are set in the editor under the Subtitles table, which renames the sidecar. The filter menu for movies and TV shows has **Unknown audio language** and **Unknown subtitle language** to find the files that need this.

**Language** in the header opens Language defaults. Choose whether a language is not the default, is the default, or is present on any track, then pick the language and an optional filename. Scope is the whole library or one movie or TV root. The list shows 1,000 files at a time. Choosing a badge sets the default audio or subtitle for that MKV, and choosing it again clears the choice. **Save all** updates the MKV files on the current page. When you have not picked a subtitle, it prefers a full subtitle, then SDH, then Forced. Files that have not been probed stay out of the list.

**Switch dubbed releases to the original language.** Settings, Files, Original language has *Enable automatic switch of default language to original language*, with a switch for Movies and one for TV show episodes (off by default). A dual-language release often plays the dubbed track first. With the switch on, the default audio of an MKV is set to the original language after a Radarr or Sonarr import and after a library scan finds a new or changed file. The original language from the scrape is used first. When it is unknown, a release or folder name such as `German.DL`, `DL.French`, `Italian.DUBBED` or `DUBBED.Italian` marks the dubbed language and the one other audio language is used; `MULTI` or `DUAL` alone, three or more languages, or tracks without a language leave the file alone. A commentary track is never picked. The default subtitle then follows **Preferred subtitle languages**, five dropdowns in priority order: with 1. English, 2. German, 3. Swedish, a full English subtitle wins, then German, then Swedish. When the audio is itself in one of those languages, only a forced subtitle in that language is chosen, and when nothing matches, no subtitle is the default. Only MKV files are changed, in place with mkvpropedit. A file whose default tracks you set by hand in Curator (a Default button or Language defaults) is skipped until the file is replaced. **Switch to original language…** on the right-click menu of a movie, show, season or episode shows the changes first and then runs as a file job, also on hand-set files. Music has no language tracks, so it has no switch.

Right-click a movie, show, season, or episode:

- **Rename files…** shows every move first, then renames files and folders from the Jinja2 patterns Settings, Files has a **Syntax builder** button under each pattern: click pieces, ready-made patterns, free text and separators together and the pattern is written into the box.
  on Settings, Files. The defaults use dots, for example
  `Apocalypse.Now.1979.Final.Cut.UHD.Bluray.2160p.TrueHD.Atmos.7.1.DV.HDR10.HEVC.part1.mkv` and
  `Severance.S01E03.In.Perpetuity.1080p.AVC.mkv`, with season folders `Season 1` and `Specials`.
  A movie split across discs is named `part1`, `part2`, and so on, so Kodi stacks them as one movie. One `.nfo` is written for the stack, using the shared name, not one file per part.
  When the current file or movie folder ends in a scene group with no space before the hyphen, such as
  `-CINEPHILES`, that group is added at the end (`...]-part1-CINEPHILES.mkv`). Each pattern box shows a
  filled-in example as you edit it.
  Sidecars (`.nfo`, artwork, subtitles) follow their video, the stored paths and artwork links are
  updated, and Kodi is asked to clean and rescan. A failed move puts back the moves already made.
  Movies that share a folder keep the folder name; only their files are renamed.
- **Normalize subtitles** converts text subtitles to UTF-8 without BOM with one line-ending style,
  and renames sidecars to `<video>.<language>[.forced][.default][.sdh][.commentary].<ext>`. Language
  codes are three letters (`eng`) or two (`en`), set on the Files tab or with
  `CMM_SUBTITLE_LANG_STANDARD`. `cc` and `hi` after a language become `sdh`; a lone `hi` is Hindi. Norwegian Bokmål (`nb`, `nob`) counts as Norwegian (`nor`) and Nynorsk (`nn`, `nno`) is its own language (`nno`). A language written twice, such as `Movie.nor.nb.srt`, is renamed to `Movie.nor.srt`. If that name is taken the file is left as it is.
- **Organize extras…** sorts extras inside a movie's own folder. The Kodi layout puts the first
  trailer next to the movie as `<movie>-trailer.<ext>` and the rest in `Extras/`. The Plex and
  Jellyfin layout uses `Trailers/`, `Behind The Scenes/`, `Deleted Scenes/`, `Featurettes/`,
  `Interviews/`, `Scenes/`, `Shorts/`, and `Other/`.
- **Download trailer** fetches the scraped YouTube trailer with yt-dlp. Quality is 2160p, 1080p, or 720p (default 1080p). A trailer already on disk is kept, unless it is below that quality and YouTube has a taller copy. The Kodi layout saves `<movie>-trailer.<ext>` next to the movie. The Plex layout saves it under `Trailers/`. The same rules apply to a show or a season.
- **Move to…** copies a movie folder, a show folder, or an artist folder into another library folder of the same type. The destination has to be a library path that is already set and mounted. The folder name stays the same. After every file matches in size, Curator rewrites the stored paths and the library root, then removes the original. No scan or probe runs. Kodi is told about the new folder. A movie that is not in its own folder, a folder shared with another item, and a destination that already has that folder name are refused.

  Move moves the whole folder, so every file in it (subtitles, extras, artwork, `.nfo`) goes along and none is left behind. **For movies and shows that Radarr or Sonarr manage, move them there instead** (Radarr: Movie Editor, Change Root Folder; Sonarr: Series Editor, Root Folder). They move the files and then send Curator a webhook, so the library is updated from what they report, and their own database stays in step. A move done only in Curator leaves Radarr and Sonarr pointing at the old path until you edit them or rescan, and they may then report the item missing or download it again. Use Move to… for items the ARRs do not manage.

Subtitle clean-up can run after every Radarr, Sonarr, and Bazarr import (Files tab). Movie
trailers can download after a Radarr import (Movies tab, On Radarr import) and season trailers
after a Sonarr import (TV Shows tab, On Sonarr import). A trailer is only downloaded when none is on
disk or the file is below the quality set under General, Trailer download quality.

**Missing trailer and Missing theme song filters.** The Movies filter menu has **Missing trailer** and
**Missing theme song**, and the TV shows menu has **Missing theme song** (TV has **No trailer**, not Missing trailer). They list items that have no trailer or theme file in their folder. They are not the same
as the **No trailer** filter, which lists items with no scraped trailer link and no file. A movie or show is
checked on disk at the end of every scan, after a trailer or theme song download, after a rename, extras or move
job, and once at startup for anything not checked yet, so a file placed by hand shows up after the next scan. An item
whose folder cannot be reached (a mount that is offline) is not flagged, and neither is one that has not been
checked yet. On TV, Missing theme song applies to shows. Both can be saved in a saved filter, and a scan then tags what they match.

**Filter counts on TV shows** are split by kind, for example *12 shows, 340 episodes*, because the list mixes shows, seasons and episodes (only the shows you have opened contribute seasons and episodes). **Unmatched** counts shows only; **No poster** counts shows and seasons.

**Duplicate subtitles:** Normalize subtitles compares the sidecars of each video by SHA-256 of their
text, ignoring encoding, BOM, line endings, and trailing spaces. Image subtitles are compared byte for
byte, and sidecars whose languages differ are never paired. The best-named copy is kept: it has a
language, follows the naming pattern, and has more flags. With **Remove duplicate subtitles** on
(Files tab, or `CMM_PURGE_DUPLICATE_SUBS=true`), duplicates are deleted, including sidecars that
match a text track inside the video. That check extracts the tracks with ffmpeg and reads the whole
file. With it off, duplicates are only listed in the log.

### Finding subtitles on OpenSubtitles.com

Right-click one movie or episode and choose **Find subtitles…**. The window lists what OpenSubtitles.com has for
the languages set in Settings, General, API credentials, OpenSubtitles.com. A subtitle made for this exact file
(matched by the OpenSubtitles file hash) is marked **File match** and sorts first, then trusted uploaders, then the
most downloaded. **Download** saves it next to the video as `<video>.<lang>[.sdh].srt`, in UTF-8, using the language
tag style chosen under Files.

The same settings page holds the API key (free at opensubtitles.com, under Consumers), the account username and
password, the languages (two-letter codes such as `en, nb, pt-br`) and whether hearing-impaired subtitles are skipped,
allowed or the only ones wanted. Searching needs the key; downloading also needs the login.

OpenSubtitles.com limits downloads per 24 hours:

- Anonymous users: 5 downloads per IP.
- Authenticated users: depending on rank, from 10 for regular users to 1000 for VIP users.

Curator always downloads signed in, so your account's limit applies. `OPENSUBTITLES_API_KEY`, `OPENSUBTITLES_USERNAME` and `OPENSUBTITLES_PASSWORD` can also be set in docker-compose.

With **Download missing subtitles from OpenSubtitles.com during a scan** on (Movies tab and TV Shows tab, During a
scan), a scan runs after the metadata lookup and saves the best match for every wanted language a movie or episode
has no full subtitle in, embedded or beside the file. Forced subtitles do not count. An incremental scan covers new
and changed items; a full or deep scan covers all of them. When the daily limit is reached the scan stops asking and
the rest are picked up by the next scan.

### Syncing external subtitles

On a movie or episode info pane, each external subtitle in the Subtitles table has a speech-bubble icon in the **Sync** column. It opens a modal with the video on the left and the subtitle lines on the right.

1. Click a line (or **Pick**), scrub the video to the moment that line should appear, and press **Mark** (or click **Pick** at the right moment). That line is now an anchor.
2. **One anchor** shifts the whole subtitle by a constant offset. **Two or more anchors** fit a straight line through them, which also corrects a different frame rate (for example 23.976 against 25). With three or more, the header shows how far the middle anchors miss the line. A banner appears when the subtitle ends more than 2% away from the video's length. In that case, mark one anchor near the start and one near the end.
3. **Piecewise** (needs two or more anchors) gives every pair of neighbouring anchors its own slope and offset. Use it when the file was cut in the middle, for example commercials removed.
4. The video shows the synced subtitle live as you work. Nothing is written until you press **Save**. A video the browser cannot play (an XviD AVI, AC-3 or DTS audio, HEVC) is converted once to a small 360p H.264 copy under `/cache/preview`. The first open waits for that, and the window shows the progress. The original file is not changed, and the timeline matches it exactly. **Sync OK** (top of the window) closes it, deletes that copy, and marks the subtitle as synced: a green *Synced* appears next to its Sync icon until the subtitle file changes again. **Close** keeps the copy for next time and leaves the status alone.

The search box above the list finds a phrase, which is the quickest way to find a line you remember hearing. **Edit** on a line fixes its text. Edited lines are marked, and the edit is applied by the next **Save**.

**Save** rewrites only the timing, and the rest of the file is kept byte for byte (ASS styles, VTT cue ids, blank lines). The previous version is kept as `<subtitle>.sync-backup`, one per subtitle. **Revert to backup** restores it. A second save replaces the backup, so revert once before you save again if you want the original. `.srt`, `.vtt`, `.ass`, and `.ssa` are supported. Only files inside a configured library can be opened.

**Sync automatically** (above the list, and on the OCR screen of a picture subtitle) runs [alass](https://github.com/kaegi/alass) in the background. It listens to the video's speech, matches it to when the subtitle has text, and proposes the fit. Nothing is written: the result becomes anchors, the video shows the result live, and **Save** works as for a manual sync. The drop-down has three choices. **Fine-tune (up to 5 s)** is the default and is meant for a subtitle that is already close: it never splits, and when alass proposes moving any line further than 5 seconds it changes nothing and says so, because a nearly-right subtitle that alass wants to move far is almost always alass being fooled. When the difference is under 0.1 s it reports that the subtitle already matches. **One shift, any size** is for a subtitle that is really off by a constant amount or frame rate. **Allow cuts, any size** also looks for separate stretches (commercials removed, a different edit) and labels them *Stepwise fit*: each stretch is shifted by its own offset and not stretched. A constant error gives one anchor, a frame rate change two, and a cut one per stretch. It works on the subtitle's timing only, so picture subtitles need no OCR first. It takes seconds to a few minutes depending on the video, runs one at a time, shows in the Jobs panel as *Automatic subtitle sync*, and can be cancelled. Check a few lines at the start, middle and end before saving: alass is good, not infallible, and a video with little speech or music over the dialogue is the hard case.

**Shift all lines** above the list moves everything at once without marking anything: the −1 s, −100 ms, +100 ms and +1 s buttons, or a typed amount (`+2.5`, `-0.3`, `250ms`; plain numbers are seconds) followed by **Shift** or Enter. With no anchors it makes one on the first (or selected) line; with anchors it moves them all, so a fit keeps its shape. Pressing **Save** still writes it.

With **After syncing or exporting a subtitle, tell the players and Bazarr** on (Settings, Video, Files tab, Subtitle sync; off by default), a saved sync (and **Sync OK**, which also asks Bazarr only) tells Kodi, Emby, Jellyfin, and Plex to re-read the folder, and asks Bazarr to scan the disk for that movie or show (Bazarr's `scan-disk` action) so it lists the changed file. The version number beside the logo is the date of the newest app file plus a short fingerprint of the files, so you can tell whether the browser is running what is on disk. Bazarr needs no path mapping, only that Radarr or Sonarr knows the movie or show and Bazarr has synced it. If Bazarr is off, unreachable, or does not know the item, nothing happens and the save is not affected.

The same settings block shows the installed OCR languages and how much disk the two caches use, with a size limit for each (preview copies default to 5 GB, recognised text to 100 MB; 0 means no limit) and a Clear button. The least recently used files go first when a limit is passed. OCR and building a preview copy show up in the Jobs panel as *Subtitle OCR* and *Video preview*.

**Picture subtitles** (VobSub `.idx` + `.sub`, and PGS `.sup`) open in the same modal. A VobSub is one row in the Subtitles table, under the `.sub` name, and setting its language or flags renames both files together. Their lines are pictures, so Curator first reads them with tesseract (OCR). That starts by itself when you open the modal and runs in the background, with a language picker that defaults to the language in the `.idx` or the file name. The progress is saved every few lines, so a cancelled or restarted run resumes. It keeps running if you close the modal. One file is recognised at a time. The recognised text is cached under `/cache/ocr` and survives a sync, because the cache is keyed by the picture, not the timestamp. After that, picking anchors, search, and live preview work as for text subtitles.

- **Save** on a picture subtitle retimes it in place. The pictures are not touched and stay pictures. For VobSub that rewrites the timestamps in the `.idx` for every language stream in the file, and each picture keeps its own on-screen duration. For PGS it rewrites the timing in each segment of the `.sup`. The backup is the `.idx` or `.sup`.
- **Export SRT** writes the recognised text, with your anchors and text edits applied, as `<name>.srt` next to the picture subtitle, and leaves the original alone. An existing `.srt` is only replaced after you confirm, and the old one is kept as a `.sync-backup`. Edited text only ever goes into the exported SRT.
- **Redo OCR** recognises the pictures again, for example with another language.
- A `.idx` with several language streams shows only the first stream in the modal. Save moves every stream by the same amount. A fit that stretches time changes when each picture appears, but each keeps its own length on screen.
- OCR is only as good as the pictures. Expect the occasional wrong letter (a capital I read as a lowercase l, for example). Fix those with **Edit** before exporting.

## How a file name is read

The probe reads codecs from the file. The name supplies the source, the edition, and the release group. A `.iso` or `.vob` is not probed. Curator reads those from the file name, and an `.iso` is a full disc.

`Scarface.1983.2160.UHD.Blu-ray.TrueHD.7.1-F13@HDSpace.iso` is stored as Complete UHD Blu-ray, 3840×2160, HEVC 10-bit, TrueHD 7.1, container iso, release group `F13@HDSpace`. `2160` without `p` counts as 4K. A UHD Blu-ray disc that does not name a video codec is stored as HEVC 10-bit. The same words on an `.mkv` stay UHD Blu-ray, because that file is not a full disc. A Blu-ray `.iso` without UHD is Complete Blu-ray. An `.iso` that already failed with "Disc images are not probed" is re-read from its name on the next scan.

A bare `WEB` is WEB-DL. `WEBRip` and `WEB-DL` stay their own sources.

`Criterion` in the middle or at the end of a file or folder name is the Criterion edition. `Criterion Collection` stays that longer name. A trailing `-Criterion` is the edition, so it is not stored as the release group. The folder name is used when the file name has no edition. An empty stored edition is filled on the next incremental scan. A stored edition that already has a value stays.

A name that ends in `.mkv`, then more text, then another `.mkv` drops that tail before the release group is read. `Thor.Ragnarok.2017.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-FraMeSToR.mkv-WtF-xpost.mkv` stores the group `FraMeSToR`. The file is not renamed. `@` is allowed inside a group token. Words in the filename-noise list, such as `xpost` and `repost`, are not a group.

Copies of the same movie collapse by TMDB id, IMDb id, or the same title and year. A 3D copy is only grouped with other 3D copies. The row label is "N versions available". When a file replaces another, the new file is probed and edition, source, hybrid, 3D, and release group are overwritten. A non-empty title, year, plot, tagline, ratings, cast, or certification is kept, and those fields are filled when they were empty. Sidecar artwork and the `.nfo` whose name matches the old stem are renamed with the new file.

## Tags

**Tags** in the Movies and TV toolbar lists every tag with how often it is used. You can rename a tag
(renaming to an existing tag merges the two) or delete it. Right-click picked movies or shows and
choose **Tags…** to add or remove tags, or **Fetch keywords from TMDB** to add the TMDB keywords as
tags. Locked items are skipped. Changed items get `tags` added to their locked fields, so a later
scrape keeps them, and their `.nfo` is rewritten when Write .nfo on edit is on.

## Filter by clicking a badge

Click a quality badge in the Movies or TV table to filter by it: resolution, HDR, Dolby Vision profile and FEL/MEL,
codecs, channels, source and 3D. The badge sets that column's filter, the same one the column header opens. Clicking
**P7** in Main HDR keeps Dolby Vision profile 7, both FEL and MEL. Clicking **FEL** on one of those rows narrows it
to profile 7 FEL, and clicking **P7** again widens back to all of profile 7. Clicking the badge that matches the
filter exactly clears it. Badges in different columns combine, for example 4K with Atmos.

The Music table works the same way: Format, Quality, Bits, Sample rate and Bitrate are shown as coloured badges
(green for lossless), and clicking one filters that column. **FLAC** and then **24-bit** keeps the 24-bit FLAC albums.

**Latest added** keeps what was added in the last 30 days and sorts it newest first, on Movies, TV Shows and Music.
A show or an artist counts from its newest episode or album. Turning it off puts back the sort you had.

## Saved filters

The ribbons, column filters and search box on Movies, TV shows, Movie sets and Music can be saved as a named
filter. **Save filter** stores the view on screen and **Saved** applies or deletes one. A movie or TV filter can
also carry a tag: a scan then adds that tag to every item the filter matches (the ribbons and column values it
can read from the database; the search box stays on the view only). Missing trailer and Missing theme song count
among those ribbons. A full or deep scan checks every movie or show in the scanned folders; an incremental scan only
the ones it added or read again. A tag is only added, never taken off when an item stops matching. A filter can also be
written as a Kodi smart playlist (see below). A movie or TV filter can also run an **action** on a schedule: Scrape
what is missing, Quick integrity check or Download trailers, every day or every week at a chosen hour, for what it matches
then. It runs as a job in the Jobs panel, and the Saved menu has **Run now**. An action reads the ribbons a scan does plus
New, Latest added, Not scraped, Scrape failed, No NFO, No poster, No trailer and Ignored (and for movies Upgrade
available, Duplicate, Probe failed and Corrupt); a filter with nothing the server can read cannot get an action. See Tags above for
how tags are written.

## Kodi smart playlists

Tick **Kodi smart playlist** when saving a movie or TV filter. Curator writes `Curator - name.xsp` to the playlist
folder (Settings, Files; default `config/playlists/video`) with a rule that lists the file names the filter matches.
Saved music filters are written to `playlists/music` as album playlists. The search box of a saved filter narrows a playlist by title. Presets that depend on the page make no playlist. It is rewritten after every scan and when a saved filter is saved or removed. Point Kodi's
`userdata/playlists/video` at that folder or copy the files there. Only files that start with `Curator - ` are removed
from it.

## Analytics and export

The chart icon in the header opens Library analytics. It has pure-CSS donuts for HDR format (Dolby
Vision P7 FEL and MEL, P8.1, P8.4, P5, P10, P20, HDR10+, HDR10, HLG, and SDR), secondary HDR under
Dolby Vision, resolution, and video codec. Bars show files and size per library path, the main audio
codec, and the source. A line shows scans per day or month for music, movies, and TV, for this week,
this month, this year, or all time. You can narrow it to movies, TV, or one path.

**Export** in the toolbar saves the list as shown: the filter, the ribbons, and the path picked in
the Scan menu all apply. Movies export one row per movie; TV exports one row per episode of the
shown shows. Movie sets, Music (one row per album) and Music videos export the same way. Every metadata and media-info column is included. Pick CSV or XML on the Files tab.

### Disk space

**Disk space** in Library analytics shows each library folder's drive: free space, what the library holds there, and
other files. Curator measures each folder once a day, so a growth line for library size and free space fills in over
time. It also shows the recycle bin's size. In the recycle bin window you can search, pick a type, sort by name, type, reason, date or size, tick several items (or all that are shown) and restore or delete them together. The Why column says what deleted each item, for example Bulk duplicate cleanup or Deleted from disk by hand. Settings, General can warn when a drive is under a free space limit and
delete the oldest recycle bin items on it first. **Could be freed** lists the duplicate, upgrade and extra episode copies, the folders that hold most of them,
and the biggest copies, with Delete (to the recycle bin).

### Orphan report

**Orphan report** in Library analytics compares Radarr, Sonarr and Lidarr with the library: files an app keeps but does
not use, library files in an app's folder that the app does not know, and app records whose file is gone. It also walks
the library folders for stray files nothing lists. Delete uses the library delete (the recycle bin, then a rescan in the
app). A file that is the only copy of its title is never offered for Delete, because the app not using it does not mean nobody needs it: it gets **Rescan in** the app instead. A missing file gets **Rescan in** the app. When most of an app's files look missing, the report warns that the path
mappings are probably wrong. **Test connections** asks each app the same questions and says what came back.

**Kodi** at the bottom of the same window compares Kodi's movies and episodes with the library, file by file, through the
Kodi path rows (Settings, Integrations): entries whose file is gone (**Clean the Kodi video library**), library files
Kodi has no entry for (**Scan in Kodi**), files Kodi has that Curator does not list, and paths or folders no row covers.
Nothing changes until you press a button; a library folder that is not mounted is left out. Music is not compared.

### Upgrade wishlist

Set a minimum per library under Settings, Files: resolution and HDR for movies and TV, lossless or 24-bit for music.
**Upgrade wishlist** in Library analytics lists what falls short, leaving out titles that already have a better copy, and
**Search** asks the app to look for it.

### Activity history

**History** in Library analytics lists what Curator deleted, restored, renamed, moved or changed, and why. Search it by
title, path or reason. The newest 20,000 lines are kept. Music renames, remux, split, removing from the library and
watched-sync changes are recorded too.

### What changed

**Tools, What changed** shows one period at a glance (last 24 hours, 7, 30 or 90 days): what was added (movies,
episodes, albums, music videos), what was deleted, removed, renamed, moved, restored or found corrupt and why, which
artwork was replaced, and which jobs failed. Each kind of change is a block you can fold. Activity history has the
full searchable list.

### Health score

Movies and TV shows carry a score from 0 to 100 beside the title. Six things count the same out of the box: matched,
scraped, .nfo, poster, fanart, and a file that is not corrupt and could be probed. For a show the .nfo and file checks
include its episodes. Hover the score to read what to fix. **Needs work** and **Complete** under More filters list the
items below and at 100. Under Settings, Movies or TV shows, below **Show the health score**, tick what counts: the six
above plus **Subtitles** and **No other file warnings** (unknown audio language, no audio, shorter than expected),
which are off until you tick them. Trailers, theme songs, extra artwork types and missing episodes never count.

### Tools menu

The **Tools** button in the header gathers the maintenance windows (duplicates, bulk cleanup, wishlist, history,
twin shows and twin artists) in one menu instead of buttons scattered over the analytics window.

## Automation (Radarr, Sonarr, Bazarr, Lidarr)

Set `CMM_API_KEY` in `.env`. Webhooks are refused until it is set. Then add a webhook in each app
that points at:

```
http://<host>:4455/api/v1/webhooks/arr?apikey=<CMM_API_KEY>
```

This address is open even when Basic Auth is on, because the key protects it.

**Follow imports** (Tools menu, or the button in the Queue window) shows each item a webhook brings in (Radarr, Sonarr,
Lidarr and Bazarr), each item restored from the recycle bin, and each library update or Kodi clean started in Curator, as a row of steps:
the webhook, waiting for more webhooks for that folder, the scan, the scrape, the file jobs (subtitles, trailers,
language and damage checks), then each player's library update (Kodi, Jellyfin, Emby, Plex or Navidrome). Green is
done, blue is running, amber is waiting, red failed and grey not reached or not needed. Point at a step for its detail. Under each import's status is its time in all and without the wait for more webhooks.
A webhook that could not be placed in the library ends at its first step with the reason. The window refreshes itself
while it is open. A scan the webhook queue starts no longer opens the scan results window or its own notices; the
window and the one "Webhook queue finished" notice per run cover it. The newest 300 imports are kept. Under Settings,
Notifications, the event **An import ended with a failed step** sends a message (with the failed step and its reason) to
the targets that have it ticked; new targets have it on.

- **Radarr and Sonarr:** Settings, Connect, Webhook. Tick On Import, On Upgrade, On Rename, and the
  delete events. Grabs need no scan and are only logged. An import that replaces a file (an upgrade) also asks
  Kodi for a clean once the queue has finished, so the old file's entry does not stay beside the new one.
- **Bazarr:** Settings, Notifications, add an Apprise `json://<host>:4455/api/v1/webhooks/arr?apikey=...`
  URL. Bazarr's message has no path, so Curator finds the movie or show by its title and year.
- **Lidarr:** the same URL works. Imports are handed to Resonance's existing Lidarr import. A Retag call (Lidarr rewrote
  the tags of one file) reads that album again, except one Lidarr sends while importing (its file id is still 0),
  which the album's Download call covers; a file in a disc folder of a box set queues the whole box set under its
  artist, as one item. Tick the delete events
  too: an album or artist deleted in Lidarr leaves the library once its folder is gone from disk (the album is found
  under the artist folder Lidarr names), and the players are asked to clean. Nothing leaves the library while the
  music folder around it cannot be read. A folder that is still there (Lidarr kept the files) is read again instead.

**+ Movie and + Show.** Next to the sort menu, Movies has **+ Movie** and TV Shows has **+ Show** (Movie sets has **+ Set**,
which makes a new set). The window searches TMDB (movies) or TMDB and TheTVDB (shows). Pick a result and Curator asks
Radarr or Sonarr to add it, using the root folder and quality profile set under Settings, Integrations (the first one Radarr or Sonarr lists when those are blank).
Curator then lists the title as wanted until the files arrive. The window has a tick box, **Ask Radarr to search for the
movie now** (Sonarr: **...for the missing episodes now**). It starts on or off to match **Start a search right away**
in Settings, Integrations (on by default), and it applies to that one add. Radarr and Sonarr add the title either way. The tick only
decides whether they also start looking for a release. While Radarr or Sonarr is being asked, the add is listed in the Jobs panel (ARR) as **Add to Radarr** or **Add to Sonarr**, and the task bar says which one it is sending to. If the integration is off or has no address and key, the window says so at the top. A show
needs a TVDB id for Sonarr, which Curator looks up through TMDB when you pick a TMDB result.

**Search missing episodes** on a show or a season asks Sonarr to search the monitored episodes it has no file for. **Search missing subtitles** on a movie, a show, or an episode asks Bazarr to search the subtitles it already lists as missing. Both need the address and API key under Settings, Integrations (or `SONARR_URL`, `SONARR_API_KEY`, `BAZARR_URL`, and `BAZARR_API_KEY`). Bazarr learns its library from Sonarr and Radarr, so the title has to be there already. Right-click a movie and choose **Look up in Radarr**, a show and **Look up in Sonarr**, or an album on the discography and **Look up in Lidarr**. Each of those opens that one title. **Search missing in Lidarr** on an artist page searches every missing studio album. The **+** button on Movies and TV searches TMDB (and TheTVDB for shows, when a key is set) and sends the chosen title to Radarr or Sonarr first. Curator keeps a wanted row, with no video file, only when that add is accepted or the title is already in Radarr or Sonarr. A rejection, a missing integration, or a show with no TVDB id leaves Curator unchanged. A later scan that finds the same TMDB or TVDB id updates that row onto the real folder.

## Dolby Vision conversion and track selection

Both tools are on a movie or episode whose file is an `.mkv`. Disc images are refused, and the tools wait while
a scan, a scrape or a file job is running. Only one runs at a time, and progress shows in the Jobs panel.

- **Convert to DV 8.1** appears when the file is Dolby Vision Profile 7 with an enhancement layer (FEL or MEL).
  Curator extracts the base layer and the Dolby Vision metadata, converts the metadata to Profile 8.1 with
  dovi_tool, and remuxes a new file named `<name>.p8.mkv` beside the original. The new file must probe cleanly.
  The original stays unless you ask for it to be removed; in that case it is removed only after a deep scan of the
  new file. This needs ffmpeg, dovi_tool and mkvmerge, which the image includes.
- **Tracks** lists every video, audio and subtitle track in the file. Tick the ones to keep and Curator rewrites
  that one file with only those tracks. Chapters and attachments stay. The file is probed again afterwards, and
  a failed rewrite leaves it unchanged.

## Duplicates and upgrades

Movies that are the same release (same source, resolution, and about the same size) get a Duplicate pill. A lower copy of the same movie gets Upgrade available, and the upgrade points at the better file. 3D copies are only compared with other 3D copies. Episodes use the same rules for one show, season, and episode number. Albums are duplicates when they share a MusicBrainz release, or when the artist and title match after edition notes such as `(Remaster)` or `[Deluxe Edition]` are ignored and the audio quality is the same. A subtitle in parentheses stays, so `Weezer (Blue Album)` and `Weezer (Green Album)` are different albums. A better-sounding album is an upgrade, not a duplicate. A remix album (MusicBrainz release type Remix, or Remix, Remixes, Remixed or "Mixes" in the title) is never a copy of the studio album. A special release (a Deluxe, Expanded, Anniversary, Special, Limited, Collector's, Extended or box set edition, bonus tracks, or a different number of tracks) has two settings under Settings, Music, both off by default: **Count special releases as duplicates** and **Count a better-sounding special release as an upgrade**. Turn on only the second to have a Deluxe edition offered as an upgrade without marking it a duplicate. Changing either records the marks again at once.

Both the duplicate and the album upgrade dialog show the songs of each copy side by side, lined up by AcoustID, fingerprint, title or position, with a missing or differently named song marked. The duplicate and upgrade dialogs list each copy with the Radarr, Sonarr, or Lidarr id of the file that app already has. A copy the app does not have is labeled that way. A lookup that does not finish leaves the copies unlabeled. **Not duplicates** hides that pair. **Undo not duplicates** puts the pills back. That undo lasts until you use it or reload the page. It does not restore a file. A copy deleted from disk goes to the recycle bin, where Restore puts it back. Deleting one side of a Not duplicates pair removes that choice, and the undo button for it goes away.

Two show folders that hold the same show (a shared TVDB, TMDB, or IMDb id and the same name once a bracketed year or country is left out, or the same title and year without ids) both get a Duplicate pill, even when their episodes are different releases. Shows are not collapsed into one row.

**Bulk duplicate cleanup** (a red button in Library analytics and the Duplicates window) keeps the best copy of each title, and among equal copies the one the app uses. Preview lists what stays, what goes and what is left alone, and untick any title. Nothing is deleted until you press the separate red confirm button. A copy is left alone when the copy to keep is missing, empty or corrupt, or when it is another edition, locked, marked Not duplicates, a file two episodes share, or an album with tracks the kept album lacks. Weaker copies only go when that box is ticked. Files go to the recycle bin when it is on.

The Duplicate pill on a show that another folder also holds opens a window comparing the folders, with Delete, Remove from library and Not duplicates.

Every compare window (albums, movies, episodes, music videos, and show and artist folders) has the same layout: a line that says why the rows are copies, the copies side by side (picture, name, facts, the Radarr/Sonarr/Lidarr line and the path), the bin at the top of a copy for Delete from disk, **Remove from library** under it, and **Not duplicates** at the bottom. Albums show their songs lined up in the middle. A music video's Duplicate or Upgrade available pill opens the same window.

Two artist folders are the same artist when they share a MusicBrainz artist id, or have the same name ignoring capitals and punctuation. Both get a Duplicate pill; clicking it compares the folders (albums, tracks, size) with **Merge…** (the usual artist merge) and **Not duplicates** (with Undo).

Deleting a copy that Radarr, Sonarr, or Lidarr is tracking asks that app to rescan when another copy of the title is still in the library, so the app can follow the file that remains. The duplicate and upgrade windows open from the database alone, reading only the copies of that item, and the Radarr, Sonarr or Lidarr line under each copy is filled in a moment later.

Deleting music from disk, like a movie or episode, asks Kodi and the other players to clean afterwards, and leaves an album alone while a batch or lookup job is writing it.

## Music

To fetch only lyrics, right-click the albums or artists and choose **Search and download lyrics**. It runs as a background job (see Jobs), skips tracks that already have lyrics and changes nothing else. When it ends, a notice says how many lyrics were saved, how many tracks LRCLIB has none for, how many albums already had lyrics and what failed; the Jobs panel lists each album.

A music scan reads tags, then looks up MusicBrainz, then fills missing biographies and reviews, then missing covers. Artwork uses Kodi names. One-disc albums keep `discart.png`. A multi-disc album also saves `discart1.png`, `discart2.png`, and so on. The Scrape music found by a webhook scan switch (Music tab and Automation) includes Lidarr import webhooks in that scan. Saving settings stores the choice, and the saved choice overrides compose.

**Prune safety.** A scan removes items whose files are gone, with limits: a mount that would lose more than 20 % of its indexed items across all its library paths, a single path that would lose more than 20 %, or a readable path that came back empty is left alone. The limits can be turned off in Settings, General, Prune safety (a readable path with nothing in it is still always left alone). Items kept this way are marked **Not found** (albums, movies and shows). Filter on it (music: the filter menu; movies and TV: the quick filter) and use the normal remove action, or the **Remove all not found** button under the library list, to drop them from the database. The mark clears when a later scan finds the item again. Items under a path that is no longer listed in Settings for that media type are removed at the end of a full scan. No file is ever touched.

Right-click an artist or an album for the music jobs: match, rename, write tags, write `album.nfo`, artwork, lyrics, ReplayGain, gap check, cue split, duplicate scan, and upgrade. Applying matches, treating as compilations, ReplayGain, Audit audio, Check missing tracks and Find metadata for several artists run as one **Album batch** job in the Jobs panel, with progress, a log line per album and a Stop button; an album that fails is logged and the rest go on, and the list refreshes the touched artists when it ends. An album page shows the label and catalog number when they are known. A leading The, A, or An is left out of the artist sort unless that option is turned off. Move an artist the same way as a movie: the folder is copied, artist, album, track, and artwork paths are rewritten, and the original is removed after the sizes match.

The synced-lyrics editor (pencil in the player bar) has Shift all (±100 ms, ±1 s or a typed amount), anchors set at the playhead with a Linear, Piecewise or Steps fit previewed while the song plays, Undo, text editing (Enter), Find, *Restore previous save* (the replaced file is kept as `.lrc.sync-backup`) and *Sync OK*, which saves and marks the lyrics Synced.

**The music list is a table.** A title bar sits over the artists and albums, with a master box that ticks every album on screen
(a dash means some are ticked). Click a column name to sort: the albums inside each artist are sorted, and the artists follow
their best album (the lowest value when the order rises, the highest when it falls), with rows that have no value always last.
The arrow beside a name filters on that column; tick one or more values (several in one column are "any of", different columns
are "all of"). Filtered columns are marked, and Clear filters clears them too. Drag a column edge to resize it, drag a name to
move it, and use **Columns** (above the list) to choose what shows. The columns are: Status (the pills that used to sit at the
end of the row), Year, Type, Edition, Tracks, Length, **Format**, **Quality** (for example `FLAC 24/96` or `MP3 320`; it sorts by
the same rank that decides Upgrade available), **Bits**, **Sample rate**, **Bitrate**, Match, Country, Label, Catalog no.,
Release status, Added, Modified, Processed, Cover, NFO and Path. The audio columns come from the tracks: the weakest track gives the
bit depth and sample rate, the bitrate is the average, and an album with several formats shows them all (`FLAC/MP3`) and is
found under each one in the filter. An artist row shows totals where they mean something (tracks, length, formats, dates).
Albums scanned before these columns existed are filled in a little after start, with no rescan, and any album still blank when the list
loads is filled right then, so the audio columns are never empty. Added, Processed and Edition
still follow their switches under Settings, UI Elements. In the poster grid there is no title bar.

Column choices, column order and widths, pane widths, sorting, density and theme are saved in `ui_state.json` in the config folder, so they survive a rebuild and are the same in every browser.

When an app sees paths that differ from Curator's (for example `/data/movies` and `/movies`), add a
row under Settings, General, Remote path mappings. The longest matching prefix wins, and a row for
a single app wins over an "Any" row.

Events wait in a queue. Every new event restarts the debounce timer (`CMM_DEBOUNCE_MINUTES`,
default 20), but the queue is never held back longer than the max postpone time
(`CMM_MAX_POSTPONE_MINUTES`, default 120). Both can be changed on the Automation tab. Then Curator scans
only the affected folders, scrapes the new items when that is turned on, and tells the media
servers. If a music, movie, or TV library scan is already running when that wait ends, the scan pauses at its next checkpoint, the import batch runs, and then the scan continues. The scan shows "Paused for queued imports". A Radarr, Sonarr, Bazarr, or Lidarr search does not wait for a library scan. A Lidarr search waits only for another Lidarr search, and that wait is listed under Jobs. The queue pill in the header shows a live countdown (e.g. `45s` or `2m`) when items are queued and not yet running. Click it to see the waiting items and recent
events, or to flush or clear the queue. While a batch runs, the Queue window and the Jobs drawer show how far it is
(`3/12`, "3 of 12 done, this stage 4 of 30 read, 5 more waiting"); albums count one by one, movie and show folders once
their library folder's scan, scrape and file jobs are done. The queue is kept in the database, so a restart does not
lose it. The lists keep your place: a redraw puts the row at the top of your view back where it was, so new calls do not push what you are reading away (at the top of the list they appear as before). **Recent webhooks** keeps each call as it arrived: **Show call** opens the JSON body the app sent, with Copy,
which helps when a call is ignored or not recognised. Calls without a movie, series or artist block (Lidarr's
DownloadFailure and ImportFailure, Health and ApplicationUpdate) are named after the app that sent them.

### Split episodes

Multi-episode MKV files can be split into individual episode files from the TV episode info pane. Open a show, right-click an episode that spans multiple episodes, and choose **Split episodes…**. The modal shows the detected cut points.

When the file has exactly one episode plan, a video player appears above the cut-point list. The player streams the file directly from Curator (`/api/v1/tv/episodes/{id}/stream`, with HTTP range support so seeking works). Focus any cut-point time field and click **Mark current time** to paste the player's current position into that field. When you close the modal the video stream is released automatically.

Clicking an episode in the list, or changing its time, moves the player to that cut. Detection places the cut on the first frame of the black picture by default; change it with **Cut on the black picture at** in the Split episodes settings.

**Restore original** undoes a previous split by re-joining the episode rows back onto the original source file.

With **After splitting, send library update to the players** on (Settings, Video, TV shows tab; off by default), a split tells the players to update, and Kodi also drops any old entry whose file is gone.

### Kodi, Jellyfin, and Plex

On the Integrations tab:

- **Kodi library updates** go to one Kodi (or a shared-database master), set with
  `KODI_LIBRARY_HOST` or `KODI_HOST`. Video and music have their own wait timers (default 60 and
  300 seconds), and each new change restarts its timer. That wait is separate from the webhook
  debounce. After deletes, upgrades and renames, Curator can also run a library clean (Kodi video). It runs once after the queue is empty, also after Curator itself deletes items from disk, removes a replaced original (Profile 8 remux), deletes a split source, moves a folder, or finds files gone in a scan. A clean Kodi refuses is tried once more and then shows as failed in the activity log.

#### Kodi path mappings

Kodi's library scan takes a folder, not a TMDB id or an IMDb id. Those ids are how Kodi matches a file it has already found. A new movie or episode is picked up only when Kodi scans the folder that holds it. Curator already knows that folder: the movie folder for a movie, and the show folder for an episode. Kodi has to be given that folder in the path text *Kodi* uses.

Curator sees a container path such as `/media/TV/Show Name`. Kodi sees the same files as a source path such as `nfs://192.168.1.20/Media/TV/Show Name/`. Settings, Integrations, **Kodi paths** translates one into the other. The longest matching Curator prefix wins. One row per share is enough when several libraries sit on the same export. A movie under `/media/4K Movies/Title` and a show under `/media/TV/Show` are both covered by Curator path `/media` and Kodi path `nfs://192.168.1.20/Media`.

If any folder in a batch has no matching row, that update scans Kodi's whole video library.

**Read the paths from Kodi's `sources.xml`:**

1. On the Kodi machine, open the userdata folder.
   - Windows: `%APPDATA%\Kodi\userdata\sources.xml`
   - Linux: `~/.kodi/userdata/sources.xml`
   - LibreELEC and CoreELEC: `/storage/.kodi/userdata/sources.xml`
   - Android: `Android/data/org.xbmc.kodi/files/.kodi/userdata/sources.xml`
2. In the `<video>` section, each `<source>` has a `<name>` and a `<path>`. Copy the `<path>` text, not the name. `nfs://192.168.1.20/Media/TV/` is the path. `TV` is only the label.
3. Drop the last library folder when several sources share one export. `nfs://192.168.1.20/Media/TV/` and `nfs://192.168.1.20/Media/Movies/` both start with `nfs://192.168.1.20/Media`. Use that shorter prefix as the Kodi path, and the container mount of that same export as the Curator path (`/media` when that export is mounted at `/media`).
4. Add one row for each export Curator mounts. Examples:

   | Curator path | Kodi path |
   |---|---|
   | `/media` | `nfs://192.168.1.20/Media` |
   | `/nas1/Media` | `nfs://192.168.1.21/Media` |
   | `/nas2/Media` | `nfs://192.168.1.22/Media` |
   | `/nas2/Media2` | `nfs://192.168.1.22/Media2` |

5. Save settings. The next movie update scans `nfs://…/Movies/Movie Folder/`. The next episode update scans `nfs://…/TV/Show Name/`.

A Curator library folder that is not inside any Kodi source, such as a folder Kodi was never given, still cannot be scanned on its own. Leave the Kodi path as Kodi wrote it, including spaces. Curator adds the trailing slash Kodi expects.

- **Kodi notifications** show an on-screen message on `KODI_HOST`.
- **Emby** (`EMBY_URL`, `EMBY_API_KEY`), **Jellyfin** (`JELLYFIN_URL`, `JELLYFIN_API_KEY`), **Plex** (`PLEX_URL`, `PLEX_TOKEN`), and **Navidrome** refresh from Settings, Integrations. Emby, Plex, and Navidrome each have an **Enable** switch. Off keeps the saved library choices and stops library updates. Emby also stops on-screen messages. The webhook queue hands the folders to a library-update queue and does not wait. Each player has its own worker, so a hung scan does not hold the others. With no path row, each player gets one full scan per media type (Kodi uses one video scan for movies and TV). With path rows, only the changed folders are scanned. One folder in the batch with no matching row makes that player's update a full scan. **Send library update** on a movie or show queues the chosen players for that title. For Kodi it also removes that title's entries whose file is gone (an old copy after an upgrade or rename), but only when the library folder that should hold the file is mounted and readable. While Kodi works through a job of several folders, the Library updates banner and the running row say which folder it is on, how many are done and how long the current one has taken, the tab's pill counts the folders still to do, and Recent webhooks gets a row for each finished folder with its time. The running queue and Recent library updates name the movie or show, with the folder under the title, followed by the same colored quality badges as the info panel: resolution, HDR, source, codecs, audio channels, bit depth and container for a movie or episode, and format, bit depth, sample rate and bitrate for an album. An item that has not been probed, or a whole artist or show, has no badges. A music update with no folder list says that no folder was included. The job leaves the queue when that player reports the scan finished.

Each target has a **Test** button. A failed call to Trakt, Radarr, Sonarr, Lidarr, Bazarr, Kodi, Emby, Jellyfin, Plex, Navidrome, TMDB, TheTVDB, OMDb, Fanart.tv, Last.fm, MusicBrainz, or another mapped host raises an alert and shows **Connection error** under that integration in Settings. The same message is kept until it changes. A later successful call clears it.

## Sync

The **Sync** tab in Settings consolidates all scheduled and external-sync settings:

- **Library scan schedules** for music, movies, and TV are moved here from the General tab.
- **Trakt** connection and sync options (previously under Integrations) are here.
- **Player clean schedules** let you run a Kodi library clean (or a full refresh scan for Emby, Jellyfin, or Plex) on a cron schedule, per media type. Pick the player, the media (video or music), set a cron expression, and save. Each entry fires in a background thread that wakes every 15 seconds; a gap longer than two hours is recovered by checking the missed minutes.

### Player watched sync

**Player watched sync** copies play counts, last-played times and resume points between the library and Kodi,
Jellyfin, Emby and Plex. Items are matched by file path through each player's path rows. The higher play count and
the later time win, so nothing is marked unwatched (unless Spread unwatching is on, below); a resume point one side
lacks is copied over. Plex is marked watched or unwatched and given a resume point, but keeps no play count above one. Jellyfin and Emby use the user named here, or the first administrator.
**Put the watched state back after Curator refreshes an item in Kodi** restores play count, last played and resume
point when a Kodi refresh drops them.

Three options widen it. **Spread unwatching** (off by default) remembers what each player said at the last sync, so
marking something unwatched in a player (or in Curator) is copied to the other side instead of being undone; with it
off the higher count still wins. **Music play counts** adds tracks (Kodi, Jellyfin, Emby and Plex; Navidrome has no
play-count sync). **Users** takes several names for Jellyfin and Emby, one pass per user. Plex stays single-user.

### Collections

Movie sets with two or more movies and saved filters with a tag can be pushed to Jellyfin, Emby and Plex as
collections, now or after every scan. Curator keeps the members of the collections it made (or found by name) in step
and leaves other collections alone.

## Trakt

Curator signs in with a device code. You approve it at <https://trakt.tv/activate>, and Curator collects the token from Trakt. Nothing has to connect back to Curator, so a local address behind a router works. A device-code connection has no redirect URL. Token refresh sends `redirect_uri` only when that value is an `http` or `https` address with a host.

A free Trakt account can have two connected apps. If Curator is already listed, reuse that app's client ID. Creating a third app is refused until one of the two is removed.

**Create the Trakt app and copy the client ID:**

1. Sign in at <https://trakt.tv>.
2. Open <https://trakt.tv/oauth/applications>.
3. If a Curator app is already there, open it and skip to step 5.
4. Choose **New application**.
   - Name: `Curator`.
   - Description: anything short, such as `Home media library`.
   - Redirect URI: Trakt's form requires an `https://` address. Curator never opens it. Use an https address you control. A local `http://192.168.x.x` address is rejected by Trakt and is not needed.
   - Save the application.
5. On the app page, copy the **Client ID**. A new Trakt app shows **Client secret: Not issued**. Curator does not ask for a secret. Leave `TRAKT_CLIENT_SECRET` empty.
6. In Curator, open Settings, Sync, Trakt. Paste the client ID and save. Or set `TRAKT_CLIENT_ID` in `.env` and recreate the container.

**Connect:**

1. Press **Connect with Trakt**. Curator opens <https://trakt.tv/activate> in a new tab and shows a code.
2. Copy the code with the clipboard button next to it. The page is served over http, so the button copies it directly.
3. Enter the code on the Trakt page and allow Curator.
4. Curator polls Trakt and then shows the connected account. If the code expires, press Connect again and use the new code. Tokens are stored in `config/trakt.json`. Curator refreshes them when it calls Trakt within a day of their expiry.

**Sync watched history** with **Sync now** beside Connect, or the Trakt button beside Queue in the Jobs popup. The same sync also runs every few hours. It matches movies by TMDB or IMDb id, and episodes by show id with season and episode number. Both sides keep the higher play count and the later last-played time, and nothing is ever marked unwatched. Pull only, push only, or both ways can be picked. Changed items get `<playcount>` and `<lastplayed>` written to their `.nfo` when .nfo writing is on; locked items keep their files.

## Recycle bin

Delete from disk moves what it deletes (movies, episodes, sets, albums, artists, extra episode copies, replaced
tracks, duplicate subtitles) into a hidden `.curator-trash` folder at the top of the library folder it was in. That
keeps it on the same drive, so a large file moves at once instead of being copied. **Settings, General, Recycle bin**
turns it on or off (on by default) and sets how long items are kept (30 days by default, up to 365). **Open recycle
bin** lists every item with its original path, size, the day it was deleted and the day it goes for good.
**Restore** puts an item back where it was (not when something else is there now) and scans it back into the library. **Delete now** and **Empty recycle bin** delete for good. Expired items are deleted
at startup, every 6 hours and when the bin is opened.

Scans skip the bin, and marker files (`.nomedia`, `.ignore`, `.plexignore`) keep Kodi, Jellyfin, Emby and Plex out of
it. When the bin is off, or a file sits outside every library folder, Delete from disk deletes at once.

## Backup and restore

Settings, Backup lists the `.dump` files in the backup folder. **Restore…** warns that the current
database will be deleted first. The Restore button only appears after you type `RESTORE` in capital
letters. Curator first saves the current database as `before-restore-<time>.dump`, then replaces it,
and puts the saved copy back if the restore fails. Scans, scrapes, webhooks, and file jobs wait until
it is done, then the page reloads.

### Snapshot before large writes

Settings → Backup has an option to dump the database before removing, deleting, batch editing or running a file job
on 5 or more items. The dump is named `before-bulk-<time>.dump`, goes to the backup folder, and only the last 2 are
kept (each is about the size of the database). It is off by default and appears in the restore list as a safety dump.

## Notifications to other apps

Settings → Notifications → "Send notifications to other apps" sends Curator's events to Discord, Slack, Telegram,
Pushover, ntfy, Gotify, an Apprise API server or any webhook. Events: scan finished or failed, import processed,
job failed, a scrape that failed or could not scrape some items (the first five named; a scrape a webhook import started is reported as the import instead), backup finished or failed, a corrupt file, a drive low on space, an import with a failed step, and OpenSubtitles quota nearly used. Scan finished and failed cover music, movies, TV and music videos. A generic webhook receives JSON with
`app`, `event`, `title`, `message`, `level` and `time`. Use Send test on a target to check it.

**Added to the library** is a daily or weekly list of what came in: the movies, the episodes grouped per show, the
albums and the music videos added since the last message (up to 15 names per kind). Set how often and at which hour
under the targets (never by default), and tick the event on the targets that should get it. **Preview** shows the
message as it would go out now; **Send now** sends it at once. When nothing was added, nothing is sent.

## Poster grid

The grid button switches a library between list and poster grid. In grid mode the S / M / L buttons set the card
size (the choice is kept in the browser). Only the visible cards are drawn, so large libraries stay fast.
Cards in the Movies, TV Shows and Movie sets grids are sized by their poster (2:3), so the number of columns follows the window width and the card size.
Tick the box in a card's corner to select it. With one or more cards ticked, the batch footer slides up with the same
buttons as the list view. The footer stays one row tall: Scrape, Rescan, Clear and a red bin are always in the row (the bin opens the same window as **Remove…**, where you choose between removing from the library and deleting from disk), and the rest sit in three menus, **Metadata** (edit, update ratings, artwork, .nfo, rename), **Media** (subtitles, trailers, thumbnails, theme songs, split episodes) and **Organize** (lock, processed, move). It slides over the status pane as far as the Scan engine button. On TV Shows the footer also lists what is ticked (shows, seasons, episodes) with a box for each kind: untick a kind and the buttons leave it alone, and the count reads *in scope / ticked*, for example *40 / 260 items*. Artwork then runs per kind, so artwork for seasons only does not touch the shows or episodes. **All** and **None** in the toolbar tick or clear
every card. In the list view, the box in the title bar ticks every row on screen. On TV Shows the seasons and episodes of
the ticked shows are ticked too, from one request to the server, so it is quick even for a large library. With a filter on (for example *No IMDb rating*) only the episodes that match the filter and are on disk are ticked, and only the seasons that hold one. Ticking the box again, or **All** / **None**, undoes it.

## Poster badges and artwork

Click a poster, album cover or artist thumbnail to enlarge it. Hover it and use the Swap bar to look up other
artwork. Standard badges (resolution, HDR, audio, counts, format) sit on the poster's top-left corner and can be
switched off per media type under UI Elements in Settings. The resolution badge stays in the bottom-right corner.

Each current artwork image has a red trash button in the artwork lookup and in the info pane's Artwork section. It
asks first, then deletes the image file.

## File health warnings

Besides "Probe failed", files that read fine but look wrong get a warning pill in the Status column: empty file,
no video stream, no audio, only unknown-language audio, or a length under half the listed runtime. Use the
"Health warnings" ribbon on Movies and TV to list them. Disc images are not checked.

**Check integrity** (right-click, or the Media menu of the selection) decodes the first and last minute of each file
with ffmpeg; **Full integrity check** decodes the whole file. A decode error gives the file a red **Corrupt** pill and
puts it under the **Corrupt** filter. Replacing the file clears the result. Settings, Files can also run a quick check after each import (with a notification, and optionally a new search in the app) and a full check of some files each day.

For music, **Audit audio** (right-click albums) tests each FLAC file against its stored checksum and decodes other formats with ffmpeg. An album with a track that fails gets a red **Corrupt** pill and is listed under **Corrupt files** in the music filter menu; the track shows Corrupt in the album. A newly found corrupt file is recorded in Activity history and sends the *corrupt file* notification. Replacing the file clears its result.

## Music videos

Give a folder the media type **Music videos** under Settings, General. The **Music videos** tab (beside Movies, TV and Music) lists them: **Scan** reads new and changed files, **Full scan** reads every file. Artist, title, album and year
come from a Kodi `<musicvideo>` .nfo beside the file, else from the file name (`Artist - Title (Year)`, or the parent
folder as the artist). Each file is probed for the same quality badges as movies, a missing .nfo is written, and Kodi
gets a video library update. **Edit** changes the fields and rewrites the .nfo, and takes a picture from the video. **Remove or delete…** offers Remove from library (the file stays, and the next scan adds it back) or Delete from disk, which takes the video with its .nfo and pictures to the recycle bin under the same guards as a movie (the Music videos folder mounted and writable); Restore brings them back together. **Look up blanks** fills a blank album, genre or plot from TheAudioDB. Watched sync covers music videos in Kodi, Jellyfin and Emby. Music videos are a library tab beside Movies and TV, with filters, Duplicate and Upgrade available pills (the movie rules: the same release is a duplicate, a weaker copy of the same artist and title gets Upgrade), a Corrupt pill, **Quick integrity check** and **Full integrity check** (the same damage check as movies), and the bulk duplicate cleanup and recycle bin cover them. Kodi needs that folder as a source with the content type Music videos.


**+ Add from YouTube** searches YouTube, lets you pick a result, and downloads it as `Artist - Title (Year)`. The button is
off until a Music videos folder is set. The artist guessed from the video's title is linked to an artist you already have
(the Artist box suggests them as you type), and the form says which folder the file will be saved in before you
download. Settings, General, **Music videos from YouTube** sets the folder rule: the artist's folder, made when it is
missing; the artist's folder only when it exists; or the top of the Music videos folder. An artist's folder is found
whatever its spelling. The `.nfo` is a Kodi `<musicvideo>` file beside the video, with the same name.

## Keyboard and small screens

Ctrl+K opens the command palette, `?` the shortcuts sheet, `/` focuses the filter, Alt+1 to Alt+5 switch library (Music, Movies, Movie sets, TV shows, Music videos),
Ctrl+A selects all visible rows and Esc closes the top window. Below 800 px wide the Music view shows one pane at a
time, chosen with the Library, Albums and Details tabs.

## Development

The tests use the standard library runner:

```sh
cd app
python -m unittest discover -s ../tests
```

### Running the tests

```
pip install -r app/requirements.txt -r requirements-dev.txt
python -m pytest
```

Python 3.11 or newer is needed (some tests use `enterContext`). A few older tests are known to be out of date
(DV profile 8 hybrid probe, Trakt authorize URL, discography owned count, some export and scan-log tests).

## Versioning

The number beside the logo (for example v1.0.0) is read from `app/VERSION`. Every update bumps the last digit, and a digit
that passes 9 rolls over into the one before it: 1.0.9 is followed by 1.1.0, and 1.9.9 by 2.0.0. Each entry in
`changelog.md` names the version it shipped in. Browsers still pick up changed files straight away, because every
static file is cache-busted by its own content hash. `APP_VERSION` in docker-compose is no longer shown.
