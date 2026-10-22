# Changelog

## v1.7.2 — 2026-10-22 — An upgrade now cleans the old file out of Kodi, and a rescan stops saying "Removing"

- **Upgrades leave no stale entry in Kodi.** When Radarr or Sonarr replaces a file with a better one, the delete of
  the old file is ignored on purpose (the import that follows covers it), and that import was queued as a plain
  update. Kodi was told to scan the folder but never to clean, so it kept the old file's entry next to the new one
  until a clean happened for some other reason. An import that Radarr or Sonarr marks as an upgrade (`isUpgrade`, or
  a list of deleted files) now asks for the same once-after-the-queue Kodi clean that a delete does. The notice still
  reads "Updated: ..." rather than "Removed: ...". It follows the existing option "Clean the Kodi video library once,
  after the whole update queue has finished" under Settings, Automation, and does nothing when that is off. Renames
  are unchanged.
- **Curator's own library needed no change.** An upgraded movie is matched to its row by folder and an upgraded
  episode by season and episode, so the row is updated to the new file rather than left behind or doubled.
- **The rescan step is no longer called "Removing".** A rescan of one movie, show, or a whole library always ends with
  a check for files that have gone, because that check is how a deleted or renamed file is dropped from the library.
  It only touches database rows (never files) and costs a moment. It now reads "Checking for movies that are gone" /
  "Checking for episodes that are gone". A "Removed N ..." line appears in the log only when something was removed.

## v1.7.1 — 2026-10-22 — Adds say which service they go to, and show in Jobs

- Picking a result in **+ Movie** now says "Sending to Radarr…" in the task bar, and **+ Show** says "Sending to
  Sonarr…". Both used to say "Sending to Radarr or Sonarr…".
- An add now appears in the **Jobs** panel while Radarr or Sonarr is working (ARR group: "Add to Radarr" or "Add to
  Sonarr", with the title). Before, only the task bar showed that something was running and Jobs said nothing was.
  The panel is asked to refresh half a second after you pick a result, so a short add is still caught. A refused add
  ends the job as failed with the reason, the same as other jobs, so it can also trigger the "A background job failed"
  notification if you have that switched on.

## v1.7.0 — 2026-10-22 — + Movie and + Show, and the poster grid works again

- **+ Movie** and **+ Show** buttons sit next to the sort menu on Movies and TV Shows (**+ Set** on Movie sets, which
  makes a set as before). They replace the unlabelled "+" in the toolbar. The window searches TMDB (or TheTVDB for
  shows), and picking a result asks Radarr or Sonarr to add it.
- New tick box in that window: **Ask Radarr to search for the movie now** (Sonarr: **for the missing episodes now**).
  It starts on or off to match Start a search right away under Settings, Integrations, and applies to that one add.
  The toast says whether a search was started. Before this, Radarr and Sonarr always followed the setting and the
  window had no say.
- The window now tells you at the top when Radarr or Sonarr is turned off or has no address and API key, instead of
  failing after you pick a title.
- **Poster grid fixed for Movies, TV Shows and Movie sets.** Every poster card also carried the class of a list row,
  which pins a row to 30 px and stacks rows on top of each other. In the S, M and L sizes the cards showed as thin
  strips or a single card with no poster. Music was not affected because it uses a different card. A test now fails if
  a grid card gets a list-row class again.

## v1.6.5 — 2026-10-22 — The scrape window keeps its Start button in view

- The movie, TV and movie set scrape window has a footer row that stays at the bottom: the progress bar, the status
  line and the **Start scrape** button (**Stop scrape** while it runs). Only the options and the log scroll, so there
  is no scrolling past every source and artwork choice to reach the button, and the progress stays in view after you
  press it. A long error message in the status line scrolls inside the footer instead of pushing the button away.
- The footer is a general building block (`.modal-footer`) that other long windows can use.

## v1.6.4 — 2026-10-22 — Update yt-dlp from the About window

- **About** (click the Curator name) has an **Update yt-dlp** button on the yt-dlp row, so a stale yt-dlp no longer
  needs an image rebuild. It downloads the newest release from GitHub, checks it against the SHA-256 list published
  with that release, runs it once to prove it starts, and only then puts it in `cache/bin/`. A download that does not
  match, or does not start, is thrown away and the working copy is left alone.
- Curator runs whichever of the updated copy and the image's yt-dlp is newer, for trailers and theme songs. Purging the
  cache folder removes the updated copy and the image's is used again.
- The yt-dlp row shows the version, how many days old it is, and (after asking GitHub when the window opens, at most
  once every six hours, nothing sent from your install) whether a newer release exists. If GitHub cannot be reached
  it says so and the rest of the window works as before.
- The Health list in About has a yt-dlp line: a warning when the version is over four months old, otherwise OK.
  This check is local and makes no request.
- A failed trailer or theme song download that blames an old yt-dlp now points at the Update yt-dlp button as well as
  the image rebuild.

## v1.6.3 — 2026-10-22 — Missing trailer and Missing theme song filters

- The filter menus on Movies and TV shows have two new presets, **Missing trailer** and **Missing theme song**. They
  list items that have no trailer or theme file in their folder, which is different from **No trailer** (no scraped
  link and no file). On TV, Missing trailer also lists seasons without a season trailer; Missing theme song applies to
  shows.
- Curator now remembers per movie and show whether those files exist, so the filters are instant on a large library.
  The flags are updated at the end of every scan, after a trailer or theme song download, after a rename, extras or
  move job, and once when the app starts for anything not checked yet. A file added by hand shows up after the next
  scan. An item whose folder cannot be reached, or that has not been checked yet, is left out rather than reported
  as missing.
- Both presets can be saved in a saved filter, and a scan tags the movies and shows they match. The disk check runs
  before that tagging, so the tags reflect the folder as the scan left it.

## v1.6.2 — 2026-10-22 — Theme song and trailer downloads: a current yt-dlp, and a clearer failure

- Theme song and trailer downloads failed with "The page needs to be reloaded". The image had a yt-dlp from March 2025
  built in, and YouTube has changed since. The image now downloads the newest yt-dlp when it is built (its own layer,
  so `docker compose build --build-arg YTDLP_REFRESH=$(date +%s)` refreshes just that; `YTDLP_VERSION` fixes a
  release), and includes Deno, the JavaScript runtime that yt-dlp has needed for YouTube since 2025.11.12. **Rebuild the
  image for this to take effect.**
- A failed download now says which yt-dlp it was and, when it is more than four months old, that it is probably the
  cause and that the image should be rebuilt.
- The file job log no longer prints the title twice ("The 'Burbs (2026): The 'Burbs (2026): ...").

## v1.6.1 — 2026-10-22 — Buttons that did nothing: trailer player, subtitle search, pending matches

- The pop-out trailer player can be closed and resized again. Its Close, Large/Compact and PiP buttons were named in a
  way the click router never sent anywhere, so pressing them did nothing.
- Three more buttons had the same fault and work again: Search and Download in the subtitle finder (OpenSubtitles), and
  the Remove button on a row in the pending matches list ("leave this one out of Apply all").
- A new test reads every fixed button name in the page and the scripts and fails when one has no handler, so this
  cannot happen unnoticed again.

## v1.6.0 — 2026-10-22 — The media info file is listed with the other files

- A movie's Files section now has a Media info row under the Folder and NFO rows, and an episode has the same row
  under NFO. It shows the `<video name>.cmm_mediainfo.xml` file Curator keeps next to the video, with the same
  mount name and path styling as the others, or "None" when there is no such file (for example when writing these
  files is switched off with `CMM_WRITE_SIDECARS=0`).

## v1.5.9 — 2026-10-22 — The open movie or episode refreshes when a scan finishes

- When a scan finishes, the movie or episode you have open is read again in place, with its scroll position kept.
  Before, only the library list was reloaded, so a subtitle found or fixed by the scan (for example an `nb` file that
  was unknown) did not show until you opened another item and came back. This covers a Rescan from the item itself
  and any scan that finishes while the item is open.
- It waits if you are typing in a field of the open pane, and a scan that is still running never reloads it.

## v1.5.8 — 2026-10-22 — Nynorsk is its own language

- Norwegian Nynorsk (`nn`, `nno`, `nn-NO`, Nynorsk) is no longer folded into Norwegian. It is its own language,
  code `nno`, and has its own entry in the language lists. Bokmål (`nb`, `nob`, `nb-NO`, Bokmål) stays with Norwegian
  (`nor`), as before. This corrects v1.5.7, which had put both under Norwegian.
- `Movie.nn.srt` is now listed as Nynorsk and Normalize subtitles names it `Movie.nno.srt` (`Movie.nn.srt` with
  two-letter codes). `Movie.nor.nb.srt` still becomes `Movie.nor.srt`, but a Bokmål tag next to a Nynorsk one is kept,
  because they are different languages.
- Wanting `nn` in the OpenSubtitles languages now searches for Nynorsk instead of Norwegian. OCR of picture subtitles
  still reads Nynorsk with the Norwegian model, because that is the only one tesseract has.
- Files read before this version keep their old language until they are scanned again.

## v1.5.7 — 2026-10-22 — Norwegian Bokmål and Nynorsk subtitles

- `nb`, `nn`, `nb-NO`, `nn-NO`, `no-NO`, Bokmål, Nynorsk and Norsk are now read as Norwegian, the same as `no`, `nor`,
  `nob` and `nno`. Before, `Movie.nb.srt` and `Movie.nn.srt` had no language at all, and a Bokmål audio or subtitle
  track marked `nb` inside a file was kept apart from Norwegian.
- A language tag written twice, such as `Movie.nor.nb.srt` or `Movie.en.eng.srt`, is now one language. Normalize
  subtitles renames it to `Movie.nor.srt`. Before, the second tag was kept as an unknown extra word, so the name never
  looked right. If `Movie.nor.srt` already exists, the other file is kept and the log says so; identical copies are
  caught by the duplicate check.
- Subtitle files already in the library keep the language they were scanned with. Run a full scan, or run Normalize
  subtitles on the item, to pick up the change.

## v1.5.6 — 2026-10-22 — Languages that MediaInfo missed are taken from ffprobe

- When MediaInfo lists a track but gives it no language (or "und"), and ffprobe read a real language for the same
  track, the probe now keeps ffprobe's. This applies to audio and subtitle tracks and needs both tools to list the same
  number of tracks. It matters most for Blu-ray images, where the playlist names the languages and a MediaInfo scan
  of the image may not. Before, ffprobe's languages were only used when MediaInfo found no tracks at all.
- Files are read again when they are scanned or when you use Update media info, so a file already flagged as
  Unknown audio language is corrected the next time it is read.

## v1.5.5 — 2026-10-22 — Confirm a language change, and the list is always visible

- Changing a language now opens a window titled "Confirm language change" with Confirm and Cancel. It names the track
  or subtitle file, the language it has now and the one you picked, and nothing is written until you press Confirm.
  This covers the Set button on embedded audio and subtitle tracks, and the subtitle editor when its language
  changes. Saving only the Forced, SDH or HI boxes of a subtitle does not ask.
- Embedded audio and subtitle tracks show the language list on every file. On an MKV it works; on any other
  container (MP4 and so on) it is greyed out with the reason on hover, and the note above the tables says the file has
  to be remuxed to MKV first. Before, those rows showed no list at all, which looked like a missing feature.

## v1.5.4 — 2026-10-22 — Language lists for embedded and subtitle tracks

- Languages are picked from a list everywhere now, never typed. The subtitle editor under Subtitles, which had a
  free-text box, uses the same list as the tracks (36 languages). Its list starts on the subtitle's current language,
  and the Save button asks you to choose one before it renames the file.
- Embedded subtitle tracks of an MKV have a language list and a Set button, the same as audio tracks, written into the
  file in place with mkvpropedit. This is where an embedded subtitle that shows as unknown can be fixed.
- The explanation above the track tables now says what applies to the file. On an MKV it describes the Default and
  Language buttons; on any other container (MP4 and so on) it says plainly that only MKV tracks can be changed in place
  and that the file has to be remuxed to MKV first, instead of leaving the buttons out without a word.
- Saving the flags of a Brazilian Portuguese or Traditional Chinese subtitle no longer drops its region from the name.

## v1.5.3 — 2026-10-22 — Filters for unknown audio and subtitle languages

- The filter menu for movies and TV shows has two new entries, Unknown audio language and Unknown subtitle language.
  They match any file with at least one such track: no language, or one that says nothing (und, zxx, mul).
  Subtitles count embedded and external ones. For shows and seasons they look at the loaded episodes, the same as
  Multi-audio does.

## v1.5.2 — 2026-10-22 — Set the language of an audio track

- The Audio table in a movie's or episode's media info has a language list and a Set button on every MKV audio track.
  It writes the language into the file with mkvpropedit, in place and in seconds, then reads the file again, so a
  file flagged "Unknown audio language" can be fixed from the app. Other containers (MP4 and so on) cannot be
  changed this way and need a remux.

## v1.5.1 — 2026-10-21 — The library list stays put when artwork is saved

- Choosing, uploading or deleting artwork in the artwork windows now holds the library list where you scrolled it.
  Before, saving artwork on a movie set could send the list back to the top. Video items (movies, shows, seasons,
  episodes, sets) and music (albums and artists) all use the same protection now.

## v1.5.0 — 2026-10-21 — No broken picture when there is no current artwork

- In the artwork compare view (music, movies, TV shows, sets), a missing or unreadable current image now shows as a
  dark half labelled "No artwork set" and the slider keeps working, instead of a broken picture. This happens when an
  item has no artwork of that type, or when the file it points to is gone.

## v1.4.9 — 2026-10-21 — Cover and poster icons in the command palette

- The command palette (Ctrl+K) shows a small cover or poster beside albums, movies, TV shows and movie sets. The
  pictures are the cached smaller copies and load as you scroll. A result with no picture looks as before.

## v1.4.8 — 2026-10-21 — Lighter artwork searches, cache purge, missing logos

- Artwork searches no longer download every option. For each candidate the first 128 KB are read, which holds the
  image size, and the server reports the file size. The whole image is downloaded later, when its card picture
  is shown (cards now load as you scroll), or when you compare or choose it. If the size cannot be read from the
  start of a file, it is downloaded whole as before.
- A cached option is checked against the size the provider reports now, so an image replaced at the same address
  is fetched again instead of showing the old one.
- Settings → Files → Purge folders also shows the size of the cache, per folder, and can purge it.
- Settings → Files has a new section, Missing logos: networks (TV) or studios (movies) with no logo, busiest first,
  each with an Upload logo button. The logo is saved under the name in `data/brands/network` or `studios`, used
  at once, and wins over a shipped logo with the same file name. Logos in the data folder are included in backups of it.
- Removed the `config_dir` aliases from `cache_store.py`, `preview_proxy.py` and `sub_ocr.py`.

## v1.4.7 — 2026-10-21 — The compare view starts from the full current image

- Opening the video artwork window from the poster on an item compared against the small cached copy shown on the
  info pane. It now starts from the original, like the candidate.

## v1.4.6 — 2026-10-21 — Backups are named curator-…

- Backup now writes `curator-<date>-<time>.dump` instead of `resonance-…`. Old `resonance-…` dumps still show in
  the restore list and are pruned together with the new ones, oldest first.

## v1.4.5 — 2026-10-21 — Artwork comparison finds its image again

- Fixed the compare view in the video artwork window showing "not found" for online candidates: v1.4.0 cut the
  address of a TMDB or Fanart.tv image down to its path. Addresses on other sites are now left as they are, and the
  compare view loads the original image instead of the small preview.

## v1.4.4 — 2026-10-21 — Movies and TV keep uploaded and replaced artwork too

- Movies, shows, seasons, episodes and sets now do what music does. An image you upload, and the image a new
  choice or upload is about to overwrite, is copied to `data/artwork/additional/movie`, `tv` or `sets`.
  The artwork picker lists them again as "Uploaded" and "Replaced" options that can be chosen like any other.
  Copies of the same image are kept once.
- Music's files moved into `data/artwork/additional/music` so every media type has its own folder. Files already
  in the data folder's top level are moved there at start.
- Settings → Files → Purge folders counts and clears all of them.

## v1.4.3 — 2026-10-21 — Uploaded and replaced artwork has its own data folder

- Artwork you upload and copies kept when a file next to the music is replaced now live in `/data/artwork/additional`
  (set by `DATA_DIR`), not under `config`. Add `./data:/data` to the compose file. At start the app moves the
  files from `config/artwork/additional` there and updates the artwork options that point at them. Without a mounted
  `/data` nothing is moved, so no file ends up inside the container, and a warning is logged.
- Settings → Files has a new section, Purge folders, that shows how many files the folder holds and how
  large it is, with a Purge button. Purging removes the files and the options that used them. The artwork saved
  next to your music files is not touched.

## v1.4.2 — 2026-10-21 — Artwork options from online sources show again

- Fixed blank results in the artwork window. Since the cache moved out of the config folder, the app refused to
  read its own cached downloads, because the cache folder was not on the list of folders it may read. It is now.
  v1.4.1's partial-file protection stays.

## v1.4.1 — 2026-10-21 — Fewer blank results in the artwork window

- Artwork options are now saved to the cache under a temporary name and renamed when complete, so a card that asks
  for an image while it is still being downloaded no longer gets half a file. An empty or unreadable cached file
  is thrown away and downloaded again instead of being served as a blank image.

## v1.4.0 — 2026-10-21 — Artwork comparison uses full images

- The compare view in the artwork windows (music and video) now loads the full-size candidate and the full-size
  current image, so resolution and quality can be judged for real. The gallery cards still show the small cached
  copies. Zoom already used the originals.

## v1.3.9 — 2026-10-21 — Smaller copies for every artwork type

- The music info pane now loads cached smaller copies of the artist banner, landscape, clearlogo, fanart and
  artist thumb, and of an album's banner, landscape, clearlogo and fanart. Before, only album covers did. Zoom,
  the artwork window and the files on disk still use the originals. Video already did this for posters, banners,
  landscapes, clearlogos and fanart.

## v1.3.8 — 2026-10-21 — The artwork cache no longer grows

- Choosing a music artwork option saves the full image beside the music files, as before, and now also removes
  the downloaded original from the cache. The row then points at the saved file. If the original is ever needed
  again it is downloaded again.
- Options you never choose are removed from `cache/music` a week after they were last used, and the least
  recently used ones go when the folder passes 1 GB. The image behind a chosen option is kept. Removed options
  are downloaded again when you open or choose them. This runs after each music scan, so the existing cache
  shrinks on the next scan.
- The resized covers in `cache/music/thumbs` and `cache/video/thumbs` are trimmed the same way (60 days without
  use, or over 1 GB each).

## v1.3.7 — 2026-10-21 — Cache folders by media type

- The cache folder is now split by media type: `cache/music` has the artwork downloaded for music, with its resized
  copies in `cache/music/thumbs`. `cache/video` has `thumbs`, `preview` and `ocr`. A stack that already moved to
  the v1.3.5 layout (`cache/artwork`, `video-thumbs`, `preview`, `ocr`, `thumbs`) is tidied on the next start, and the
  paths saved for downloaded artwork are updated. Video artwork itself is saved beside the video, so it has no
  cache folder of its own.

## v1.3.6 — 2026-10-21 — Faster music covers

- Music grids, the discography list, the upgrade tools and the artwork gallery load a smaller copy of each cover
  instead of the full image. The copies are made on first use, kept in the `cache` folder, and made again when the
  image changes. The album page, the zoom and the files on disk still use the original. Cover, artwork and preview
  addresses accept `?w=` (160, 342, 500 or 780; the nearest is used), the same as the video artwork address.
- The resizing code is shared between music and video (`resonance/thumbs.py`).

## v1.3.5 — 2026-10-21 — A separate cache folder

- Removed the music setting "Keep art in the config cache". Music artwork is always saved beside the music files,
  as before by default. Nothing else changes, and an old value in `settings.json` is ignored.
- Anything Curator can rebuild now lives in its own `cache` folder (`CACHE_DIR`, mounted as `/cache`), apart from
  `config`: thumbnails, artwork downloaded from a web address, the video copies the subtitle editor plays, and
  recognised subtitle text. It can be deleted at any time.
- Artwork that cannot be fetched again stays in `config`: uploaded files and the copies kept when a file is
  replaced (`config/artwork/additional`), and the undo files (`config/undo`, outside the artwork folders because undo is not only about artwork). These used to share the
  artwork cache folder, where a cleanup could have removed them.
- On the first start the old files are moved into place and the paths saved in the database are updated. Files
  that cannot be moved are left alone and keep working. Downloaded images are only moved once `/cache` is a
  mounted volume, so they are never copied into the container.
- Add `- ./cache:/cache` and `CACHE_DIR: /cache` to your `docker-compose.yml` (both are in
  `docker-compose.yml.example`). `cache/` is also ignored by git.

## v1.3.4 — 2026-10-21 — More network icons

- Movie studios share logos by family: any Universal Pictures, Warner Bros., Walt Disney, Paramount, BBC, Nordisk
  Film or Zentropa name without a logo of its own uses the family logo. New aliases cover DC Films, Lionsgate
  Premiere, Marvel Knights, Amblin Partners, SF Studios and others.
- `GET /api/v1/brands/missing?media=movies` lists movie studios with no logo in `media/studios`, as the TV
  version does for networks.
- New ribbon "No IMDb rating" on Movies and TV shows. On TV it lists the episodes without an IMDb rating. Episode
  rows now carry their IMDb rating.
- Fixed: generating missing episode thumbnails failed with "column e.root does not exist" in the database log.
  The query now takes the root from the show, so thumbnails are generated again.
- A network now also finds a logo whose file name carries a country or quality tag: "Sky One" uses
  `sky-one-uk.png`, "MGM+" uses `mgm-plus-us.png`, "ORF 1" uses `ORF1 HD.png`. An exact name still wins, and
  when several countries fit, the UK and US come first and non-HD files before HD ones.
- Added 60 logos from the tv-logos pack to `media/network`, plus aliases for other spellings (for example
  "ABC (US)" and "Spike"). Nine more logos (Space, Angel, Sky 3D, THT, Nippon TV, DR3, MagentaTV, W.) came from the
  picons pack, the SVG ones converted to PNG. Logos you added by hand (Freevee, Stan, ITVX, KBS, Rutube and others) are matched too, with aliases for
  names that differ from the file ("Sky Deutschland" → `sky.png`, "Danmarks Radio (DR)" → `dr.png`, "Xbox Video" →
  `xbox.png`). `GET /api/v1/brands/unused` lists the logo files in `media/network` that no show uses. Over 190 of the 246 networks that had no icon now have one.

## v1.3.3 — 2026-10-21 — Networks without icons

- New list of TV networks in your library that have no logo in `media/network`, with the number of shows for each:
  open `/api/v1/brands/missing` for JSON, or `/api/v1/brands/missing?format=csv` to download a CSV. It uses the same
  name matching as the icons on the show page, so a network that matches through an alias or suffix is not listed.

## v1.3.2 — 2026-10-21 — Fixed-width status panel

- The status panel next to Scan engine in the taskbar now keeps a fixed width (34 rem) instead of growing and
  shrinking as scans, jobs and library updates change what it shows. It only narrows when the window is too small.

## v1.3.1 — 2026-10-21 — Tab hover colors

- Hovering a tab in Settings no longer fills it with the bright highlight, so the label stays readable. The Queue
  window tabs and the phone pane tabs got the same fix.

## v1.3.0 — 2026-10-21 — README sections

- The README now documents Dolby Vision Profile 7 to 8.1 conversion, track selection, and saved filters.

## v1.2.9 — 2026-10-21 — README summary

- The README has a new Summary section near the top listing the most important features.

## v1.2.8 — 2026-10-21 — Poster badge layout

- Poster badges are now two rows: resolution and HDR along the top, source/format (for example UHD BluRay REMUX)
  and audio along the bottom, in a smaller size.
- The artwork size and shape (for example 342×513 · 2:3) moved off the poster into the Swap bar, which now reads
  "Swap · 342×513 · 2:3" on hover and covers the bottom badges. The Swap bar no longer lights up on hover.

## v1.2.7 — 2026-10-21 — Shorter database label

- The label in the top left corner now reads just "PostgreSQL"; the lamp beside it shows whether it is connected.

## v1.2.6 — 2026-10-21 — Queue button toggles

- The Queue buttons in the taskbar (dock, queue pill and jobs bar) now close the queue window when it is already
  open, instead of only opening it. The "Open the queue" link in Settings still only opens it.

## v1.2.5 — 2026-10-21 — Audit fixes

- Fixed the Kodi check for missing files, which crashed because a module import was missing.
- Fixed the artist biography preview failing whenever TheAudioDB was one of the sources (a variable shadowed a
  helper).
- Fixed locking or unlocking a field in the music artist/album editor throwing an error after the lock was saved.
- Removed two duplicate definitions left in the code.

## v1.2.4 — 2026-10-21 — Delete artwork for movies, TV and sets

- Movies, shows, seasons, episodes and sets now have a red trash button on each current artwork image, both in the
  artwork lookup window (on the selected or current-file card) and in the Artwork section of the info pane. It asks
  first, then deletes the image file and forgets it. Only image files are ever deleted. Music already had this.
- Movie sets gained the same Artwork section as the other video types.

## v1.2.3 — 2026-10-21 — Tests cleaned up

- Fixed the 15 out-of-date tests (Python 3.10 compatibility, renamed scan log files, plain disc numbers, hybrid
  detection from the release name, Trakt's sign-in address, and fake database modules leaking between test files)
  and added tests for the new poster-badge settings. The full suite now passes.

## v1.2.2 — 2026-10-21 — Poster badges and click-to-zoom

- Posters, album covers and artist thumbnails no longer have the magnifier button. Click the picture itself to
  enlarge it. Swapping artwork is now a separate "Swap" bar along the bottom of the picture (shown on hover, always
  visible on touch screens); clicking only that bar opens the artwork lookup. Items without artwork still open
  the lookup when clicked.
- New standard badges on the detail-pane poster, top left: resolution, HDR and audio for movies and episodes,
  season and episode counts for shows and seasons, the movie count for sets, and the format/quality pill for
  albums. Turn them on or off per media type under Settings → the media type's UI Elements.

## v1.2.1 — 2026-10-21 — File health warnings

- Videos that probed fine but look wrong now get a "⚠" warning pill in the Status column: empty file, no video
  stream, no audio, audio with unknown language only, or much shorter than the listed runtime (under half).
  Hover the pill for the details. Failed probes keep their own "Probe failed" pill, and disc images are skipped.
- New "Health warnings" ribbon for movies and TV, and the warning words are searchable in the Status column.

## v1.2.0 — 2026-10-21 — Notifications to other apps

- Settings → Notifications has a new "Send notifications to other apps" manager, like the Radarr/Sonarr entries:
  add as many targets as you like. Types: webhook (JSON), Discord, Slack, Telegram, Pushover, ntfy, Gotify and
  Apprise API. Each target has its own events, an On switch and a Send test button.
- Events: a scan finished, a scan failed, an import from Radarr/Sonarr/Lidarr/Bazarr was processed, a background
  job failed, a database backup finished or failed, and the OpenSubtitles quota is nearly used (at most once a day).
- Addresses and tokens are hidden once saved; leave a box empty to keep the saved value. Messages go out on their
  own threads, identical messages within a minute are sent once, and a failing target is logged and skipped, so it
  can never hold up a scan.

## v1.1.9 — 2026-10-21 — Phone: list redraws when you return to it

- On a phone, going back to the Library tab left the bottom of the Movies table empty until you scrolled. The list
  had been drawn for a hidden (zero-height) pane. It now redraws as soon as its tab is shown again.

## v1.1.8 — 2026-10-21 — Fix empty Music tree after leaving the poster grid

- Going from the poster grid back to the list in Music could show an empty tree with a single album at the bottom.
  The grid's scroll position was saved as the list's, and a position far below the end of the short list painted
  nothing. The grid no longer records its position, the list starts at the top when the view is switched, and a
  saved position past the end of the list is clamped.

## v1.1.7 — 2026-10-21 — Processed in the Status column, Sort beside Batch select

- The Status column and the status chips now say "Processed" for processed items, so the column can be filtered
  and searched by it.
- On Movies and TV the Sort menu sits on the same row as Batch select (it wraps below on a narrow list).

## v1.1.6 — 2026-10-21 — Ticked grid checkboxes stay visible

- In the poster grid, a ticked checkbox on a card stays visible after the pointer leaves. On Small cards the
  checkbox was hidden again as soon as the pointer left, because the card was not marked as selected until the next
  redraw. The card is now marked straight away, and a ticked box is always shown.

## v1.1.5 — 2026-10-21 — Readable poster card text on hover

- The title and artist/year strip under a poster no longer turns light on hover, which made the text unreadable. It
  now gets a faint accent tint and keeps its normal text colours.

## v1.1.4 — 2026-10-21 — Poster grid: card sizes and windowing

- The Poster Grid (Music, Movies, TV and Sets) has an S / M / L card size toggle beside the grid button. Small shows
  titles only, for scanning many items at once; Medium is the previous size; Large uses sharper posters and adds a
  row of badges (resolution, HDR, codec, audio and edition for movies; status and episode counts for shows; type,
  format and track count for albums).
- The grid is now windowed, like the list: only the cards in view and a few rows around them are in the page, so a
  library of thousands is as light as a small one. Arrow-key movement still scrolls the selected card into view.

## v1.1.3 — 2026-10-21 — Clearer column filter checkboxes

- The unticked boxes in the column filter menus have a thicker, lighter outline and a faint fill, so they are easy
  to see before they are ticked.

## v1.1.2 — 2026-10-21 — Column filter ticks

- The tick marks in the column filter menus now follow the selected state directly and are updated before the list
  is redrawn, so a picked value always shows its tick. Several values per column could already be picked.

## v1.1.1 — 2026-10-21 — Music syntax builder, grouped rename patterns

- Settings → Files now has one "Rename patterns" heading with Music, Movie and TV Show renaming patterns under it.
- The music folder and file patterns have a Syntax builder button like the movie and TV patterns. It clicks fields,
  free text, number padding, Before/After text and "skip when empty" together into the %token% syntax, with
  ready-made patterns and a live example.

## v1.1.0 — 2026-10-21 — Lidarr update shows where the refresh is in Lidarr's queue

- After "Update library in Lidarr", the alert now says whether Lidarr started on the refresh straight away or queued
  it behind other tasks (named), and that Lidarr fetches fresh artist data before it rescans the folder. The wait
  before albums update is Lidarr's own queue and metadata fetch, not Curator.

## v1.0.9 — 2026-10-21 — Fix empty Health section in About

- The Health section was empty because its address clashed with the existing /health status check, which answered
  instead. It now has its own address (/about/health).

## v1.0.8 — 2026-10-21 — Phone layout for Movies, TV and Sets

- On screens narrower than 800 px, Movies, TV and Sets now have List and Details tabs like Music, so the details
  of an opened item are no longer pushed below the list. Opening a movie, show, season, episode or set switches to
  Details; a refresh of the item already open does not. Changing library goes back to the list.

## v1.0.7 — 2026-10-21 — Keyboard shortcuts that were missing, phone layout for Music

- Alt+1 to Alt+4 switch between Music, Movies, Sets and TV, and Ctrl+A selects everything visible in the list.
  Both were on the shortcuts cheat sheet but did nothing. The command palette (Ctrl+K) can now open About and the
  shortcuts sheet.
- On screens narrower than 800 px the Music view shows one pane at a time with Library, Albums and Details tabs
  above it, instead of stacking all three. Opening an artist or album moves to Albums, and picking a track moves to
  Details. Dialog padding and a few two-column forms also collapse to one column there.
- Saved views (saved filters) already exist for Music, Movies, TV and Sets, so no change was needed.

## v1.0.6 — 2026-10-21 — Health in About, Undo in alert history, database snapshots

- About now has a Health section: the database, every library folder (readable, and free disk space with a warning
  under 5%), ffprobe and ffmpeg, the last finished scan and failed jobs in the last 7 days. All checks are local;
  nothing calls another service.
- Lock, Unlock and batch edits (music albums, movies, shows, episodes) add an Undo button to their entry in the
  alert history. Batch edits only offer Undo when the old value of every edited field could be read for every
  changed item.
- Settings → Backup has "Snapshot the database before large writes", off by default. When on, removing, deleting,
  batch editing, file jobs and deleting music on 5 or more items first write a before-bulk-… dump to the backup
  folder. Only the last 2 are kept. A failed snapshot is logged and the action still runs.
- Escape closes only the top window when several are stacked, instead of all of them.
- Modal audit: all 53 windows already share one header, body and Close layout, so nothing needed changing there.

## v1.0.5 — 2026-10-21 — Test suite runs cleanly together

- Added `tests/conftest.py`, which imports the real packages before any test file is collected. Several older test
  files stub missing modules with mocks; collected in one run those stubs replaced real modules for every other
  test and caused unrelated failures. The full run went from 51 failures to 15.
- Documented how to run the tests in the README.

## v1.0.4 — 2026-10-21 — Dry run for Normalize subtitles

- Normalize subtitles now shows what it would do before it runs, like Rename files and Organize extras: renames,
  files that would be re-encoded to UTF-8, and duplicates (marked Remove when purging is on). The preview reads
  the files but never writes them, and the Normalize button only enables when there is something to do. The
  Subtitles button in the batch bar opens the same window for a single group of items.
- Move already had a preview. Trailers, theme songs and thumbnails only add files, so they keep running directly.

## v1.0.3 — 2026-10-21 — About window, split alert, Jobs entries, sync after download, download quota

- **About:** click the Curator logo for an About window with the version, how long the app has been running, the
  database and Python versions and the version of each tool Curator uses (ffmpeg, mkvmerge, alass and the rest).
  It says so when the page you have open is older than the server, which is the "reload to update" check.
- **Splits:** finishing a split now shows an alert ("Split 2 files", or the error), also when the split waited in
  the queue and the window was closed. Splits appear in the Jobs list as Episode split.
- **Jobs list:** a saved subtitle download shows as Subtitle download and a saved sync as Subtitle sync. Manual
  scrapes were already listed.
- **Sync after download** (Files tab, Subtitles): a subtitle from OpenSubtitles.com that was not matched by file
  hash is lined up with the audio using the automatic sync (alass). A large proposed change is refused and the
  subtitle is left as it is. A manual download syncs in the background; a scan does it before moving on.
- **Download quota:** OpenSubtitles reports the downloads left today. Find subtitles shows it in the alert after a
  download, and the scan log ends its subtitle line with it.

## v1.0.2 — 2026-10-20 — Scan window titles name where the scan came from

- The scan window title is now "Movies - Incremental deep scan (Manual scan)": the word scan is lower case like
  the mode before it, and a bracket at the end says what started it: Manual scan, Scheduled scan, Webhook
  (a Radarr, Sonarr, Lidarr or media server import) or File job (the deep scan after a Dolby Vision conversion).
  The bracket shows while a scan runs; before one starts there is nothing to name.

## v1.0.1 — 2026-10-20 — One Lock button in the batch bars

- The batch bars of Movies, Sets, TV Shows and Music had a Lock and an Unlock button. They are one button now:
  it says Lock, and says Unlock when every selected item is already locked. With a mix of locked and unlocked
  items it locks them all.

Versions: the number shown beside the logo comes from `app/VERSION`. Every update bumps the last digit
(1.0.0, 1.0.1 ... 1.0.9, then 1.1.0 ... 1.9.9, then 2.0.0). Each entry below names the version it shipped in.

## v1.0.0 — 2026-10-20 — Initial release

- The version beside the logo is now `v1.0.0`, read from `app/VERSION`, instead of a date and a build
  fingerprint such as `v2026.10.20.fb1056`. The earlier entries below were written before versioning started and
  are all part of this release.

## 2026-10-20 — Update library in Lidarr no longer times out

- Finding the artist in Lidarr downloaded Lidarr's whole artist list, which took more than 30 seconds on a big
  library and timed out. It now asks Lidarr for that one artist by its MusicBrainz id, and only falls back to the
  full list (with a 3 minute allowance) if that fails.
- Update library in Lidarr, Radarr and Sonarr now shows "Asking … to rescan…" at once, and a Lidarr error is
  shown instead of being swallowed as "none of the selected artists".

## 2026-10-20 — Update library in Lidarr works

- Lidarr answered HTTP 500 "Sequence contains no matching element" because Curator sent it a command it does not
  have (RescanArtist). It now sends RefreshArtist, which refreshes the artist and reads the artist folder again.
  This also fixes the rescan Curator asks of Lidarr after deleting or moving music files.

## 2026-10-20 — OpenSubtitles Test button shows the green check

- The OpenSubtitles Test button now shows "Testing…" and then the green check or red cross for three seconds,
  like the other connection tests.

## 2026-10-20 — Subtitles from OpenSubtitles.com: Find subtitles and download during a scan

- **Find subtitles…** on the right-click menu of a movie or an episode opens a window that searches
  OpenSubtitles.com for the configured languages. Results show the release, downloads and badges (File match,
  Trusted, SDH, Machine, Forced) and sort a subtitle made for this exact file first (OpenSubtitles file hash), then
  trusted uploaders, then downloads. Download saves `<video>.<lang>[.sdh].srt` beside the video as UTF-8 and
  updates the file's subtitle list. A name that already exists is never overwritten. You can change the
  languages in the window and search again.
- **Settings:** a new OpenSubtitles.com block under API credentials holds the API key, username, password
  (a Test button checks them), the subtitle languages and whether hearing-impaired subtitles are skipped,
  allowed or the only ones. The key and password can also come from `OPENSUBTITLES_API_KEY` and
  `OPENSUBTITLES_PASSWORD` (the username from `OPENSUBTITLES_USERNAME`). The README now lists the site's
  download limits per 24 hours: 5 per IP anonymous, 10 to 1000 per account by rank.
- **During a scan:** new option "Download missing subtitles from OpenSubtitles.com during a scan" on both the
  Movies and TV Shows tabs. After the metadata lookup it saves the best match for each wanted language the item has
  no full subtitle in (embedded or beside the file; forced subtitles do not count). Incremental scans cover new
  and changed items, full and deep scans cover all. The scan stops asking when the account's daily download
  limit is used up, and the result line shows subtitles saved and lookups that failed.

## 2026-10-20 — Split cut on the first black frame; preview seeks to the cut; artwork size badge moved

- Split detection put the cut in the middle of the black picture, which landed about a second late when the
  black lasts a couple of seconds. The cut is now placed on the black picture's first frame. New setting under
  Files, Split episodes: "Cut on the black picture at" with first frame (default), middle or last frame.
- Clicking an episode in the split window, editing its time or opening the window moves the preview video to
  that cut time, so the cut is seen straight away.
- Existing artwork in the media info pane: the resolution badge sits at the top right of each image so it no
  longer collides with the enlarge button.

## 2026-10-20 — Queue watcher crash fixed

- The previous fix left the queue watcher with an unset variable whenever a split was still running, so it
  crashed instead of waiting and a second split pair queued behind a running split never started. It now waits
  and starts the queued split when the running one is done.

## 2026-10-20 — Queued splits actually run; short silences next to a black picture are found

- A split that was queued behind a scan or scrape never started: the queue watcher held its lock while starting
  the split, which needs the same lock, so it waited forever. The split now starts once everything is idle.
- The queued notice names what it is waiting for (a scan, a scrape, a file job) instead of "scan queue".
- Silence next to a black picture: the normal check ignores silence shorter than 0.4 s or quieter-than -50 dB
  and needs 0.25 s of overlap. When a black picture is found without matching silence, a second pass around it
  looks for silence down to 0.1 s at -35 dB within 1 s of the black picture. A hit is shown as "Uncertain, black
  picture with brief silence" and still needs your confirmation.

## 2026-10-20 — Split detection suggests a lone black or silent moment before guessing

- 12:10 was not detected. When chapters and the "black picture and silence at the same time" check both find
  nothing within 15 s and then 45 s of the expected point, the split fell back to the expected point itself,
  which is the episode runtimes shared out proportionally (halves when runtimes are unknown), labelled Manual.
- Before that fallback, the black picture or the silent stretch nearest the expected point is now used on its
  own, labelled "Uncertain, black picture only" or "Uncertain, silence only". It stays unconfirmed, so you
  check it before splitting. Only if neither exists does it fall back to Manual.

## 2026-10-20 — Split episodes no longer fails with Internal Server Error

- Choosing Split episodes (and Restore or Delete source) called a check, `_ensure_idle`, that did not exist, so
  the server returned Internal Server Error before it looked at the file. It is defined now. Planning a split
  only reads the file, so it no longer waits for a scan or scrape; it only refuses while another split is
  running. Restore and Delete source still wait for every other job.

## 2026-10-20 — Sort dropdown for Movies, Sets and TV Shows; music buttons beside the sort

- **Music:** Apply All Matches and + Artist moved up into the row with the Library sort dropdown.
- **Movies, TV Shows and Sets:** a Sort dropdown after the Batch select row. It lists every shown column
  (Sets: Name, Years, Movies) in both directions, for example "Sort by Year ↓". It sets the same sort as
  clicking a column heading, so the two stay in step and the choice is remembered.

## 2026-10-20 — Apply match window for music

- The music **Apply All Matches** button used to start applying at once. It now opens a list of the albums
  with a loaded match (artist, album, the loaded match and its track count) with a **Remove** button per
  row and **Apply all** for the rows left. Remove leaves an album out of that run and keeps its loaded match.
- The music scan engine window has the same **Apply match (N)** button next to Start scan, shown when no
  scan is running and at least one match is loaded.

## 2026-10-20 — Apply match only shows the movies or shows of the window you are in

- The Apply match button counted held movies and TV shows together, so four unmatched shows also showed up
  on the Movie scan window. The button and its list now count only the media type of the window: movies in
  the Movie scan window, TV shows in the TV scan window, nothing in the music or sets windows.
  `GET /api/v1/match/pending` takes `media=movies|tv`, and the scan status carries
  `pending_match_movies` and `pending_match_tv`.

## 2026-10-20 — Apply match: remove items, Fix Match queue, fixed items leave the list

- **Remove:** each row in the Apply match window has a Remove button. It leaves that item out of Apply all
  (it stays waiting, and shows again next time). Apply all writes only the rows still listed.
  `POST /api/v1/match/apply` accepts an optional `ids` list.
- **Fix Match queue:** choosing a match while another scrape is running no longer fails with "wait". The id is
  saved at once and the scrape is queued; queued ones start one after another when the running scrape (or
  Apply match) finishes. The message says how many are waiting.
- **Fixed items leave the list:** an item you matched by hand is no longer counted as waiting for Apply
  match, and its row disappears from the open window. Before, the held flag stayed until a scrape wrote
  something, so a fixed and scraped item could still be listed.

## 2026-10-20 — Apply match shows what it will apply

- The **Apply match (N)** button in the movie and TV scan window used to start writing at once, without
  saying which items were involved. It now opens a list of the held movies and shows (title, type,
  folder, and a Fix match… button for each) with **Apply all** and Cancel. New route
  `GET /api/v1/match/pending`.

## 2026-10-20 — Scan results window: real cause of the empty space

- The empty area under the lists was not the button bar. A general rule capped every `modal-wide` window body
  at 45 % of the screen height (`.modal-wide .modal-body`), so the lists stopped short and the bar sat
  below a blank area. That cap is removed for every window: a window body now takes the height it needs and
  scrolls only when the window reaches the screen edge (the window itself is still limited to the screen),
  so no window keeps a blank area under its content. The scan results lists fill the window and the button
  bar sits flush at the bottom.

## 2026-10-20 — Movie and TV scans show the scan results window too

- Only the music scan opened the Scan results window when it finished. A movie or TV scan now opens the
  same window: files without an episode number (or not placed), read failures, and empty folders, with
  Copy results, Copy status and Export JSON. The window shows a failed or stopped scan the same way.
  Movies and shows have no "looked up" list, so that box holds the unplaced files instead.

## 2026-10-20 — Scan results window: lists get the height, buttons in a slim bar

- The three lists (Looked up, Failures, Empty folders) used to split the window equally, so a list with
  "No failures." still took a third of it. A list with nothing in it now shrinks to one line and the lists
  that have lines share the height.
- Copy results, Copy status and Export JSON moved into a bar along the bottom that is only as tall as the
  buttons, with the log note beside them.

## 2026-10-20 — One Mark as processed/new item; Update library in Radarr, Sonarr and Lidarr

- **Mark as processed / new:** the movie, show, season, episode and set right-click menus had two items
  for one switch. There is now one: it says Mark as new when everything selected is processed, and Mark as
  processed otherwise. A selection that mixes both is greyed out. Mark as ignored is unchanged.
- **Update library in Radarr / Sonarr / Lidarr:** a new item, with the app's icon, on the movie, show and
  music artist menus. It asks that app to rescan the selected items (`RescanMovie`, `RescanSeries`,
  `RescanArtist`), through the new `POST /api/v1/library/arr-rescan`. It is greyed out when the app is off in
  Settings, and the message says how many items the app knew. The older **Update library…** item still sends
  to Kodi, Emby, Jellyfin and Plex.

## 2026-10-20 — Video artwork window keeps its Upload buttons when the online search fails

- If the online artwork search fails (no TMDB key, no TMDB id yet), the movie, show, season, episode and
  set artwork window used to stay on "Searching artwork…". It now shows the reason and every artwork type
  with its Upload button. The show list also gains Discart, which the server already accepted.

## 2026-10-20 — Syntax builder, music options matching video, scrape switches are settings only

- **Syntax builder:** each Jinja2 rename pattern (Settings, Files) has a Syntax builder button. The modal
  offers ready-made patterns and clickable pieces (movie, show, episode and media fields), free text and
  separators between them, per-piece options (skip when empty, dots, clean, two digits), and a live example.
  Use this pattern writes the result into the box; nothing is saved until Save settings. The help text now
  says the release group stays at the end as `-ReleaseGroup`.
- **Music options:** Keep a `.nfo.bak` when a rewrite replaces a file, Show date added, Show
  processed/unprocessed checkmark (artist and album rows), and a music Export format (CSV or XML) are on the
  Music tab. Writing `.nfo` after a scrape is the existing `.nfo` button under What Apply match writes.
- **Environment variables removed:** `CMM_SCRAPE_MUSIC`, `CMM_SCRAPE_MOVIES` and `CMM_SCRAPE_TV` are gone from
  the code, `.env.example` and `docker-compose.yml`. The three "Scrape … found by a webhook scan" switches
  in Settings are unchanged and default to on. Remove those lines from your own `.env` if you set them.

## 2026-10-20 — Music .nfo dialect, Lidarr import section, Collapse versions moved

- **Music .nfo dialect:** Settings, Music, Storage and structure has a new `.nfo dialect` choice like the
  video one. Kodi writes the plain files. Emby / Jellyfin adds a `lockdata` tag. Plex adds a `guid` tag
  (`musicbrainz://<id>`). It applies to artist and album `.nfo` files from every writer. The file names are
  still set by the Kodi/Jellyfin or Emby choice above it.
- **On Lidarr import:** "Scrape music found by a webhook scan" moved from General to a new section at the
  bottom of the Music tab, matching On Radarr import and On Sonarr import. The Automation copy stays in sync.
- **Collapse versions:** the movie "Collapse versions of the same movie into one row" checkbox moved into
  Movies, UI Elements.

## 2026-10-20 — Yellow outline on a search box that has text

- The movie, TV and music search boxes get a yellow outline while they contain text, including
  text put there by clicking a cast member, genre, studio or tag.

## 2026-10-20 — Clickable cast, crew, studios and tags now filter; cast cards restyled

- **Filtering:** clicking a cast member, writer, genre, studio, country or tag in a movie or show page
  puts it in the library search box, but the search only looked at titles, ids, genres and (for
  movies) directors and studios. The movie and show lists now carry a search text with the cast
  names, writers and tags, and the search also covers countries (movies and shows), studios,
  directors and the show status for TV. The movie list was changed and loads slightly more.
- **Cast cards:** the clickable cast buttons no longer get the default blue button background or
  sit to the right; photo and text are centred, and the blue only shows on hover or keyboard focus.
- Not tried in the browser or against your library.

## 2026-10-20 — Season trailers after a Sonarr import, and the trailer settings moved

- **TV Shows, On Sonarr import:** download the season trailers. After an import is scanned and
  scraped, each season that received episodes gets its trailer (when the scraper saved a YouTube
  link for it). A season is only fetched when it has no trailer, or the file is below the chosen
  quality and YouTube has a taller copy.
- **Movies, On Radarr import:** the existing movie trailer option moved here from the Files tab.
- **General, Trailer download quality:** the highest quality to search for (2160p, 1080p, 720p)
  moved here from the Files tab. It applies to every trailer download.
- Setting key for the new option: `trailer_on_sonarr_season`. Not tried against a real Sonarr import.

## 2026-10-20 — The same band in two library paths now keeps its MusicBrainz artist id on both entries

- The artist's MusicBrainz id was unique in the database, so the second entry of a band (one per
  library path) could not store it, and the artist.nfo field showed "not in the database". The
  uniqueness is dropped on start-up; two entries may share the id when they have the same name
  (ignoring capital letters). An entry with a different name still cannot take an id that another
  artist holds, and typing such an id into the artist page still offers Merge with….
- The next scan fills the id on the entry that lacked it. Not tried against your database.

## 2026-10-20 — Duplicate pill on artist entries

- An artist entry whose name matches another artist entry (the same band in two library paths)
  now carries the **Duplicate** pill in the library tree, not only its albums. Matching is by name,
  ignoring capital letters. Not tried against your database.

## 2026-10-20 — Setting: show or hide the edition badge on album rows

- Settings, Music, UI Elements: **Show the edition badge** (on by default). Off hides the Original
  studio album / Deluxe edition / EP / Single badge on the album rows in the library tree.

## 2026-10-20 — Music: one artist entry per mount, no library root in the tree, edition badge position

- **Same band in two library paths:** each path's artist folder is now its own artist entry with its
  own albums, and the copies are flagged Duplicate. Before, the album tag's MusicBrainz artist id
  pulled every album onto the first entry and left the second one empty. An album filed under a
  differently named artist folder still follows its tag.
- **Library root never listed:** an artist row that sits exactly on a library path that holds many
  artists is no longer shown in the tree.
- **Edition badge** (Original studio album, Deluxe edition, EP, Single, ...) now sits left of the
  date added, instead of after it.
- Not tried against your database. **Merge with…** already exists on the artist page; it was not
  changed.

## 2026-10-20 — Music quick filters toggle, stale answers dropped, scan results window, leftover artist

- **Quick filters:** pressing a lit filter badge in the music pane clears it and goes back to All, like
  the movie and TV badges. A library answer that arrives after you have already changed the filter
  or the search is dropped and asked for again, so an old answer can no longer replace the one you
  wanted (this is what needed several clicks on All).
- **Scan results window:** uses the full height between the top row and the task bar, the three
  lists share the height, and there is a **Copy results** button (summary, looked up, failures,
  empty folders).
- **Leftover artist:** an empty artist row sitting exactly on a library path that holds many
  artists (for example `music` after `/…/temp` was a library path and `/…/temp/music` later became
  one) is removed at the end of a music scan.

## 2026-10-20 — Scan engine: Copy status, Export JSON and Start/Cancel scan stay in view

- In the music and video scan engine windows the button row sits in a footer that stays at the
  bottom of the window while the log scrolls.
- The music scan log now ends the prune step with `Library now holds N albums by N artists
  (<path>: N albums, ...)`, so a library that looks empty can be told apart from one that is
  merely hidden.

## 2026-10-20 — Music tree: a saved filter that matches nothing falls back to All

- The tree stayed empty after scans because the saved filter was still **Duplicates**, which matches
  nothing once the copies are gone (the container log shows `GET /api/library?filter=duplicates`).
  When the library loads with a filter whose count is 0 and no search text, it now switches to
  **All** and says so.

## 2026-10-20 — Music: the outside-library removal can no longer touch an album the scan just found

- The removal now skips every album path the scan walked, whatever the stored row says, and the
  scan log shows up to three example paths of what it removed so a wrong removal is visible.
- Tests: `tests/test_purge_unmounted.py`. Not tried against your database.

## 2026-10-20 — Fix: removing items outside the library paths could take found items with it

- The "outside every library path" removal for movies and TV shows compared a row's library root
  with the path typed in Settings exactly. A different spelling (a symlinked path, a nested
  library path) made found items look outside. It now treats a row as inside when its root or its
  own path is at or below any library path of that media type, as typed or resolved, and the
  music version does the same. Nothing is removed when no library path is set.
- Tests: `tests/test_purge_video_outside.py`.

## 2026-10-20 — Prune safety setting, and Remove all not found

- **Settings, General, Prune safety** (on by default): when on, scans hold back removals that
  would drop more than 20 % of a mount or of one library path. When off, the scan removes what it
  cannot find whatever the share. A library path that is readable but completely empty is always
  left alone either way. Applies to music, movies and TV shows. Setting: `prune_safety`.
- **Remove all not found** button at the left of the bottom row under the library list, for music
  and now for movies and TV shows. It shows the number of items marked Not found, hides when there
  are none, and asks for confirmation first. Files on disk are not touched.
- The movie and TV list panes get the same bottom row as music: **Items Selected: N** on the
  right.
- Tests: `tests/test_tv_prune_safety.py`. Not tried in the browser or against your database.

## 2026-10-20 — A "Not found" pill and filter for items kept by prune safety

- When a scan skips removing missing items because of a prune safety limit (20 % of a mount, 20 %
  of a path, or a path that came back empty), those items are now marked **Not found** instead of
  silently staying. This covers albums, movies and TV shows.
- The pill shows on the album, movie and show rows. In music, **Not found, kept by prune safety**
  is in the filter menu; in the movie and TV views, **Not found** is a quick filter and a Status
  value. Select the filtered items and use the existing **Remove selected albums from database**
  or **Remove from library** to drop them. No files are touched.
- The mark clears by itself when a later scan finds the item again, and is gone if the item is
  removed. New column `prune_held` on `albums`, `movies` and `tv_shows`, added on start-up.
- Not tried against your database; the pill's colour is a first guess.

## 2026-10-20 — TV scans: the same prune safety limits as movies and music

- A TV scan used to remove every show missing from a path with no limit, except when nothing at
  all was found. It now applies the same rules as movies and music: a mount that would lose more
  than 20 % of its indexed shows across all of its library paths is left alone, a single path
  that would lose more than 20 % is skipped, and a path that is readable but empty is skipped.
  Each skip says so in the scan log. Paths you remove in Settings are still removed in full.
- The limits only apply to library paths that are mounted and walked.
- Tests: `tests/test_tv_prune_safety.py`. Not tried against your database.

## 2026-10-20 — Movie and TV scans: remove items filed under a library path that is gone

- Same fix as music, for the other media types. At the end of a full movie or TV scan, movies
  and shows whose library root is no longer listed in Settings for that media type are removed
  from the database, even if the folder still exists on another mount. Offline, excluded and
  empty library paths are still listed in Settings, so they are protected. Wanted titles filed
  under the gone root go too. No file is touched; the scan log says how many.
- The per-mount and per-path 20 % limits are unchanged and still apply to mounted paths only.
- Tests: `tests/test_purge_video_outside.py`. Not tried against your database.

## 2026-10-20 — Music scan: removes rows left behind by a library path that is gone

- **Why the old `/music/Music Albums/temp/music/...` albums stayed:** the scan only removed a
  path's rows when Settings recorded it as explicitly removed, and only through the prune that
  also guards mounted paths. If the removal was not recorded (the path was changed along with the
  volume, or the entry was edited rather than removed) nothing ever came back for those rows.
- **Fix:** at the end of a music scan, albums and artists that sit outside every library path
  are removed from the database, even if the folder still exists on another mount. Offline, excluded and
  came-back-empty library paths are still protected, and an artist that still has albums elsewhere
  is kept. No file is touched. The scan log says how many rows went.
- Tests: `tests/test_purge_unmounted.py`. Not tried against your database.

## 2026-10-20 — Music: the Duplicate pill and the Duplicates window now agree

- **Why the pill came back after a rebuild:** the pill is set at the end of a scan when two albums
  have the same artist and title or the same MusicBrainz release, but the Duplicates window only
  listed albums with matching AcoustID or fingerprints. An album could carry the pill with an
  empty window. My last change cleared the pill when the window was empty, and the next scan set
  it again, because the other copy really is still in the database.
- **Fix:** the window now also lists those copies, under **Same release**, with the reason ("Same
  artist and title" or "Same MusicBrainz release") and both paths, so you can see which folder the
  second copy is in and delete or remove it. The pill is no longer cleared just because the
  window had no fingerprint match. A mark is still cleared when no other copy exists at all.
- These pairs have no **Not duplicates** button (that works on matching tracks).
- Tests: `tests/test_orphan_flags.py`. Not tried against your database.

## 2026-10-20 — Music: Expand all, Export and the grid/list toggle moved to the quick filter row

- **Expand all**, **Export** and the grid/list button now sit at the right end of the quick filter
  row; the quick filters stay on the left. The filter menu, Clear filters, Save filter, Saved and
  the sort menu stay where they were. Same buttons and actions, only moved. Not looked at in a
  browser.

## 2026-10-20 — Music quick filters use the badge style

- The music quick filter buttons now use the same rounded badge style and small count as the movie
  and TV ones (`vribbon`). They had no style of their own and showed as ordinary blue buttons. Not
  looked at in a browser.

## 2026-10-20 — Music: five quick filters; stale Duplicate and Upgrade pills are cleared

- **Quick filters:** the music pane keeps **All, New, Unmatched, Partial** and **NFO Change**. 100%,
  No Art, No NFO, NFO Changes, Duplicates and Upgrade are only in the filter menu (they were already
  listed there, with counts).
- **Stale pills:** a Duplicate or Upgrade mark is now cleared when it no longer points at another
  copy. `upgrade.clear_orphan_flags()` removes a Duplicate mark from an album that has no other
  album with the same artist and title or the same MusicBrainz release, and an Upgrade mark whose
  source is gone or is not a copy of the album. It runs when the server starts and whenever the
  Duplicates window is opened, and the tree drops those pills at once. Marks that still have a
  partner are left alone.
- **Empty windows:** opening Duplicates for an album that no fingerprint pair lists clears that
  album's Duplicate pill; an Upgrade window with no higher-quality copy clears the Upgrade pill; the
  same for a movie or episode whose copies window shows only itself.
- **Probable cause of what you saw:** after the volume change both copies existed, each flagged the
  other, and the marks were only recomputed at the end of a scan, so a mark could outlive the copy
  it pointed at. I could not see your database, so this is inferred from the code.
- A mark that has a partner by shared MusicBrainz release but no matching fingerprints is cleared
  on the album you opened the window for, and a later scan can set it again while the two albums
  still share a release.
- Tests: `tests/test_orphan_flags.py`. Not tried against your database.

## 2026-10-20 — Trakt scrapes TV show details; OMDb scrapes movie details (English)

- **Trakt, TV shows:** Trakt now supplies a show's title, year, first-aired date, plot, tagline,
  runtime, certification, genres, network, country, language, status, cast and creators, trailer
  and rating (`TraktRatings.show_base`, English, no artwork). It takes part in the usual field
  order like TMDB and TheTVDB, leads when you pick Trakt as the metadata provider (scrape dialog,
  per-show choice, or first in the TV order), and is the fallback: when TMDB and TheTVDB find
  nothing the scrape no longer stops with "No confident match" if Trakt has the show (it needs the
  Trakt client ID and an IMDb or Trakt id on the show). In that case seasons and episodes are not
  touched, since Trakt's lists are not used. The source is recorded as `trakt`.
- **OMDb, movies:** the one OMDb request per movie now also returns the English plot, release date,
  runtime, genres, countries, languages, cast, directors, writers and production company
  (`Omdb.movie_base`, `parse_movie`), next to the ratings it already gave. TMDB still wins where
  it has a value unless OMDb is earlier in the order or chosen as the provider. OMDb can now also be
  the lead provider for a movie and the fallback when TMDB has no entry (it needs an IMDb id).
  OMDb cast has no photos or roles. The quota rules are unchanged (one request, not two).
- Settings: the source name "Trakt ratings" is now "Trakt"; the OMDb key text mentions the details.
- Tests: `tests/test_trakt_show_omdb_movie.py` (fake clients). The full scrapes need the database
  and were not run; please re-scrape one movie with OMDb first and one show that TMDB does not have.
  The OMDb and Trakt TV details were not tried against the real services.

## 2026-10-20 — Consistency pass: version label, Bazarr on Sync OK, menus, headers, dead routes

- **Version label:** the pill after the logo showed `v1` (the `APP_VERSION` default) and never changed.
  It now shows the date of the newest app file plus a 6-character fingerprint of every template and
  static file, such as `v2026.10.20.a1b2c3`. A browser or container running old files shows a
  different value from the one on disk. If you set `APP_VERSION` to something other than `1`, it
  is put in front. (Read once at startup, so it is `v1` for the first second after a restart.)
- **Bazarr on Sync OK:** Sync OK now asks Bazarr to re-read the subtitles of that movie or show, like
  Save and Export already did. It follows the same switch ("After syncing or exporting a subtitle,
  tell the players and Bazarr") and runs in the background so Sync OK does not wait for Bazarr.
- **Sticky table headers:** the gap fix for the patterns window now covers every table in a modal
  body that uses the sticky header (that also fixes the batch rename preview). Other tables in
  windows do not use a sticky header, so they have no gap.
- **Music filter picker:** the current filter now has a check mark, like the video column menus.
  It already scrolled and listed every choice.
- **Duplicate routes removed:** `curator/routes/copies.py` defined `GET/POST /artwork/choices/…`
  again after `scrape.py` did. `scrape.py` is registered first, so it answered and the copy never
  ran. The copy is deleted; `scrape.py` is unchanged.
- Not run against a live server (the test sandbox has no web framework installed).

## 2026-10-20 — Video artwork: upload your own image

- Every artwork type in the movie, show, season, episode and set artwork window now has an
  **Upload** button, like the music one. The image (up to 25 MB, any format Pillow can read) is saved
  under the same Kodi file name as a picked candidate (`poster.jpg`, `season01-poster.jpg`, …),
  replacing the current file of that type, and recorded on the item. New route
  `POST /api/v1/artwork/upload/{kind}/{id}` (`art_pick.choose_upload`, `art_fetch.save_bytes`).
- The window also shows the Upload buttons when no candidates were found, so an item without a TMDB
  id can still get artwork.
- Tests: `tests/test_video_art_upload.py` (write, replace, rejects non-images/unknown types). The
  button and file picker were not clicked in a browser.

## 2026-10-20 — Slow "mark processed" is logged

- A status change that takes more than 2 s in the database now writes a warning
  ("status change on N … row(s) took Xs") to the log, so a slow mark can be told apart from a slow
  screen update. No behaviour change.

## 2026-10-20 — Folder and file patterns: no gap above the sticky table header

- The preview table's header stuck 16 px below the top of the scrolling area (the modal body's
  padding), so rows scrolled through the gap. In this modal it now sticks flush with the top bar.
  Not tried in a browser; other modals with sticky table headers were left alone.

## 2026-10-20 — Matrix column filter menus: all values, scrolling, check marks

- **Missing values:** the menu listed only the first 80 values, so typing in "Find values…" could not
  find the rest. It now lists every value.
- **Scrolling:** the menu is a flex column and its rows shrank to fit instead of overflowing, so the
  bottom could not be reached. Rows no longer shrink; the menu scrolls, the search box stays on top,
  and its height follows the window.
- **Check marks:** the box is now fixed at 14 px so it cannot be squashed away. I could not see this
  menu in a browser, so if the marks are still missing, tell me which column and I'll look closer.

## 2026-10-20 — Networks: NRK and Viaplay logos match by name

- Any network whose name contains "Norsk Rikskringkasting" or "Norsk Rikskringkastning" now gets
  `nrk.png`, and any containing "Viaplay" or "Via Play" gets `viaplay.png` (`curator/video/brands.py`).
  An exact logo file for the full name still wins. Test: `tests/test_brands.py`.

## 2026-10-20 — Alerts: the Clear button works

- The button had no handler (`clear-alerts` was never wired to `clearAlerts()`), so it did nothing.
  Not tried in a browser.

## 2026-10-20 — Alerts panel stays open when clicked; Force scan now runs on the first click

- **Alerts panel:** clicking inside the list closed it, because only the bell counted as "inside".
  Only a click outside closes it now. The latest-alert popup also stays while the pointer is over it,
  and a new alert no longer redraws the list while you have text in it selected.
- **Force scan now:** the click set the queue's timer to zero, but the queue re-read its timer from
  the database a few seconds later and put the old countdown back, so it looked like a reset. The
  forced flag now survives that refresh (until the queue is empty) and wakes the queue straight away.
  Test: `tests/test_force_flush.py`. Not tried against a live queue.

## 2026-10-20 — Library analytics: the empty area at the bottom is gone

- **Cause:** `.modal-wide .modal-body` limits every wide modal's body to 45% of the window height.
  The analytics modal uses it, so its content was cut off at that height; my earlier forced
  stretch made the box taller without lifting the cap, leaving an empty area under the content.
- **Fix:** the cap is lifted for the analytics modal and the forced stretch is removed. The modal is
  as tall as its content needs, up to the space between the top bar and the bottom dock, and the
  body scrolls inside when the report is longer. A short report (one library) leaves no blank pane.
- Not looked at in a browser.

## 2026-10-20 — Video: the matrix pane stretches; music panes keep room for the centre

- **Video:** the list (matrix) pane on the left now takes all the leftover width and the info pane on
  the right keeps its width, so a wider screen gives the matrix more room. The width of the right pane
  is what is saved (`curator.videoRight`, also mirrored to the server). Until you drag the splitter,
  the right pane is what the old layout left over (from your old saved left width, or the old
  default), so nothing jumps on first load. Limits: the right pane is at least 360 px and leaves the
  list at least 420 px (movies) or 220 px (sets, TV). Double-click the splitter to reset. The layout
  is re-applied when the window is resized.
- **Music:** when the saved side panes together leave the centre pane under 360 px (for example
  widths saved on an ultrawide, opened on a laptop), they are scaled down for display, not below
  180 px each. The saved widths are not changed, so the wide screen gets them back.
- Checked in jsdom: default, saved, ultrawide, small-screen and old-setting conversion cases for
  video; squeeze and restore for music. Not looked at in a browser.

## 2026-10-20 — Layout choices survive rebuilds; analytics modal uses the full height

- **Saved on the server:** the chosen matrix columns, their order and widths (movies and TV), the
  music columns and widths, the pane widths (music and video), sorting, density, theme and the
  collapsed bio/review state are now also stored in `ui_state.json` in the config folder, the same
  folder that survives a rebuild. They were only in the browser's storage, so a different address,
  another browser or cleared site data reset them.
- **How it works:** a new first script, `core/ui-sync.js`, asks the server for the saved copy before
  the other scripts read their settings, then mirrors every later change (half a second after the
  last one). The first time, whatever your browser already has is uploaded, so nothing is lost.
  The server copy wins on load; two browsers share one layout, the last change wins.
- New `GET/PUT /api/v1/ui-state`, open while the app is still starting so the first page after a
  rebuild already gets the saved layout. Only a fixed list of keys is accepted.
- **Library analytics:** the modal now stretches to the height between the top bar and the bottom
  dock, with the content scrolling inside it (`.insights-modal { align-self: stretch }`).
- Tests: `tests/test_ui_state.py`; the browser script was checked in jsdom (server values applied
  first, first-run upload, debounced mirroring, server down). Not run against your server, and the
  modal height was not looked at in a browser.

## 2026-10-20 — Loading screen says "Loading libraries"

While any library (music or video) is still loading, the loading screen shows "Loading libraries"
instead of "Loading movies and the music library" (`boot.js`, `paintClientBoot`).

## 2026-10-20 — All libraries load at startup; music library timing

- **Parallel startup loads:** the movies, TV shows and movie sets lists now all start loading as
  soon as the page starts, not after the loading screen has closed. The loading screen still waits
  only for the music library and the library on screen, so it does not get longer. Switching to
  another library is instant once its list has arrived.
- **Why it could not be done before:** the video loads shared one "latest request wins" counter, so
  a second load started while the first was in flight made the first discard its answer. Each
  library now has its own counter (`state.video.loadEpochs`); the shared one still cancels in-flight
  change refreshes. `preloadOtherLibraries` skips a list that is loaded or loading.
- **Music library timing:** the server logs `music library: N artists, artists …s, totals …s,
  filter counts …s, prepare reply …s` and `library list: artists query …, albums query …, building
  the list …` when the library takes over 3 s, so the 15 s music load can be pinned down from the
  next log. No change to the music queries yet.
- Checked in jsdom with the real page for all four start modes: each list is requested once, all
  are loaded, no boot step is left pending. Not run against your server.

## 2026-10-20 — Slow start, the real cause: path display did ~24,000 disk checks per list load

Your second log: `movie list: 5964 movies, 65.0s to build`, with no `.nfo` check line, so the .nfo
check from the entry below was not the cost (it stays; it is harmless and avoids repeat reads).

- **Cause:** for every movie the list called `display_path` for its path, folder and .nfo. Each call
  checked the file exists, resolved links, stat'ed it and then stat'ed it again under every other
  mount. About four calls a movie is roughly 24,000 checks on a network share on every load.
- **Fix:** `paths.display_path_fast` resolves the library folder once (kept for 10 minutes) and
  appends the rest of the path. The movie and TV lists and the duplicate check use it. Paths outside
  a library folder still take the full route. Links inside a library folder are no longer followed
  in these lists (single-item views still use the full `display_path`).
- **Timing:** `movie rows: query …, paths and fields …, duplicate check …, .nfo check …` is logged
  when the build takes over 3 s, so any remaining slow phase is named.
- Tests: `tests/test_display_path_fast.py`. Not measured on your library; the figure to look for in
  the next log is the `movie list:` line.

## 2026-10-20 — Slow start: the movie list re-read every changed .nfo on each load

Your startup log showed the movie list taking 51 s of a 53 s boot.

- **Likely cause:** every movie showing the purple "changed" pill had its `.nfo` read from disk and
  compared again on every list load (the check that clears pills whose difference is invisible).
  Files that really differ never clear, so the same files were re-read each time, which is slow on a
  network share. Rows already confirmed as really different are now remembered for 10 minutes
  (while their fingerprints are unchanged) and skipped; a row whose difference disappears still
  clears, and an edit in the app is re-checked at once (`nfo_digest._clear_hidden_changes`).
- **Timing in the log:** the server now logs `movie list: N movies, X s to build … Y s to prepare the
  reply` when the list takes over 3 s, and `nfo check (movies): read N .nfo files in X s` when the
  check takes over 1 s. If the boot is still slow after this, those lines show which part it is.
- **Quieter boot warnings:** steps waiting behind a library load are no longer reported as "has not
  started"; only a step that is running too long, or one left over after the libraries finish, is.
- Tests: `tests/test_nfo_confirm_cache.py` (read once, re-check on change, expiry, hidden changes
  still clear). The speed-up itself was not measured; I could not run your library here, so the cause
  is the most likely one from the code, not a confirmed one.

## 2026-10-20 — Startup problems are now reported to the server log

A script that fails to load or a startup step that stalls used to leave only a line in the browser
console. Now `docker logs` shows it too.

- **Browser to log:** new `POST /api/v1/client-log` writes the browser's report as `browser: …`
  under the `curator.client` logger. Rate limited (40 a minute), truncated, newlines removed.
- **What is reported** (`static/js/boot.js`): any script error with file and line (a syntax error
  such as the `scrape.js` one names the file and line), a file that failed to load, unhandled
  promise rejections, every `[boot] … error` from the startup calls, a step that is still waiting
  after 10 s (once per step, naming the step and whether it started), and a one-line summary with
  the time each step took when the app opens.
- **On screen:** after 10 s the loading screen adds a line "Still waiting for: scan (12.4s)", so the
  stuck step is visible without opening the console.
- Tested the reporting in jsdom and the endpoint's limit and newline handling; not against a
  running server.

## 2026-10-20 — Loading screen stuck on "Checking scans" (syntax error in scrape.js)

- **Cause:** `static/js/video/scrape.js` declared `const card` twice in `chooseVideoArt`, a
  syntax error. The browser dropped the whole file, so `bindVideoScrape` did not exist; `initVideo`
  threw before it reached the scan check, the "scan" boot step was never finished and the loading
  screen never closed. The server was healthy, as the log showed.
- **Fix:** the duplicate line is removed.
- **Guard:** `tests/test_js_syntax.py` runs `node --check` on every script (skipped without node).
- **No timers:** the 20 s / 2 min boot timeout added earlier is removed again, because a large
  library can legitimately take longer. Instead, if a startup call throws, the steps it would have
  started (which can never finish) are marked done so the screen opens, and the error is logged to
  the browser console. A slow step is always waited for.

## 2026-10-20 — Startup hang on "Checking scans" resolved with resilient boot watchdog

- **Root Cause:** In [`app/static/js/boot.js`](file:///c:/Users/gideo/Documents/claude/curator/app/static/js/boot.js), boot step timeouts were only created when `watchBoot(id)` was explicitly invoked. If initialization exited early or threw before reaching `pollVideoScan()` / `pollVideoFiles()`, the `scan` and `files` steps remained `started: false, done: false` forever without any watchdog timer running, locking the boot screen indefinitely on `"Checking scans"`.
- **Automatic Per-Step Watchdogs:** In `beginClientBoot()`, every registered boot step now starts an individual safety watchdog timer (3.5 s for quick steps, 20 s for library steps). Even if `watchBoot(id)` is never called or a request stalls, the step is automatically marked done.
- **Global Boot Fallback:** Added a global 8-second safety timeout in `beginClientBoot()`. If any step has still not completed by 8 seconds, all steps are forced done and `completeBootBar(true)` dismisses the boot screen immediately, preventing any infinite lock-in.
- **Conditional Video Steps:** `scan` and `files` steps in `bootClientSteps()` are now only registered when `media` is `movies`, `tv`, or `sets`, so music startup is not burdened by video job checks.
- **Fail-Safe Initializers:** In `startCurator()`, each subsystem initializer (`loadSettings`, `loadStoredMatches`, `pollSystem`, `initVideo`, `initMedia`, etc.) is wrapped in `try / catch` so a failure in one cannot abort subsequent startup tasks.
- **Guarded DOM and Bindings:** In `initVideo()`, guarded `video-columns-menu` lookups, wrapped all binding functions in `try / catch`, and ensured `pollVideoScan()` and `pollVideoFiles()` are safely invoked even if UI elements are absent. In `loadVideo()`, wrapped `renderVideoList()` in `try / catch` to ensure promise resolution.

## 2026-10-20 — Artwork lookup modal: restored download button, full-height flexing, and connected backend endpoints

- **Artwork Lookup Modal Download Button**: Restored the download button and icon on the lower left of each artwork card in the artwork modal ([`videoArtCard()`](file:///c:/Users/gideo/Documents/claude/curator/app/static/js/video/scrape.js#L428-L442)). All artwork looked up in the modal now displays the download button overlay with its download icon.
- **Full-Height Flexing**: Made both video and music artwork lookup modals flex to utilize the full height of the window, only constrained by the top title/settings bar and the footer task bar (`--chrome-top` and `--chrome-bottom`). Overrode the `45vh` body cap and container width constraints in [`app/static/app.css`](file:///c:/Users/gideo/Documents/claude/curator/app/static/app.css#L3315-L3339) so the artwork grid and side-by-side comparison stage expand to fill all vertical space.
- **Artwork Choices Endpoints**: Added `GET /api/v1/artwork/choices/{kind}/{item_id}` and `POST /api/v1/artwork/choices/{kind}/{item_id}` in [`app/curator/routes/scrape.py`](file:///c:/Users/gideo/Documents/claude/curator/app/curator/routes/scrape.py#L425-L449) backed by `art_pick.choices()` and `art_pick.choose()`, allowing looking up remote artwork and saving selections directly from the modal.

## 2026-10-20 — Synced-lyrics editor gets the sync window's tools


The synced-lyrics editor (the pencil in the player bar) now works like the subtitle sync window.

- **Shift all:** ±100 ms and ±1 s buttons and a typed amount (`-1.5`, `1.5 s`, `300 ms`; a bare
  number is seconds). It replaces the old "Global offset" box, which only applied on save.
- **Fit with anchors:** select a line, play the song and press *Mark at playhead* (or **M**). One
  anchor shifts every line; more anchors fit them. Modes: Linear (offset and stretch), Piecewise
  and Steps (same maths as the subtitle window). The result is previewed live while the song plays;
  *Apply fit* keeps it, *Clear anchors* drops it.
- **Undo** (button or Ctrl+Z) for every change; **Enter** edits the text of a line; **Find** jumps
  to the next line containing some text.
- **Restore previous save:** a save keeps the file it replaced as `<track>.lrc.sync-backup` (one level).
- **Sync OK** saves, marks the lyrics Synced (shown in the editor header while the file is
  unchanged) and closes. Reuses the subtitle `subtitle_sync_marks` table; no schema change.
- New endpoints `POST /api/tracks/{id}/lyrics/revert` and `/lyrics/synced`; `GET` also returns
  `has_backup` and `synced`.
- Automatic sync (alass) is not offered: it compares subtitles to speech in a video and cannot
  align lyrics to music.
- Tested the browser logic with jsdom (shift, anchors, undo, edit, find, Sync OK). The new
  endpoints were not run against a database here.

## 2026-10-20 — .nfo "changes" that could not be saved, and a purple pill that stayed

A movie whose database edition was the placeholder `NONE` showed a difference
(Edition: file "Standard Edition" / database "NONE"), but Write .nfo said the file was already up
to date and the purple pill never cleared.

- **Cause:** the writer treats `NONE` as "no edition" and writes `<videoassettitle>Standard
  Edition</videoassettitle>`, so its output equalled the file. The diff compared the raw `NONE`
  with that default title instead. And when the output equals the file, nothing was written and
  the stored fingerprint (the pill) was never refreshed.
- **Diff:** `NONE` now counts as no edition, and a `videoassettitle` of "Standard Edition" (the
  writer's default) is not read as an edition the user set (`curator/video/nfo.py`).
- **Writer:** when the .nfo already holds exactly what would be written, the fingerprint is stored
  anyway, so the pill clears (movies, movie sets, seasons; shows and episodes already did).
  `nfo_write.same_text`.
- Tests: `tests/test_nfo_edition.py`. The pill and the write were not run against a database here.
  The pill should clear the next time the movie list loads.

## 2026-10-19 — The chosen metadata provider is asked first (movies: Trakt and TheTVDB)

A movie matched to a Trakt-only title failed with "No confident TMDB match": the movie scrape
always asked TMDB first.

- **Trakt or TheTVDB chosen as the source** (the scrape's primary provider, the Settings order, or
  the per-movie preferred source): that provider is asked first and its values win. TMDB is then
  asked and only fills in what the first lacks (artwork, collection, cast photos...). If TMDB has no
  entry, the scrape carries on with the chosen provider and the log says so; the TMDB id that does
  not exist is dropped for that scrape. Trakt supplies title, year, release date, plot, tagline,
  runtime, certification, genres, country, language, crew, cast (no photos), trailer and rating
  (`TraktRatings.movie_base`, no artwork); TheTVDB already returned the full movie including artwork.
- **TMDB chosen as the source** behaves as before. Only when TMDB has nothing at all does it try
  Trakt, then TheTVDB, before giving up.
- **OMDb** still needs TMDB to find the movie (it only has ratings).
- Trakt needs the client id (Settings, Trakt) and a Trakt or IMDb id on the movie. TheTVDB needs its
  key and finds the movie from its TVDB id, the IMDb id, or the title.
- Not done: TV shows still ask TMDB first. Tests: `tests/test_trakt_base.py` with a fake Trakt; the
  full movie scrape was not run (it needs the database), so please re-run your movie.

## 2026-10-19 — Synced status on a subtitle

- **Sync OK** now also records that the subtitle has been checked and is in sync. The Subtitles table
  shows a green "✓ Synced" next to that subtitle's Sync icon (hover for the date). A VobSub shows it
  on its single row.
- The mark is kept in a new table `subtitle_sync_marks` (path, modification time, date) and only
  counts while the file still has that modification time, so a later Save, Revert, edit or
  replacement of the subtitle clears it. Close (as opposed to Sync OK) leaves the status alone.
- `POST /subs/synced`; `curator/video/sync_marks.py`; the status is added when the file is loaded for
  the info pane (`store._file`). Tests in `tests/test_sub_sync.py`.
- Not verified here: the schema change against a real database, and the badge in a browser.

## 2026-10-19 — Sync OK button deletes the temporary video copy

- New yellow **Sync OK** button in the sync window's header. It closes the window and deletes the
  cached preview copy of that video (`/config/preview/<hash>.mp4`), so it is no longer there the
  next time you open the window (it is simply rebuilt if you open it again). The original video
  is never touched. A copy that is still being built is left alone.
- `POST /subs/video-discard`; `preview_proxy.discard()`; tests in `tests/test_sub_sync.py`.
- **Close** still keeps the copy, so reopening the window is instant. The copies are also trimmed
  by the size limit under Settings, Files, Subtitle sync.

## 2026-10-19 — Sync automatically button is yellow

- The **Sync automatically** button in the sync window is now yellow (`.btn-auto-sync`) so it stands out from the grey buttons.

## 2026-10-19 — Automatic sync no longer throws off a subtitle that is already in sync

Reported: automatic sync moved a subtitle that was already correct. alass has no confidence score,
and when the audio gives it little to go on (music, little speech, a different cut) it can still
return a confident-looking large shift. Changes:

- **Fine-tune is now the default** (`mode: "fine"`): no cut-splitting, and any proposal that moves
  a line more than 5 s is refused with an explanation instead of being applied. The other choices,
  *One shift, any size* and *Allow cuts, any size*, are explicit.
- **Already in sync is recognised**: a single offset under 0.1 s is reported as "already matches"
  and nothing is changed.
- The refused or unchanged result is also what the Jobs entry says. `POST /subs/auto` takes
  `mode` (fine | shift | cuts) instead of `split`.
- Tests added for the refusal limit, the unchanged case, and real alass runs on an already-synced
  file (unchanged) and a 20 s shift (refused in fine mode). I could not reproduce your file here
  (no real speech to test with), so what actually fooled alass on it is not known. If it still
  gets a synced subtitle wrong within 5 s, tell me the file type and how far off it was.

## 2026-10-19 — Automatic subtitle sync (alass), including VobSub and PGS

- **Sync automatically** in the sync window, and on the OCR screen of a picture subtitle. alass
  matches the subtitle's timing to the speech in the video and the result is turned into anchors:
  one anchor for a constant error, two for a frame-rate drift, and one per stretch for a cut
  release. Nothing is written until **Save**, and the live preview shows the proposal first.
  *Allow cuts* / *One shift for the whole file* picks alass's split mode.
- **Picture subtitles need no OCR for this.** alass only needs timings, so a throwaway `.srt` is
  built from the VobSub/PGS timings (text is just the line number). Save then retimes the pictures
  as usual.
- **New "steps" fit** (`sub_sync.transform_steps`, `segments_for`, `effective_mode`): every stretch
  between anchors gets its own constant offset and is not stretched, which is what a cut file needs
  (Piecewise interpolates between anchors instead). Works for text and picture subtitles.
- New `curator/video/sub_auto.py` (run, derive anchors, background job, cancel), endpoints
  `POST /subs/auto`, `GET /subs/auto-status`, `POST /subs/auto-cancel`; Jobs panel entry
  "Automatic subtitle sync"; `alass` added to `/health` tools and the Settings cache block.
- **Dockerfile** installs the static alass 2.0.0 binary on amd64 and skips it, with a message, on
  other CPUs (the Automatic button is then hidden).
- **README**: advice to move ARR-managed movies and shows in Radarr/Sonarr (they send webhooks),
  and a note that Move to… takes the whole folder with it.
- **Tests.** `tests/test_sub_auto.py`: deriving anchors (offset, noise, drift, cut, dropped lines),
  the steps maths, and real alass runs for a text subtitle and a VobSub (skipped without alass).
  The modal's automatic flow was run in the DOM harness. Verified here with alass 2.0.0 on
  synthetic subtitle pairs and a generated video with gated noise (offset found to within ~120 ms).
  Not tried: real speech, a real movie, the Docker build.

## 2026-10-19 — Sub sync: cache limits, Jobs, shift buttons, Bazarr scan, pair-safe normalize

- **Cache limits.** `/config/preview` (video copies) and `/config/ocr` (recognised text) now have
  size caps, default 5 GB and 100 MB, 0 = no limit (`preview_cache_gb`, `ocr_cache_mb`). The least
  recently used files go first, after each build and each OCR run; stale half-written files are
  removed. Files are touched when used so what you open stays. New `curator/video/cache_store.py`,
  `GET /subs/cache`, `POST /subs/cache/clear`.
- **Settings, Files tab, Subtitle sync** (new block; the notify checkbox moved here from the TV tab):
  limits, current sizes with Clear buttons, tesseract status and installed OCR languages.
- **Jobs panel.** OCR runs ("Subtitle OCR") and preview-copy builds ("Video preview") are listed as
  jobs with progress, and as completed, cancelled, or failed afterwards. New
  `curator/video/work_track.py`; it never fails the task it mirrors.
- **Shift all lines** in the sync modal: ±100 ms / ±1 s buttons and a typed amount (`+2.5`, `250ms`).
- **Modal notes.** A multi-language VobSub says only the first stream is shown and that Save moves
  all of them; picture subtitles say each picture keeps its own on-screen length.
- **Bazarr.** After a sync or export, with the notify setting on, Curator now calls Bazarr's
  `scan-disk` for the movie (Radarr id) or show (Sonarr series id). No path mapping needed. This
  replaces the earlier claim below that Bazarr would notice the changed file by itself.
- **Normalize subtitles keeps a VobSub pair together**: the `.idx` and `.sub` are renamed together,
  or neither is when a target name is taken (a failed second rename undoes the first). Rename files,
  Move and Delete already took both files because they match by name prefix.
- `docker-compose.yml.example` shows the `TESSERACT_LANGS` build argument.
- **Tests.** New `tests/test_sub_sync.py`: the fit maths, text save/backup/revert/edit/CRLF, VobSub
  pair rename, the ffprobe decision, cache trimming. The modal (shift, Piecewise toggle, cue edit,
  save payload) was also exercised in a DOM harness; that harness needs jsdom and is not in the repo.
  Not run here: the Docker build, a real Bazarr, the Jobs panel against a live database.

## 2026-10-19 — Brand icon mapping for Nordic networks & Matrix Studio/Network columns

- **Network icon mapping for Nordic broadcasters**:
  - Mapped `tv2.png` to TV2, TV 2, and channel variants (TV 2 Norge, TV2 Play, TV 2 Direkte, etc.).
  - Mapped `nrk.png` to NRK, NRK1, NRK 1, NRK2, NRK 2, NRK3, NRK 3, and related channels (NRK Super, NRK P3).
  - Mapped `tvnorge.png` to tvnorge, tv norge, and TVN variants.
  - Mapped `viaplay.png` to viaplay, via play, and regional variations (viaplayno, viaplayse, viaplaydk).
- **Matrix table columns: Studio (Movies) & Network (TV Shows)**:
  - Added **Studio** column to the Movies matrix table defaults.
  - Added **Network** column to the TV Shows matrix table defaults (replacing the movie-specific "Set" column).
  - Dynamically labels the column header and column picker menu as "Network" in TV Shows mode and "Studio" in Movies mode.
  - Automatically migrates existing saved table column layouts in localStorage so existing users see the columns immediately.
  - Propagates network/studio values down to seasons and episodes in the TV tree matrix view.

## 2026-10-19 — Sync window plays videos browsers cannot (XviD AVI, AC-3, HEVC...)


The sync window streamed the original file straight into the browser, so an XviD `.avi` (like the
DuckTales DVDRip) showed a dead player. Now the server decides:

- **`app/curator/video/preview_proxy.py`** (new) - probes the file with ffprobe. H.264 8-bit /
  VP8 / VP9 / AV1 with AAC / MP3 / Opus / Vorbis / FLAC audio in MP4 / MOV / Matroska / WebM plays
  as it is. Anything else gets a 360p H.264 + AAC MP4 built once with ffmpeg in the background,
  cached under `<config>/preview/` and reused. Same timeline as the original (no trim, no
  frame-rate change), so anchors marked in the copy are right for the real file. One build at a
  time; the original is never touched.
- **`app/curator/routes/sub_sync.py`** - `POST /subs/video`, `GET /subs/video-status`,
  `GET /subs/proxy` (range-aware, so seeking works).
- **`app/static/js/video/sub_sync.js`** / **`index.html`** - the modal asks the server first and
  shows "a small copy is being prepared (n%)" under the player until it is ready, or the reason
  it failed.

The first open of a file that needs a copy waits for the build (roughly a minute or two for a
DVD-length episode, depending on the CPU); after that it opens at once.

## 2026-10-19 — VobSub listed once; picture-subtitle OCR starts by itself

- **One row per VobSub.** The Subtitles table and the language/flags editor on the info pane no
  longer list the `.idx` and the `.sub` as two rows; the pair is shown once under the `.sub` name
  (`externalSubtitleRows()` in `app/static/js/video/common.js`). The Sync icon on that row opens
  the pair.
- **Renaming a VobSub keeps the pair together.** Setting the language or flags on that row
  (`subtitles.retag`) now renames the `.idx` and `.sub` to the same new name, and refuses before
  moving anything if the partner's new name is already taken. Before, only the file in the row
  was renamed, which would have split the pair.
- **The sync modal starts OCR on open** instead of waiting for a Run OCR click that was easy to
  miss (it looked stuck on "367 pictures found"). A cancelled earlier run resumes; an error stays on
  screen with the button; Redo OCR still waits for you.

## 2026-10-19 — Movies matrix: removed folder/file name from multi-edition version rows

- Removed folder and file name text (`versionFileLabel`) from expanded multi-edition movie rows in [`movieTitleHtml()`](file:///c:/Users/gideo/Documents/claude/curator/app/static/js/video/movies.js#L311-L336).
- Each version row now displays cleanly as `Title (Year · Edition)` (e.g. `Alexander (2004 · Final Cut)` and `Alexander (2004 · Ultimate Cut)`) without appending the raw folder name or release filename after the title.

## 2026-10-19 — Sub sync: VobSub / PGS picture subtitles (OCR)

Picture subtitles (`.idx` + `.sub` VobSub and `.sup` PGS) now open in the same sync modal as text
subtitles. Their lines are pictures, so they are recognised with tesseract first (one background
job, cached, resumable); after that, search, anchors, linear/piecewise fit and the live preview work
as before. **Save** retimes the picture subtitle in place (the pictures are never re-encoded) and
**Export SRT** writes the recognised text as a text subtitle.

- **`app/Dockerfile`** - installs `tesseract-ocr` plus the languages in the new `TESSERACT_LANGS`
  build argument (default eng nor swe dan fin deu fra spa ita nld por pol).
  **Needs `docker compose build`** - a restart alone does not add tesseract.
- **`app/curator/video/sub_ocr.py`** (new):
  - VobSub: `.idx` parser (palette, `delay:`, every `id:` stream, timestamp lines kept for an exact
    rewrite), MPEG program-stream reader for the `.sub` (MPEG-2 and MPEG-1 PES headers, system
    headers and padding skipped, SPUs spanning several sectors), DVD sub-picture control
    sequences (palette, alpha, area, interlaced RLE) and timing from the SPU start/stop dates.
    A stop time later than the next picture (some encoders write "until further notice") is clamped
    to the next picture, and no cue lasts over 60 s.
  - PGS: segment scanner (PCS/PDS/ODS/END, epoch handling, objects split over several ODS
    segments, palette-only fades are not new cues) and RLE decoder.
  - Bitmaps become black-on-white greyscale by brightness x opacity (text black, outline and
    background white, anti-aliasing kept), upscaled for tesseract. Tries page-segmentation 6, then
    7, then inverted, and cleans the result (`|` becomes `I`).
  - OCR job: one at a time, a thread pool of up to 4 tesseract processes, progress saved every 25
    lines, cancel/resume, a second file is refused with a clear message, and 10 failures in a
    row with no success stops the job with an error instead of "recognising" nothing.
  - Cache in `<config>/ocr/`, keyed by the pictures (the `.sub` file, or the `.sup` path + size),
    never by the timestamps, so a retime keeps the recognised text.
  - Retime: `.idx` timestamp lines (all language streams) or the PTS/DTS of every `.sup` segment,
    in place, after the usual `.sync-backup`; a failed write restores the backup.
  - Language: `.idx` `id:` or a language token in the file name, mapped to a tesseract language;
    falls back to English with a note when that language pack is not installed.
- **`app/curator/video/sub_sync.py`** - `read()` hands `.idx`/`.sup`/`.sub` to `sub_ocr`; new
  `retimer(anchors, mode)` (the same maths as `apply` / `apply_segments`, as a function of ms);
  `is_image()`; `.idx` and `.sup` added to `SUPPORTED_EXTS`.
- **`app/curator/routes/sub_sync.py`** - a `.sub` path resolves to its `.idx`; sync/preview on a
  picture subtitle retimes without touching text; new `POST /subs/ocr`, `GET /subs/ocr-status`,
  `POST /subs/ocr-cancel`, `POST /subs/export-srt`. The post-save library update also fires
  after an SRT export when `sub_sync_notify` is on.
- **`app/curator/routes/system.py`** - `tesseract` added to the tools in `/health`.
- **`app/static/js/video/sub_sync.js`** - OCR panel (language picker, Run / Resume / Cancel, progress
  bar, polling every 1.5 s, Back to the lines), **Export SRT** (with a replace confirmation when the
  `.srt` exists), **Redo OCR**, picture-subtitle note; Save is anchor-only for pictures and keeps
  text edits for Export SRT. Opening a file now also resets edits, search and the piecewise
  choice left over from the previously opened file.
- **`app/static/js/video/common.js`** - the Sync icon appears on `.idx` and `.sup` rows, and on a
  `.sub` row when its `.idx` is listed too.
- **`app/static/app.css`** - OCR panel and progress bar.
- **`tests/test_sub_ocr.py`** (new, 14 tests) - builds real VobSub (2048-byte MPEG-PS sectors,
  RLE-encoded SPUs, `.idx`) and PGS files from rendered text, then checks decoding, timing, OCR,
  in-place retime + revert, the cache surviving a retime, SRT export, the one-job rule and the
  open-ended stop time. The fixtures were also checked with ffmpeg's own VobSub and PGS decoders,
  and a `.sub` produced by ffmpeg's DVD-subtitle encoder and muxer was read and recognised.
- **`README.md`** - new "Syncing external subtitles" section (it covers text subtitles too, which
  had no README section), tesseract and `TESSERACT_LANGS` in Running, and the split-notify setting.

Fixed in the same change (found by running the routes through a test client, which the previous
sub-sync round had not done):

- **Saving a text subtitle with Piecewise on failed with HTTP 500.** The sync response carried
  `scale` and `offset_ms` as NaN (piecewise has no single pair), and NaN is not valid JSON. The
  file *was* written before the error, so a retry would have saved on top of the backup. The
  response now sends `null` for both. (`app/curator/routes/sub_sync.py`)

Not verified here: a Docker build (tesseract is installed in the dev environment but the image was
not rebuilt) and a real-world disc rip (the NAS file was not reachable). Note that one detail
is by design: a VobSub keeps each picture's own on-screen duration when scaled by a framerate fit.

## 2026-10-19 — Music top bar: shortened AcoustID button label

- Abbreviated the button label from `AcoustID match` to `AcoustID` in [`app/templates/index.html`](file:///c:/Users/gideo/Documents/claude/curator/app/templates/index.html#L68) to shorten the button width in the music header controls area while preserving its full explanatory tooltip (`title="Match the open album with MusicBrainz and AcoustID"`).

## 2026-10-19 — Season studio icons & TV shows top bar stats cleanup

- **Studio Icons on Seasons**: Seasons now display their studio/network logo on the top right of the hero header, consistent with TV shows and episodes:
  - Added `season["network_icons"] = show["network_icons"]` in `show_detail()` in [`app/curator/video/store.py`](file:///c:/Users/gideo/Documents/claude/curator/app/curator/video/store.py#L1075).
  - Wrapped season title and episodes count row in `brandRow(head, (season && season.network_icons) || (show && show.network_icons))` in `renderSeasonInfo()` in [`app/static/js/video/tv.js`](file:///c:/Users/gideo/Documents/claude/curator/app/static/js/video/tv.js#L497-L503).
- **TV Shows Top Bar Stats**: Removed the disk size (e.g. `252.53 TB`) and runtime (e.g. `41,291 h`) pills from the top header bar for TV Shows in [`paintMediaTotals()`](file:///c:/Users/gideo/Documents/claude/curator/app/static/js/core/media.js#L112-L118), keeping only `${shows} shows · ${seasons} seasons · ${episodes} episodes` so the header remains compact.

## 2026-10-19 — Info panes: removed redundant artwork download buttons from posters and gallery cards

- **Artwork Gallery Cards**: Removed the overlay download button (`artDownloadButton`) from each artwork thumbnail in [`artGallery()`](file:///c:/Users/gideo/Documents/claude/curator/app/static/js/video/common.js#L990-L1005). The artwork in this gallery is already downloaded and present on disk; the button redundantly re-triggered the item-wide fetch routine, which is already available as "Download missing artwork" above the gallery.
- **Movie, TV Show, Season, Episode & Set Posters**: Removed `${artDownloadButton(owner)}` from [`artFrame()`](file:///c:/Users/gideo/Documents/claude/curator/app/static/js/video/common.js#L631-L642). Posters now display only the click-to-swap behavior, missing sash (if applicable), and zoom preview button, avoiding duplicate controls since the dedicated "Download missing artwork" button is right underneath the poster column.
- **Music Verification**: Verified that artist thumbs and album covers in Music already omit overlay download buttons and rely cleanly on the action buttons below them ("Download missing artist artwork" and "Download missing album artwork").

## 2026-10-19 — Top Header: moved library stats between media switch and Scan button for all media types

- **Relocated Library Stats**: Moved the library stats pills (`#video-library-stats`) from the video toolbar filter box into the top header (`.header-pills`) between the media type switch buttons (`Music`, `Movies`, `Sets`, `TV Shows`) and the `Scan` button.
- **Unified Across All Media Types**:
  - **TV Shows**: `${shows} shows` · `${seasons} seasons` · `${episodes} episodes` · `${size}` · `${runtime}`
  - **Movies**: `${movies} movies` · `${size}` · `${runtime}`
  - **Sets**: `${sets} sets` · `${movies} movies`
  - **Music**: `${artists} artists` · `${albums} albums` · `${tracks} tracks` (size and hours omitted to keep header compact)
- **Backend Music Totals**: Enhanced `library.totals()` in `app/resonance/library.py` to calculate total track `bytes` and `seconds` so music displays disk size and total duration alongside artist/album/track counts.
- **Responsive Header Styling**: Styled `.video-library-stats` with `flex-wrap: nowrap`, compact pill sizing, and horizontal scroll fallback with hidden scrollbars so the header row stays clean and single-line across all window widths.

## 2026-10-19 — Movies & TV library trees: UI Elements settings and year/edition display

- **Movie Tree Titles**: Movies in the library tree now display their release year and edition in brackets beside the title (e.g. `(1992 · Assembly Cut)` or `(1992)`) styled in a slightly darker font color using `<span class="muted">` across all 12 themes.
- **Movies UI Elements Settings**: Added a new **UI Elements** section under Settings → Movies with toggles (all enabled by default):
  - Show release year in title (`ui_movie_year`)
  - Show edition in title (`ui_movie_edition`)
  - Show date added (`ui_movie_date_added`)
  - Show processed/unprocessed checkmark (`ui_movie_processed`)
- **TV Shows UI Elements Settings**: Added a new **UI Elements** section under Settings → TV with toggles (all enabled by default):
  - Show year in title (`ui_tv_year`) — also formatted in slightly darker font color consistent with movies
  - Show number of seasons (`ui_tv_seasons`)
  - Show number of episodes (`ui_tv_episodes`)
  - Show date added (`ui_tv_date_added`)
  - Show processed/unprocessed checkmark (`ui_tv_processed`)
- **Backend Persistence**: Updated `config.normalize` in `app/curator/video/config.py` to persist all 9 UI settings with boolean defaults.

## 2026-10-19 — Header: replaced Duplicates text button with duplicate vector icon

- Replaced the top row text button `Duplicates` in [index.html](file:///c:/Users/gideo/Documents/claude/curator/app/templates/index.html) with an icon button (`.icon-btn` with `id="duplicates-btn"`).
- Styled with a clean SVG vector reproducing the uploaded example: a primary framed card on the left, an open clone card emerging on the right, and two right-pointing dashed transfer arrows connecting them.
- Preserves `data-action="open-duplicates"`, `title="Duplicates"`, and `aria-label="Duplicates"`.

## 2026-10-19 — Header: replaced Language text button with speech bubble icon

- Replaced the top row text button `Language` next to `Duplicates` in [index.html](file:///c:/Users/gideo/Documents/claude/curator/app/templates/index.html) with an icon button (`.icon-btn` with `id="lang-btn"`).
- Uses a vector SVG styled after the uploaded reference: a solid rounded speech bubble with a bottom-right tail, featuring cutouts for the Latin capital letter **"A"** and the Chinese character **"文"** via `fill-rule="evenodd"`.
- Retains `data-action="lang-open"`, accessibility title, and `aria-label="Language defaults"`.

## 2026-10-19 — Library queue: consistent update result messages across all players

- **Kodi**: `run_library` and `run_kodi` in `app/curator/notify.py` now return `f"Kodi updated {count} folder{'s' if count != 1 else ''}."` on folder scans, and `f"Kodi finished scanning the {noun} library."` on full scans. Previously returned `None`, leaving Kodi's Result column showing only "Finished" without the folder count.
- **Plex**: `_plex_job` now returns `f"Plex updated {count} folder{'s' if count != 1 else ''}."` to match Jellyfin, Emby, and Kodi.
- **Consistent Fallback**: Added a fallback in `app/curator/library_queue.py` (`_finish_row`) ensuring every player update records a clean `{Player} updated {N} folder(s).` or `{Player} finished scanning the {noun} library.` entry in the history work log.

## 2026-10-19 — Duplicate & Upgrade modals: ARR provider icons, full-width filename, full-height modal flex

### ARR Provider Icons & ID Number
- Replaced text labels for ARRs (`Radarr <id>`, `Sonarr <id>`, `Lidarr <id>`) across duplicate and upgrade modals with their provider icons from `/media/providers/` (`radarr.png`, `sonarr.png`, `lidarr.png`) alongside the ID number in monospace font.
- Unmonitored/untracked copies render a muted `Not in` preceding the provider icon.
- Handled uniformly via `arrCopyLine(item)` in `app/static/js/music/tools.js` and styled with `.dup-arr` in `app/static/app.css`.

### Full-Width Filename Under Poster
- Removed the restrictive `max-width: 17rem` cap from `.video-dup-card .dup-name`, allowing the filename under the poster to use the full width of its pane.
- Added `overflow-wrap: anywhere; word-break: break-word;` for clean wrapping of long release filenames.
- Updated `.dup-facts` and `.video-dup-card .upgrade-path` to also utilize the full pane width (`width: 100%; max-width: none;`).

### Full-Height Modal Flexing
- Flexed `#duplicates-modal` and `#upgrade-modal` to expand to the full height of the window, constrained within `--chrome-top` and `--chrome-bottom`.
- Styled `#duplicates-modal .modal-content` and `#upgrade-modal .modal-content` with `height: 100%; max-height: 100%; display: flex; flex-direction: column;`.
- Styled `.modal-body` with `max-height: none; flex: 1 1 auto; min-height: 0; overflow-y: auto;`, and `#upgrade-actions` with `margin-top: auto; padding-top: 14px; flex: 0 0 auto;`.

## 2026-10-19 — Sub sync: cue text editing, piecewise fit, post-save library update

Three of the four deferred items from the sub-sync plan, implemented in one pass.

### Cue text editing

Each cue row in the sub-sync modal has an **Edit** button that swaps the text span for a
textarea. The textarea gets focus straight away and the Done button saves the change back
to in-memory state. Edited cues get a mauve left border and an italic accent-coloured
text so they stand out from the untouched rows. On Save the backend writes the new text
alongside the timings; the local edits map is then cleared so the modal reflects what is
now on disk.

- **`app/curator/video/sub_sync.py`** - `_rewrite_srt` and `_rewrite_vtt` now replace the
  body lines after the time line with `new.get("text")` when provided; `_rewrite_ass` sets
  `parts[9]` the same way. If no text is given the original body is preserved, so timing-
  only syncs still produce a byte-identical body.
- **`app/curator/routes/sub_sync.py`** - `SyncBody` and `PreviewBody` gained a
  `cue_edits: [{index, text}]` field. The sync endpoint applies the transform first and
  then overlays the text edits by index, so timing and text can be changed in the same
  Save without interfering with each other.
- **`app/static/js/video/sub_sync.js`** - `subSyncState.edits` map tracks per-cue text
  overrides across repaints; `subSyncState.editing` holds the cue index whose textarea is
  currently open. New `startSubSyncEdit` / `finishSubSyncEdit` handlers and the matching
  `sub-sync-text-edit` / `sub-sync-text-done` actions. The row renderer shows an edited
  badge and the Save button now also enables when edits exist (even with no anchors).

### Piecewise linear fit

A **Piecewise** checkbox appears in the header actions when there are two or more anchors.
When on, the sync endpoint fits one `(a, b)` per gap between consecutive anchors instead
of a single least-squares pair, so files whose drift resets between anchors (commercials
removed, reels concatenated, audio replaced mid-way) can be synced correctly end to end.

- **`app/curator/video/sub_sync.py`** - `transform_segments(anchors)` returns
  `[(sub_from_ms, sub_to_ms, a, b)]` with the first segment extending to -inf and the
  last to +inf, so every cue time lands in exactly one segment. `apply_segments(cues,
  segments)` picks the segment covering each cue's start time. Fewer than two anchors
  falls back to the single linear fit, so callers can treat it uniformly.
- **`app/curator/routes/sub_sync.py`** - `SyncBody.mode` of `"piecewise"` (default
  `"linear"`) routes to the segment pipeline. The response reports the mode it actually
  used (if the user asked for piecewise with only one anchor it quietly degraded).
- **`app/static/js/video/sub_sync.js`** - The toggle is a `<input type="checkbox">` with a
  `change` listener attached in `paintSubSync` / `repaintSubSyncHeader` (not through the
  click dispatcher, because label-synthesised clicks read the pre-toggle state). Preview
  and Save both send the current mode. The header text updates: "Piecewise fit: N
  segments" when on, with a hint about when to use it.

### Post-save library-update notify

New setting under TV shows, off by default: **After syncing an external subtitle, send
library update to the players**. When on, the sync route calls `notify.request("video",
folders=[parent folder], ...)` after the write. That goes through the same path as the
split-notify I added last turn, so the Kodi stale-prune step runs on the follow-up scan
and Kodi/Emby/Jellyfin/Plex re-read the retimed sidecar. A configured Bazarr sees the
mtime change and leaves the sub alone on its next pass.

- **`app/curator/routes/sub_sync.py`** - `_after_sync_notify(path, cfg)` fires after a
  successful write, opt-in via the setting, best-effort (any failure is logged and
  swallowed - a notify problem never fails a saved sync).
- **`app/curator/video/config.py`** - `sub_sync_notify` default (false) + validator.
- **`app/static/js/core/video-settings.js`** - Checkbox below the split-notify one,
  bound to `cfg.sub_sync_notify`, saved through the usual video-settings collector.

### VobSub / PGS OCR

Done in the "Sub sync: VobSub / PGS picture subtitles" entry at the top of this file.


## 2026-10-19 — External subtitle sync

### Quick search in the sub-sync modal

A search box in the right pane filters the cue list by phrase, case-insensitive. The match
is highlighted in each row. The box is pinned so typing does not lose focus between
keystrokes - the list repaints under it while the input stays in the DOM. Anchoring and
Mark still rebuild the surrounding header too, so the mode line (offset / linear fit) and
Save state follow along; the search input survives those repaints via a dedicated DOM
slot that is never replaced.

- **`app/static/js/video/sub_sync.js`** - New `paintSubSyncList()` and
  `updateSubSyncSearch()`; `paintSubSync()` now sets up a stable `#sub-sync-search` input
  and a `#sub-sync-header-slot` and triggers only `paintSubSyncList()` as the user types.
  Anchor toggles / Mark now use `repaintSubSyncHeader()` + `paintSubSyncList()` instead of
  the full `paintSubSync()` so the search text and focus persist.
- **`app/static/app.css`** - `.sub-sync-search-wrap` input styling + `<mark>` highlight
  colour derived from the accent token so it reads cleanly in both themes.


New feature. A speech-bubble icon on each external text subtitle row in the Media info
panel opens a sync modal with the same two-pane layout as the split-episode modal: video
on the left, cue list on the right. The user picks cues, scrubs the video to where each
should appear, and clicks Mark; one anchor applies a constant offset, two or more apply a
linear fit (framerate-drift correction), three or more also show a middle-anchor drift
check. Live preview via a WebVTT track driven by the fitted anchors updates in the
player as the user works.

Format support: `.srt`, `.vtt`, `.ass`, `.ssa` (and `.ssa` same path as ASS). `.sub/.idx`
(image-based VobSub) is not offered - a dashed cell in the Sync column instead - because
raster frames cannot be retimed.

- **`app/curator/video/sub_sync.py`** - Parsers for SRT/VTT/ASS, `transform(anchors)` ->
  `(a, b)` via least-squares (1 anchor = constant offset, 2+ = full linear fit),
  `apply(cues, a, b)`, `anchor_drift(...)` for the middle-anchor validation, `rewrite()`
  that preserves everything in the file verbatim except the Dialogue:/-->/time fields,
  and `backup()` / `revert()` with a single `.sync-backup` sidecar per sub (overwritten
  on next save, so there is always exactly one undo and no indefinite accumulation).
- **`app/curator/routes/sub_sync.py`** - Routes under `/api/v1/subs`:
  `GET /subs?path=` reads cues; `GET /subs/raw?path=` streams for a `<track>`;
  `POST /subs/sync` applies anchors (preview: true returns transformed cues without
  writing; preview: false writes through the save pipeline);
  `POST /subs/revert` restores from backup; `GET /subs/preview-track?path=` returns the
  current file as WebVTT; `POST /subs/preview-track` returns the file as WebVTT with the
  user's anchors applied, for live overlay. All paths gated by `folders.servable()`.
- **`app/curator/routes/__init__.py`** - Router registered.
- **`app/templates/index.html`** - `#sub-sync-modal` added, same shape as
  `#episode-split-modal`. `video/sub_sync` added to the script load list.
- **`app/static/js/video/common.js`** - Media info Subtitles table gains a Sync column;
  external text subs get the speech-bubble icon with
  `data-action="sub-sync-open"` + `data-sub-path` + `data-video-path`. Non-text externals
  (`.sub`, PGS, etc) show a dashed placeholder with a tooltip explaining why.
- **`app/static/js/video/sub_sync.js`** - All UI state and controller logic. Anchors are
  tracked by cue index; marking replaces an existing anchor rather than duplicating. The
  live-preview `<track>` is re-fetched after every anchor change via
  `POST /subs/preview-track` and attached as `data-sub-sync="1"` so previous previews are
  cleaned up on each refresh.
- **`app/static/js/core/events.js`** - `sub-sync-*` actions routed through
  `SUB_SYNC_ACTIONS` (declared in `sub_sync.js`); click anywhere on a cue row (not on a
  button) selects it.
- **`app/static/app.css`** - `.sub-sync-list` / `.sub-sync-row` layout plus the two-pane
  modal sizing matching the split modal (`width: min(96vw, 1500px)`, `max-height: none`
  on the body, stacks under 1000px wide with the player capped at 34vh so the cue list
  keeps its room).

### Different-framerate hint

When the subtitle's apparent duration (last cue end) differs from the video's reported
duration by more than 2%, the modal shows an amber banner steering the user to the
2-anchor pattern (near the start AND near the end). This is a UI nicety; the fit still
works without it. Rolled in with v1 because the detection costs nothing - the subs are
already parsed.

### Not in v1

- `.sub` + `.idx` (VobSub) and PGS - needs OCR.
- Editing cue text - this is sync only.
- Piecewise linear between consecutive anchors (needed only for TV broadcasts with
  commercials removed; add later behind an "Advanced" toggle if asked).
- Bazarr notify after save - say if you want it; a one-liner.


## 2026-10-19 — TV Library: Episodes Inherit Banner in Prioritized Order

Episodes now inherit the artwork pane banner in the prioritized order requested:
1. Season's banner (`episode.season_artwork.banner`)
2. TV show's banner (`episode.show_artwork.banner`) if no season banner is available
3. Or fallback TV show landscape + TV show clearlogo (`episode.show_artwork.landscape` + `episode.show_artwork.clearlogo`)

- **`app/static/js/video/tv.js`**:
  - Added `episodeBannerArt(episode)`, `episodeLandscapeArt(episode)`, and `episodeClearlogoArt(episode)` helper functions implementing the prioritized resolution order.
  - In `renderEpisodeInfo(episode)`, passed the resolved `banner`, `landscape`, and `clearlogo` into `videoHero`, along with a dual fallback `[episode.season_artwork, episode.show_artwork]`.
- **`app/static/js/video/movies.js`**:
  - Updated `videoHero` to accept explicit `banner`, `landscape`, `clearlogo`, and array fallbacks.

## 2026-10-19 — Music Library: Albums Inherit Artist Landscape + Clearlogo Combo Fallback

When an artist banner is unavailable, the hero banner area falls back to displaying the artist landscape backdrop with the artist clearlogo overlaid on it. Albums now properly inherit this fallback combo:

- **`app/static/js/music/center.js`**:
  - Added `resolvedArtistAssets` helper to safely look up artist assets from `artist.assets` or `state.artistDetail.artist.assets`.
  - Added `albumLandscapeUrl(album, artist)` and `albumClearlogoUrl(album, artist)` so albums fall back to the artist's `landscape` and `clearlogo` when the album doesn't have its own.
  - Updated `renderAlbum()` to pass `albumLandscapeUrl` and `albumClearlogoUrl` into `infoBanner`.
- **`app/static/js/video/common.js`**:
  - Updated `infoBanner()` so that when `landscape` is rendered (in absence of `banner`), `clearlogo` is also rendered if available, creating the full landscape + clearlogo combo.
  - Updated `infoBannerFallback()` so that when a banner image fails and transitions to `landscape`, the `clearlogo` is dynamically appended into the hero banner.
- **`app/static/app.css`**:
  - Added `z-index: 1;` and a drop-shadow filter to `.info-banner .clearlogo` for crisp legibility when layered above the landscape image backdrop.

## 2026-10-19 — Four task-bar / split polish items

### Job chip opens the drawer in its default position

The drawer's own CSS pins it above the dock (`position: absolute; right: 0;
bottom: calc(100% + 8px)`). My earlier anchor-based positioning was overriding that with
inline `fixed` coords tied to the clicked chip, which put the drawer off-screen when the
activity bar sat near the bottom of the window. The anchored placement is gone; the chip is
still remembered on the drawer so clicking the same chip again toggles it closed.

- **`app/static/js/core/events.js`** — `placeJobsDrawer()` now only removes `.hidden` and
  clears any inline position/size left over from the previous shape; the CSS does the rest.

### Alert toast no longer dismisses on inside-click

Clicking anywhere on `#toast-pop` dismissed it, which made it impossible to select and copy
the alert text. The pattern is standard dialog behaviour now: a click INSIDE the toast is
left alone (text selectable), a click OUTSIDE the toast dismisses it.

- **`app/static/js/core/events.js`** — The `#toast-pop` early-return that fired
  `dismissToast` has been replaced with an outside-click check at the top of `onClick`.
- **`app/static/app.css`** — `.toast-pop { cursor: pointer }` removed; it is not a button.

### Split episodes while a scan is running queues instead of refusing

Clicking Split while a scan, scrape, file job or restore was running answered
"Wait for the running scan or file job to finish". Now the request is queued and the modal
closes with "Split episodes added to scan queue"; a background watcher drains the queue
once the system is idle.

- **`app/curator/video/split.py`** — New `_pending` list protected by `_lock`, drained by
  `_watch_pending`, and `start_many` now returns `{started, queued, message}` rather than a
  bare bool. The 409 AppError is gone; only an empty job list is still an error.
- **`app/curator/routes/split.py`** — Routes forward the dict with `split.status()`.
- **`app/static/js/video/tv.js`** — `runEpisodeSplits` notices `queued: true`, shows the
  message as a toast and closes the modal. The split watcher brings the split in on its
  own, and the user can reopen the episode later to see the result.

### After splitting, send a library update

New setting on the TV shows tab, off by default: when on, the split calls
`notify.request("video", folders=[parked folder], media="tv")` once the files are in place.
That goes through the same path as a Sonarr webhook, so the Kodi stale-prune I wired into
`_run_one` fires too — a user who deletes the parked `.split-source-eps-NN-NN.mkv`
afterwards gets Kodi's old row removed on the follow-up scan with no extra steps.

- **`app/curator/video/config.py`** — `scan_split_notify` default (false) + validator.
- **`app/curator/video/split.py`** — `_after_split_notify(results)` collects the parked
  folders of successful parts and calls `notify.request` when the setting is on. Failures
  are logged, not raised: a notify problem never fails a successful split.
- **`app/curator/video/split.py`** — `_apply_many` also kicks `_start_watcher()` after it
  finishes, so a queue that filled while this split ran drains straight away.
- **`app/static/js/core/video-settings.js`** — Checkbox added below the shortest-part
  input, bound to `cfg.scan_split_notify`, saved via the usual video-settings collector.


## 2026-10-19 — Webhook Queue Scan Synchronization and Targeted Episode Scraping

### 1. Wait for Music Scan & Scrape Before Handing Over to Player Queues
- **Issue**: Triggering the webhook queue (or clicking "Force scan now") for music immediately sent player library update requests (e.g. Kodi music scan) while Lidarr scanning and scraping had only just started. As a result, Kodi scanned folders before audio tags, MusicBrainz rematches, Cover Art Archive/Fanart.tv artwork, AcoustID fingerprints, synced lyrics, and NFO files were written to disk.
- **Root Cause**: In `app/curator/ingest.py`, `_music(rows, interrupt=False)` called `jobs.enqueue_lidarr(...)`, which queued albums into an asynchronous background worker (`_lidarr_worker`), and immediately called `notify.request("music", folders=folders, ...)`.
- **Fix**:
  - **`app/curator/ingest.py`**: `_music(rows)` now scans each album folder synchronously using `jobs.scan_lidarr_now(path, artist, label)`. Only after all albums have finished scanning, scraping, fingerprinting, lyric fetching, and NFO writing does `_music` call `notify.request("music", folders=folders, ...)` with the updated artist/album folders. If rows represent removals (`row.get("removed")`), scans are skipped while `clean=True` is properly passed to players.
  - **`app/resonance/jobs.py`**: Added `notify_players=False` parameter to `_run_lidarr_item`. In `_lidarr_worker()` (which handles direct `/api/webhooks/lidarr` webhook calls), `_run_lidarr_item` is called with `notify_players=True`, ensuring player library update queues are also only notified *after* `scanner.scan_release` finishes with `status == "completed"`.
  - **`tests/test_kodi_music_mapping.py`**: Added unit tests verifying `scan_lidarr_now` runs synchronously before `notify.request`, skips scanning for removed items, and passes correct folders and clean flags.

### 2. Targeted Episode Scraping on TV Webhooks
- **Issue**: When a TV webhook arrived for a newly downloaded episode (e.g. `Rocco Schiavone S04E01`), the scraper rescraped the entire TV show (all seasons and episodes), downloading metadata and artwork for every episode and taking several minutes instead of quickly scraping just the imported episode.
- **Root Cause**: `store.ids_under("tv", present)` resolved folder paths to TV show IDs, and `_video` passed the show ID to `_scrape("tv", ids)` and `_file_jobs("tv", ids)`.
- **Fix**:
  - **`app/curator/ingest.py`**: In `_video`, when `media == "tv"` and `rows` includes imported episode files (`row["files"]`), query `tv_episodes` for the corresponding episode IDs. If found, call `_scrape("episodes", ep_ids)` (which sets `job.only_episode_ids` and restricts scraping to only those imported episodes) and call `_file_jobs("tv", found, ep_ids=ep_ids)` to process subtitle cleanup targeted specifically to those episodes.
  - **`tests/test_kodi_music_mapping.py`**: Added unit test verifying `_video` with imported episode files calls `_scrape("episodes", ep_ids)` and `_file_jobs("tv", found, ep_ids=ep_ids)`.

### 3. Immediate History Log Appearance on Finished Library Updates, Scans & ARR Tasks
- **Issue**: In the Library Update queue tab, after a library update (e.g. Kodi music scan, Kodi video scan, Emby, Jellyfin, Plex, Navidrome) finished, it was removed from the Running list but did not immediately appear in the 'Recent library updates' history log below. Users had to close and reopen the queue modal for the finished line to show up. The same issue affected the Scan Queue ('Recent scans') and ARR Queue ('Recent ARR') tabs.
- **Root Cause**: `events.ticker` broadcast `QUEUE_TICK` carrying current active queue snapshots (`queue_state.snapshot()`), which caused the UI to remove the completed job from the active/running list. However, history rows (`work_log.recent(...)`) were only requested from `/api/v1/queue/events` when opening the modal. When jobs completed in `library_queue`, `arr_queue`, or `scan_queue`, `work_log.note()` recorded the event in the database, but no live WebSocket event was broadcast, leaving the UI's history cache stale until the modal was closed and reopened.
- **Fix**:
  - **`app/curator/events.py`**: Added `set_loop(loop)` and `emit(kind, data=None)` threadsafe helpers to broadcast events to connected clients from worker threads.
  - **`app/main.py`**: Registered the asyncio event loop with `events.set_loop(loop)` on startup and lifespan.
  - **`app/curator/work_log.py`**: In `note()`, broadcast `"WORK_EVENT"` whenever a work event finishes across any lane (`library`, `scan`, `arr`). In `recent()`, added `id::text AS id` to SELECT queries so action buttons (such as Retry on failed library updates) have access to the event ID.
  - **`app/curator/library_queue.py`**: Updated `_run_deferred_clean` to also record deferred Kodi video cleans in `work_log`.
  - **`app/static/js/core/live.js`**:
    - Handled `"WORK_EVENT"` to trigger `refreshQueuePanelSoon()`.
    - In `QUEUE_TICK`, added `hasFinishedItem` detection: if any item that was previously in `library`, `scans`, or `arr` has left the active list, immediately trigger `refreshQueuePanelSoon()`.
  - **`app/static/js/core/automation.js`**:
    - In `selectQueueTab(tab)`, trigger `refreshQueuePanelSoon()` so switching tabs always fetches the freshest events for that tab.
    - In `armQueueClock()`, refresh history if the cache is older than 8 seconds while the modal remains open.
  - **`tests/test_library_queue.py`**: Added unit tests in `WorkLogTests` covering `WORK_EVENT` emission on `work_log.note()`, `id` selection in `work_log.recent()`, and `library_queue._finish_row()` recording.

## 2026-10-19 — Fast episode scraping, full-height queue modal, and Kodi music path mapping fix

### 1. Fast Episode/Show Scraping & Scrape Scoping
- **Fast Scraper Timeouts**: Scraping a single episode or show could previously hang for 2+ minutes during lookup if secondary rating sites (Rotten Tomatoes, Metacritic, AniList, OFDb, TVMaze, etc.) were slow or unresponsive, blocking `asyncio.gather` for the whole lookup.
  - **`app/curator/scrapers/http.py`**: Reduced default timeout in `Client.text()` from 40.0s to 10.0s and retries from 3 to 2 attempts (`range(2)`). Reduced `Client.json()` retries default to 2.
  - **`app/curator/video/scrape.py`**: Added a default 15.0s timeout to `_quiet()` using `asyncio.wait_for`. Secondary sources that time out now log a warning and continue without stalling the entire scrape. Added a 20.0s timeout to TMDB and TVDB series lookups.
- **Source Lookup Progress & Result Logging**: Previously, lookups ran silently until the episode scrape began, leaving no visibility into which sources succeeded, failed, or had no match.
  - **`app/curator/video/scrape.py`**: `_quiet()` now logs live progress as each source finishes: `{label}: succeeded{detail}` (with item counts or ratings list), `{label}: no match found` (or `no artwork found`), `{label}: timed out after {timeout}s`, or `{label}: {error}`. Primary sources TMDB and TVDB now log `succeeded (id {id})`, `no match found`, timeout, or error. Prerequisite checks for OMDb and Fanart.tv log clear skip notices if required IDs are missing.
  - **`app/curator/scrapers/rottentomatoes.py` & `metacritic.py`**: In `_direct`, re-raise `ScrapeError` when no Crawlbase token is present instead of swallowing HTTP errors into empty strings, allowing `_quiet` to log the true error (e.g. 403 Forbidden or 503 Service Unavailable).
  - **`app/curator/scrapers/anilist.py` & `ofdb.py`**: Allowed `ScrapeError` to propagate to `_quiet` for accurate error logging.
  - **`tests/test_scrape_source_logs.py`**: Added unit test suite covering result detection, detail formatting, timeout logging, error logging, and direct scraper error propagation.
- **Scrape Scoping**: Selecting an episode or season in the TV tree or checking an episode checkbox previously collapsed the scrape scope to the whole TV show (`media = "tv"`), causing all 24 episodes to be rescraped instead of only the requested item.
  - **`app/static/js/video/scrape.js`**: `openVideoScrapeModal()`, `selectedScrapeIds()`, and `scrapeSelectedRows()` now preserve the episode (`media: "episodes"`, `ids: [...]`) or season (`media: "seasons"`) scope rather than falling back to `tvCheckedShows()`.

### 2. Queue Modal Flex & Full-Height Layout
- The queue modal (`#queue-modal`) now flexes to utilize the full viewport height, constrained cleanly between the header bar (`--chrome-top`) and taskbar (`--chrome-bottom`).
  - **`app/static/app.css`**: Updated `#queue-modal .modal-content` to `height: 100%; max-height: 100%; display: flex; flex-direction: column;`. Configured `#queue-modal .modal-body`, `.queue-items`, `.queue-history`, `.queue-events`, and `.manual-library` with flex layout and independent vertical scrolling so all panels expand to fill the available space.

### 3. Kodi Music Update Folder/Artist Path Mapping Fix
- Kodi music updates previously triggered a full music library scan every time instead of targeting the specific artist folder.
- **Root Cause 1**: In `app/curator/ingest.py`, `_music(rows)` called `notify.request("music", message=...)` without passing `folders`. `scope_for` in `library_queue.py` saw empty folders and assumed a full scan was required (`full = True`, reason: `"no folder was included"`).
- **Root Cause 2**: When path mapping was applied, remote Kodi paths (e.g. `nfs://...`, `smb://...`) passed to `notify.run_kodi` were checked against local mapping roots in `_kodi_folder`. Since a remote path does not start with a local path, `_kodi_folder` returned `None`, which triggered Kodi's fallback to scan everything (`{"directory": None}`).
- **Root Cause 3**: Settings mapping keys could use either `"kodi"` or `"remote"`.
- **Fixes**:
  - **`app/curator/ingest.py`**: `_music(rows)` now collects artist folders from `row["extra"]["artist"]` or `posixpath.dirname(row["path"])` and forwards `folders=folders` to `notify.request("music", folders=folders, ...)`.
  - **`app/curator/arr_hooks.py`**: Lidarr webhook handling in `_lidarr()` computes `artist_folder` from `payload["artist"]["path"]` (mapped) or `posixpath.dirname(folder)` and records `artist=artist_folder` in the queued item.
  - **`app/curator/notify.py`**:
    - `_kodi_folder()`: Detects existing remote Kodi URLs (`nfs://`, `smb://`, `dav://`, `ftp://`, `http://`, `special://`, etc.) and returns them directly with a trailing slash. Supports both `"kodi"` and `"remote"` mapping configuration keys and cleans paths with `automation.clean_path`.
    - `kodi_directories()`, `_local_from_kodi()`, and `_mapped_paths()`: Updated to support both `"kodi"` and `"remote"` keys and handle already-mapped paths.
  - **`app/curator/routes/automation.py`**: Extended `/api/v1/library/update` endpoint to accept `kind in {"movie", "show", "artist", "album", "music"}`. For `artist` or `album`, looks up the artist directory in the music library and notifies players with `media = "music"`.
  - **`tests/test_kodi_music_mapping.py`**: Added 14 unit tests covering local-to-remote mapping, remote pass-through, Lidarr webhook parsing, ingest folder forwarding, and manual library update routes.

## 2026-10-19 — Scan log timestamp prefix and webhook queue load_settings import fix

### 1. Webhook Queue Import Fix (`load_settings`)
Force scanning or automated queue processing previously halted after starting an episode scan, left items in the queue, reset the debounce timer, and triggered the alert:
`Webhook queue finished. cannot import name 'load_settings' from 'resonance.settings' (/app/resonance/settings.py)`.
When the video scanner finished scanning the episode, `_write_log` attempted `from resonance.settings import load_settings`. `resonance.settings` defined `load` instead of `load_settings`.
- **`app/curator/video/scanner.py`** — Changed import in `_write_log` to `from resonance.settings import load as load_settings`.
- **`app/resonance/settings.py`** — Added module-level alias `load_settings = load` for compatibility across the codebase.

### 2. Timestamp Prefix on Scan Log Filenames
Scan log files now use the timestamp as the prefix to make them sort naturally by latest in directory listings and file explorers:
- Music: `<timestamp>_music_scan.log` (e.g. `2026-10-19-123456_music_scan.log`)
- Movies: `<timestamp>_movies_scan.log`
- TV: `<timestamp>_tv_scan.log`
- Movie sets: `<timestamp>_sets_scan.log`
- Collision handling appends `-<suffix>` to the timestamp (`<timestamp>-<suffix>_<media>_scan.log`).

- **`app/curator/video/scanner.py`** — Updated `_write_log` to generate `{stamp}_{media}_scan.log`, handle timestamp collisions, and updated log pruning to prune oldest logs considering both new timestamp-prefixed and legacy filenames.
- **`app/resonance/scanner.py`** — Updated `_write_scan_log` to write `{stamp}_music_scan.log` and updated `_prune_scan_logs` to match both new and legacy formats. Adjusted `_scan_log_keep` default to 30 (max 100).
- **`app/curator/scan_logs.py`** — Updated `_NAME` regex, `_media(name)`, `_label(name)`, and `_matches_media(name, media)` to recognize and filter both new timestamp-prefixed files and legacy files without losing any historical logs.
- **`app/static/js/core/settings.js`** — Updated settings note to reference the `YYYY-MM-DD-HHMMSS_<media>_scan.log` format.
- **`tests/test_scan_logs_filter.py`** — Added unit test coverage for new timestamp-prefixed filenames, media matching, log sorting, `load_settings` export, and log writer execution.

## 2026-10-19 — Separate scan engine modal log windows and saved scans per media type

Previously, opening the scan modal or the "Saved scans" list from one scan engine (e.g. Music, Movies, TV shows, Movie sets) could display previous scan logs from other media types. The video scanner (`app/curator/video/scanner.py`) stored only a single global state and log deque in memory, which caused Movies and TV scans to overwrite each other. Furthermore, `/api/v1/scan/logs` listed all log files (`movies-scan-*.log`, `tv-scan-*.log`, `scan-*.log`, `sets-scan-*.log`) together without media filtering, meaning opening "Saved scans" in the Music scan modal listed movie and TV scans as well.

- **`app/curator/scan_logs.py`** — Added media filter support (`_matches_media` and `list_logs(media=...)`), a `latest_log(media)` helper to read the most recent log file for a specific media type, and media classification (`_media`).
- **`app/curator/routes/scan.py`** — Updated `/api/v1/scan/logs` and `/api/v1/scan/status` to accept and forward an optional `media` query parameter.
- **`app/curator/video/scanner.py`** — Added per-media scan states (`_media_states`) and log buffers (`_media_logs`) for `movies` and `tv`. Extracted `_finish_scan` helper and added cold-start hydration (`_load_initial_media_state`) from the database and newest log file so opening a modal immediately shows the previous scan log for that specific media type rather than an empty/overwritten log. `status()` now returns per-media snapshots in `snapshot["scans"]`.
- **`app/curator/video/scrape.py`** — Added sets scan state and log persistence (`_sets_state`, `_sets_log`), saves `sets-scan-{stamp}.log` upon completion via `_write_log`, and hydrates the latest sets log on startup.
- **`app/static/js/video/scan.js`** — Tracks separate scan state per media (`state.videoScans = { movies: ..., tv: ..., sets: ... }`). `videoScanFor(media)` strictly returns the focused media's state and log. Added `clearVideoScanLog()` to clear the active media's log in `#video-scan-log`.
- **`app/static/js/video/scrape.js`** — `applyVideoScrape` now keeps `state.videoScans.sets` up-to-date with live sets scrape status and logs.
- **`app/static/js/core/scan.js`** — `openScanHistory(targetMedia)` now detects caller context (`#scan-modal` -> `music`, `#video-scan-modal` -> `movies`, `tv`, or `sets`), sets the modal title appropriately (e.g. "Saved movie scans", "Saved TV scans", "Saved music scans", "Saved movie set scans"), and filters queries to `/api/v1/scan/logs?media=...`.
- **`app/static/js/core/events.js`** — Dispatches `openScanHistory` with the active modal's media focus, and handles `clear-video-scan-log`.
- **`app/templates/index.html`** — Added Clear button to `#video-scan-modal` log toolbar matching `#scan-modal`.

## 2026-10-19 — Scan chip in the activity bar not opening the music scan engine

### Related: Job chip opened the drawer off-screen

The activity bar is anchored to the bottom of the window, so its chips sit near the bottom.
`placeJobsDrawer` positioned the drawer at `top: rect.bottom + 8`, which on an ordinary-height
viewport landed below the viewport entirely. The drawer was dutifully opening - and nobody
could see it. Measured on a 1600 x 1000 viewport: chip top 951, chip bottom 987, drawer top
995. Five pixels of drawer in-viewport, the rest below.

- **`app/static/js/core/events.js`** — `placeJobsDrawer` now compares the space below the
  chip with the space above and places the drawer wherever the room is. When there is more
  room above, it is hung by its bottom edge (`bottom: innerHeight - rect.top + 8`,
  `top: auto`) so it grows upward and its top is always inside the viewport. A `max-height`
  equal to the available side keeps it from spilling off the opposite edge. The old
  below-the-chip placement still runs when there is room below.
- **The scan modal is a full-page overlay** (position: fixed, top: var(--chrome-top), …) so
  it never had this positioning problem. The scan chip's modal, after the fast-path, opens
  centred: measured 56-936 of a 1000-tall viewport.

### What the user should still check

The scan chip was reported as not opening too. In my simulation it does open (and the modal
sits centred inside the viewport). The fast-path and `?v=` fix in the previous entry are the
two likely causes - they both get picked up by a container restart plus a hard refresh. If
after the restart it still does not open, the fast-path's console log tells us where the
click went: see the previous entry for what to look for.


Clicking the "Scan · Music · Incremental deep …" chip in the activity bar did not open the
music scan engine modal. In a simulated running-scan state the normal dispatch path reached
`openScanModal()` and the modal opened, so this is not a bug in the chip HTML or the
dispatcher branch itself. Something else on the live page intercepts the click.

- **`app/static/js/core/events.js`** — Scan chip fast-path added at the very top of
  `onClick`. Any ancestor with `data-action="open-activity"` + `data-open="scan"`,
  `data-action="open-scan"` or `data-action="open-activity-scan"` opens the matching scan
  engine immediately via `openScanModal` / `openVideoScanModal(media)`, with
  `event.preventDefault()` and `stopPropagation()` so nothing further swallows the click. It
  also catches the "Scan engine" button inside the jobs drawer. If the normal dispatcher is
  the problem, this bypasses it; otherwise it is a no-op because the normal flow would have
  reached the same functions.
- Also logs `"[scan-chip] clicked …"` to the browser console on every scan-chip click, so if
  the modal still does not appear we can see from devtools whether the click reached the
  handler and what media it dispatched.

### Related: static URLs were double-stamped

`_url_for` added `?v=HASH` to every static URL, and the template appended `?v={{ ui }}` on
top, producing `?v=HASH?v=UI`. Flask served the file either way (unknown query params are
ignored), so this was not what prevented the modal from opening - but it was broken and had
to go.

- **`app/main.py`** — `_url_for` now always returns a URL with exactly one `?v=`, falling
  back to `APP_VERSION` when the per-file content hash is not computed yet.
- **`app/templates/index.html`** — The manual `?v={{ version }}-xxx` and `?v={{ ui }}`
  suffixes stripped from the favicon, logo, stylesheet and script tags. The now-unused
  `{% set ui = … %}` line removed.


## 2026-10-19 — Kodi stale-prune before a library update

Kodi could keep an old row for an episode, movie or album after the file was upgraded or
renamed outside Kodi's own view. A library scan writes the new row alongside the old one
rather than replacing it, so the user sees both. Kodi's Clean would eventually drop them,
but only on a separate pass that is often scheduled much later.

- **`app/curator/notify.py`** — New `_prune_stale_kodi(kind, cfg, directory)` is called from
  `_run_one` right before each `_send_scan`, scoped to the folder about to be scanned. It
  works the same way for every media type by querying Kodi by path prefix, not by
  show/season/episode or TMDB id. No identity has to be threaded through the
  arr_hooks → ingest → notify pipeline for this to work on movies, episodes **and** albums.
  - Video: `VideoLibrary.GetEpisodes` and `VideoLibrary.GetMovies` with
    `{field: "path", operator: "startswith", value: <folder/>}`, properties `["file"]`.
    Each returned entry's `file` is translated through `kodi_paths` back to a container
    path and checked with `os.path.isfile`. A gone file triggers
    `VideoLibrary.RemoveEpisode` / `VideoLibrary.RemoveMovie`.
  - Music: `AudioLibrary.GetSongs` with the same path filter. A song whose file is gone
    is removed with `AudioLibrary.RemoveSong`. If an album is now empty
    (`GetSongs` with `albumid` filter returns zero) it is removed too, so the follow-up
    scan does not have to rely on a separate Clean pass.
  - Safety: the prune skips entirely when `kodi_paths` has no mapping for a Kodi path -
    the file cannot be verified, so it must not be removed. Any Kodi error from the prune
    is logged and swallowed, and the normal scan still runs. The prune is scoped by the
    folder being scanned, so it cannot reach a sibling library.
  - It runs only on the first scan attempt, so a retry does not re-check what was already
    verified in the same loop.
- **`app/curator/notify.py`** — New `_local_from_kodi(kodi_path, mappings)` is the inverse
  of `_kodi_folder`, longest-match-wins. The forward and reverse mappings share the one
  settings table, so adding a new `kodi_paths` entry works for both directions
  automatically.

The `Rename` webhook from Radarr/Sonarr is handled by the same code path: the targeted
rescan writes the new path, and the prune that follows removes any Kodi entry that still
pointed at the old one. Lidarr's `TrackRetag` / `Retag` events run through this too.


## 2026-10-19 — Library analytics 500: "cannot get array length of a scalar"

### Correction: chapters is INT, not JSONB

The earlier repair statement called `jsonb_typeof(chapters)` and the writer coerced `chapters`
to `[]`, but `chapters INT DEFAULT 0` in the schema: it is a count, not an array. The faulty
`jsonb_typeof(integer)` call aborted the migration at container startup, so the app would not
boot ("Curator could not start"). Only `subtitle_tracks`, `audio_tracks` and
`external_subtitles` are JSONB arrays; `chapters` was wrongly included in both places.

- **`app/schema.sql`** - `chapters` repair removed from the one-off normalisation.
- **`app/curator/video/store.py`** - `chapters` removed from the array-coerce set in
  `save_file`. The three real JSONB array columns stay guarded.

My apologies for the breakage. I should have read the schema before writing the statements.


### Root cause

Opening Library analytics for TV threw `psycopg.errors.InvalidParameterValue: cannot get array
length of a scalar` from `_subtitle_report` in `app/curator/insights.py`:

```sql
jsonb_array_length(COALESCE(f.subtitle_tracks, '[]'::jsonb))
```

`COALESCE` only replaces SQL `NULL`, not JSON `null`, scalars or objects, and
`jsonb_array_length` throws on any of those. A row in `video_files` had `subtitle_tracks` or
`external_subtitles` as JSON `null`, and the whole analytics call aborted. The
`video_files.subtitle_tracks` column is `JSONB NOT NULL DEFAULT '[]'::jsonb`, but
**JSON null is not SQL NULL**, so a `None` passed through `Jsonb(None)` landed as JSON
`null` without tripping the NOT NULL constraint. The sibling query in the same function
already guarded with `jsonb_typeof(…) = 'array'`; the aggregate query did not.

### Fixes

- **`app/curator/insights.py`** — `_subtitle_report`'s aggregate query now wraps every
  `jsonb_array_length(f.subtitle_tracks)` / `jsonb_array_length(f.external_subtitles)` call in
  `CASE WHEN jsonb_typeof(x) = 'array' THEN jsonb_array_length(x) ELSE 0 END`. `CASE WHEN` is
  used rather than a guarded `OR`, because PostgreSQL does not promise to short-circuit `OR`
  operands - the planner can reorder them and call `jsonb_array_length` on a scalar. The SQL
  spec does guarantee CASE evaluation order.
- **`app/curator/video/store.py`** — `save_file` now coerces `subtitle_tracks`,
  `audio_tracks`, `external_subtitles` and `chapters` to `[]` when the probe handed back a
  non-list value, so this cannot happen again from a half-failed probe.
- **`app/schema.sql`** — One-off repair runs at startup: any existing row whose array-typed
  JSONB column holds `NULL` or a non-array JSON value is normalised to `'[]'::jsonb`.
  Idempotent, so later restarts are no-ops.


## 2026-10-19 — Scan progress finish date and capitalized labels

- **`app/static/js/core/scan.js`** —
  - Added `formatScanClockTime()` so scan finish estimates indicate the estimated date, weekday, and day delta (e.g. `Finishes Tue, Oct 20, 03:29 AM (+1 day)`) when completing on a subsequent day, or `today, ...` when completing on the current day.
  - Capitalized all scan progress line segments to match UI standards: `This stage`, `Scan`, `About ... left`, `Finishes ...`, `Paused for queued imports`, and `Finished ...`.

## 2026-10-19 — Allow splitting episodes with parts shorter than the default minimum

- **`app/curator/video/split.py`** —
  - `validate_times()` now provides informative error messages stating the exact part number, calculated length, and required minimum threshold (e.g., `Part 2 would be 18.5s, shorter than the minimum 30.0s`).
  - `_run_split()` now permits split execution down to the container minimum floor of 1.0 second, allowing intentional short episodes/cartoons/interstitials to be split when clicking **Split anyway** without being blocked by the 30s default setting.
  - Duration verification in `_run_split()` now checks `actual < 1.0 or abs(actual - planned) > max(5.0, planned * 0.02)` instead of `actual < cfg["split_min_part"]`, preventing intentionally short split parts from being deleted after `mkvmerge` succeeds.
  - `plan()` checks proposed parts against `split_min_part` and marks `ready = False` when a part is under the threshold, ensuring the user is prompted with **Split anyway** for review.

## 2026-10-19 — Split modal interactive episode highlighting & TV tree auto-load

### Split modal: highlight episodes and mark their cut times
- **`app/static/js/video/tv.js`** — Replaced plain split part lines with interactive `.split-part-card` elements. Episode 1 is highlighted by default when opening the modal, and clicking any episode card (e.g., Episode 2) highlights it, focuses its cut input, and sets the player target label (`Target: End of S01E02 · Title`). Pressing **Mark current time** updates the cut timestamp of the active episode and animates a pulse confirmation. The final episode is cleanly styled as "End of video".
- **`app/static/app.css`** — Added styles for `.split-parts-list`, `.split-part-card` (hover, active border/glow, badge, tags, and cut inputs), and `@keyframes splitMarkPulse`.

### TV library tree no longer stuck on "Loading…" after refreshing
- **`app/static/js/video/tv.js`** — Added `ensureExpandedTvShows()` to `renderTvTree()`. When `showDetails.clear()` runs after a split or file operation, any show that remains expanded in the tree automatically fetches its seasons and episodes in the background and re-renders, preventing the tree from being stuck displaying `Loading…`. Also added `refreshVideoItems("episode")` to `deleteSplitSource()` and `restoreEpisodeSplit()` so the tree stays in sync after source removal or restoration.


## 2026-10-19 — Split parts were never indexed, so they appeared nowhere

A multi-episode file split into three left the three parts invisible in the library. The split
worked: the parts were written, the source was parked as `.split-source-eps-42-44.mkv`, and the
episode rows were pointed at the new paths. But the same statement set `file_id = NULL`, and
nothing ever filled it in again.

`video_files` holds everything about a video — resolution, codec, HDR, size, duration, bitrate,
tracks — and `FILE_BRIEF` reaches it through `LEFT JOIN video_files f ON f.id = e.file_id`. With
`file_id` null that join produced nothing, so each part had a path and no file: no size, no
duration, no media info. Nothing re-scanned either, because a split is not a scan, so no
`video_files` row was ever created for the parts.

- **`app/curator/video/split.py`** — New `_index_parts()`, run after the parts are in place and
  before the episode rows are updated. For each part it does what the scanner does for any video
  it finds (`probe.analyze()` then `store.save_file()`), which also writes the mediainfo sidecar,
  and returns the row ids. The update now sets `file_id = %s` from that list instead of `NULL`.
  A part whose probe fails keeps a null id rather than failing the whole split.
- **`app/curator/video/reprobe.py`** — `refresh()` created the `video_files` row but never linked
  it, so **Update media info** could not repair an item whose `file_id` was null: the media info
  was stored and still displayed nowhere. New `_link_file()` points the item at the row it just
  wrote, but only when the item has no `file_id` and the path matches, so it cannot re-point a
  movie away from one of its parts. This is also the repair path for episodes split before this
  fix.


## 2026-10-19 — Split episodes: button moved, modal reachable

### Split episodes sits with the other actions

- **`app/static/js/video/tv.js`** — `splitEpisodesButton(episode)` split out of `splitButtons()`,
  which keeps only Restore original and Delete source file.
- **`app/static/js/video/edit.js`** — The button now sits in the `.vactions` row right after
  Write .nfo. That alone gives it the standard size: it was in `.job-actions`, whose
  `.btn-ghost` rule is `padding: 2px 8px; font-size: 0.72rem`, noticeably smaller than the rest.

### The split modal no longer runs off the screen

The bottom of the modal was unreachable, so the split and review controls could not be used.
`.episode-split-layout` was a plain flex column with no `flex` or `min-height: 0`, so it would
not shrink below its content height - video up to 40vh, plus controls, plus a 45vh body - and
`.modal-content`'s `overflow: hidden` clipped whatever did not fit. Nothing scrolled, because
the overflow was on the element that was clipping.

- **`app/static/app.css`** — The layout is now a row: the video and its mark-time controls on
  the left, the split points in a pane of their own on the right that scrolls. Every box in the
  chain carries `min-height: 0` so the panes shrink to the modal instead of overflowing it, and
  `#episode-split-modal .modal-body` overrides the 45vh cap `.modal-wide` puts on every modal
  body. The player's controls are `flex: 0 0 auto` so they stay put while the video takes the
  slack.
- **`app/static/app.css`** — Side by side needs the width, so the content is
  `min(96vw, 1500px)`. `.modal-wide` puts its width on the *overlay* rather than the content, so
  the overlay is freed to 100% first; without that it capped the content at 980px.
- **`app/static/app.css`** — Under 1000px wide the panes stack again, with the video capped at
  34vh so the split list keeps its room.

Verified in a 1600x1000 viewport: content 1500px wide and centred, player 869px beside a 629px
split pane, both panes level, the right pane scrolling (2555px of content in 761px), the last
button reachable, and all four edges of the modal inside the viewport.


## 2026-10-19 — Lock button keeps its red, and no longer resizes

The lock button on the info banner turned red on hover with the label **Lock**, but on being
pressed it went to a transparent background with a green border. It also changed width with the
label, so the action row next to it shifted while hovering and toggling.

- **`app/static/app.css`** — `button.vlock.is-locked` now keeps the matte red the hover showed
  when it was pressed, with the label **Locked**. Hovering a locked button previews the unlocked
  green and reads **Unlock**, mirroring how an unlocked button previews the locked red — so the
  hover still shows the state the click will produce.
- **`app/static/app.css`** and **`app/static/js/video/scrape.js`** — The two labels are wrapped
  in a `.vlock-label` span and stacked in a single grid cell shared with a hidden `"Unlocked"`
  sizer, so the button is always as wide as the longest label. Verified in the browser: the
  unlocked, locked, and both hover labels all measure 89.56px, so the row cannot shift.

Both come from the one `lockButton()` generator and the one `.vlock` rule, so this applies to
movies, TV, seasons, episodes and music alike.


## 2026-10-19 — Removal is now only ever what the user removed

### Wanted titles are removed with their path, and "remove" vs "delete" is now used precisely

- **`app/curator/video/store.py`** — `delete_under_root()` is now `remove_under_root()` and no
  longer carries `NOT wanted`, so a wanted title rooted at a removed path goes with it. A wanted
  row is a title with no file yet, holding the root its file was meant to land in; once that root
  is not a library path it has nowhere to land and would be left as a broken placeholder. Radarr
  or Sonarr still holds the request. It returns the ids plus how many were wanted, and the scan
  log reports that count. Rows only: no file is touched.
- **Wording** — Throughout the code, comments and log lines this work touched, *remove* now means
  a database row and *delete* is reserved for a file on disk, matching how the rest of the app
  already words it ("remove rows from the library only, or delete from disk"). The scan log now
  says "Removed N movies from the database ... No files were touched."

### "Cannot be listed" is now its own state, with an alert and a badge

A folder that exists but cannot be listed - a permission problem, or a mount still attached
while every read fails - was lumped in with an away mount, because reachability is probed by
listing. It is worth telling apart, since the fix is different.

- **`app/resonance/paths.py`** — `offline_library_paths()` now means "not a directory" (the
  mount is away). New `unreadable_library_paths()` means "is a directory, cannot be listed".
  New `unscannable_library_paths(kind)` is the union, which is what a scan must not prune
  under, so splitting the two did not weaken the protection.
- **`app/curator/routes/music_system.py`** — `/api/system` gained `unreadable_paths`.
- **`app/static/js/music/tools.js`**, **`app/static/js/core/scan.js`** —
  `noteUnreadablePaths()` raises an error-level notification naming the folders and pointing at
  permissions or the mount.
- **`app/static/js/core/folders.js`**, **`app/static/app.css`** — An `unreadable` badge on the
  row and a third warning line above the list. The three states are mutually exclusive on a
  row, so a folder reads as exactly one of offline, unreadable or empty.
- **`app/resonance/scanner.py`** — The music scan protects the union rather than just the away
  mounts.

### The 20% cap now also judges the whole mount

The cap was per library path. A mount can hold several library paths, of more than one media
type, so a mount that came back half-populated could have every one of its paths stay under the
per-path limit while the mount as a whole lost a great deal.

- **`app/resonance/scanner.py`** and **`app/curator/video/scanner.py`** — Both scans now measure
  every root first, aggregate what would be removed per detected mount (`mount_for()`), and if a
  mount would lose more than 20% of what it holds - counting more than 10 items - **no path on
  that mount is pruned**, with a log line naming the mount and how many paths were held back.
  The per-path cap and the empty-root guard still apply on top, for a single path losing a lot
  on its own.
- **`app/resonance/paths.py`** — New `mount_for(path)`: the longest detected mount containing a
  path.

Scans no longer infer deletions from "this path is not in the configured list". That list goes
empty for an offline mount, an excluded folder or a hand-edited config, and anything inferred
from it was deleted silently. Deletion is now driven by an explicit record of what the user
took out of Settings, and is fenced so it cannot reach past that path.

### Explicit removal record

- **`app/resonance/settings.py`** — New `pending_path_removals` setting: `[{path, kind}]`.
  `save()` diffs the previous `music_paths` / `movie_paths` / `tv_paths` against the saved ones
  and records every path that went away. `take_path_removals(kind)` pops the entries for one
  library kind and rewrites just that key through `atomic_write`, so a scan clearing its own
  removals cannot disturb anything saved meanwhile.

### Music: targeted deletes instead of "outside the library"

- **`app/resonance/scanner.py`** — The blunt
  `DELETE FROM albums WHERE NOT (path LIKE '<root>/%' …)` over every configured root is gone.
  In its place, one delete per recorded removal: `(path = %s OR path LIKE %s)` for the removed
  path, **and** `NOT` under any path that is still configured. So removing one path on a mount
  clears that path and leaves its siblings alone, and removing every path on a mount clears the
  whole mount. A path that merely stopped being configured is never touched.

### Movies and TV: removal implemented at all

- **`app/curator/video/store.py`** — New `delete_under_root(media, root)`. Rows carry the
  library root they were found under, so matching on it cannot reach a sibling path on the same
  mount and a nested path keeps its own rows. Wanted entries are curated placeholders, not files
  on disk, so they survive.
- **`app/curator/video/scanner.py`** — New `_clear_removed_paths(job, media)`, called after the
  movie prune and after the show prune. Previously nothing ever removed items under a path the
  user took out, so they lingered as orphans forever.

### Empty folders now raise an alert, not just a log line

- **`app/resonance/paths.py`** — New `empty_library_paths()`: configured, readable, and holding
  no entries at all. That is what a mount that remounted empty looks like, and also what a
  folder the user emptied looks like.
- **`app/curator/routes/music_system.py`** — `/api/system` gained `empty_paths`.
- **`app/static/js/core/scan.js`**, **`app/static/js/music/tools.js`** — `noteEmptyPaths()`
  warns once per change, naming the folders and saying that nothing under them is removed while
  they are empty, and that the path should come out of Settings if the folder is finished with.
- **`app/static/js/core/folders.js`**, **`app/static/app.css`** — An `empty` badge on the folder
  row beside the `offline` one, plus a second warning line above the list.

### Music gained the movie scan's prune cap

- **`app/resonance/scanner.py`** — The per-root music prune now refuses to drop more than 20% of
  a root in one pass once that root holds more than 10 albums, matching the movie scan, and says
  so in the scan log. New `_known_album_count(root)` backs it. A mount that comes back partly
  populated looks exactly like a large deletion, so it is held for the user to confirm with a
  full scan.


## 2026-10-19 — Offline library folders: alert, and never delete their items

### Data loss: "Exclude" deleted the folder's indexed items

Same class of bug as the offline one, found while tabulating the prune cases. `configured` is
built as `[path for path in mounted_roots if path not in skip]`, so an excluded folder is
stripped out of it, and `_prune()` uses that list as the keep-list for
`DELETE FROM albums WHERE {outside}`. An excluded folder matched no keep-list prefix, so
ticking **Exclude** deleted everything indexed under it on the next music scan — while the UI
says "Exclude leaves the folder in the library and skips it on scans".

- **`app/resonance/scanner.py`** — The keep-list passed to `_prune()` is now built explicitly
  as `configured` plus the excluded, offline and came-back-empty roots. Excluded folders stay
  out of the walk and out of the per-root prune, but their rows are kept.

### Data loss: an offline music mount had its albums deleted on the next scan

Found while answering whether an offline mount raises an alert. It did not, and worse, it
could silently empty part of the library:

1. `music_roots()` drops any path failing `os.path.isdir`, so an offline mount disappears
   from `configured`.
2. Because it is no longer in `configured`, it is never walked, so it never reaches the
   `os.path.isdir` check inside the walk loop and never lands in `failures` / `failed_paths`.
3. `_prune()` then runs `_outside_library(configured)` — `DELETE FROM albums WHERE NOT (path
   LIKE '<root>/%' …)` for each remaining root. Albums on the offline mount match none of
   them and are deleted.

The `failed_paths` guard that would have protected them only covers roots that got far enough
to fail a read, which an offline root never does. No alert, no scan-log line, no confirmation.

- **`app/resonance/paths.py`** — New `readable_dir()`, `offline_library_paths()` and
  `protected_prefixes()`. `readable_dir()` probes the contents with `os.scandir` rather than
  trusting `os.path.isdir` alone, because an NFS or CIFS mount that has gone away can still
  answer `isdir` while every read fails. `offline_library_paths()` returns the configured
  paths that cannot be read, keyed by `music` / `movies` / `tv`.
- **`app/resonance/scanner.py`** — The music scan now collects the offline roots up front,
  logs one scan-log issue per root, and passes them to `_prune()` as part of the configured
  list. They therefore count as *inside* the library for the outside-library delete and their
  rows survive. The per-root prune still runs only over roots that were actually walked.
- **`app/resonance/scanner.py`** — A root that reads as online but yields no album is almost
  always a mount that came back empty, which would prune every album under it. Such roots are
  now dropped from the per-root prune and added to the protected list, with a scan-log issue.
- **`app/curator/video/scanner.py`** — Same guard for movies: a readable root the walk found
  no movie in is skipped by the prune with a log line, instead of relying on the 20% cap,
  which only applies above 10 known movies and so would not have saved a small root.

### Alert when a library folder is offline

- **`app/curator/routes/music_system.py`** — `/api/system` gained `offline_paths`.
- **`app/static/js/core/scan.js`** and **`app/static/js/music/tools.js`** — The system poller
  stores `state.offlinePaths` and `noteOfflinePaths()` raises a warning notification naming the
  folders, firing once per change rather than on every poll.
- **`app/static/js/core/folders.js`** — Library folders rows carry an `offline` badge and an
  `is-offline` class, with a warning line above the list and a note explaining that an offline
  folder is skipped and nothing under it is removed, so taking the path out and scanning again
  is how a folder's items are removed.
- **`app/static/app.css`** — Styling for the badge, the offline row and `.settings-warning`.
- **`app/curator/folders.py`** — `choose()` no longer reports a configured-but-unreadable
  folder as "not a TV folder"; it says the folder cannot be read and that nothing indexed
  under it will be removed.

### Already correct before this change

Offline folders were already left out of scans: `folders.mounted()` and `music_roots()` both
gate on `os.path.isdir`, and the video prune only iterates roots it actually walked. The gap
was the music outside-library delete, the empty-root case, and the absence of any alert.


## 2026-10-19 — Trakt sync in the header, Schedules tab, player update/clean schedules

### "loadSyncTab is not defined" when saving settings

- **`app/static/js/core/settings-tabs.js`** — `showSettingsTab()` called `loadSyncTab()` whenever
  the Sync/Schedules tab became active, but that function is defined nowhere (a leftover from the
  task 12 work). The `ReferenceError` aborted the rest of `showSettingsTab()`, which is what
  surfaced as an error on **Save settings** — the save re-activates the tab. It also meant the
  lines after it never ran for that tab. Removed the dead call; `loadTrakt()` on the line stays,
  since the Trakt **Sync now** button's enabled state depends on it.

### Trakt watched sync from the header

- **`app/templates/index.html`** — Added `#trakt-sync-btn` beside the settings button: the Trakt
  logo, `data-action="trakt-sync"`. `app/static/js/core/events.js` already routes every `trakt-*`
  action to `onVideoAction()` without checking the current media, so it fires from the music tab
  too. `startTraktSync()` reads the direction from the Schedules tab when it is rendered and
  falls back to "Both ways" otherwise.
- **`app/static/app.css`** — Header sizing for the button (17px logo, 5px padding) next to the
  existing `#settings-modal .trakt-sync-icon` rule.

### Sync tab renamed to Schedules

- **`app/templates/index.html`** — The tab now reads "Schedules". Its `data-settings-tab` key
  stays `sync`, so every `data-tab="sync"` section and the `loadSyncTab()` hook are untouched.

### Player schedules: update or clean, per player, many per player

Was "Player clean schedules" and could only ever clean, even for the players that have no clean.

**Which players have a separate clean.** Kodi has real ones in JSON-RPC: `VideoLibrary.Clean` and
`AudioLibrary.Clean`, distinct from `VideoLibrary.Scan`. Plex has no clean call, but emptying a
section's trash (`PUT /library/sections/{id}/emptyTrash`) is the operation that drops items whose
files are gone, so that serves as its clean. Emby and Jellyfin have neither — they remove missing
items as part of an ordinary library scan (`POST /Items/{id}/Refresh` / `/Library/Refresh`), so
Clean is not offered for them and resolves to Update.

- **`app/static/js/core/settings-tabs.js`** — Section renamed **Player schedules**. New
  **Schedule type** select (Update / Clean) between Player and Library. `PLAYER_CLEAN_SUPPORT`
  marks kodi and plex; `syncPlayerCleanKinds()` (on the player select's `onchange`, and after each
  tab paint) rebuilds the type options, disables the select for a player without a clean, and
  explains why in `#player-clean-kind-note`. The saved list now shows the type:
  `Kodi — Clean — Video library — 0 4 * * 0`.
- **`app/static/js/core/settings.js`** — `savePlayerCleanSchedule()` stores `kind`, coercing
  Clean to Update for an unsupported player. The duplicate check now includes the type, so the
  same player/library/cron can hold both an update and a clean.
- **`app/resonance/settings.py`** — `_player_clean_schedules()` validates `kind` and coerces
  Clean to Update where unsupported. Module-level `PLAYER_CLEAN_SUPPORT = {"kodi", "plex"}` is the
  one source of truth for the backend. Entries saved before this change have no `kind` and were
  all cleans, so they default to `clean` and then coerce — Kodi and Plex keep cleaning, Emby and
  Jellyfin become updates, which is what they were actually doing anyway.
- **`app/curator/curator_schedule.py`** — `_fire_clean()` became `_fire_schedule(player, media,
  kind)`. A clean runs Kodi's `clean_only` queue job or `notify.clean_plex()`; an update runs a
  full library scan (`enqueue(..., full=True)` for Kodi, `queue_for()` for the servers), which is
  also the fallback for a clean on a player without one. The de-dupe key now includes the kind so
  an update and a clean on the same cron both fire.
- **`app/curator/notify.py`** — New `clean_plex(media)` and `_plex_put()`: resolves the Plex
  sections for that media type via the existing `_plex_sections()` and empties the trash on each.


## 2026-10-18 — Settings modal: Trakt tab placement, footer height, lyrics icons

### Trakt moved back to Integrations, with a sync option of its own on Sync

The whole Trakt block (PKCE explanation, Client ID, Save Trakt app, connect/disconnect,
"Connected as …", last-sync line) had been moved onto the Sync tab. The connection belongs
on Integrations; only the sync option belongs on Sync.

- **`app/static/js/core/trakt.js`** — `traktSection()` is back to `data-tab="integrations"` and
  now holds only the connection: the PKCE note and `#trakt-box` (Client ID, Save Trakt app,
  Connect/Disconnect, connected state, last watched sync).
- **`app/static/js/core/trakt.js`** — New `traktSyncSection()` (`data-tab="sync"`): a
  "Trakt watched sync" option with Direction, the sync interval, a **Sync now** button
  (`#trakt-sync-now`) and the `#trakt-sync-box` progress area. It points at the Integrations
  tab for connecting.
- **`app/static/js/core/trakt.js`** — The sync trigger and `#trakt-sync-box` were removed from
  the integration panel so those ids stay unique. `paintTraktSync()` now disables **Sync now**
  when Trakt is not connected as well as while a sync is running, and `paintTrakt()` calls it so
  the button tracks the connection. The now-unused `traktSyncButton()` helper was deleted.
- **`app/static/js/core/settings-tabs.js`** — `traktSyncSection()` registered in
  `videoSettingsSections()`.

### Enormous empty pane under the save footer

The settings modal had a large dead area at the bottom with the Save button sitting at its
top-right. Cause: task 12 added

```css
.modal-wide .modal-body { max-height: 45vh; overflow-y: auto; }
```

for the short wide prompt modals, but the settings modal is also `.modal-content.modal-wide`, so
`#settings-body` — the modal's only growable row (`flex: 1 1 auto`) — was capped at 45vh. It could
no longer fill the height the modal was given, and the leftover height became dead space below the
footer. Measured in a 1600×1000 viewport: modal content 856px tall, body pinned at 450px (45vh),
children ending 263px above the content box's bottom edge.

- **`app/static/app.css`** — Added `#settings-modal .modal-body { max-height: none; }` after the
  `.modal-wide` rule, exempting the settings body from the cap. Higher specificity (id + class), so
  it wins regardless of order, and the other `.modal-wide` modals keep their 45vh cap. Verified:
  body 450px → 712px, footer flush to the modal bottom, dead space 263px → 1px, body still scrolls.
- **`app/static/app.css`** — Separately, `.settings-footer` was left at the flex default
  `align-items: normal` (stretch), which stretched the lone Save button to the row's content box.
  It now has `align-items: center`, `.settings-footer > button { align-self: center; }`, and padding
  tightened `10px 16px` → `8px 16px`: the row is 46px for a 29px button.

### Lyrics icons were swapped the wrong way round

The pencil variant (the synced-lyrics *editor* icon) had been applied to the general lyrics
indicator. The pencil belongs only on the player-bar synced-lyrics button.

- **`app/static/js/music/badges.js`** — `lyricsIcon()` keeps the document-with-text-lines and
  double-note artwork but the pencil, eraser band and eraser cap are gone, and the viewBox is
  tightened from `0 0 40 26` to `0 0 24 26` now that nothing occupies the right-hand third.
- **`app/static/app.css`** — `.lyrics-mark svg` resized `28px × 18px` → `17px × 18px` to match the
  narrower viewBox so the badge no longer letterboxes.
- **`app/templates/index.html`** — `#player-lyrics-edit` (Edit synced lyrics, player bar) now uses
  the pencil icon — the same document/note artwork plus the pencil — replacing the previous
  unrelated glyph.


## 2026-10-18 — Video artwork, trailers and NFO sidecars fixed (404 "Artwork is not available")

### Root cause

All movie and TV artwork, trailers and NFO sidecar reads returned `404 Artwork is not available`,
while music artwork (served by a different router) was unaffected. Three things combined:

1. **`app/curator/folders.py` — `owner()` is too narrow to be a confinement check.** `owner()`
   answers *which library* a path belongs to by string-matching the path against
   `realpath()` of each configured library root. A library root can be a symlink or a bind
   mount of the same share, and `realpath()` does not always traverse a symlink that lives
   inside an NFS mount. A file can therefore sit on a mounted media volume and be perfectly
   readable while its path matches no configured root — at which point `owner()` returns
   `None` and every `/api/v1/artwork`, `/api/v1/media` and NFO request for it 404s. The same
   applies to anything under a mounted volume that is not itself a library root (for example
   a staging folder), which is where the affected shows lived.
2. **`app/static/js/video/common.js` — the `cv=2` cache buster exposed it.** Artwork URLs
   gained a constant `cv=2` parameter, which changed every artwork URL and discarded the
   browser's cached images. Those cached `200`s had been masking the server-side 404s, so the
   breakage appeared the moment the parameter shipped rather than when the cause landed.
3. **`app/curator/routes/library.py` — `Cache-Control` had been weakened to `no-cache`**,
   so nothing was cached any more and every repaint re-issued the failing request.

### Fixes

- **`app/curator/folders.py`** — Added `media_volumes()`, `on_media_volume()` and `servable()`.
  `media_volumes()` lists the mounted media volumes from `discover_mounts()` (cached for 15 s,
  since artwork requests hit this once per image) and drops `/`. `on_media_volume(path)` is true
  when `realpath(path)` sits on one of those volumes. `servable(path)` is the confinement check
  for serving a file by path: inside a configured library **or** on a mounted media volume.
  `owner()` is unchanged and stays strict — it still answers which library a path belongs to and
  is still what scans, writes and deletes are gated on.
- **`app/curator/routes/library.py`** — The five read-by-path endpoints (`/artwork`, `/media`,
  the episode stream, and both NFO readers) now gate on `folders.servable(real)` instead of
  `folders.owner(real) is not None`. Path traversal is still blocked: the path is `realpath()`d
  and must land on a mounted media volume, and the per-endpoint type checks (`is_image`,
  `naming.is_video`, `.nfo`) are unchanged.
- **`app/curator/routes/library.py`** — Restored `Cache-Control: private, max-age=3600` on
  `/artwork`. Invalidation after an artwork edit is already handled by the `v=` timestamp that
  `noteArtVersion()` adds to the URL, so a constant buster is not needed.
- **`app/static/js/video/common.js`** — Removed `params.set("cv", "2")` from `artUrl()`. The
  `v=` parameter remains and still busts the cache for an image that actually changed.


## 2026-10-18 — Bug fixes, security, scan speed, and new features

### Startup fixes & first-boot performance

- **`app/schema.sql`** — Removed stale `ALTER TABLE settings ADD COLUMN IF NOT EXISTS skip_patterns …`. The `settings` DB table was replaced by a JSON config file long ago; this dead statement crashed the migration on every fresh database with `UndefinedTable: relation "settings" does not exist`.
- **`app/resonance/db.py`** — Schema migration now runs inside a single `conn.transaction()` block instead of executing ~850 individual autocommit statements. On a fresh database this eliminates hundreds of round-trips and makes the migration atomic (all-or-nothing). The `schema_checksum()` result is memoised after the first disk read so the file is not read twice per migrate call.
- **`app/main.py`** — `_build_static_hashes()` (SHA-256 walk of every static file) is now launched in a daemon thread at startup instead of blocking the import path. The event loop is no longer held up while all JS/CSS/image files are hashed; the cache populates in the background (typically < 1 s) and pages served before it finishes simply omit the cache-busting query string for unhashed files.

### Artwork cache — orphan sweep

- **`app/resonance/artwork.py`** — Added `sweep_cache()`: walks `artwork_cache_dir()`, fetches the set of all `local_path` values from `artwork_pool`, and deletes any cache file not in that set. The `undo/` subfolder is skipped (managed by the undo machinery). Removed files and any errors are logged at INFO/WARNING level.
- **`app/resonance/jobs.py`** — `sweep_cache()` is called automatically at the end of a successfully completed scheduled music scan, so orphans left by Postgres CASCADE deletes are cleaned up without manual intervention.

### Bug fixes
### Scan stepper — wrong stage highlighted and active-stage visual polish
### Video library — unmatched items show ⚠️ warning icon

- **`app/static/js/video/common.js`** — `titleFacts()` now appends a ⚠️ icon in the title column for movies and shows that have no `tmdb_id`, `imdb_id`, or `tvdb_id` — i.e. items the scan could not match to any database. The icon has `title="Not matched to any database"` for hover context.
- **`app/static/app.css`** — Added `.process-mark.unmatched` to scale the ⚠️ emoji to match the surrounding text size.


- **`app/static/js/core/scan.js`** — `renderScanModal()` now skips spans that are hidden (metadata/artwork hidden when `fill_missing_during_scan=false`): those spans get their `.done` and `.active` classes cleared and are not counted in phase-index arithmetic. Previously a hidden span with `index >= 0` could incorrectly receive `.done` if the current phase happened to follow it in the full `PHASES` array.
- **`app/static/js/video/scan.js`** — `paintVideoScanSteps()` now clears `.done` and `.active` from hidden spans before returning early. Also fixed a real bug: when trailers download **alongside** the lookup phase (parallel thread), they finish before lookup does and the backend sets `trailers_done=true` while `scan.phase` is still `"lookup"`. The stepper was immediately showing Trailers as green/done. Now, if `trailers_done` becomes true while the scan is still in `lookup`/`read` phase, the Trailers pill stays `.active` (shown as still-in-flight) until the scan actually advances past that phase.
- **`app/static/app.css`** — `.stepper span.active` now renders as a solid filled pill: accent background, dark text, bold weight, and a soft box-shadow glow. The previously plain coloured border was easy to miss at a glance; the new style makes the running stage immediately obvious.


- **BUG 1 — TV show-folder detection** (`video/scanner.py`): `_show_folders` no longer treats the root itself as a single show when it already contains named show subfolders. The root is treated as a single show only when a `tvshow.nfo` exists *and* there are no show subdirectories.
- **BUG 2 — Prune safety threshold** (`video/scanner.py`): a single scan run can now remove at most 20% of the known movies for a root. If the walk would remove more, the prune is skipped and the anomaly is logged. This prevents mass-deletions when a mount is temporarily offline.
- **BUG 3 — Folder mtime for incremental skip** (`video/scanner.py`, `schema.sql`): `_folder_newer()` now walks one level deep to find the real max mtime rather than relying on the top-level folder's mtime alone. Comparisons are timezone-aware. A new `folder_mtime TIMESTAMPTZ` column is written in place of the broken `updated_at` fallback.
- **BUG 4 — Connection-pool stall** (`resonance/db.py`): the pool `max_size` is now `max(16, probe_workers + 6)` so that 8 probe workers, 6 other threads, and the main thread can all hold a connection without blocking.
- **BUG 5 — Unreadable subfolder aborts walk** (`video/scanner.py`): an `OSError` on an unreadable subdirectory during the movie walk is now logged and skipped; it no longer aborts the entire scan.
- **BUG 6 — Symlink loop protection** (`video/scanner.py`): `os.walk(followlinks=True)` is used everywhere and a `seen_realpath` set prevents loops from cycling indefinitely.
- **BUG 7 — (MISSING — deferred)**: placeholder.
- **BUG 8 — Sidecar rewrite on every scan** (`video/mediainfo_xml.py`): `.cmm_mediainfo.xml` sidecars are now compared content-by-content before writing. A file whose content has not changed is left alone, avoiding spurious mtime updates. Controlled by `CMM_WRITE_SIDECARS` (default `1`).
- **BUG 9 — Atomic rename race** (`video/rename.py`): the TOCTOU exists-then-rename pattern is replaced with a direct `os.rename` wrapped in `try/except FileExistsError`. DB updates are rolled back when the rename succeeds but the DB write fails.
- **BUG 10 — Cross-filesystem move** (`video/relocate.py`): moves on the same filesystem now use `os.rename` (instant, no copy). Cross-filesystem copies check free space first (refuses when `src_size > free × 0.95`), add `progress` and `cancel` support, and wrap the two DB updates in a single transaction.
- **BUG 11 — DST-aware scheduling** (`resonance/cron.py`): `get_timezone()` now checks `CMM_TIMEZONE` before `TZ` and the system default. `zoneinfo.ZoneInfo` handles DST transitions (spring-forward gap, fall-back fold) correctly.
- **BUG 12a — `clock_timestamp()` in polling** (`video/store.py`): `changes()` now reads wall-clock time with `SELECT clock_timestamp()` instead of calling `NOW()` (which is pinned to the transaction start).
- **BUG 12b — Lidarr delete events ignored** (`curator/arr_hooks.py`): `AlbumDelete`, `ArtistDelete`, and `TrackFileDelete` are now included in `LIDARR_EVENTS` and trigger a rescan.
- **BUG 12c — DB call inside lock** (`curator/ingest.py`): the `running_items` database query in `snapshot()` is now executed before acquiring `_cache_lock` to avoid blocking other threads.
- **BUG 12d — dovi_tool Popen leak** (`video/probe.py`): if the second `Popen` for dovi_tool fails, the already-started ffmpeg process is now killed and waited on before re-raising.

### Security

- **WebSocket Origin check** (`main.py`): `/ws/events` validates the `Origin` header against a comma-separated whitelist in `CMM_ALLOWED_ORIGINS`. When the variable is not set the endpoint is permissive (any origin), preserving existing docker-compose deployments.

### Scan speed

- **MediaInfo `--ParseSpeed=0`** (`video/probe.py`): tag parsing is set to the fastest mode. MediaInfo is now called conditionally: skipped entirely when ffprobe already has the video codec and stream details, and run only for files where HDR/Dolby Vision or codec info is missing.
- **Music artist scan parallelised** (`resonance/scanner.py`): the per-artist local scan loop now runs in a `ThreadPoolExecutor` (default 4 workers, configurable via `CMM_ARTIST_WORKERS`). Online lookups (MusicBrainz etc.) still run serially to respect rate limits.
- **Single `scandir` pass for album directories** (`resonance/scanner.py`): `_album_directories` uses `os.scandir` instead of `os.listdir` + `os.path.isdir`, halving the number of syscalls per directory.
- **Skip `_refresh_artist_name` for unchanged artists** (`resonance/scanner.py`): the expensive name-refresh query is now skipped when no tracks in the artist changed.
- **Auto-sized DB connection pool** (`resonance/db.py`): see BUG 4 above.
- **`text_pattern_ops` indexes** (`schema.sql`): LIKE-prefix indexes on `movies.folder`, `movies.title`, `tv_shows.folder`, `tv_shows.title`, `albums.path`, `artists.path`, and `artists.name`.
- **`GZipMiddleware`** (`main.py`): all API and page responses ≥ 1 KB are now gzip-compressed.
- **Content-hashed static file URLs** (`main.py`): `url_for("static", filename=…)` appends a short SHA-256 digest (`?v=<12 hex chars>`) so browsers can cache static assets indefinitely without serving stale JS or CSS.

### New features

### New feature — Synced Lyrics Editor

- **Button in the player dock** (`app/templates/index.html`): a pen-and-notes icon button (`#player-lyrics-edit`) appears next to the volume knob whenever the currently selected track has `lyrics_type = "lrc"`. The button is hidden for all other tracks.
- **Edit Synced Lyrics modal** (`app/templates/index.html`): a full-width modal lists every LRC line as a timestamp + lyric row. Double-clicking a line seeks the player to that position.
- **Keyboard shortcuts inside the modal**:
  - `Space` — stamps the current playback time on the focused line and advances to the next.
  - `Shift+Space` — stamps and moves back one line (for corrections).
  - `↑ / ↓` — navigate between lines.
  - `← / →` — nudge the focused line ±100 ms.
  - `Ctrl/Cmd+S` — save immediately.
- **Global offset** — an offset input shifts every timestamp by a fixed number of milliseconds before saving (useful for fixing a track that is consistently early or late).
- **Backend endpoints** (`app/curator/routes/music_jobs.py`):
  - `GET /api/tracks/{id}/lyrics` — reads the `.lrc` sidecar file and returns its raw content.
  - `PUT /api/tracks/{id}/lyrics` — accepts the edited LRC content and writes it atomically via `atomic_write`.
- **JS editor** (`app/static/js/music/lyrics-editor.js`): parses `[mm:ss.cc]` timestamp tags, maintains in-memory lines, and serialises back to LRC on save. The main `#player` audio element is reused so the audio keeps playing while the user stamps lines.
- **Hooks in events.js / keyboard.js**: `data-action="lyrics-edit"` is dispatched to `openLyricsEditor()`. `paintPlayerIdentity()` calls `updateLyricsEditButton()` on every track change.


- **`CMM_SKIP_PATTERNS`** (`video/naming.py`): a comma-separated list of glob patterns (e.g. `*.tmp,__pycache__`) that are excluded from directory walks, in addition to the existing hard-coded "bad words" and the SKIP_DIRS list.
- **`skip_patterns` setting** (`schema.sql`): a `TEXT[]` column on the `settings` table stores UI-managed skip patterns alongside the env-var list.
- **`CMM_WRITE_SIDECARS`** (`video/mediainfo_xml.py`): set to `0`, `false`, or `no` to disable `.cmm_mediainfo.xml` sidecar creation entirely.

### Schema

- Added `folder_mtime TIMESTAMPTZ` to `movies` and `tv_shows`.
- Added `missing_since TIMESTAMPTZ` to `movies` and `tv_shows` (placeholder for future missing-state tracking).
- Added `skip_patterns TEXT[]` to `settings`.
- Added `text_pattern_ops` indexes on path/title columns for fast LIKE prefix queries.

### Build

- Pinned base image to `python:3.11-slim-trixie` (was `python:3.11-slim`).
- Pinned `yt-dlp` to `2025.03.31` instead of `releases/latest`.
- Flask was never in `requirements.txt`; the stale `.venv` entry is a local artifact.


## 2026-10-18
### Changed
- **Probe workers cap raised from 8 to 20** (`CMM_PROBE_WORKERS`, Settings → Scan).
  Each probe worker opens one file at a time (ffprobe, then MediaInfo when needed, then
  dovi_tool for DV). On a 16-core machine with a NAS library the extra workers keep more
  reads in flight during I/O waits, shortening the probe phase of a deep scan. The NAS
  throughput ceiling still limits the gain, but 8→20 is a meaningful step for large remux
  libraries. The DB connection pool scales with probe_workers automatically.

### Fixed
- **probe.py**: MediaInfo skip condition was too broad — it skipped MediaInfo for any file
  with a video codec name, which stripped all Dolby Vision profile/compat/EL-type data from
  the output. MediaInfo now always runs when ffprobe's side-data contains a DOVI configuration
  record, preserving P7 FEL/MEL detection, dvhe.xx.xx profile strings, HDR10/HLG compat flags,
  MaxCLL/MaxFALL, and audio commercial names for all DV content.


### Movie and TV scans

- **Incremental deep scan** and **Full** finish the folder walk before any probe starts. The walk builds the list of files that need work. Probe workers then read that list. The walk does not wait on the workers, because they are not running yet.
- **Incremental deep scan** compares size, modification time, the `.nfo`, and the folder time. A match is left alone. A file that differs is probed after the walk.
- **Full** reads every file during the walk. A file that already has every enabled field and image, and has not changed, is left alone. A file that is new, changed, or whose last probe failed or never finished is probed after the walk. Missing metadata and artwork are looked up after probing.
- **Deep** counts folders and video files first. That pass lists names only. The progress bar and the time estimate use that file total. Every file is then probed, with one group the size of the worker setting open at once.
- A folder with no episode files is not probed for episodes. A new or changed `tvshow.nfo` or `season.nfo` in that folder is still read. Empty folders are logged and counted in the scan report. A video file on disk with no episode row is stored as a new episode.
- Local `.nfo` metadata and local artwork are saved during **Folders and files**. The log at the end of that stage lists `.nfo` files and every stored artwork type.
- The movie and TV stepper is **Folders and files**, **Metadata and artwork**, **Trailers**, then **Write .nfo**. The folder walk is about 10% of the scan bar, probing about 45%, and the metadata and artwork lookup about 40%.
- An empty library offers Deep scan only. Otherwise Incremental deep scan is selected when the scan dialog opens.
- Removal still waits until the walk of that folder has finished and the probe workers have drained.
- `CMM_PROBE_WORKERS` stays 1 to 8. The compose default is 8.

### Scraping

- The three write modes are gone. Movies, TV, and movie sets each have **Overwrite metadata** and **Overwrite artwork**. On replaces a value the lookup has. Off fills an empty value. An image is replaced only when the new file is larger.
- `CMM_OVERWRITE_ALL` turns both switches on until Settings are saved.
- The scrape dialog has those two switches for the current run, starting from the saved settings, and **Rewrite .nfo files this time**. On replaces the `.nfo` and keeps a `.nfo.bak` when backup is on. Off writes an `.nfo` only when one is missing.

### Library updates

- **Send library update** queues the selected players. Recent library updates name the movie or the TV show, with the folder listed under that title.
- Emby, Plex, and Navidrome each have an **Enable** switch. Off keeps the saved library choices and stops library updates. Emby also stops on-screen messages.

### Connections

- A failed call to Trakt, Radarr, Sonarr, Lidarr, Bazarr, Kodi, Emby, Jellyfin, Plex, Navidrome, TMDB, TheTVDB, OMDb, Fanart.tv, Last.fm, MusicBrainz, or another mapped host raises an alert and shows **Connection error** on that integration in Settings. The same message stays until it changes. A later successful call clears it.
- Trakt device-code refresh sends `redirect_uri` only when it is an `http` or `https` address with a host.

### Music

- `CMM_SCRAPE_MUSIC` includes Lidarr import webhooks in the music scan. The switch is on General and on Automation. A saved setting overrides compose.

### Interface

- While another scan is running, the Scan button says `Queue |` and still shows the selected folder, or All music, All movies, or All tv shows.

## 2026-10-18 — New feature batch (continuation)

### Task #10 — Webhook queue countdown in taskbar

- **`app/templates/index.html`** — Added `<span id="dock-queue-countdown">` inside the `#dock-queue` button to display a live countdown.
- **`app/static/js/core/live.js`** — `paintQueuePill()` now reads `live.queue.remaining_seconds` and `live.queue.queued_items_count` to populate the countdown span with a short label (`45s`, `2m`). The span is hidden when the queue is empty or already running.
- **`app/static/app.css`** — Added `.dock-queue-cd` styling (accent background pill) for the countdown label.

### Task #4 — "Unmatched" preset filter in video dropdown

- **`app/static/js/video/movies.js`** — Added `["unmatched", "Unmatched", (m) => !m.tmdb_id && !m.imdb_id && !m.tvdb_id]` to `MOVIE_RIBBONS` (not in `QUICK_RIBBONS`, so it appears only in the dropdown).
- **`app/static/js/video/tv.js`** — Same addition to `TV_RIBBONS`.

### Task #5 — Lyrics editor dirty-state indicator

- **`app/static/js/music/lyrics-editor.js`** — Added `_updateDirty()` helper; called after every stamp/nudge/save/close. Toggles `is-dirty` class on the save button and sets `data-dirty` on the editor title.
- **`app/static/app.css`** — `#lyrics-editor-title[data-dirty="1"]::after` shows a yellow dot; `#lyrics-save-btn.is-dirty` shows an accent glow ring.

### Task #6 — Scan log retention as user setting

- **`app/resonance/settings.py`** — Default `scan_log_keep` raised from 10 → 30; cap raised from 10 → 100.
- **`app/static/js/core/settings.js`** — `#scan-log-keep` `max` raised to 100, default value updated to 30.
- **`app/curator/video/scanner.py`** — `_write_log` now reads `scan_log_keep` from settings instead of using a hardcoded 10.

### Task #7 — n/total count in music scan phase label

- **`app/static/js/core/scan.js`** — `paintScanMeters()` appends ` N/total` to the "This stage" label when `scan.total > 0`.

### Task #8 — Bulk "fix match" flow for video

- **`app/static/js/video/scrape.js`** — Context menu shows `Fix Match… (N)` when multiple items are selected. Introduced `_bulkMatchQueue`, `_bulkMatchIndex`, `openFixMatchBulk()`, `_openNextBulkMatch()`, and `skipBulkMatch()`. After each successful apply the queue advances automatically with a 300 ms delay.
- **`app/templates/index.html`** — Added `#video-match-bulk-progress` span and `#video-match-skip-btn` button to the match modal header.

### Task #9 — Episode thumbnail generation

- **`app/curator/routes/library.py`** — New `POST /api/v1/tv/episodes/{id}/thumb` endpoint: runs ffprobe for duration, seeks to ~40% (bounded [5 %, 90 %]), uses ffmpeg `select=gt(scene,0.05)` to avoid black frames, falls back to a plain seek if the scene filter yields nothing.
- **`app/curator/video/scanner.py`** — `_generate_missing_ep_thumbs()` generates thumbs for all episodes under the scan roots that are missing artwork, using the same ffmpeg logic. Called at the end of every TV scan when `scan_generate_ep_thumb` is enabled.
- **`app/curator/video/config.py`** — Added `scan_generate_ep_thumb` (default `True`).
- **`app/static/js/video/edit.js`** — "Generate thumb" button on episode info pane; calls the new endpoint and refreshes the pane.
- **`app/static/js/core/video-settings.js`** — Checkbox "Generate episode thumb if missing during TV scan".

### Task #11 — Sync tab in Settings

- **`app/templates/index.html`** — Added "Sync" tab button to the settings navigation bar.
- **`app/static/js/core/settings-tabs.js`** — Added `"sync"` to `SETTINGS_TABS`; `applySettingsTab()` now calls `loadSyncTab()` for the sync tab (loads Trakt status and refreshes player clean schedule list). Added `loadSyncTab()`, `paintPlayerCleanSchedules()`, and `playerCleanScheduleSection()` helpers.
- **`app/static/js/core/settings.js`** — `scheduleSection()` now uses `data-tab="sync"` for scan schedules (moved from General tab). Added `showPlayerCleanPanel()`, `_readPlayerCleanCron()`, `savePlayerCleanSchedule()`, and `removePlayerCleanSchedule()` functions.
- **`app/static/js/core/trakt.js`** — Trakt section now uses `data-tab="sync"` (moved from Integrations tab).
- **`app/static/js/core/events.js`** — Added handlers for `save-player-clean-schedule`, `remove-player-clean-schedule`, and `player-clean-mode` radio changes.
- **`app/resonance/settings.py`** — Added `player_clean_schedules` default (`[]`), `_player_clean_schedules()` validator, and merge into normalised settings.
- **`app/curator/curator_schedule.py`** — New module: background thread that checks `player_clean_schedules` every 15 s and fires `_fire_clean(player, media)` when a cron expression matches. Kodi uses `enqueue(..., clean_only=True)`; other players fall back to a full library scan.
- **`app/main.py`** — `curator_schedule.start()` called at boot alongside the existing `schedule.start()`.


### Task #12 — Split episodes modal + embedded video player

### Bug fix — video artwork broken by bad stream endpoint

- **`app/curator/routes/library.py`** — The `/tv/episodes/{episode_id}/stream` endpoint introduced in Task #12 called `store.get("tv_episodes", episode_id)` but no such function exists in `store.py`. This caused an `AttributeError` at runtime when the route was hit, which manifested as video artwork (poster, banner, fanart) failing to load across the entire video library. Fixed by replacing the invalid call with `db.fetchone("SELECT * FROM tv_episodes WHERE id = %s", (_uuid(episode_id),))` and correcting the column reference from `file_path` to `path` (the actual column name in `tv_episodes`).

- **`app/curator/routes/library.py`** — New `GET /api/v1/tv/episodes/{episode_id}/stream` endpoint: validates the episode file is within the configured library via `folders.owner()`, parses the `Range` header, and returns a `StreamingResponse` with `206 Partial Content` (or `200` for a full response). The `_iter_file()` generator yields chunks of up to 1 MiB so the browser can seek freely.
- **`app/templates/index.html`** — Episode split modal gains `.modal-wide` class. A persistent `#episode-split-player-wrap` div (with `<video id="episode-split-video">`, a timecode display, "Mark current time" button, and a target label) sits above the dynamic `#episode-split-body`. The player section is hidden by default and only shown when a single episode's splits are being edited.
- **`app/static/app.css`** — Added `.modal-wide`, `.episode-split-layout`, `.episode-split-player`, `.episode-split-player-controls`, and `.split-timecode` styles for the wider modal and video player panel.
- **`app/static/js/video/tv.js`** — `_formatSplitTime(seconds)` formats a timestamp as `H:MM:SS.mmm`. `_bindSplitVideoPlayer(plan)` sets the video `src` to the stream endpoint and shows the player when there is exactly one episode plan; hides it otherwise. `markSplitVideoTime()` copies the formatted current time into whichever `[data-split-time]` input was last focused (`state._splitFocusedInput`). `paintEpisodeSplits()` calls `_bindSplitVideoPlayer()` after rendering. `stopSplitPoll()` now pauses and clears the video src so the stream connection is released when the modal closes.
- **`app/static/js/video/edit.js`** — Added `"video-split-mark": () => markSplitVideoTime()` action handler so the "Mark current time" button wires up through the existing data-action event system.
