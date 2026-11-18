# Changelog

## v4.3.8 — 2026-11-18 — Deleting from the recycle bin cannot leave the bin folder

- **A guard on every permanent delete.** Delete now, Delete selected, Empty recycle bin, the automatic emptying after
  the chosen number of days and the low-space cleanup all go through one function. It now refuses any path that is
  not strictly inside a recycle bin folder (`.curator-trash` at the top of a library folder, in the item's own
  subfolder) and inside the bin of the library folder the item came from. Such a row is skipped, stays listed, and
  an error is written to the log. The paths were always written that way; this makes sure a wrong or damaged row can
  never point a delete at a library folder or a drive.

## v4.3.7 — 2026-11-17 — No Kodi alert when there was nothing to update; Copy log works in Recent jobs

- **No more "Kodi refreshed 0 items" for new albums.** When Curator saves artwork for an album or artist it asks Kodi
  to show the new picture, because Kodi keeps showing its cached copy of the old one otherwise. Curator cannot know
  whether Kodi has the album without asking, and during a Lidarr import Kodi does not have it yet. That is not news:
  such a refresh now leaves no alert and no row in Recent library updates (the container log still has a line). The
  same goes for an artist or a movie set Kodi does not have. A refresh that did update something is reported as before.
- **Copy on a job's log in Jobs, Recent works.** The copy waited in the action queue, and over plain http a browser
  only lets a page copy while it is still handling the click, so it was refused without a word. It now copies straight
  from the click, and says so when the log is still loading or the browser refuses.
- Nothing changed in when Kodi scans music: the albums of a webhook run are sent to the players once every item of
  that run has been scanned in Curator, and Kodi reads their artwork during that scan.

## v4.3.6 — 2026-11-17 — Follow imports shows the players side by side

- **Players are one step with a branch each.** Kodi, Jellyfin, Emby, Plex and Navidrome have always been updated at
  the same time, each on its own; one never waits for another. Follow imports drew them one after the other on the
  line, which read as if Kodi waited for Jellyfin. With two or more players they are now one last step, a branch per
  player joined by a dotted line, each with its own state and time. A single player is drawn as before.

## v4.3.5 — 2026-11-17 — Music videos from YouTube: needs a folder, folder rule, linked to an artist

- **+ Add from YouTube is off until a Music videos folder is set** under Settings, General. Hovering the button says
  why. With more than one Music videos folder, the download form has a Folder choice.
- **Folder rule.** Settings, General, Music videos from YouTube chooses where a download is saved: in the artist's
  folder, made when it is missing (the default); in the artist's folder only when there already is one; or at the top
  of the Music videos folder. An artist folder is found whatever its spelling (AC/DC, AC-DC and ac dc, or Beatles and
  The Beatles, are the same folder), so no second folder is made for an artist.
- **The video is linked to an artist.** The artist guessed from the YouTube title is matched to the artists you
  already have (music videos first, then the music library) and takes that spelling. The Artist box suggests your
  artists as you type, so you can search and pick one when the guess is wrong. Under the names the form says which
  artist the video is linked to and which folder it will be saved in, before you download.
- **The .nfo follows Kodi more closely.** It already was a Kodi `<musicvideo>` file next to the video with the same
  name (title, artist, album, plot, director, year, genre, play count). It now also writes `<premiered>`, which newer
  Kodi versions read in place of `<year>`; only the year is known, so the date is the first of January, as Kodi
  itself exports it. Existing .nfo files get it the next time they are written (Write .nfo).

## v4.3.4 — 2026-11-17 — The info pane no longer jumps down to the trailer

- **The YouTube trailer is a picture with a play button until you click it.** The player used to load with the
  page. On some videos the YouTube player takes the keyboard focus as it loads, and the browser then scrolls the
  info pane down to it, which is why only certain movies or shows jumped. Now nothing from YouTube loads until the
  trailer is played, so the pane stays at the top. Clicking the picture plays the trailer in place.
- Unchanged: a downloaded trailer file plays in place as before, and Pop out player works the same.

## v4.3.3 — 2026-11-17 — Fix Match overwrites seasons and episodes too, and logs what became of the title

- **Fix Match on a show also lifts the field locks on its seasons and episodes.** Season names, episode titles, plots
  and dates that were locked under the old match are replaced by the new one. Kept are the locks that say where a
  file belongs or what you watched: season number, episode number, edition, tags, your rating and watched state.
  A season or episode locked as a whole is left alone.
- **The scrape log of a Fix Match now has a line about the title**: the old and the new title, or why the old one
  stayed (the field is locked, or the new match gave no title, or both matches have the same title). Open the job
  under Jobs, Recent to read it.

## v4.3.2 — 2026-11-17 — Fix Match replaces a title that was edited by hand

- **Fix Match no longer keeps the old title.** A title (or plot, year, original title and so on) that was once edited
  by hand is locked against scrapes, and Fix Match respected that lock: everything changed to the new match except
  the locked field, so a wrongly matched show kept its wrong name. Fix Match on a movie or a show now lifts the field
  locks that belonged to the old match before it scrapes, so the new match lands completely.
- Kept: the locks on edition, movie set, tags, your own rating, watched state and episode order, which are about your
  copy and not about which title it is. An item that is locked as a whole still refuses Fix Match, as before. Field
  locks on single seasons and episodes are left alone. Undo Fix Match puts the old locks back with the old values.

## v4.3.1 — 2026-11-17 — The Sonarr, Radarr and Lidarr rescan no longer reads like a player update

- **Menu names.** The right-click entry that asks Sonarr, Radarr or Lidarr to rescan was called *Update library in*
  followed by only that app's icon, next to *Update library…* for the players, so the two were easy to mix up. It
  is now **Rescan in Sonarr** (or Radarr, Lidarr), with the icon and the name, and the players' entry is **Update
  player library…**.
- **The message says what did and did not happen.** After a Sonarr, Radarr or Lidarr rescan the message ends with
  "No player was asked to update: use Update player library for Kodi, Emby, Jellyfin or Plex." For Sonarr it also
  says why Curator scans the show afterwards: Sonarr only reports files it adds or removes, so changed episode
  numbers or paths would otherwise go unnoticed.

## v4.3.0 — 2026-11-17 — Recycle bin: select several, delete or restore them together, no reload

- **Tick boxes in the recycle bin.** Every row has a box, the header has one that ticks or clears them all, and
  **Select all** above the list does the same (it reads **Deselect all** when everything is ticked).
- **Delete selected** and **Restore selected** work on the ticked rows and show how many are ticked in a count on
  the button. Delete selected asks once, naming the number of items and their total size.
- **The list is no longer read again after a change.** Deleting or restoring one item or several takes just those
  rows out of the list, and the list stays where you had scrolled it. An item that could not be deleted or restored
  stays listed, and ticked. **Refresh** still reads the bin again.

## v4.2.9 — 2026-11-17 — The restart rule covers Emby, Jellyfin and Plex too

- **A full scan a player is still running is not sent again after a restart, on every player that can tell.** What
  v4.2.8 did for Kodi now also holds for Emby and Jellyfin (their Scan Media Library task) and Plex (the library
  sections that report refreshing): Curator waits for the scan in progress and removes the re-queued job, and the
  Recent library updates row says so.
- Navidrome does not report a scan in progress to Curator, so its scan request is sent again. As before, an idle or
  silent player and an update of named folders are sent again.

## v4.2.8 — 2026-11-17 — A restart no longer repeats a full Kodi scan that is still running

- **A full Kodi scan in progress is not sent again after a restart.** A full video or music library scan that was
  running when Curator stopped is put back in the queue on start, as before. When Kodi is still scanning at that
  moment, Curator now waits for that scan to finish and removes the job instead of sending the same scan a second
  time. The alert and the Recent library updates row say so. The updates queued behind it still wait their turn.
- Unchanged: when Kodi is idle or does not answer, the scan is sent again, and an update of named folders is always
  sent again, because the folders behind the one Kodi was on were never scanned.

## v4.2.7 — 2026-11-17 — Player library updates say what triggered them

- **Every player library update records its trigger.** The Queue's Library updates rows show **Triggered by:** under
  the scope, and the finished row in Recent library updates ends with it too. The Kodi alerts "library scan sent
  for…" and "Kodi is still scanning… waits" name it as well. Triggers are, for example, *Radarr webhook (Download)*,
  *Sonarr webhook (Download, Rename)*, *Scheduled video library update*, *Manual library update*, *Library update*
  (the button on selected items), *Retry button in Recent updates*, *File job (rename)*, *Bulk duplicate cleanup*,
  *Music videos scan (incremental)*, *Lidarr import scan* and *Scan from the Kodi report*.
- **Folded updates keep every trigger.** When several requests become one job (two full Kodi scans, or more folders
  for the same player), the row lists each trigger once, up to six.
- **An update that was running when Curator stopped says so.** Curator has always put such an update back in the queue
  on start, which after a rebuild looks like a scan nobody asked for. Its trigger now ends with *Curator restarted
  while this update was running*.

## v4.2.6 — 2026-11-17 — Choose what the health score counts

- **The health score no longer counts subtitles or the lesser file warnings.** An unknown audio language, no audio
  track or a shorter-than-expected file, and missing subtitles, no longer lower a movie's or show's score. Six things
  count out of the box: matched, scraped, .nfo, poster, fanart, and a file that is not corrupt and could be probed.
- **Choose what counts.** Under Settings, Movies and Settings, TV shows, below **Show the health score**, there is one
  box per check, including **Subtitles** and **No other file warnings** for those who want them back. Movies and TV
  shows have their own choices. Every check that is ticked counts the same; with none ticked there is no score. The
  Needs work and Complete filters follow the same choices.

## v4.2.5 — 2026-11-17 — Health score for movies and shows; What changed window

- **Health score.** Every movie and TV show gets a score from 0 to 100 beside its title, green at 100, amber from 70
  and red below. Seven things count the same: matched to a database, scraped, .nfo present, poster, fanart, subtitles
  and a file without warnings. For a show the .nfo, subtitle and file checks cover its episodes too (an episode
  without an .nfo, without subtitles or marked corrupt lowers the show's score). Hover the score to read what to fix.
  A missing trailer, theme song or extra artwork type does not lower it, and missing episodes do not either (they
  have their own filter). Seasons and episodes have no score of their own.
- **Needs work and Complete filters** under More filters on Movies and TV shows list what is below 100 and what is
  at 100. They stack with the other filters and can be saved like them.
- **Show the health score** under Settings, Movies and Settings, TV shows (List options) turns the badge off. It is
  on by default.
- **Tools, What changed.** One window for a period (last 24 hours, 7, 30 or 90 days): movies, episodes, albums and
  music videos added, what was deleted, removed, renamed, moved, restored or found corrupt (from Activity history,
  with the reason), artwork that was replaced, and the jobs that failed with their message. Each kind is a block that
  folds; empty kinds are left out. It is built from what Curator already records, so it covers the days before this
  version too.

## v4.2.4 — 2026-11-17 — Undo for video artwork; add a music video from YouTube

- **Undo last artwork in the video artwork window.** When a picture of the open movie, show, season, episode or set
  was replaced (by a pick, an upload, Clean artwork or a scan) and is still kept, the window's header shows **Undo
  last artwork**. It puts that picture back, whatever its type. Pressing it again brings the newer one back.
- **Music videos: + Add from YouTube.** Search YouTube from the Music videos tab, pick a result, check the artist,
  title and year Curator guessed from the video's title, and download. The file is saved as `Artist - Title (Year)`
  in the artist's folder when your library already has one and otherwise at the top of the Music videos folder, at
  the quality set under Settings, General, Trailer download quality. It never overwrites a file. One download runs at
  a time, shown in the Jobs panel, and the video joins the list with its .nfo when it is done. A download YouTube
  refuses is reported with yt-dlp's own message and leaves nothing behind.

## v4.2.3 — 2026-11-17 — Music filters stack, sets can be rescanned, music videos get filters and bulk actions

- **Music: several filters at once.** Picking a filter adds it to the ones that are on, and they must all hold
  ("Unmatched" and "No Art" together). Picking a lit one takes it off; **Clear all** or All takes them all off. A
  saved filter keeps the combination. The filter button says "2 filters" and lists them in its tooltip.
- **Movie sets: Rescan** in the selection bar. A set has no folder of its own, so this scans the folders of its
  movies, with the same Incremental, Full and Deep choices as movies.
- **Music videos: quick filters,** as on the Movies and TV tabs: No NFO, No picture, No year, No album, 4K, 1080p,
  Below 720p, Duplicate, Upgrade available, Corrupt, Locked. Several can be on at once.
- **Music videos: tick several.** A tick box per row and a bar for the ticked ones: Write .nfo, Rename, Lock or
  Unlock, Quick integrity check, and Remove or delete (to the recycle bin, or from the library only). A locked video
  shows a lock by its title.
- **Music videos: Rename** to `Artist - Title (Year)`, in the video's own folder. The .nfo, the media info file and
  the pictures are renamed with it. It shows what would change first, and never overwrites a name that is taken.
- Export and the integrity check already existed for music and sets (Export on every tab; *Audit audio* in the album
  menu), and music videos could already be locked and deleted to the recycle bin one at a time.

## v4.2.2 — 2026-11-17 — Settings: the same sections on every library tab

- **Music** has a **During a scan** heading for its scan switches, with a new one: *Replace artwork with the wrong
  shape during a scan* (it was on with no switch).
- **Movie Sets** has **During a scan** (the wrong-shape check, which runs at the end of a movie scan) and **Metadata
  fields** (a set has one scraped field, its overview; untick it and a scrape leaves the overview alone).
- **TV Shows and Movie Sets show Artwork languages and Writing.** These settings are shared by movies, TV and sets and
  could only be found on the Movies tab. They now appear on the other tabs too, marked as shared: changing one
  changes the same setting everywhere.
- **Movies** has its own **Media info files** heading, as TV has (the switch sat under Writing).

## v4.2.1 — 2026-11-17 — Music and movie sets catch up with the artwork features of movies and TV

- **Music artwork window: tick several pictures.** Every card has a tick box; a bar offers Download, Ban and Delete
  for all the ticked ones. The first ticked cover (banner, logo and so on) becomes the file the players use, and
  further ones of that type are saved next to it as `folder1.jpg`, `folder2.jpg`…; fanart and booklet pages are one
  more file each, as before. The window does not list those numbered files yet.
- **Music: ban a picture.** A banned picture is never suggested and never picked by the automatic artwork download.
  It stays in the window, greyed out, with an Unban button. Bans are shared with the video artwork window.
- **Music: wrong shapes.** A fanart, banner, landscape or disc art listed at the wrong shape for its type is marked
  **Wrong shape**, never suggested and never picked automatically, and a music scan replaces a selected one with a
  right-shaped picture from its list. Covers, artist thumbs and logos come in every shape and are not judged. There is
  no switch for this in Settings yet; it is on.
- **Movie sets get the wrong-shape check** at the end of a movie scan (sets have no scan of their own).
- **Kodi is told about artwork changes of movie sets, albums and artists**: it forgets its cached copy and takes the
  new file, as it already did for movies and shows. The item is found in Kodi by its name. Plex, Emby and Jellyfin
  read that artwork on their own scans. This could not be tried against a Kodi here.
- **Recent jobs name the albums a music scan added or changed,** and a Lidarr import names its album. Movie set jobs
  already named their sets.
- Music artwork sizes were already kept in the database (every listed picture has its resolution), so nothing changed
  there.

## v4.2.0 — 2026-11-17 — Settings in cards

- **Settings is tidied up.** Every heading and the options under it now sit in a card of their own, with a marked
  title, on every tab, so the groups read apart. An option is a row that lights up under the pointer; the note that
  explains it is smaller, quieter and set in under the option's text; fields keep a sensible width instead of
  running across the window; sub-headings are small capitals; and a warning is a red box that cannot be missed. No
  setting moved or changed its meaning.

## v4.1.9 — 2026-11-17 — Schedules in words, Kodi refresh alerts, webhook scans in the Scan Queue, a tidier Queue window

- **Player schedules say when they run in plain words** ("Every day at 03:00", "Every Wednesday at 04:00"), with the
  cron text after it.
- **Every Kodi refresh leaves an alert,** also one that only changed artwork: "Kodi shows the new artwork of 3 items",
  with the titles, in Alerts and Recent webhooks. Before, an artwork update to Kodi only showed in Recent library
  updates, so there was no telling whether it had been sent or had worked. A failed one was already reported.
- **The Scan Queue lists the webhook imports while they are scanned.** The webhook queue scans and scrapes its
  folders itself, outside the scan queue, so that tab stayed empty and the items seemed to jump straight to Library
  updates. The running batch now shows there as "Webhook imports", with its titles, its stage ("2 of 3 scraped") and
  its time.
- **Queue window:** the status line (imports, files, jobs) sits in the header next to the title, and the Recent list
  of each tab folds away with a click on its heading, leaving the room to what is waiting. The choice is remembered.

## v4.1.8 — 2026-11-16 — Card buttons keep a readable hover

- **Fixed: hovering a movie in a set, a season on a show, an album in an artist's discography or a pick in a search
  result filled it with a light colour while the title stayed white,** so the label could not be read. These cards now
  show hover with an outline (sets and seasons) or a faint tint and an accent border (discography and picks), and keep
  their text colour.

## v4.1.7 — 2026-11-16 — The badge images travel as one file, media.zip

- **The shipped badge images (studio, network and record label logos, codec, resolution and provider badges, about
  4,750 small files) are packed into one file, `app/media.zip`,** built with `python scripts/pack-media.py`. The app
  serves them from the zip, and the Docker image holds only the zip: the `media/` folder stays out of the build, so
  copying the project and building the image no longer go through thousands of files. The build stops with a clear
  message when the zip is missing. A checkout that was not packed still works from the folder. `media/network/unused`
  (600 files nothing reads) and desktop junk such as `Thumbs.db` are left out of the zip.
- Badge images are sent with an ETag and may be kept by the browser for a day, so a page load no longer asks the
  server about every logo again. Logos you add in Settings, Files are unchanged: they live in the config folder.

## v4.1.6 — 2026-11-16 — Several posters can be ticked in the artwork window

- **Fixed: only one poster (or fanart, or any other single-file type) could be ticked at a time** in the artwork
  window; ticking a second one unticked the first. Any number can be ticked now, so several posters can be banned,
  deleted or downloaded in one go.
- **Several ticked pictures of one type are all saved.** The first ticked poster (fanart, banner, and so on) becomes
  the file the players use; the others are saved next to it as `poster1.jpg`, `poster2.jpg`… The players ignore those,
  and scans leave them alone. The artwork window lists them under their type as "poster1 next to it", each with a
  **Use** button that makes it the main file (the old main file is kept, to pick again) and a bin.
- The count pills on the Queue window's tabs sit on the middle of the label now, not low in the button.

## v4.1.5 — 2026-11-15 — Library updates: each album once, counts in pills, the folder Kodi is on with its time

- **Fixed: a library update row listed every album twice,** once in a comma list and again with its quality badges.
  When every title has its own line with badges, the comma list is left out.
- **The Queue window's tab counts are pills,** like the alert counts in the header, instead of brackets after the
  label. The Library updates count is the number of folders or titles still to do, not the number of jobs: a Kodi job
  of 37 folders with 4 done counts 33.
- **The Library updates banner names the folder Kodi is on and how long it has taken:** "Kodi · Music · scanning 5 of
  37: Sonic Youth — Star Power · 0:42, 32 more waiting", ticking each second. The running row says "Scanning 5 of 37"
  too. Kodi scans its folders one at a time; the other players send one request per folder and keep their old line.
- **Recent webhooks gets a row for every folder Kodi finishes,** with how long it took ("Kodi music library scan
  finished for /music/… (12 s)"). Before, only the start of each folder was recorded, and the end of the whole job.

## v4.1.4 — 2026-11-15 — A wider Queue window, with labels that stay whole

- **The Queue window is wider:** 96% of the window, up to 1400 px (it was 980 px), so the Item column has room for long
  paths next to the other columns.
- **Fixed: "Download" and "Remove" broke in the middle of the word** when the Item column squeezed the others. Only
  titles and paths may now break inside a word; event labels and buttons stay on one line.

## v4.1.3 — 2026-11-15 — The Queue panel's lists no longer jump while you read them

- **Fixed: Recent webhooks (and the other Queue panel lists) jumped away from what you were reading.** The lists are
  redrawn within a moment of every webhook and every few seconds anyway, and each redraw rebuilt the rows, so a new
  call at the top pushed the row you were reading down. A redraw now finds the row that was at the top of your view
  and puts it back in the same place. At the top of the list nothing is held, so new calls still appear there as
  before. This covers Waiting and Recent in every Queue tab (webhooks, scans, ARR, library updates).

## v4.1.2 — 2026-11-15 — Clean artwork for movie sets

- **Clean artwork works on movie sets.** Tick sets in the Movie sets tab and choose Metadata, *Clean artwork…*. A set
  offers **Fanart** (a fanart with a title or logo on it is replaced by the clean one the artwork window suggests),
  **Extra fanart** (repeats out, pictures with text swapped, topped up with clean ones) and **Any artwork with the
  wrong shape** (poster, fanart, banner, disc art and the rest). The pictures are saved in the set's folder inside the
  central set folder, as the artwork window does; without a central set folder (Settings, Movie Sets) a set is left
  alone and the job log says why. Locked sets and pictures you uploaded or kept stay.
- Curator does not send set artwork to the players itself yet, so the window shows a note instead of the player boxes
  for a selection of sets only; the players read set artwork from the central set folder when they scan the movies in
  the set. *Update artwork in players* still works on movies and shows only.
- Set artwork keeps its sizes in the database too, like movie and TV artwork.

## v4.1.1 — 2026-11-15 — A file job no longer reports the last job's result when it starts

- **Fixed: starting a file job could show the previous job's result at once** (for example "Clean artwork: 5698
  changed, 397 unchanged, 4 failed" right as a new Clean artwork run began). The page hears about the file job from
  three places: the live channel, the Jobs panel refresh and the file job window's own refresh. A refresh sent just
  before the new job started could arrive just after it, and the page took it as the new job ending. Every file job
  status now names its job and carries a number that only grows; the page drops a status older than the one it has,
  and announces the end only of the job it saw running.

## v4.1.0 — 2026-11-15 — Artwork sizes are kept in the database

- **The width and height of every movie, show, season and episode artwork file are now kept with its path.** The
  artwork map in the database gets a `_sizes` entry per file (width, height, modification time, file size). It is
  filled whenever artwork is saved, by a scan, a pick, an upload or a download, and a file is opened only when it is
  new or its time or size changed. Files that are gone lose their entry.
- **Shape checks read the database, not the files.** The scan step, Clean artwork's *Any artwork with the wrong
  shape* and the artwork window take the sizes from there. A file without a stored size (artwork from before this
  version) is opened once and its size written back, so the first scan after the update fills them in and later scans
  open nothing.
- **The scan step now checks every episode thumb** of the shows it looks at, not only the episodes it added or read
  again.

## v4.0.9 — 2026-11-15 — Season artwork and episode thumbs get the shape check; Download missing artwork takes Suggested

- **Season artwork and episode thumbs are checked for the wrong shape too.** Clean artwork's *Any artwork with the
  wrong shape* now also checks every season's poster, banner, landscape and fanart, and every episode thumb, of the
  selected shows, and gives a wrong one the suggested picture for that season or episode. The scan step checks the
  seasons of the shows it looked at and the thumbs of the episodes it added or read again (a full TV scan does not
  open every thumb in the library). Locked seasons and episodes stay. An episode thumb may be 4:3 up to 2.5:1, so a
  frame from a widescreen film still fits.
- **Download missing artwork takes the picture the artwork window marks Suggested** for each missing type: clean
  fanart first, the right shape and the largest. It took the first listed picture before.
- Scrapes (including the scan's artwork lookup and the webhook queue) already put clean fanart and character art
  first whenever *Prefer clean fanart* is on, which is the default; nothing changed there.

## v4.0.8 — 2026-11-15 — Artwork of the wrong shape is never chosen, and is replaced

- **Artwork of the wrong shape for its type is never chosen automatically.** A picture a site lists under the wrong
  type (a fanart among the posters) is skipped by scrapes, by *Download missing artwork* and by Clean artwork's extra
  fanart top-up. Fanart.tv lists no sizes, so every downloaded picture is also checked itself before it is saved, and
  the next candidate is tried. The artwork window still shows such a picture, marked **Wrong shape**, and never
  suggests it; you can still pick it yourself. The shapes are wide ranges per type: posters and key art tall,
  fanart, landscape and episode thumbs wide, banners a long strip, disc and square art square. Logos, clear art and
  character art come in every shape and are not judged.
- **Clean artwork: Any artwork with the wrong shape.** A new choice under Artwork types. Every picture of the
  selected movies or shows whose file is the wrong shape for its type, such as a fanart saved as the poster, gets the
  picture the artwork window suggests for that type. The files are checked on disk first, so an item whose pictures
  are all fine is not looked up online. Pictures you uploaded or kept, and locked items, stay.
- **Scans replace artwork of the wrong shape.** *Replace artwork with the wrong shape during a scan* (Settings, Movies
  and TV shows, under During a scan) is on by default. It checks the files of the items the scan looked at (an
  incremental scan the ones it added or read again, a full scan all) and replaces only the wrong ones, before Clean
  artwork. The scan log names each one (`Heat: poster 1920×1080, a poster should be tall`), and the progress shows it
  in the Clean artwork step. The players get the new pictures with the scan's own artwork update.
- Season and episode artwork is not checked by Clean artwork or the scan step yet, only by the downloads.

## v4.0.7 — 2026-11-15 — Lidarr's import-time Retag calls queue nothing

- **Lidarr Retag calls sent during an import are skipped.** While Lidarr imports an album it writes the tags into each
  new file and, with *On Track Retag* ticked, sends one Retag call per file before the album's Download call. Those
  calls carry a file id of 0 (the file is not saved yet) and only repeat what the Download call reports. Curator now
  records them in Recent webhooks as ignored, with the reason, and queues nothing; the Download call scans the album.
  A Retag of a file Lidarr already had (a real file id, for example from Lidarr's Retag button) is still scanned.

## v4.0.6 — 2026-11-15 — Ban bad artwork suggestions

- **Ban a picture in the artwork window.** Every online picture has a ban button (a crossed circle) next to its details,
  and the tick bar has **Ban** for several at once. A banned picture is never marked Suggested, never picked by Clean
  artwork, never downloaded by a scrape and never chosen by *Download missing artwork*. It stays in the window, greyed
  out and marked **Banned**, at the end of its type and outside the cap per site, with an Unban button. You can still
  download it yourself with its download button.
- A ban is kept by the picture's address, so it covers every type that lists that picture (a fanart is also an extra
  fanart candidate). The same shot on another site has another address and needs its own ban.

## v4.0.5 — 2026-11-15 — Extra thumbs are legacy and off by default

- **Extra thumbs (`extrathumbs/`) are now off by default and labelled legacy.** Kodi dropped them and few players read
  them, so a new install no longer downloads up to 10 per movie and show. Settings, Movies and TV shows, lists them as
  *Extra thumbs (extrathumbs/) · legacy, few players read them*; a choice you saved before is kept, so untick them there
  if you had them on. The scrape window's Extrathumbs (legacy) box starts ticked only when Settings has them on.
- **With extra thumbs off, the artwork window leaves them out completely.** It shows no Extrathumbs section, offers no
  candidates, and does not read or compare the files in `extrathumbs/`. Those files stay on disk untouched. Tick them in
  Settings to see and manage them again.

## v4.0.4 — 2026-11-15 — Lidarr Retag calls from a box set queue the box set under its artist

- **Fixed: a Lidarr Retag call for a box set queued the disc folder as an album and the box set as its artist.** A
  Retag call names the one file whose tags Lidarr rewrote, so its folder could be a disc folder such as
  `Playback/HDCD5`. Each disc became its own webhook queue item, the box set was scanned once per disc, and the scan was
  handed the box set folder as the artist. The album is now found the way a full library scan finds it, so a whole box
  set is one queue item under the real artist folder, the same item an import of that album uses. The album scan also no
  longer accepts an artist folder that is the album folder itself; the folders around the album decide.
- Retag calls restart the webhook timer like any other call, up to the maximum postpone counted from the oldest waiting
  item.

## v4.0.3 — 2026-11-14 — Artwork window: tick several images, extrathumbs in one section

- **Tick several images in the artwork window.** Every card has a tick box in its top left corner. While something is
  ticked, a bar above the cards shows how many, with **Download**, **Delete** and **Clear ticks**. Download saves the
  ticked online pictures one after another and the players get one artwork refresh for the item at the end. Extra
  fanart and extrathumbs add one new file per ticked picture. Any other type holds one file, so ticking a second
  picture of that type unticks the first. Delete moves the ticked files on disk to the recycle bin after one
  confirmation. A file that cannot be deleted or downloaded is reported, and the rest still go.
- **Fixed: extrathumbs were drawn as one section per file.** The artwork window now has a single **Extrathumbs**
  section for movies and shows, like Extra fanart. It shows the files in `extrathumbs/` as they are on disk and offers
  every landscape picture as a candidate (the same pictures a scrape uses for extrathumbs). Choosing or uploading one
  adds it as the next `thumbN` and replaces nothing. A candidate that is already in the folder is marked **In use**.
  Deleting one numbers the rest from the disk again.

## v4.0.2 — 2026-11-14 — Recent jobs name the movies and shows they worked on

- **Recent jobs now say which items they worked on.** Each finished job in the Jobs panel's Recent list shows the
  movies, shows or episodes it handled under its label, such as "Heat (1995), Alien (1979) and 3 more", with every
  kept name in the tooltip. This covers file jobs (Clean artwork, rename, subtitles and the rest), movie and TV scans
  (the items they added or read again; an incremental TV scan names the episodes when there are 25 or fewer), and
  scrapes, including the ones the webhook starts. A Kodi library update ends with what it scanned, for example
  "Kodi video library scan finished: Heat (1995), Alien (1979)." The first 25 names are kept per job, with the count.
  Jobs that finished before this version show no names.

## v4.0.1 — 2026-11-14 — Ticking a collapsed versions row selects all its versions

- **Fixed: a collapsed versions row selected only its best version.** With *Collapse versions of the same movie into
  one row* on, ticking such a row added one movie to the selection, so the count was too low and every action (Clean
  artwork, rename, scrape, delete and the rest) ran on that one version only. The row now selects every version in it,
  the count includes them all, and the row shows as ticked when all its versions are. This holds for the list and the
  poster grid, for a shift-click range and for the tick-all box. Expand the row to tick a single version.

## v4.0.0 — 2026-11-14 — The Jobs panel keeps finished jobs: Recent, with result and log

- **Recent in the Jobs panel.** A job vanished from the panel the moment it ended, so there was no way to see how it
  went. Under Running and Waiting, the panel now lists the last 30 finished jobs of every kind (file jobs such as
  Clean artwork, rename and integrity checks; scans; scrapes; background jobs), newest first, with Done, Failed or
  Stopped, when each ended and its summary (for a file job "1 changed, 3 unchanged"). **Log** opens the full log, with
  Copy, for file jobs, background jobs and music scans; movie and TV scans and scrapes point to Scan history, which keeps
  theirs.
- **File jobs are now recorded** when they end, with their log (the last 300 are kept). Before, their log lived only
  in memory until the next file job started.

## v3.9.9 — 2026-11-14 — The artwork bin deletes the picture you clicked, into the recycle bin

- **Fixed: deleting extra fanart in the artwork window could remove another file, or nothing.** The window numbers
  extra fanart from the folder as it is now, while the delete looked the number up in what the last scan stored, which
  can be numbered differently. The bin now sends the exact file it belongs to (in the artwork window and in an item's
  artwork strip), and Curator deletes only that file, when it is one of the item's artwork files or inside its folder.
- **Deleted artwork goes to the recycle bin** (Tools) instead of being removed at once, so a wrong click can be restored.
  The confirm names the file.

## v3.9.8 — 2026-11-14 — Clean artwork can also download missing clean pictures

- **Also download missing clean pictures**, a box in the Clean artwork window (on by default, remembered): an item
  without fanart or character art gets the clean picture the artwork window suggests, and extra fanart is topped up
  with clean pictures that are not there yet, up to the Maximum extra fanart in Settings, as the next fanartN files.
  Untick it to only clean what is already there. The scan stage only cleans; the lookup before it already fetches
  missing artwork.

## v3.9.7 — 2026-11-14 — Clean artwork as a scan stage

- **Clean artwork during a scan** (Settings, Movies and TV shows, under During a scan; off by default): a scan stage
  after the metadata and artwork lookup and before the .nfo files. It runs Clean artwork on the ticked types (Fanart;
  Character art for shows; Extra fanart) with *Only pictures with a title or logo on them*: an incremental scan for the
  items it added or read again, a full or deep scan for every item in the scanned folders. An item whose fanart was
  already picked or cleaned is skipped without asking TMDB, unless Extra fanart is ticked. The scan progress shows a
  Clean artwork step and the log a line per item.
- **The scan's player refresh now also drops Kodi's cached pictures** for items whose artwork changed (from this stage
  or from the lookup), so *Update client libraries for items with updated artwork* shows the new pictures in Kodi
  instead of the cached old ones.

## v3.9.6 — 2026-11-14 — Extra fanart repeats are found when the same shot is framed differently

- **Fixed: Clean artwork left repeats in extra fanart.** It compared a fingerprint of the whole picture, which only
  matches the same picture at another size. Fanart sites mostly hold the same shot framed tighter or wider, and those
  looked like different pictures. Pictures are now compared by searching one inside the other at several zoom levels:
  on real TMDB backdrops a reframed copy of one shot scores 0.95 to 0.98 and the closest two different pictures 0.83,
  and repeats count from 0.90. The same comparison now decides which extra fanart has text on it (it matches an online
  picture listed with a language) and which candidates the artwork window marks In use.
- The image now includes numpy, which does the comparison in about 2 ms per pair.

## v3.9.5 — 2026-11-14 — The artwork window shows extra fanart as it is on disk, and every card's size and type

- **Fixed: the Extra fanart section showed none of the files already there** until a picture was added, then suddenly
  all of them. It showed what the last scan had recorded; it now reads `extrafanart/` when the window opens.
- **Candidates already in extra fanart are marked In use**: the picture a file was added from (now recorded when you
  add one), or the same picture at another size (compared by fingerprint). They stay in the list, so a larger copy can
  still be chosen.
- **Every artwork card says its size and type**: the files on disk show their width × height, file type (JPG, PNG) and
  file size, and the online pictures their width × height and file type.

## v3.9.4 — 2026-11-14 — Clean artwork tidies extra fanart

- **Extra fanart in Clean artwork.** Tick it to tidy `extrafanart/` of the picked movies and shows: a picture that is
  there more than once (the same picture at another size, or from TMDB and from Fanart.tv) keeps its largest copy, and
  a picture with a title or logo on it (it matches an online picture listed with a language) is swapped for a clean
  picture that is not there yet, under the same file name, or taken out when no such picture is left. Every file taken
  out goes to the recycle bin, and pictures that match nothing online are left alone. The job line says how many
  repeats went, how many were swapped and how many stayed.

## v3.9.3 — 2026-11-13 — New artwork shows without a reload; In use survives scans; the page says when Curator was updated

- **Clean artwork's new pictures show at once.** The new file keeps the old name (fanart.jpg), so the page kept showing
  the copy it had already loaded until a reload. The job now tells the page which files it wrote, and the page loads
  those again and redraws the list and the open item when the job ends. Its notice says *Clean artwork* instead of
  *File job*.
- **Fixed: In use disappeared after a scan, and the artwork window suggested the same picture again.** A scan rebuilds an
  item's artwork from the files on disk and dropped the note of which online picture each file came from. It now keeps
  that note for every picture whose file is unchanged.
- **An open page says when Curator was updated.** After a rebuild, an open page keeps running its old scripts until it
  is reloaded, which looked like features missing (the Extra fanart candidates, for one) or fixes not working. The page
  now sees the newer build and shows *Curator was updated while this page was open* with **Reload** and **Later**.

## v3.9.2 — 2026-11-13 — Clean artwork: fanart and character art only

- **Replace artwork… is now Clean artwork…, for fanart and character art only**, the two types that should carry no
  title or logo. Fanart is ticked by default; Character art is offered when shows are picked. Posters, landscape,
  logos and the other types are no longer offered (an earlier choice of them is dropped).
- **Character art gets the clean rules of fanart**: the three Replace choices apply to it, the artwork window lists
  and suggests clean character art first, and scraping prefers it (Settings, Movies: *Prefer clean fanart and
  character art*).

## v3.9.1 — 2026-11-13 — Replace artwork: pick the artwork types; the fanart choices only touch fanart

- **Clean fanart is now Replace artwork…, with a box per artwork type.** Fanart is ticked by default; Poster,
  Landscape, Clearlogo, Clearart, Banner, Disc art, Keyart or Character art and Square art can be ticked too, and the
  choice is remembered. Each ticked type gets the picture the artwork window marks Suggested for it, unless the current
  file is already that picture; nothing else on the item is touched.
- **The fanart choices are worded as fanart choices** and show only while Fanart is ticked: only fanart with a title
  or logo on it, that and fanart that matches no picture online, or any fanart that is not the suggested one. "Every
  fanart that is not the suggested picture" read as if it replaced all artwork; it never did.
- The job log line names each type it replaced.

## v3.9.0 — 2026-11-13 — Clean fanart runs the artwork window's own code

- **Clean fanart now builds its list with the artwork window's own function and saves with the download button's own
  function.** Before, the job had its own copy of the selection, which matched the window in every test but not on a
  real library. Now the card marked Suggested in the window is, by construction, the picture the job saves.
- **Its log says what it did and which Curator ran it**: the first line names the version, and each item names the
  picture it saved, or why it left the fanart (for a fanart TMDB lists without a language, it names the suggested
  picture that *Every fanart that is not the suggested picture* would put there).

## v3.8.9 — 2026-11-13 — Clean fanart can put the suggested picture everywhere

- **Replace, in the Clean fanart window**, now has three choices: fanart that matches a picture with text on it (as
  before), that and fanart that matches no picture online, or **every fanart that is not the suggested picture**. The
  last puts the picture marked Suggested in the artwork window on each item whose fanart is not already that picture.
  TMDB lists many backdrops with the title on them as having no language, so the first two take such a picture for clean
  and leave it; Landman's fanart, put there by the job before 3.8.4, is one. The new choice fixes those in one run.

## v3.8.8 — 2026-11-13 — The artwork window shows which picture is in use; Clean fanart names its pick

- **In use** on a picture in the artwork window: the current file was downloaded from it (by Clean fanart or a pick),
  with a dashed outline next to the Suggested one. If they are not the same card, the current file is not the
  suggestion.
- **Clean fanart names the picture it took** in its job log (TMDB or Fanart.tv file name and size), and says it is the
  one the artwork window suggests.
- Checked against Landman's real TMDB list (46 backdrops, 28 of them without a language): the job takes the window's
  suggestion in every order and every vote tried. Clean fanart before 3.8.4 took the clean picture with the highest
  vote instead, which on TMDB is often one with the title on it; rebuild if About shows an older version.

## v3.8.7 — 2026-11-13 — Curator's own folders are no longer offered as a library

- **Fixed: Settings offered `/data` as a library folder.** Curator's own data folder (artwork you uploaded or
  replaced) is a volume, so Settings, General, Library folders listed it under Volumes not in a library and under
  Detected mounts, and the folder picker let you add it. Curator's own `config`, `cache` and `data` folders are now
  left out everywhere a library folder is offered, and saving refuses a new library folder that is one of them, holds
  one, or sits inside one, with a message naming the folder. A library folder saved earlier keeps working and saving.
  The movie set folder picker still lists every volume.

## v3.8.6 — 2026-11-13 — TheAudioDB works again

- **Fixed: TheAudioDB found nothing.** TheAudioDB retired its old free API key (2), which now answers 404 Not found,
  so every lookup came back empty: artist and album artwork from TheAudioDB, biographies and album reviews from it,
  and music video details. Curator now uses the current free key (123). The request pacing is unchanged. Found by the
  setup wizard's TheAudioDB test, which now passes.

## v3.8.5 — 2026-11-13 — Setup wizard

- **New: a setup wizard.** It opens by itself on a new install (nothing configured and nothing scanned yet) and from
  **Settings → About → Run setup wizard** any time. It goes one step at a time, with Back, Skip, Save and continue and
  a progress bar: library folders for music, movies, TV and music videos, each checked at once (exists, readable,
  writable, on a mounted volume); keys for TMDB, TheTVDB, OMDb, Fanart.tv, Last.fm and AcoustID with a Test each, the
  MusicBrainz contact, a Test for MusicBrainz and TheAudioDB, and Trakt sign-in; Radarr, Sonarr, Lidarr and Bazarr with
  Test connection, the webhook address with the key filled in, and path mappings with a test that the mapped folders
  exist; Kodi, Plex, Emby, Jellyfin and Navidrome with Test connection, one box per library, and path mappings with a
  test; and a summary that offers one box per library to start the first scans. Every step saves through the same
  settings the Settings window uses, and secrets are stored the same way.
- The folder picker behind **Settings → General → Library folders → Add path** lists Music videos as a media type too.

## v3.8.4 — 2026-11-13 — Clean fanart takes the picture the artwork window suggests

- **Fixed: Clean fanart could put a fanart with the title on it.** It took the clean picture with the highest TMDB vote,
  and a backdrop with the title or logo on it is often uploaded to TMDB without a language (so it counts as clean) and
  voted up. The artwork window suggests the largest clean picture of the right shape instead, so the two disagreed. The
  job now takes exactly the picture the window marks Suggested. A picture that TMDB lists without a language but that
  has text on it cannot be told apart by Curator; if one is already in place, pick the suggested one in the artwork
  window (Clean fanart sees it as clean and leaves it).

## v3.8.3 — 2026-11-13 — One box per player for artwork updates

- **You choose which players get the new artwork.** Since 3.8.0 a replaced fanart, and a picture chosen in the artwork
  window, went to every player switched on for that library. Now there is one box per player, named after it:
  *Update library in Kodi after fanart download*, *Update library in Jellyfin after fanart download* and so on, in the
  Clean fanart window; *Update library in Kodi after artwork download* in the title bar of the artwork window; and
  *Update library in Kodi* in **Update artwork in players…**, which now opens a window with the boxes and a Start button
  instead of sending at once. Only players switched on for movies or TV under Settings are listed. A player you untick
  stays unticked in that browser until you tick it again. This replaces the single box of 3.8.2.

## v3.8.2 — 2026-11-13 — The Clean fanart window says it updates the players, with a box to turn it off

- **Show the new fanart in Kodi and the other players** in the Clean fanart window, ticked by default. Since 3.8.0 the
  replaced fanart already went to Kodi, Plex, Emby and Jellyfin as an artwork refresh, but the window did not say so.
  Now it does, and unticking the box leaves the players alone (the job log says so); Update artwork in players in the
  Metadata menu sends it later.

## v3.8.1 — 2026-11-13 — Kodi gets one request at a time

- **Every request to a Kodi now waits for the one before it.** Each part of Curator already sent its own Kodi calls one
  after the other, but the library update queue, watched sync, the Kodi report, connection tests and on-screen notices
  run in their own threads and could reach Kodi at the same moment. All Kodi calls now pass one lock per Kodi address,
  so Kodi only ever has one request from Curator to answer. A large job, such as the artwork refresh after Clean fanart,
  takes longer but never floods Kodi. A pause between calls (waiting for a Kodi scan to finish) does not hold the lock.

## v3.8.0 — 2026-11-13 — New artwork shows in Kodi without a rescan; library workers survive a database error

- **Changed artwork reaches Kodi without a rescan or a wipe.** Kodi keeps a cached copy of every picture it has shown, so
  a new `fanart.jpg` under the same name stayed hidden behind the old one (Update library re-reads the item but keeps the
  cache). Now, after Clean fanart and whenever a picture is chosen or uploaded in the artwork window, Curator queues an
  artwork refresh of that movie or show in the Library updates queue: Kodi drops its cached copy of the changed pictures
  and, when the file name changed (another extension), the item is pointed at the new file. Kodi shows the new picture
  the next time the item is on screen. Nothing is rescanned, the .nfo is not read again and the watched state is not
  touched. Plex, Emby and Jellyfin refresh the item. Clean fanart hands its items to the queue 100 at a time.
- **Update artwork in players** in the Metadata menu at the bottom does the same for the movies or shows you pick, with
  all their pictures: for artwork changed before this update, or outside Curator.
- **Fixed: a database error stopped a player's library updates until Curator was restarted.** When a connection dropped
  (Postgres restarting, for example), the worker thread of each player ended. It now logs the error and goes on after
  10 seconds.

## v3.7.9 — 2026-11-13 — Clean fanart: replace fanart that has a title or logo on it

- **Clean fanart…** in the Metadata menu at the bottom (pick movies or shows; select all for the whole library) replaces
  the fanart you already have when it has a title or logo on it. Curator does not record where a scraped fanart came
  from, so each file is matched with the online pictures: by its exact size among the TMDB pictures (no download), or
  else by comparing the picture with small previews. Fanart that matches a picture with text is replaced with the best
  clean one (the clean-fanart order of 3.7.7); fanart that is already clean stays, and an item without fanart gets a
  clean one. Fanart that matches nothing online stays unless *Also replace fanart that matches no picture online* is
  ticked.
- It never touches fanart you picked or uploaded in the artwork window, or a locked item, and keeps an item's fanart when
  no clean picture exists online. A replaced file stays in that item's artwork window, so it can be picked back. It runs
  as a file job in the Jobs panel with a line per item (replaced, already clean, no clean fanart online, left alone),
  and asks TMDB and Fanart.tv at their usual pace. Rescraping with *Overwrite artwork* could not do this, because it only
  replaces a picture with a larger one.

## v3.7.8 — 2026-11-13 — No movie results window on a TV import; fanart choices also offered as extra fanart

- **Fixed: Force scan now on the webhook queue opened the Movie scan results window** with an old movie scan's numbers,
  although only episodes were queued. The page hears about a running scan from two places: the live update for the scan
  that runs (here TV) and its own check for the scan of the open tab (Movies). It compared the two, so "TV running"
  followed by "the last movie scan, finished" looked like a movie scan that had just ended. A scan is now compared only
  with the earlier state of its own library. A scan you start still opens its results when it ends.
- **The artwork window offers every fanart picture as extra fanart.** The extra fanart already on disk showed as rows
  named extrafanart1, extrafanart2 and so on with no candidates, while the Fanart row above had many. There is now one
  **Extra fanart** section for movies, shows and sets: it shows the files in `extrafanart/` and lists every fanart
  candidate (clean ones first). Choosing one, or uploading a file there, adds it as the next `fanartN`; nothing already
  there is replaced. The bin on a file there still deletes just that file.

## v3.7.7 — 2026-11-13 — Lyrics downloads report back, Show call for webhooks, clean fanart first

- **A lyrics download says what it did.** Search and download lyrics only said it had started. When it ends, a notice
  now says how many lyrics were saved, how many tracks LRCLIB has none for, how many albums already had lyrics and
  what failed (or that LRCLIB could not be reached), and the open album is read again so its lyrics marks are current.
  The Jobs panel keeps the line per album.
- **Show call on Recent webhooks.** Each webhook row keeps the call as it arrived (up to 64 KB). **Show call** in the
  Queue window, Recent webhooks, opens the JSON body with a Copy button, so an ignored or unrecognised call can be read.
  Calls received before this update have no body to show.
- **Lidarr DownloadFailure and other calls without an item are recognised.** Lidarr's DownloadFailure and ImportFailure
  carry no artist block, so they were reported as *Unknown … Not a Radarr, Sonarr, Bazarr or Lidarr payload*. They
  now go to the Lidarr activity feed, named after the release. Health, HealthRestored and ApplicationUpdate calls from
  Radarr, Sonarr and Lidarr are named after the app that sent them (by its instance name) instead of Unknown.
- **Prefer clean fanart** (Settings, Movies, under Artwork languages; on by default). With an artwork language order
  set (English by default), fanart followed it like posters, so English fanart with a title or logo on it beat a clean
  one. Fanart without text now comes first, and a picture with text is used only when there is no clean one. Posters,
  landscape, banners and the rest keep the language order, so landscape art keeps its title. The artwork window lists
  and suggests clean fanart first. Existing fanart is not replaced; scrape artwork again (or pick it) to change one.

## v3.7.6 — 2026-11-12 — Music search on the page, a scrape-failed notification, one webhook file job per step

- **Music search filters the loaded list at once.** Typing in the Music search box asked the server for the whole
  filtered library again after each pause and showed a progress overlay. The page already holds every album of the open
  filter, so the search now runs there, with the same rule: an artist whose name matches keeps all its albums, otherwise
  only the albums (and missing releases) whose title matches are shown. On a 28,500-album library it draws in about
  0.13 s and sends no request. Select all, the column filters, the poster grid and Export follow the search, and an album
  page stays open while it is filtered out. Clear filters empties the search without reloading.
- **A scrape that fails, or leaves items unscraped, sends a notification.** New event under Settings, Notifications:
  *A scrape failed, or could not scrape some items*, with the first five titles and their reasons. It is on for new
  targets; tick it on existing ones. A scrape started by a webhook import is reported by *An import ended with a failed
  step* instead, so one import never sends two messages.
- **Webhook file jobs run once per step.** Subtitle clean-up, trailers, theme songs and season trailers after an
  import ran once per item; each step now takes every imported item at once, so the episodes of one show are handled
  together. An item that fails is logged and the rest still run.
- The Music videos API moved out of the recycle-bin routes into its own file. The addresses are unchanged.

## v3.7.5 — 2026-11-12 — Integrity wording everywhere; a stale front-end test

- **The integrity settings use the button names**: *Quick integrity check after a Radarr or Sonarr import* and *Full
  integrity check per day*, and the README and specification call the Music videos buttons *Quick integrity check* and
  *Full integrity check* (renamed in 3.6.7). The specification describes the music video copy rules of 3.6.6.
- **The front-end test for the Music videos filters** still expected any two videos with the same artist and title to
  be Duplicates. It now checks the movie rules (Duplicate for the same release, Upgrade available for the weaker copy).
  The Python suite skips this test when Node is not installed, which is how it went unnoticed.

## v3.7.4 — 2026-11-12 — Kodi's stale entries are removed again, more carefully

- **Fixed: Kodi entries of files that are gone were never removed.** After an upgrade, a rename or a delete, Curator
  asks Kodi which entries point at files that are no longer there (Update library on a movie or show, and the check
  before a folder scan) and removes them. Kodi's answer was read one level too deep, so no entry was ever found and
  nothing was removed; the tests fed it the wrong shape and passed. It now reads the answer as Kodi sends it.
- **Safer while it is switched on for real**: an entry is removed only when the library folder that should hold its file
  is mounted and can be read (a drive that is away looks exactly like files that are gone), and the check before a
  folder scan only touches entries inside that folder, whatever Kodi's filter returns. Entries whose path no Kodi path
  row translates are still left alone.
- Expect a one-off tidy-up in Kodi the next time a movie or show gets a library update: entries of old files that piled
  up are removed then. The activity log says how many.

## v3.7.3 — 2026-11-12 — Saved filters can run an action on a schedule; the Kodi report

- **A saved movie or TV filter can run an action**: *Scrape what is missing*, *Quick integrity check* or *Download
  trailers*, every day or every week on a chosen day, at a chosen hour (the time zone under General). It runs for what
  the filter matches at that hour, as a job in the Jobs panel that waits for a running scan. Set it in the Save filter
  window; the Saved menu shows the schedule and has **Run now**, with the last result in its tooltip. The action reads
  more ribbons than scan tagging does (New, Latest added, Not scraped, Scrape failed, No NFO, No poster, No trailer,
  Ignored, and for movies Upgrade available, Duplicate, Probe failed and Corrupt); the search box and the few ribbons
  that only work on screen are left out, and a filter with nothing the server can judge cannot get an action, so an
  action never falls back to the whole library. Scan tagging keeps its rules.
- **The Kodi report** (Tools, Orphan report, Kodi, **Compare with Kodi**) reads Kodi's movies and episodes, in pages of
  2,000, translates each file through the Kodi path rows and compares it with the library: entries whose file is gone
  (**Clean the Kodi video library**), library files Kodi has no entry for (**Scan in Kodi**, per folder or for all),
  files Kodi has that Curator does not index, Kodi paths no row translates, and library folders no row reaches. Nothing
  changes until a button is pressed, and a library folder that is not mounted is left out so an offline drive shows
  nothing. Music is not included: Kodi lists music by song, which on a large library is slow on Kodi's side.

## v3.7.2 — 2026-11-12 — Undo Fix Match; a music scan failure from v3.6.6 fixed

- **Fixed: music scans and Lidarr imports since v3.6.6 reported every album they wrote as failed** ("unsupported
  operand type(s) for +=: 'int' and 'list'"): new and changed albums in an incremental scan or a Lidarr import, and
  every album in a full or deep scan. The tracks were still written, but the album was listed under Failures and its
  MusicBrainz lookup and missing artwork were skipped in that run. An incremental scan leaves those albums alone because their files did not change, so run a full music scan once after this update to look them up. The batched
  write of unchanged tracks reused the name of the count the album step returns. A test against a real database now
  runs that step.
- **Undo Fix Match.** A movie or show page has **Undo Fix Match** for seven days after a Fix Match. It puts back the
  metadata, ids, seasons and episodes (numbers included), and the artwork and .nfo files Curator keeps next to the item,
  as they were just before the Fix Match. Placeholder episodes and empty seasons the Fix Match added are removed, ones it
  removed come back, and artwork or .nfo files it added go to the recycle bin. Video files, paths and which file an item
  points to are left as they are now. It waits while a scan or scrape runs, and only the last Fix Match of an item can be
  undone. A Fix Match that waited in the queue is covered too: the state is saved when it is applied.

## v3.7.1 — 2026-11-12 — "Added to the library" notification

- **A daily or weekly message listing what was added.** Settings, Notifications has a new event, *Added to the
  library*, and below the targets a schedule for it: never (the default), every day, or every week on a chosen day, at
  a chosen hour (in the time zone set under General). The message lists the movies, the episodes grouped per show
  (*Fargo (2014) S01E01–E04*), the albums and the music videos added since the last one, up to 15 names per kind.
  When nothing was added, nothing is sent. Tick the event on each target that should get it; new targets do not have
  it on.
- **Preview** shows the message as it would go out now, and **Send now** sends it at once to the targets that have the
  event ticked and starts the next window. The time of the last message is kept in `config/digest_state.json`, so a
  restart neither sends it twice nor loses what came in meanwhile.

## v3.7.0 — 2026-11-12 — One compare window layout for every Duplicate pill

- **Albums, movies, episodes, music videos, and show and artist folders compare the same way.** Each window says why
  the rows are copies, shows the copies side by side with a picture, the name, the facts, the Radarr/Sonarr/Lidarr line
  and the path, puts **Delete from disk** in the bin at the top and **Remove from library** at the bottom of each copy,
  and ends with **Not duplicates**. The middle is what fits the media: the songs of each album, the file facts of a
  movie or episode, the folder totals of a show or artist.
- **Albums gain Remove from library** in the compare window, and **Not duplicates** for every pair whose songs line up
  (by title or position as well as AcoustID or fingerprint); same-release pairs had no such button.
- **Show and artist folders gain Remove from library and a reason line** (the shared TheTVDB, TMDB, IMDb or MusicBrainz
  id, or the same name), and use the full window width instead of narrow cards.
- **Music videos have a compare window.** Their Duplicate and Upgrade available pills open it (they used to type the
  title into the filter box), with the suggested copy to keep, Delete and Remove from library.
- **Movie duplicate groups also mark the suggested copy to keep**, as the upgrade window did.
- **The tab names stay on one line** on screens wider than 1,100 px (Movie sets, TV shows and Music videos wrapped out
  of the tab bar).

## v3.6.9 — 2026-11-12 — Bulk album actions run as one job

- **Applying matches, treating as compilations, ReplayGain, Audit audio, Check missing tracks and Find metadata for
  several artists run as one job.** The page sent one request per album, one after another, and waited for all of them
  before it showed anything. Now one job starts at once and shows in the Jobs panel as *Album batch*, with progress, a
  log line per album and a **Stop** button (it stops after the album it is on). An album that fails is logged with the
  reason and the rest go on. When the job ends, the page reads again only the artists it touched, clears the loaded
  matches that were applied, and says how many went through and the first failure. Apply all matches uses the same job.
- **ReplayGain and Audit audio in a batch no longer add one Jobs entry per album**, and a batch audit sends one
  *corrupt file* notification for the whole run.
- One batch runs at a time; starting another while one runs says so instead of queueing it.

## v3.6.8 — 2026-11-12 — The .nfo check on the movie and TV lists stops reading every plot

- **The purple "NFO differs" check reads only rows that changed.** Each load of the Movies or TV list fetched the plot,
  outline, tagline and other .nfo fields of every movie, show, season and episode and fingerprinted them in Python
  (about 0.2 s for 10,000 movies and 0.4 s for 50,000 episodes, plus moving every plot out of the database). The
  database now returns an md5 of those columns instead, and only a row whose md5 changed since the last load is read
  in full and fingerprinted again. Any change to those columns, from a scan, a scrape, an edit or a watched sync, changes
  the md5, so the check stays exact. The first load after a restart still reads everything once.
- **The lists no longer write while loading, except the first time a file is seen** (its baseline) and after the
  .nfo itself was checked; a row that looks changed is still confirmed against its .nfo before it turns purple.

## v3.6.7 — 2026-11-12 — Small fixes from the review: scans, indexes, Follow imports, menus, export, and slow requests in About

- **A full music scan of one folder fills release fields for that folder only.** Label, catalog, barcode, release
  status, country and MusicBrainz ids were filled from the tags of every track in the library; now only albums under the
  scanned folders that still have a blank field are read.
- **New indexes** on the movie TMDB and IMDb ids, the show TheTVDB and TMDB ids (also trimmed, as the copy windows
  compare them), and on `updated_at` of albums and episodes, which the list refreshes during a scan read.
- **Follow imports stops resending an unchanged list.** The open window asks every 3 seconds; when nothing moved the
  answer is one line instead of 100 rows (the running times still count up).
- **Large replies are compressed a little less.** gzip level 6 instead of 9: on a 34 MB music list it took 0.32 s
  instead of 0.60 s, for 3% more bytes.
- **Video menus have Stop ignoring**, like Music, when every picked item is ignored (it sets them back to New).
- **Music right-click menus have Update library and Move…** (artists), and **Update library** (albums: one update per
  artist folder), which were only on the artist and album pages.
- **A filter that matches nothing stays on**, with *Nothing matches these filters* and a **Clear filters** button, in
  Music, the poster grids and Music videos. Music used to switch back to All by itself.
- **The last three browser confirm boxes** (merging a season, discarding unsaved lyrics, purging the data or cache
  folder) use Curator's own confirm window.
- **Integrity buttons have one name everywhere**: *Quick integrity check* and *Full integrity check*.
- **Music video scans send the scan finished and scan failed notifications**, like the other libraries.
- **Music videos have Export** (CSV or XML, the shown list).
- **Creating a movie set** says which movies could not be added instead of leaving them out silently, and the TMDB
  collection id typed in the **+ Set** window is kept (it was sent under a name the server did not read).
- **Follow imports shows what a Lidarr import's scan did**: the scan step lists its stage times (MusicBrainz, Artwork
  and so on), and a scan that failed now shows as failed instead of done.
- **The movie and episode compare windows say why the rows are copies**: the id that tied them (TMDB, IMDb, TheTVDB,
  or title and year), and for a duplicate group what makes it the same release.
- **About lists slow requests**: every request that took two seconds or more since Curator started (newest 50), with
  its time, so a slow window can be named without reading the logs.

## v3.6.6 — 2026-11-12 — Faster TV refreshes, scans and music counts; music videos follow the movie rules; a music Corrupt filter

- **TV list refreshes during a scan check only the shows that changed.** Each refresh read every season and episode
  .nfo in the library, and every show to look for twin folders. It now reads those of the changed shows only.
- **The music scanner writes a track in one statement.** A changed track was a lookup and then an update or insert; an
  unchanged track was one update each. A changed track is now one insert-or-update, and the unchanged tracks of an
  album one statement together.
- **The music list no longer reads every album review**, only whether one is there (for Missing album review). The
  filter counts are one pass over albums and one over artists instead of about twenty, and the Incomplete tags filter
  asks once for the whole list instead of once per album.
- **Music videos follow the movie rules for copies.** Duplicate now means the same release (same source, resolution and
  about the same size); a weaker copy shows **Upgrade available**. Before, any two videos with the same artist and title
  were Duplicates.
- **Deleting a music video uses the movie guards and window.** The Music videos folder must be mounted and writable, as
  for a movie, and the window offers **Remove from library** as well as Delete from disk. Restoring a music video from the
  recycle bin brings back its .nfo, media info file and pictures with it.
- **Music has a Corrupt pill and filter.** Audit audio already tested FLAC files; it now also decodes other formats with
  ffmpeg. An album with a track that does not decode cleanly shows **Corrupt**, the filter menu has *Corrupt files*, a
  newly found corrupt file is recorded in Activity history and sends the *corrupt file* notification, and a track whose
  file is replaced loses its old audit result.
- **One wording for every menu.** Music right-click items read like the video ones (*Find metadata (3)*, *Write .nfo*,
  *Mark as processed*, *Remove or delete…*), with the count only when more than one is picked. The tabs read
  *Movie sets*, *TV shows* and *Music videos*, Alt+5 opens Music videos, and the Tools menu no longer repeats the Music
  videos tab and the Library analytics button.

## v3.6.5 — 2026-11-11 — Copy windows open without Radarr or Sonarr; Lidarr deletes reach the library; music edits refresh only what changed

- **The movie and episode Upgrade and Duplicate windows open at once.** They read every movie, or every episode in
  the library, to find the copies of one item, and then waited for Radarr or Sonarr to say which copy it has. They now
  read only the item's possible copies (same TMDB, IMDb or TheTVDB id, season and episode), and the Radarr and Sonarr
  lines are filled in a moment after the window opens (`GET /api/v1/copies/{kind}/{id}/arr`,
  `GET /api/v1/video-duplicates/arr`), the way the album windows load Lidarr since 3.6.4. A Duplicate pill reads only
  that item's group, and the Duplicates window only the open library. Replacing a copy no longer asks Radarr or Sonarr
  first.
- **Lidarr deletes reach the library.** AlbumDelete, ArtistDelete and TrackFileDelete were taken as imports: an album
  or artist delete was dropped ("did not include any imported file paths"), and a deleted folder showed as a failed
  import. They are now removals. The album is found under the artist folder Lidarr names (by MusicBrainz release group,
  else title). When its folder is gone, the album (or, for an artist, every album under that folder) leaves the library
  and the players are asked to clean; Activity history says "Removed in Lidarr". Nothing leaves the library when the
  music folder around it cannot be read, so a mount that is away never empties it. When the folder is still there
  (Lidarr kept the files, or one track file went) the album is read again; an artist whose files Lidarr kept stays.
- **Music edits refresh only the artists they touched.** Applying a match, treating albums as compilations, album jobs,
  finding artist metadata, writing an .nfo, an upgrade, an artist merge and adding an artist reloaded all 29,000 albums
  afterwards. They now read again just those artists, and artist folders with the same name, whose Duplicate and Upgrade
  marks can follow (`POST /api/library/refresh`), under the open filter and search.
- **Deleting music from disk cleans the players and leaves busy albums alone.** Like a movie or episode delete, it now
  asks Kodi and the other players to clean the artist folders, and it skips an album a batch or lookup job is writing
  ("A running job is using this item").

## v3.6.4 — 2026-11-11 — The Duplicate window and deleting a copy no longer wait for Lidarr

- **The Duplicate pill opens its window at once.** The window waited for Lidarr to say which copy it uses, and for a
  copy without a MusicBrainz release group that meant reading Lidarr's whole artist list. The pairs now come from the
  database alone and the Lidarr lines are filled in a moment later. The lookup of albums that share a recording or a
  fingerprint read every track in the library; it now uses two new indexes (about 0.04 s for one album on a library of
  340,000 tracks).
- **Deleting a duplicate copy is quick.** Telling Lidarr to read the artist folder again now runs in the background
  instead of holding up the delete, and the window that reloads after it opens at once too.
- **Import logs time the catalogue notes on their own.** Release countries, duplicates, upgrade copies and original
  years were counted inside "Artwork took …"; they now have their own "Countries, duplicates and upgrades took …" line.
- **The music Scan icon is redrawn**: two beamed notes with the magnifier in the same place as the movie and TV icons.
  The second note's stem stopped short of its head.

## v3.6.3 — 2026-11-11 — Special releases: one setting for duplicates, one for upgrades

- **Special releases have a setting per relation.** A special release is a Deluxe, Expanded, Anniversary, Special,
  Limited, Collector's, Extended or box set edition, an album with bonus tracks, or a copy with a different number of
  tracks. Settings, Music, Duplicates and upgrades now has *Count special releases as duplicates* and *Count a
  better-sounding special release as an upgrade*, both off by default, so a Deluxe edition can be offered as an
  upgrade without being marked a duplicate (or the other way round). They replace the two v3.6.2 settings. Remix
  albums never count as either.

## v3.6.2 — 2026-11-11 — Remix albums and special editions are not copies; the Duplicate and Upgrade pills open fast

- **A remix album is never a duplicate or an upgrade of the studio album.** Edition notes such as "(Remixes)" were
  dropped when titles were compared, so "Californication (Remixes)" counted as a better copy of "Californication". A
  remix album (MusicBrainz release type Remix, or Remix, Remixes, Remixed or a "(… Mixes)" note) is now its own kind,
  next to album, single, EP, live and compilation.
- **Two settings under Settings, Music, Duplicates and upgrades**: *Keep special editions apart* (on by default:
  Deluxe, Expanded, Anniversary, bonus tracks, Special, Limited, Collector's, Extended, box sets) and *Keep copies with
  a different number of tracks apart* (off by default). They apply to the pills, the comparison windows and the bulk
  duplicate cleanup, and changing one records the marks again at once.
- **The upgrade window and an album's Duplicate pill read only that album and its possible copies** (an artist of the
  same name, the same MusicBrainz release, or a shared recording or fingerprint), not the whole library. On a test
  library of 29,000 albums the upgrade window took 0.02 s instead of loading every album first (0.3 s here), and the
  Duplicate window 0.11 s instead of 0.77 s; a slower database gains more. A Duplicate pill whose mark no longer
  holds is still cleared instead of opening an empty window.

## v3.6.1 — 2026-11-11 — Music scan log times each stage; recording duplicates for a few albums no longer reads the library

- **The music scan log says how long each stage took**, where it ends, named like the stages on the progress bar:
  "Directory walk took 0.7s", "MusicBrainz took 14.3s", "Artwork took 2.6s" … A stage under a tenth of a second is
  left out. The "Time per step" line at the end still splits the stages into their parts.
- **"Countries, duplicates and upgrades" read the whole library for a scan of two albums** (20 s on a real library):
  it loaded every album and the tags of every track to compare copies. It now loads only the albums that can be
  copies of the scanned ones (same artist name or same MusicBrainz release), with the same marks as before: 0.65 s →
  0.02 s for one album on a test library of 29,000 albums. A mark left behind elsewhere is still cleared by the
  catalogue maintenance at start.
- **A scan of several albums by one artist does the artist-level work once** (website, artist artwork, the name from
  tags), after that artist's last album; it ran once per album. "Time per step" shows it as "Artist folder".

## v3.6.0 — 2026-11-11 — Follow imports: the line fills in order

- **The line between steps turned green out of order**: the line into a step was green as soon as that step was waiting
  or running, so the library update (waiting from the moment an import is picked up) showed a green line while the
  scrape and the file jobs before it had not run. The line into a step is now green only once the step before it is
  finished, so it fills from left to right.

## v3.5.9 — 2026-11-11 — Follow imports names every episode of a season import

- **A season imported as many webhooks showed only its first episode** ("Cheers (1982) S01E01 · 23 webhooks"). It now
  shows the episodes the webhooks named, as ranges: "Cheers (1982) S01E01–E23 (23 episodes)". A gap stays visible
  ("S01E01–E03, E05, S02E01 (5 episodes)"). This is the same list of episodes the queue already kept for the folder.

## v3.5.8 — 2026-11-11 — Faster library lists and imports: work only on what changed

A pass over the code for work done on the whole library when only a few items changed, slow fixed waits, and one
database query per item where one per batch does. Measured on a test library of 6,500 movies, 30,000 episodes and
29,000 albums with 342,000 tracks. No request limit of an outside service was touched.

- **The library lists open faster**: music 2.9 s → 1.2 s, movies 1.4 s → 0.6 s, TV 2.0 s → 0.5 s, with the same
  content (compared reply by reply). FastAPI passed every value of these large, already cleaned lists through its
  generic converter (1.6 s for the music list alone); they now go straight to JSON. The TV list counted each show's
  episodes, new, missing, duplicate, upgrade and multi-episode files in seven separate passes; it now does one
  (checked equal on 1,000 shows).
- **An import with the player refresh on snapshots only the imported movies or shows**, not the whole library folder
  (0.7 s per TV import on 30,000 episodes before).
- **A scan refreshes only its own side's playlists**: a movie or TV import no longer rewrites the music playlists, and
  a music scan no longer rewrites the movie and TV ones.
- **Reading an album asks the database once for its stored tracks**, not once per track.
- **An import whose scrape has to wait for another scrape starts within a second** of it ending (it checked every 5 s).
- Checked and left as they are: recomputing duplicate and upgrade marks for the whole library takes 0.1 s for 6,500
  movies and 0.4 s for 30,000 episodes; the other fixed waits are background loops that wake as soon as there is work.

## v3.5.7 — 2026-11-11 — A scan of chosen albums: faster start, only their artists sent to the players

- **A scan of a few albums asked Kodi (and the other players) to scan the whole music library**: it named no folder.
  It now names the artist folders of the scanned albums, so Kodi scans only those.
- **The start of such a scan did work for the whole library.** To find the one album it listed every album folder of the
  artist and looked inside each for audio, a directory listing per album over a network share; it now goes straight to
  the album (a disc folder still resolves to its box set). With the player refresh on, it also took a snapshot of every
  album and track in the library before and after the scan; it now reads only the chosen albums and their artists.
  On a test library of 29,000 albums and 342,000 tracks the snapshot went from 1.5 s each way to under 0.1 s.
- **A scan of chosen albums ends with "Time per step"** like movie and TV scans: reading the albums, MusicBrainz and
  AcoustID, missing metadata and artwork, .nfo files, the player refresh and the rest, slowest first.

## v3.5.6 — 2026-11-11 — Scan times an hour off; the walk of one album counts its tracks

- **"This stage" could be an hour too long**, with an "About 1:37:08 left" to match: the stage start was written as the
  container's local time without its time zone, and a browser in another zone read it an hour wrong. Job start and end
  times (scans, scrapes, file jobs, splits, watched sync, Trakt sync, ARR checks and the orphan report) now carry their
  offset, so the page reads the right moment.
- **A scan of chosen albums counts tracks, not albums**: "Reading Classic Album Collection: 34 of 102 tracks". A scan of
  one box set sat at 0% until the whole set was read.

## v3.5.5 — 2026-11-11 — Time per step in every movie and TV scan; imports stop losing up to a minute

A one-movie import took 54 s to scan on a real library. On a test library of 5,000 movies and 30,000 episodes a
one-movie or one-show import scans in about a second, also with the player refresh on (its snapshot of every item
costs about 0.7 s for TV), so the time goes elsewhere. To show where:

- **Every movie and TV scan ends with "Time per step"**, slowest first: reading the files, probing (split into ffprobe,
  MediaInfo and dovi_tool for Dolby Vision files), saving file details, artwork notes, trailers and themes on disk,
  saved filter tags, playlists, .nfo files, duplicate and upgrade marks and the player refresh. Follow imports adds it
  to the scan step's detail, so pointing at a slow scan says which part took the time.
- **An import that had to wait for another scan looked again only once a minute**, so it could lose up to 59 seconds
  after the other scan had ended. It looks every 5 seconds now, Follow imports shows the scan step as waiting with the
  reason, and the finished step says how long it waited.

## v3.5.4 — 2026-11-11 — Follow imports shows how long an import took

- **Each import shows its time under its status**: "5m 8s in all · 1m 17s without waiting". The first is from the
  webhook to the end of the last step (up to now while it is on its way), the second leaves out the quiet period it
  waited for more webhooks. Pointing at it says how much of it was waiting.

## v3.5.3 — 2026-11-11 — A window opened from another one opens in front

- **Follow imports opened behind the Queue window** when started from its button, so it only showed once the Queue
  window was closed. Windows sat at one level and overlapped in page order. Now any window that opens while another is
  open comes in front of it, and Escape closes it first. This also covers any other window opened from a window.

## v3.5.2 — 2026-11-11 — The album upgrade window compares the tracks too

- **The upgrade window lists every copy's songs side by side**, under the release rows, like the duplicate window does.
  Songs are lined up on the open album by AcoustID recording, then fingerprint, then disc, number and title, then title,
  then position, so a differently numbered copy still lines up. A song one copy lacks gets an empty cell, and a
  differing title or a missing song is marked like any other difference. Each song shows its format, bit depth, sample
  rate and bitrate.

## v3.5.1 — 2026-11-11 — Upgrade and Duplicate pills: clickable in the music tree, red while busy

- **Upgrade available and Duplicate in the music tree** are buttons now. Clicking one turns it busy at once ("Looking up
  upgrades…") and opens the window, like the button on the album page; before, it was a label that gave no sign it was
  working while the album and its copies were looked up, and an error went unreported.
- **A busy pill is red with a red outline and glow.** The Upgrade pill's green pulse kept a green outline and glow on it,
  and the Duplicate pill's own colours hid the busy state completely on movies and TV, so those never looked busy.
  This covers every Upgrade and Duplicate pill (music, movies, episodes, show folders).

## v3.5.0 — 2026-11-11 — Follow imports: an item is not Done before its player update

- **Imports showed Done while their last step had not started.** When several items were imported together, each one
  counted as finished as soon as its own scan was done, but the players' library update is queued only after every
  item of the run is scanned. An item now keeps a waiting library step from the moment it is picked up, and the
  player's own step (Kodi, Plex ...) takes its place when the update is queued, so it turns green when that player is
  done.
- **A finished import says why a step was skipped**, for example "Library update: No player library update is turned on
  for music", so a grey dot is explained.

## v3.4.9 — 2026-11-11 — Faster imports: no long Kodi waits, albums side by side, metadata three at a time

I timed every scan type (all items, 10 and 1) and every webhook from the queue to the player, on a test library of 40
movies, 12 shows and 30 albums with a stand-in Kodi whose folder scans take a second.

- **Kodi library updates no longer wait 5 to 185 seconds per folder.** Curator looked at Kodi every 5 seconds after
  sending a folder scan. A one-folder scan often ends sooner, so Curator never saw it, waited the full 90 seconds,
  sent the same scan again and waited again. It now looks every half second for the first 10 seconds, takes a Kodi
  that answered "not scanning" all that time as done, and checks for the end every 2 seconds. Measured: 10 movies from
  forcing the queue to Kodi done went from 121 s to 25 s, 1 movie from 53 s to 5 s. The 90-second wait and the second
  try stay for a Kodi that does not answer at all.
- **Lidarr imports of different artists run side by side** (three at a time); one artist's albums stay in order. Each
  site keeps its own request limit across threads, so no site is asked faster than before. 10 albums: about 60 to 85 s
  instead of about 140 s; the online sites vary from run to run.
- **The missing-metadata step of a music scan does three artists or albums at a time**, for the same reason. A full scan
  of 30 new albums went from 454 s to 387 s; what is left is mostly the MusicBrainz step, which MusicBrainz's own rule
  holds to one request a second.
- The import notices the end of its scrape within half a second instead of 2 seconds.
- Measured and fine as they are: movie and TV scans (the whole test library in 4 to 8 s, 1 or 10 folders in under
  4 s, an unchanged library in about 2 s), an unchanged music library (2 s), and one album (6 s).
- Not changed: an import waits for the quiet period (`CMM_DEBOUNCE_MINUTES`, 20 minutes by default) before it starts, so
  more webhooks for the same folder join one run. That wait is the largest part of an import's time; Force scan now in
  the Queue window skips it.

## v3.4.8 — 2026-11-11 — Movie clean-up on Update library, failed-import alerts, more sources in Follow imports, browser smoke test

- **Update library on a movie** now also removes Kodi's entries for that movie whose file is gone (an old copy left by an
  upgrade into a renamed folder, a stacked copy whose parts are all gone), like a show already did. Another copy whose
  file is there stays, and nothing is removed when the movie folder is not there.
- **A failed import sends a notification**: the new event "An import ended with a failed step" goes once per import to
  the targets that have it ticked, with each failed step and its reason. New targets have it on.
- **Follow imports covers every way to a player**: items restored from the recycle bin, and library updates and Kodi
  cleans started in Curator (Update library, the Queue window's manual update and clean). Bazarr events already went
  through the webhook queue and show there; a test now says so.
- **One test library with every kind of copy** (movies, an upgrade, a show in two folders, twin artists, album copies,
  a box set with a leftover disc entry, music video copies) checks every duplicate detector and the bulk cleanup plan
  together on a real database.
- **The smoke test opens the app in a headless browser** (Playwright in Docker) and goes through every library tab,
  Tools window and Settings tab, failing on a JavaScript error, a server error or an error notice. `SKIP_BROWSER=1`
  leaves it out; the first run pulls the Playwright image (about 2 GB).
- The 9-second pause I reported in the bulk cleanup was the gap between two of my own test commands, not the app.

## v3.4.7 — 2026-11-11 — Follow imports: each webhook item's path, step by step

- **Follow imports** (Tools menu, and a button in the Queue window) shows each item Radarr, Sonarr or Lidarr sends as a
  row of steps: webhook, waiting, scan, scrape, file jobs, then each player's library update. Every step shows its
  status and time, and pointing at it shows the detail; the step that failed or is running is written out under the
  row. A webhook that could not be placed in the library (no path mapping) ends at its first step with the reason. The
  window refreshes itself every 3 seconds. Each item is recorded in a new table, `ingest_journeys` (newest 300 kept).
- **An import no longer pops up the scan results window** and its own start and finish notices over what you are
  doing. A failed import scan still shows its error, and the run still ends with one "Webhook queue finished" notice
  (the second, near-identical "Curator Run received" notice is gone; it still shows when the run fails).

## v3.4.6 — 2026-11-11 — Fixes from a debugging pass: missed release files, false errors in Settings, version label

I ran every test layer (Python on Windows and on Linux in the image, JavaScript, Postgres, the smoke test), pyflakes over
the source, and then used the built image with generated media in a browser: every library tab, every Tools window,
every Settings tab, the item pages, the duplicate windows, a damage check and a real bulk cleanup.

- **A movie or episode whose release group is OTHER, SCENE, SHORT, EXTRA or INTERVIEW was never scanned.** The file name
  ended in `-OTHER`, which the extras rule reads as a Plex extra (`-other`), so the file was skipped as a bonus video. A
  name that carries a resolution, source or codec (1080p, BluRay, WEB-DL, x264 ...) is now always the release itself.
- **Opening Settings showed three red errors** ("Radarr is not set up", the same for Sonarr and Lidarr) when those apps
  are not configured: Settings asked each of them for its profiles. Only an app with an address and a key is asked now.
- **The header could show v1 instead of the version** right after a restart, until a background job had hashed every
  static file. The version is read at start now.
- **About showed "dev" as the version**: it read a page element that no longer exists. It shows the server's version.

## v3.4.5 — 2026-11-11 — Box set disc folders stay one album; a deep scan of chosen albums writes only their .nfo

- A scan of one folder (a Lidarr import or retag, or a selected album) took the folder it was given as the album and its
  parent as the artist. For a disc folder of a box set (`Artist/Box Set/CD 03 - ...`) that made each disc an album of its
  own, under the box set folder as its "artist", next to the box set album a full scan had already made. The albums then
  showed as duplicates of each other. Those scans now resolve a disc or wrapper folder to its album folder the same way a
  full scan does, so the box set stays one album with all its discs.
- Disc albums made before this fix are dropped by the next full music scan, which removes albums it did not see.
- **A deep scan of chosen albums rewrote the .nfo of every album in the library** when Rewrite .nfo was on: the
  selected-albums scan handed no album list to the .nfo step in deep mode. It now hands over the chosen albums, so only
  their files are written. A deep scan of the whole library still rewrites everything.
- **Every stage of a scan of chosen albums now stays on those albums**, in every scan mode. The sidecar count and the
  discography refresh used to cover the whole artist folder; the Lidarr import scan recorded release countries and
  duplicate and upgrade marks for the whole library. A scan of chosen albums now also records those marks for its
  albums, so a stale Duplicate pill clears without a full scan.
- **Old disc albums go when their box set is scanned.** Album entries inside a scanned album folder that no longer hold
  a track (the leftovers of a disc folder scanned on its own) are removed, with an artist entry left without albums.
  Rows only, never a file, and never inside an artist folder of loose tracks.

## v3.4.4 — 2026-11-10 — Local disc art, missing disc art, season new-episode pill, lyrics-only download

- **A disc image that is already in the album folder now counts.** The D pill looked only at images marked selected, so a
  local `discart.png` (or `back.jpg`, `spine.jpg` and so on) that was found by a scan but never selected showed as
  missing. The album now also counts any such file in its folder.
- **Download missing artwork saves images again when the image marked selected has lost its file.** A selected row
  whose file had been deleted or moved blocked the download for that type, so the disc art found by a manual search
  was never saved. The missing image is now fetched and selected again.
- **A season shows "N new episodes"** like the show does, for each season that has episodes marked NEW. Missing
  episodes are not counted.
- **Search and download only lyrics.** Right-click one or more albums or artists and choose "Search and download lyrics
  for selected albums" (or artists). It queues a lyrics-only job as a background job that you can follow in Jobs. Tracks that
  already have lyrics are skipped, and nothing else (tags, artwork, .nfo) is touched.

## v3.4.3 — 2026-11-09 — Folders and files are created group-writable

- **The container now runs with umask 002**, so folders Curator creates are 775 and files are 664 (owner and group can
  write, everyone can read, so Kodi still reads them). Before, folders came out as 755 and most files as 644, and
  only `.nfo` and artwork written through the shared writer got 664. `UMASK` defaults to 0002 in the image, in both compose files and in `.env.example`; change it there
  to use another value. Existing folders and files keep their permissions. A `UMASK` that is not a valid umask now falls
  back to 0002 with a message in the log, instead of stopping the container.
- The IMDb status test expected the old `Curator/` user agent and now expects the Mozilla default.

## v3.4.2 — 2026-11-07 — Update library on a show removes that show's stale Kodi episodes

- **About** shows the real release date, read from the new `app/RELEASE_DATE` file (it was fixed text from v2.4.0).
- **About** rows now have space between the label and the value (Version, Release date, Libraries, NFO dialects).
- **IMDb data user agent** defaults to a common Mozilla browser name instead of naming Curator. Anything typed in Settings is still sent instead.

- **Update library…** on a TV show only scanned. A Kodi scan never removes the entry of an episode whose file is gone, and
  the clean-up Curator ran before the scan covered just the folder it scanned. It now also asks Kodi about that show (found
  by a shared id, else title and year, so a renamed folder still matches) and removes the entries of its episodes whose
  file is gone from disk, plus the show when none is left. Other shows and the rest of the library are not touched, and
  nothing is removed when the show folder is not there (an offline mount).
- The dialog said "Queued" even when nothing was queued (a library with that media type switched off). It now says so.
- Movies are not covered yet.

## v3.4.1 — 2026-11-07 — Kodi video clean after every change that leaves an old entry

Old items stayed in Kodi after newer ones were scanned, because only some changes asked Kodi to clean its library.

- **Renames** from Radarr and Sonarr now ask for a clean (before, only imports that replaced a file and deletes did).
- **Curator's own changes** now ask for one too: deleting items from disk, replacing the original after a Profile 8
  remux, deleting a split source, moving a folder, and a scan that removed missing files. It is a clean with no scan,
  one waiting job however many requests arrive, and nothing happens when the Kodi clean setting is off.
- **A clean Kodi refuses** is tried once more and then recorded as failed. Before, the history said it finished.
- Removing an item from the library keeps its files, so Kodi still has them and it asks for no clean.
- Not changed: music has no clean after a webhook (Curator removes stale songs per folder), because an audio clean
  drops albums with missing files. Not verified against a real Kodi.

## v3.4.0 — 2026-11-02 — Tools menu, music video tab, unwatching, music play counts, duplicate artists, CI

- **Tools menu** in the header for the maintenance windows; the analytics window no longer carries those buttons.
- **Wishlist searches** report which items were searched in batches instead of silently stopping at the first 100.
- **Music videos are a library tab** with filters, a Duplicate pill, integrity checks (Check, Full check), bulk duplicate
  cleanup and the recycle bin. The old window and its header button are gone (the tab and the Tools menu open it).
- **Watched sync**: optional unwatching (remembers the last synced state per player), several Jellyfin/Emby users, and
  music play counts for Kodi, Jellyfin, Emby and Plex. Settings `watch_sync_unwatch`, `watch_sync_music`.
- **History** now records music renames, remux, split, removal from the library and watched-sync changes.
- **Duplicate artists**: same MusicBrainz id or same name; the Duplicate pill opens a compare window with Merge and
  Not duplicates (new table `dismissed_artist_twins`).
- **CI**: GitHub Actions run the Python, SQL and JavaScript tests.
- A browser smoke test of the built image found that the artist Duplicate pill opened the artist instead of the compare window (the
  row's click handler took it first). Fixed.
- **Lidarr label on duplicate albums**: copies without a MusicBrainz release group got no Lidarr id or "Not in" at all.
  They are now found through Lidarr's artist folder and track files.
- The Music videos tab reloads its list each time it is shown (a scan run elsewhere left it stale), and the library
  scan route refuses `musicvideos` instead of failing on a column length.
- Plex now un-marks watched items when Spread unwatching is on. The artist compare window shows small sizes in KB.
  `scripts/smoke-test.sh` runs the image against generated media and checks the API.
- Not verified against live Jellyfin, Emby, Plex or Lidarr apps.

## v3.3.3 — 2026-11-02 — Fixes from a smoke test of the built image

I built the image, ran it against a throwaway Postgres with generated media, and used the new windows in a browser.
That found bugs the mocked-database tests could not, and they are fixed here. Every one has a test on a real Postgres.

- **Full TV scans failed.** `LIKE 'missing://%'` sat inside a query that takes parameters, so Postgres read the `%` as a
  placeholder. This was in code from the v3.0 incremental-scan work (`ids_with_gaps` and the No NFO check). A new test
  scans all source files for a lone `%` in a `LIKE`.
- **Music video scans failed.** The write guard did not know the music video folders, and a movie or TV scan deleted
  their file rows (so they also lost their quality badges after every scan). Those cleanups now keep a music video's
  file, and a scan that is cleaned up between saving and linking a file saves it again.
- **Deleting an album with no MusicBrainz id crashed** after its files had moved (`refresh_album_peers` compared a
  uuid column with `''`). It affected every unmatched album.
- **A bulk cleanup stops being fragile**: one unexpected error on one copy no longer aborts the rest of the run.
- **Movies were matched by their folder, not their file.** `movies.path` is the movie's folder; the file is
  `video_files.path`. The Kodi smart playlist listed folder names, watched sync and collections never matched a movie,
  the Radarr part of the orphan report could not find owners, the Kodi and Plex item refresh fell back to scanning the
  folder, the integrity check after an import found no file, and the cleanup checked that the copy to keep still had
  its folder, not its file. All use the video file now (`store.movie_file_paths`).
- **The disk dashboard could not record music video folders** (`kind` held 10 characters, "musicvideos" is 11).
- **Delete windows showed a "Remove from library" button** that did nothing, in the orphan report, the disk dashboard,
  the twin shows window and music videos. The recycle bin warning now shows without it.
- **An integrity check updates the list on the spot**: the Corrupt pill and the filter count no longer wait for a reload.
- **A music video delete also takes its media info sidecar**, and a picture on a video under 30 seconds says why it
  cannot be made. The orphan report's summary line follows what is left after a delete.

## v3.3.2 — 2026-11-02 — Fixes from a review of the new features

- **Music videos now use the recycle bin.** Their folders were not known to the bin, so Delete removed a music video
  and its .nfo at once. They go to the bin like everything else.
- **The orphan report never offers Delete on a title's only copy.** "The app does not use this file" is not "nobody needs
  it": a movie Radarr has not imported, or an episode Sonarr has not matched, may be the only copy. Those rows now say
  "Only copy in the library" and offer Rescan in the app instead. The server enforces it too: only a row that is in
  the report can be deleted, and the app and id come from the report, not from the request.
- **Bulk duplicate cleanup takes a database snapshot** first when Settings asks for one before bulk changes. Each delete
  was one item, which never reached the setting's minimum, so no snapshot was ever taken.
- **The cleanup window no longer re-downloads its whole preview** every 1.5 seconds while it deletes.
- **A manual integrity check skips disc images** (ISO and similar) instead of calling them corrupt.
- **A show or season with corrupt episodes shows the Corrupt pill** (with the count), not only the Corrupt filter.
- **The webhook queue status reads the running scan outside the queue's lock**, so the two cannot wait on each other.

## v3.3.1 — 2026-11-01 — Fixes from the first run against a real Postgres

- **Fixed an import cycle** from the v3.3.0 file split: `scan_stages.py` or `store_edits.py` imported before
  `scanner.py` or `store.py` failed. The app imports the old modules first, so it was not hit, but a tool or test that
  imported the new module first was. Either order works now, and `tests/test_module_split.py` guards it.
- **`scripts/test-postgres.sh` works on Windows** (Git Bash rewrote the container's paths and the wait loop never
  ended), stops after 60 seconds if Postgres does not start, and prints its log.
- **`tests/test_postgres_sql.py` covers more**: the whole schema applied twice, scoped music updates, show twins, the
  wishlist, the integrity import and scheduled pass, music videos, watched sync, collections, the restored-item queue,
  every new route, and a bulk cleanup run on real rows and files (delete, recycle bin, history, Restore). All 10 pass on
  Postgres 16.

## v3.3.0 — 2026-11-01 — Bulk duplicate cleanup, activity history, upgrade wishlist, stray files, and the gaps from v3.2

- **Bulk duplicate cleanup** has its own red button (Library analytics and the Duplicates window) and its own window: a
  warning, a Preview that lists what is kept, deleted and left alone with the space saved, a tick per title, and a
  separate red confirm button that stays off until there is a preview. With the recycle bin off, the warning says the
  files cannot come back and an "I understand" box must be ticked too. It keeps the best copy, and among equal copies
  the one Radarr, Sonarr or Lidarr uses. It leaves a copy alone when the copy to keep is missing, empty or corrupt, or
  when the copy is another edition, locked, marked Not duplicates, the same file through another mount, a file two
  episodes share, or an album with tracks the kept album lacks. Weaker copies only go when that box is ticked.
- **Activity history** (Library analytics): a searchable list of what was deleted, restored, emptied, renamed, moved or
  changed and found corrupt, and why. A delete from a job is listed with that job as its reason.
- **Upgrade wishlist** (Library analytics, targets under Settings, Files): movies, shows and albums under the wanted
  resolution, HDR or audio quality, with Search per item and for everything shown (up to 100).
- **Integrity**: optional quick check after each Radarr or Sonarr import, with a notification and an optional new search
  when a file is corrupt, and an optional daily full check of the files checked longest ago.
- **Low disk alert** (Settings, General): a notification under a set free space, once a day per folder, and optionally
  deleting the oldest recycle bin items on that drive first.
- **Orphan report**: now walks the library folders for stray files nothing lists, and covers Lidarr (unmapped files,
  album copies with none of Lidarr's files, track files that are gone).
- **Test buttons**: Test players (Settings, Sync) and Test connections (Orphan report) read each app the way the real
  job does and say what came back. Nothing is written.
- **Recycle bin**: Restore now scans the item back into the library by itself. The disk dashboard shows the bin's size.
- **Twin shows**: the Duplicate pill opens a window comparing the folders, with Delete and Not duplicates (and Undo).
- **Disk dashboard**: albums can be deleted from it, and music video folders are included.
- **Webhook queue**: the status also shows how far the running scan or scrape is ("this stage 4 of 30 read").
- **Kodi playlists**: the saved search box now narrows a playlist by title, and saved music filters can be playlists
  (albums, in playlists/music). Presets that depend on the page, such as Gold match, make no playlist.
- **Music videos**: an editor per item (typed values, lock, plot), a picture taken from the video, Delete with the
  .nfo and pictures, Look up blanks from TheAudioDB, watched sync with Kodi, Jellyfin and Emby, and removing a folder
  now clears its rows on the next scan.
- **Code and tests**: the scan stages moved to `video/scan_stages.py`, the stored item edits to `video/store_edits.py` and
  the video duplicate windows to `js/video/duplicates.js` (every old name still works). New `tests/js/logic.test.js` runs
  front end logic, and `scripts/test-postgres.sh` runs Curator's SQL against a throwaway Postgres.

## v3.2.2 — 2026-11-01 — Duplicate albums say which copy Lidarr uses

- **Same release pairs in the duplicate album window now show Lidarr**, as the AcoustID and fingerprint pairs already
  did: "Id N · in use" on the copy holding Lidarr's files, and Not in on a copy that does not. The upgrade window gets
  the same "in use" wording.
- **A pair where Lidarr uses neither copy** now says Not in on both, because Lidarr can use a third copy. A copy with
  no release group id is checked through the other copy of the pair. When Lidarr's files are not on disk the copies
  stay unmarked, since the path mappings are the likely cause.
- The check reads the albums Lidarr holds instead of searching MusicBrainz, so it stays quick with many pairs.

## v3.2.1 — 2026-10-31 — Format badges on artist rows

- **The Format cell of an artist row shows the colored badges** its albums use (green for lossless such as FLAC, grey
  for lossy such as MP3), one per format, instead of plain text like FLAC/MP3. Clicking one filters the Format column
  on it, as on an album row.

## v3.2.0 — 2026-10-31 — Player watched sync, integrity check, orphan report, playlists, collections, disk space, music videos

- **Duplicate album window compares track by track.** Tracks without an AcoustID or fingerprint match now sit side by
  side by disc and track number, then by title, in the left album's order. Before, the left album's tracks were
  listed first and the right album's under them.
- **Player watched sync** (Settings, Sync): play counts, last-played times and resume points between the library and
  Kodi, Jellyfin, Emby and Plex, matched by file path. The higher count and the later time win; a resume point one
  side lacks is copied over. Both ways, pull or push, now or every N hours. Movies gained resume columns.
  **Put the watched state back after Curator refreshes an item in Kodi** (on by default) re-finds each refreshed item
  and restores its play count, last played and resume point when the refresh dropped them.
- **Video integrity check**: Check integrity (quick, the first and last minute) and Full integrity check (the whole
  file) decode with ffmpeg from the right-click menu and the Media menu of the selection footer. A decode error gives
  the file a red **Corrupt** pill and puts it under the new Corrupt filter (movies and TV). A replaced file (other
  size or mtime) drops the old result.
- **Radarr and Sonarr orphans** (Library analytics): files Sonarr keeps but no episode uses, library files in an app's
  folder the app does not know, and app records whose file is gone. Delete goes through the library delete (recycle
  bin, then a rescan in the app); a missing file gets Rescan in the app. A report where most files look missing warns
  about the path mappings instead.
- **Kodi smart playlists**: a saved movie or TV filter can be written as "Curator - name.xsp", listing the file names
  that match, rewritten after every scan and when filters change. Folder under Settings, Files.
- **Collections in Jellyfin, Emby and Plex** (Settings, Sync): movie sets with two or more movies and saved filters
  with a tag are pushed as collections. Curator keeps the members of the collections it made or took over in step.
- **Disk space dashboard** (Library analytics): free space and library size per library folder, growth over time
  (measured daily), and the duplicate, upgrade and extra copies that would free the most space, with Delete.
- **Music videos**: a new folder media type. The music video window (header icon) scans the folders, reads artist,
  title and year from a <musicvideo> .nfo or the file name, probes each file for quality badges, writes a Kodi .nfo
  when one is missing, and sends Kodi a video library update.
- **Incremental scans touch only what they added or read again** in the remaining stages: video duplicate and upgrade
  marks (plus items already marked, so a removed copy's partner is looked at again; very large scans still check
  everything), the music sidecar count, release countries, music duplicates, upgrades and original years, and the
  music library update to the players (only the changed album folders, none when nothing changed).
- **Dry run for the client library refresh** (Movies, TV and Music scan settings): the scan log says "would refresh N
  items" and names them, and nothing is sent.

## v3.1.1 — 2026-10-31 — Duplicate pill for twin show folders, webhook queue progress

- **Two show folders that hold the same show now both get a Duplicate pill**, even when none of their episodes is a
  duplicate release (for example when one folder is the better copy, so its episodes only carry Upgrade available).
  Folders are the same show when they share a TVDB, TMDB or IMDb id and their names match once a year or country in
  brackets is left out (`Show` and `Show (2019)`), or, with no ids, the same title and year. The pill tooltip says how
  many other folders hold the show. The Duplicate filter and Status column include them. Shows still cannot be
  collapsed into one row.
- **The webhook queue shows how far a running batch is**: the Queue window ring and clock show done of total (for
  example `3/12`), the status line adds "3 of 12 done, 5 more waiting", and the Jobs drawer shows the same. Music
  counts each album as it finishes. Movies and TV count a library folder's items once that folder's scan, scrape and
  file jobs are done. Imports that arrive during a run are listed as more waiting.

## v3.1.0 — 2026-10-30 — Recycle bin for Delete from disk

- **Delete from disk can be undone.** Deleted movies, episodes, sets, albums, artists, extra episode copies, replaced
  tracks and duplicate subtitles move into a hidden `.curator-trash` folder at the top of their own library folder.
  It is on the same drive, so even a large file moves at once. Each item is listed in the new `trash_items` table.
- **Settings, General, Recycle bin** switches it on or off (on by default) and sets how many days items are kept
  (30 by default, 1 to 365). Open recycle bin lists each item with where it came from, its size, when it was deleted
  and when it goes for good, with Restore and Delete now per item and Empty recycle bin for all.
- **Restore** moves the item back to where it was, and refuses when something else is there now. Scan its folder
  afterwards to bring it back into the library.
- **Old items are deleted for good** at startup, every 6 hours and whenever the bin is opened.
- Scans skip the bin folder, and `.nomedia`, `.ignore` and `.plexignore` markers keep Kodi, Jellyfin, Emby and Plex
  out of it. With the bin off, or for a file outside every library folder, Delete from disk deletes at once as
  before. The delete warning says which of the two happens.
- New routes: `GET /api/v1/trash`, `POST /api/v1/trash/restore`, `/trash/delete` and `/trash/empty`.

## v3.0.9 — 2026-10-30 — Incremental scans tag only new and changed items

- **Saved filters that carry a tag** now only tag the movies and shows an incremental scan added or read again, like
  the other incremental stages. Before, every movie or show in the scanned folders was checked against each tagged
  filter. Full and deep scans still check them all.

## v3.0.8 — 2026-10-30 — Incremental video scans stay with new and changed items

- **The check for trailer and theme song files on disk** now looks only at the movies and shows an incremental scan
  added or read again. It used to look at every movie or show in the library. Full and deep scans still check them
  all.
- **Generating missing episode thumbnails** now looks only at the episodes an incremental scan added or read again.
  It used to look at every episode on disk under the scanned folders. Full and deep scans still check them all.

## v3.0.7 — 2026-10-30 — Video scans only rewrite .nfo files on full and deep scans

- **Rewrite .nfo files at the end of a scan (Movies and TV) now applies to full and deep scans only.** With it on, an
  incremental scan and every webhook import used to rewrite every .nfo under the scanned folders. They now write only
  the missing ones, as with the box off; scrapes still write the .nfo of what they change.
- The scan log now says how many items were already up to date. Video .nfo files that already hold the same text
  were already left alone (no write, no .nfo.bak, not counted); that is unchanged.

## v3.0.6 — 2026-10-30 — Music scans only write .nfo files that change

- **Rewrite .nfo files at the end of a scan (Music) now applies to full and deep scans only.** With it on, an
  incremental scan used to rewrite every artist.nfo and album.nfo under the scanned folders. It now writes only the
  albums it found new or changed, and any album.nfo that is missing, as it does with the box off.
- **An artist.nfo or album.nfo that already holds the same text is left alone.** Before, every file the step covered
  was written again: it got a new .nfo.bak when backups are on, the album's or artist's Modified date moved, and it
  counted as written. Now only real changes are written and counted; the scan log says how many were already up to
  date, and how many artist files were written. This applies wherever Curator writes music .nfo files.

## v3.0.5 — 2026-10-30 — Lidarr Retag webhooks are read

- **Every Lidarr Retag webhook was ignored with "Lidarr did not include any imported file paths", and the history
  did not say which artist it was.** Lidarr sends Retag after it rewrites the tags of a track file, with the artist
  and that one file under `trackFile`; Curator only read the `trackFiles` list that Download and Rename send. Retag is
  now read: the album folder of the retagged file is queued for a music scan, so the new tags reach the library and
  the players, and the history names it Artist — Album (the album taken from the folder name, as Retag does not
  send it). Many retags of one album become one scan. A Lidarr event that is ignored for another reason now still
  shows the artist.

## v3.0.4 — 2026-10-30 — Unnumbered bonus videos are not each other's upgrades

- **Bonus videos the scan could not number showed Upgrade available, with every other one as a copy.** A file
  without an episode number is stored as Season 0, Episode -1, and copies are matched on show, season and episode,
  so all of them looked like copies of one episode. An episode without a real number is now only ever itself; its
  Upgrade or Duplicate mark goes away the next time the marks are worked out (a scan, or opening the window).
- **"Special Features", "Bonus Features" and "Bonus Material" folders are extras**, like Extras and Featurettes. A TV
  scan no longer stores their videos as episodes, and Organize extras sorts such a folder inside a movie or show
  folder into the extras layout.

## v3.0.3 — 2026-10-30 — The info pane follows a deleted duplicate

- **After deleting or removing a copy in the duplicate or upgrade window, the info pane could still show the file
  that was deleted.** The pane was only read again when the open episode kept its row and its second file took over.
  When the duplicate was a separate episode or movie, or the pane showed one of the other copies, it kept the old
  path. Now the show is read again and whatever is open is refreshed; when the open item was the one deleted, the
  pane moves to a copy that stayed. Keeping one copy in the upgrade window also reads the show's episode list again.

## v3.0.2 — 2026-10-30 — The Sonarr "in use" mark now shows

- **v3.0.1's "in use" and "Not this episode's file" marks never appeared.** The duplicates window and the upgrade
  window build their copies without the season and episode number, so the check had no episode to compare with and
  both copies only showed the Sonarr file number. The copies now carry the episode, and a test goes through the same
  step the window uses.

## v3.0.1 — 2026-10-29 — Duplicates show which copy Sonarr uses for the episode

- **The duplicates window could show a Sonarr number on both copies of one episode.** The number is Sonarr's file
  id, and Sonarr can keep a file record that is attached to another episode, or to none, next to the one it uses.
  The window now also reads Sonarr's episode list and marks each copy: "File 563445 · in use" for the file Sonarr
  attaches to this episode, and "Not this episode's file (attached to S01E02)" or "(attached to no episode)" for a
  record Sonarr keeps but does not use here. Radarr and Lidarr numbers now read "Id".

## v3.0.0 — 2026-10-29 — A TV scan no longer fails on its first file without an episode number

- **"TV scan failed: 'unmatched_count'".** The page reads the last saved scan the first time it asks for the scan
  state. When that first request came while a scan was already running (right after a restart, for example), the
  saved totals replaced the running scan's totals, and the first file without an episode number (or the first
  failure) then stopped the whole scan. The saved state is now read when a scan starts and never replaces a running
  one, and a missing total starts at zero instead of failing.
- **Files and show folders deleted while a scan runs are logged as "Gone during the scan"** instead of being listed as
  failures. Their library entries are kept until the next scan, which sees the folders as they are then.

## v2.9.9 — 2026-10-29 — No DVD icon beside DVDRip in the info pane

- **The media icons in the info pane showed both DVDRip and DVD.** They now follow the same rule as the badges
  (v2.9.5): when the release format already names the source, only the format's icon is shown. The source icon stays
  when the format has no icon of its own (HDRip shows DVD). Blu-ray Remux keeps its two icons, the Blu-ray disc and
  Remux, which together read Blu-ray Remux. The rule now lives on the server too (`sources.source_covered`), with the
  same format-to-source table as the page.

## v2.9.8 — 2026-10-29 — TV No NFO filter lists the shows its count names

- **No NFO on TV Shows counted hundreds of episodes but listed only the shows that lack a tvshow.nfo.** The count
  took the episodes of every show the page had loaded, while the list kept a show only for its own .nfo, so those
  episodes never appeared. A show is now listed when it or any of its episodes on disk has no .nfo, the same way the
  other episode filters (No IMDb rating, No subtitles) work. Open the show to see the episodes. The show list carries
  a new per-show total (no_nfo_count) for shows whose episodes are not loaded yet.
- Missing-episode placeholders no longer count as having no .nfo (they have no file to write one for), and neither
  does a season that holds only those.

## v2.9.7 — 2026-10-29 — Incremental TV scans only look up subtitles for new episodes

- **An incremental TV scan searched OpenSubtitles.com for every episode of a show that had one new episode.** The scan
  recorded which shows changed, and the subtitle step then took all of their episodes, using up the daily download
  quota on episodes that were already done. It now records the episodes it added or read again and looks up only
  those. Movies were not affected. Full and deep scans still check every episode, as before.
- The automatic switch to the original language after a scan now also takes only those episodes.

## v2.9.6 — 2026-10-29 — Blu-ray spelled one way, one source badge per file

- **Blu-ray is always written Blu-ray.** Bluray, BluRay, blu ray and BLU-RAY in badges, the Source and Source format
  columns, their filters and the source text now read Blu-ray (UHD Bluray reads UHD Blu-ray). Only what is shown
  changes; renamed files keep the scene spelling BluRay.
- **One source badge when the format says it.** Besides DVD next to DVDRip, Blu-ray next to Blu-ray Remux and WEB next
  to WEB-DL, the source is now also hidden when the format belongs to it under another name: UHD Blu-ray next to UHD
  Remux, BD-Rip next to Blu-ray Rip. The page uses the same format-to-source table as the server, and a test keeps them
  in step.

## v2.9.5 — 2026-10-29 — One source badge when the format names it

- **DVDRip no longer comes with an extra DVD badge.** When the release format already names the source (DVDRip names
  DVD, Blu-ray Remux names Bluray, WEB-DL names WEB), only the format badge is shown. This applies to the info panel,
  the badges in Library updates, the Source column (left empty then) and the source text. The duplicates window
  already worked this way.

## v2.9.4 — 2026-10-29 — Quality badges for every imported item in Library updates

- **Some Radarr and Sonarr imports showed no quality badges in Library updates.** The lookup took only the first
  file the webhook named and looked for it as the movie's or episode's main file. A file Radarr or Sonarr renamed, an
  upgrade stored next to the old file as a second copy, or a queued show whose file list had been re-sorted found
  nothing, and a movie only fell back to its folder when the webhook named no file at all.
- Now every file the webhook named is looked up among all probed files, a file still on disk is preferred over one an
  upgrade replaced, and a title that still has nothing falls back to its movie folder, or to its show folder and the
  episode code in the title (S38E04).

## v2.9.3 — 2026-10-29 — One set of path mapping rules

- **Path mapping uses one set of rules everywhere** (`curator/path_map.py`). Each app keeps its own path rows; only
  the code that applies them is shared, by Kodi, Emby, Jellyfin and Plex updates, paths Kodi reports back, and paths
  from Radarr, Sonarr, Bazarr and Lidarr. Before, four copies differed in small ways. Now, for all of them: the
  longest root wins; `/tv` never matches `/tv2`; trailing slashes and backslashes do not matter; a root with a drive
  letter or a UNC share (`\\nas\tv`) ignores letter case; a target written with backslashes (a Windows server) gets
  backslashes; and a row for the root folder `/` works.
- Tests that assume the container's Linux paths (`test_imdb_data.py`, `test_ytdlp_update.py`) are skipped on Windows,
  so a local test run there shows only real failures.

## v2.9.2 — 2026-10-29 — Music track pills and column widths, one ARR client

- **Fixed: the FLAC OK, Corrupt and Upscaled pills never showed on music tracks.** Two scripts defined `audioBadge`,
  and the video one (codec and language text for the language editor) replaced the music one. The video one is now
  `audioTrackLabel`.
- **Fixed: column widths in the music track table.** Two scripts defined `columnWidth`; the movie table's version
  took a column object and replaced the music one, which takes a column name. The movie one is now `matrixColumnWidth`.
- **New test against this:** `tests/test_js_scripts.py` fails when two scripts define the same top-level function,
  `const`, `let` or `class`, and runs `node --check` on every script when Node is installed.
- **One HTTP client for Radarr, Sonarr, Lidarr and Bazarr** (`curator/arr_client.py`). The not-set-up check, API
  key header, timeouts, refused keys, the app's own error text and the connection note now work the same for all
  four. Lidarr now says "Lidarr refused the API key" for a wrong key, and its errors read "Lidarr answered 500:
  ..." like the others. Each app keeps its own API base.

## v2.9.1 — 2026-10-29 — Writing a show's .nfo files clears its NFO changes

- **The NFO changes pill on a show could stay after Write .nfo, however often it was pressed.** Three causes are fixed:
  - A missing-episode placeholder kept the .nfo of the file it once had. A later lookup changed its fields, so it
    counted as a change, but placeholders are never written. Placeholders no longer count, and writing the show drops
    the old .nfo from them (the file on disk is left alone).
  - A season with a season .nfo on disk but no folder and no episode files of its own was skipped by the writer. Its
    .nfo is now rewritten too.
  - Two episode rows that point at the same .nfo (the same episode listed twice, or one file under two spellings of
    its name on a share that ignores letter case) each wrote it in turn, so every press rewrote the same files
    ("Wrote 30 .nfo files" again and again). Only one row writes now; the others are named in a warning after the
    write and in the container log.

## v2.9.0 — 2026-10-29 — Scans refresh the items they changed on the players

- **New switches under During a scan** for Movies, TV and Music, off by default: *Update client libraries for items
  with updated metadata*, *with updated artwork* and (Movies and TV) *with updated ratings*. The last step of any scan,
  incremental, full or deep, then refreshes the items whose metadata, artwork or ratings changed, including values
  filled in for the first time, values replaced because overwrite is on, and items the scan added.
- **Per-item refresh where a folder scan is not enough.** Kodi gets RefreshMovie, RefreshTVShow or RefreshEpisode for
  each changed item, so it reads the .nfo and artwork again; Plex gets a metadata refresh per item. Emby and Jellyfin
  get the item folders marked as changed. An item a player does not have yet gets a scan of its folder instead. A
  changed season refreshes its show.
- Music: Emby, Jellyfin and Plex refresh the changed album and artist folders. Kodi and Navidrome already scan after
  every music scan; Kodi has no way to refresh one album's album.nfo or artwork.
- The refresh runs in the library update queue as one job per player (Library updates shows "Refresh"), and does not
  merge with folder scans. Players without path rows are left out, with the reason in the scan log.

## v2.8.3 — 2026-10-29 — Bazarr version in the connection test

- **Test connection now shows and saves the Bazarr version.** Bazarr names it `bazarr_version` in its status reply,
  so the test said only "Connected to Bazarr" and saved no version.

## v2.8.2 — 2026-10-29 — Add show by TMDB id on Sonarr 5

- **Add show works for a show with no TVDB id on Sonarr 5 and newer.** Curator still looks for the TVDB id first
  (through Sonarr and TMDB). When there is none, Sonarr adds the show by its TMDB id and Curator keeps it as wanted
  until the files arrive. When Sonarr reports a TVDB id for it, that id is saved too. Below Sonarr 5 such a show is
  still refused, now with a note that Sonarr 5 can add it.

## v2.8.1 — 2026-10-29 — ARR versions saved, Sonarr 5 API and TMDB lookups

- **Test connection saves the version.** Radarr, Sonarr, Lidarr and Bazarr: the version the app reports is logged
  and saved in `config/arr_versions.json` with the API used and the time, and shown under the Test connection button.
- **Ready for Sonarr 5.** When the test finds Sonarr 5 or newer and its new `/api/v5` answers, Curator uses it for
  every Sonarr call. An endpoint v5 does not have is tried again on `/api/v3`. Sonarr 3 and 4 keep using `/api/v3`.
- **Shows with only a TMDB id can be looked up in Sonarr 5.** Look up in Sonarr, Look up all episodes, Search
  missing episodes and the missing-episode search find the show by TMDB id there, and add it by TMDB id when Sonarr
  does not have it. Below Sonarr 5 these stay greyed out for shows without a TVDB id, and the server refuses them.
  Test the connection again after upgrading Sonarr.

## v2.8.0 — 2026-10-29 — One bin on the right-click menus

- **The right-click menus have one red Remove/delete… item instead of Remove from library and Delete from disk.** It
  sits at the bottom with the bin icon and label centred and opens the Remove window, which offers Delete from disk and Remove from library,
  the same window as the bin in the selection footer. This is on movies, sets, shows, seasons, episodes, artists and
  albums, and saves a row on every menu.
- Music now asks in that one window too. Before, artists and albums had two separate questions. A music folder Curator
  cannot write to only offers Remove from library.

## v2.7.9 — 2026-10-29 — Same actions on every media type

- **Music has Latest added.** A new quick filter (and filter menu entry) lists albums added in the last 30 days,
  newest first. An artist sorts on its newest album, also when sorting on the Added column.
- **Music quality badges filter the list.** Format, Quality, Bits, Sample rate and Bitrate in the Music table are now
  coloured badges (green for lossless), like the Movies and TV tables. A click filters that column, and badges in
  different columns combine. Clicking a badge no longer opens the album.
- **Original language in the selection footer.** Movies and TV have an Original language button under Media. One kind
  of item shows the changes first, as on the right-click menu.
- **Organize extras for a season.** The right-click menu offers it for a season too; it sorts the extras of that
  season's show, as it does for an episode.
- **Sonarr items need a TVDB id, like Radarr needs a TMDB id.** Look up in Sonarr and the Sonarr searches are greyed
  out for shows without one, with a hint to scrape the show first, instead of failing after the click.
- Update library… stays on movies and shows only: Kodi and the other players scan a whole show folder, not one
  season or episode.

## v2.7.8 — 2026-10-29 — Fixes from a review of the last releases

- **Original language: languages outside the common list now match.** TMDB gives two-letter codes (`ta`, `te`, `fa`,
  `cn`) and MKV tracks three-letter ones (`tam`, `tel`, `per`, `chi`), so a Tamil, Telugu, Persian or Cantonese film
  was always left alone. Release names with Tamil, Telugu, Malayalam, Kannada, Bengali, Punjabi, Urdu, Persian,
  Indonesian, Malay, Catalan, Tagalog, Mandarin or Cantonese next to DL or DUBBED are now recognised too.
- **Clear filters and saved filters now undo the Latest added sort.** Before, clearing the filters turned Latest
  added off but kept the list sorted newest first, and a saved filter with Latest added did not sort at all.
- **The date added shown under a show now matches the Added column** (the newest episode on disk).
- **Library queue badges go next to the right item.** A history row titled with two items, of which only one had
  quality facts, showed that item's badges after both names. They are now listed under the title with the item name.

## v2.7.7 — 2026-10-29 — Info pane banners keep room for their buttons

- **A shrinking banner stops at 56px tall**: one row of the Processed, Lock and Delete buttons with 10px above and
  below, so the buttons no longer hang over the text under the banner. Narrower than that (about 300px), the banner's
  sides are trimmed again instead of it getting lower.

## v2.7.6 — 2026-10-29 — Info pane banners shrink with the pane

- **A banner at the top of the info pane now scales down when the pane is narrowed**, for movies, sets, TV shows,
  seasons, episodes, artists and albums. Before, the banner was held at 148px tall and its sides were cut off once
  the pane was narrower than about 800px. It now keeps its shape and gets smaller. From about 800px wide it stays
  148px tall as before. A landscape image shown in place of a missing banner keeps the old strip.

## v2.7.5 — 2026-10-28 — Latest added sorts newest first

- **Latest added now sorts the list newest first.** Before, it only kept items added in the last 30 days and left them
  in the column sort (title, usually). Turning it on now sorts on the Added column, newest at the top, on Movies and
  TV Shows. Turning it off puts back the sort you had, unless you changed it in the meantime.
- **A show counts from its newest episode.** The show list carries a new `last_added` date (the newest episode on
  disk, or the show itself), so a show that got an episode yesterday is in Latest added and at the top, and the Added
  column sorts on it. Seasons and episodes stay in season order under their show.
- The Added column sorts on the real date instead of the text, so `2024-05-01 12:00` and `2024-05-01T12:00` sort together.

## v2.7.4 — 2026-10-28 — Filter the library by clicking a quality badge

- **Quality badges in the Movies and TV tables filter the list when clicked.** A badge sets the column filter of its
  column to every value that holds it: **P7** in Main HDR keeps DV P7, DV P7 FEL and DV P7 MEL. Clicking **FEL** on
  one of those rows narrows it to DV P7 FEL, and **P7** again widens back to all of profile 7. Clicking the badge that
  matches the filter exactly clears it.
- Works on Res, Main HDR, DV profile, EL, Secondary HDR, Video codec, Audio codec, Channels, Audio, Source, Source
  format and 3D. Badges in different columns combine, and the column header shows the filter as usual.

## v2.7.3 — 2026-10-28 — Switch dubbed releases to the original language

- **New setting: Enable automatic switch of default language to original language** (Settings, Files, Original
  language), one switch for movies and one for TV episodes, both off by default. After a Radarr or Sonarr import, and
  after a library scan finds a new or changed file, the default audio of an MKV is set to the original language.
- The original language from the scrape is the first choice. When it is unknown, a release or folder name such as
  `German.DL`, `DL.French`, `Italian.DUBBED` or `DUBBED.Italian` names the dubbed language and the one other audio
  language is used. `MULTI` or `DUAL` alone, three or more languages, or unknown track languages leave the file alone.
  Commentary tracks are never picked.
- **Preferred subtitle languages**, five in priority order, choose the default subtitle after the switch: the first
  language with a full (or SDH) subtitle wins. When the audio is in one of those languages, only a forced subtitle in
  it is chosen. With no match, every subtitle default is cleared, so a dubbed forced track does not stay on. The list
  starts from the OpenSubtitles languages until it is saved.
- **Switch to original language…** on the right-click menu (movie, show, season, episode) previews the changes and runs
  as a file job.
- Only MKV files are changed, with mkvpropedit, then probed again. Defaults set by hand with a Default button or
  Language defaults are remembered (new `video_files.user_default_size` column) and automatic runs skip that file
  until it is replaced.

## v2.7.2 — 2026-10-28 — Quality badges in the library update queue

- **Library updates show what quality was added.** The waiting and running library updates and Recent library
  updates now follow each movie, episode or album with the same colored badges as the info panel. Video shows
  resolution, aspect ratio, HDR (with Dolby Vision profile and layer), source, video codec, audio codec and
  channels, bit depth and container. Music shows the format (green when lossless), bit depth, sample rate and
  bitrate. A batch with several items lists each one with its own badges under the title.
- The webhook queue reads the facts from the probed file or the album when it hands the items to the players, and
  **Send library update** on movies does the same. History rows keep them in a new `work_events.quality` column, so
  updates logged before this version have no badges.

## v2.7.1 — 2026-10-24 — Fix Match removes the old show's missing episodes and seasons

- **Matching a show to another title no longer leaves the old title's seasons and missing episodes behind.** Louis
  Theroux's folder, matched wrongly to Harvey Birdman, kept Harvey Birdman's seasons 3 and 4 after it was matched
  correctly. Fix Match now removes the missing-episode placeholders that the new match does not list, and any season
  left empty. Locks do not protect them, since the old identity is gone. Only database entries are
  removed, never files on disk, and episodes that have a file are kept.
- If the new match lists no episodes at all, all of the old match's missing episodes and empty seasons are still removed.
- **Old artwork goes too.** When the new match has no image of a kind that the old match had (a banner, say), the old
  image is removed instead of kept. Only the image file Curator saved for that kind is deleted.
- **The warning triangle for episodes that are not in the TMDB season goes away.** Fix Match forgot nothing of the
  old match's season episode lists, so every episode looked out of place. They are cleared and refilled from the new
  match.
- **Duplicate and upgrade pills are redone after Fix Match**, since the new show title changes which episodes count as
  the same one.
- **Missing episode rows can be highlighted, and removed.** A missing row can now be clicked and is highlighted, and
  its right-click menu has "Remove S02E05 from the missing list" for an episode that does not belong to the show.
- **A scrape that replaces data also replaces each season's episode list**, so a stale list from an earlier wrong
  match no longer leaves rows such as S02E05 behind.
- **The "new episodes" pill no longer counts missing episodes**, which cannot be marked as processed.
- **A black frame is never kept as an episode or movie thumbnail.** The grab checks the picture and tries another spot
  in the file (25%, 55%, 70%, 15%, 85%) when it is black. A thumbnail that is already black is replaced by grabbing it
  again.
- **The Duplicate pill shows on a show and on a season** when any of its episodes has another copy, like the Upgrade
  pill already did.
- **E-AC-3, eac3, DD+ and Dolby Digital Plus show as one audio format** (Dolby Digital Plus) in badges, columns and
  cards, so one file no longer looks like it has two formats.
- **Every job in the Jobs window has a red ✕ on its right** that stops it when it runs and removes it from the queue
  when it waits (music and video scans, scrapes, file jobs, queued scans and ARR queue items).
- **The episode edit pane has an Episode number field.** The number is changed inside the season and kept (locked)
  against later scrapes. A missing-episode placeholder holding that number is replaced; a real episode with it is
  refused.
- **Saving in the Language defaults window no longer runs the search again.** The list stays as it is, with the saved
  tracks shown as the defaults, and the scroll position is kept.
- **Language defaults saves only what you picked.** Picking an English subtitle no longer also sets the audio default
  to English. A file with no pick still gets the preferred tracks when you use Save all.
- **Language defaults save shows its progress clearly.** The status is bold in a framed box with a progress bar, and
  the count no longer repeats ("11 of 176 11 of 176"). The Save button turns red and reads Saving… until the whole
  save is done, like other busy buttons.
- A `CLAUDE.md` in the project root holds the build, database migration and testing commands and the project rules.
- The scrape log says how many were removed. Run Fix Match once more on a show that was matched already to clean it.

## v2.7.0 — 2026-10-24 — The Fix Match log says what happened to each image

- **A Fix Match scrape now logs every artwork kind:** replaced (with the file name), no image found for the new
  match so the old one is kept, or candidates found but none could be saved. The line shows in the scrape log and
  under Saved scrapes, so a poster that did not change can be explained.

## v2.6.9 — 2026-10-24 — A wrong auto match is less likely, and Fix Match replaces the old artwork

- **A folder with no ids is no longer matched to a lone search result with an unrelated name.** The match took the
  only hit when there was exactly one and the year fitted, without looking at its name. A search for "Louis Theroux When
  Louis Met" could return another show and be accepted. A lone hit now needs a name that resembles the title; otherwise
  the show is left for Fix Match, as the log says ("No confident match … Use Fix Match"). This applies to movies and
  shows on TMDB and TVDB.
- **Fix Match now replaces the artwork of the item, not only larger images.** "Overwrite" only swapped an image for
  one with more pixels, so a show matched to the right title kept the wrong show's poster and fanart when the old
  image was bigger. After Fix Match, new artwork replaces the old whatever its size.
- A show that was already matched wrongly keeps its ids; run Fix Match on it once.

## v2.6.8 — 2026-10-24 — The scan stage is called "Trailers and subtitles"

- **The scan's Trailers stage is now named "Trailers and subtitles",** because subtitles are downloaded right after the
  trailers. The step also shows when only subtitle downloads are on, and stays lit while subtitles download.

## v2.6.7 — 2026-10-24 — The Upgrade and Duplicate windows warn about copies in different show folders

- **When the copies of an episode sit in different show folders, the Upgrade and Duplicate windows say so** and name
  both folders, above the copies. A show entry that was matched to the wrong show (a Louis Theroux folder matched as a
  second Harvey Birdman) pairs its files with the real show's episodes. The warning makes that visible before you
  delete anything.

## v2.6.6 — 2026-10-24 — "S12E02.-.19.Title" is episode 2, not episodes 2 to 19

- **A number after a spaced dash is no longer read as the end of an episode range.** Hell's Kitchen
  `S12E02.-.19.Chefs.Compete.mkv` was taken as episodes 2 to 19, so S12E02, E03 and E04 all claimed the same
  episodes and appeared as copies of each other. `S01E01-04`, `S01E01-E04` and `S01E01.-.E04` are still ranges.
- Rescan the show so its files are read again with the new rule. Until then the old episode numbers and the false
  Upgrade and Duplicate pills stay.

## v2.6.5 — 2026-10-24 — Episodes of different shows are never copies of each other

- **An episode is no longer matched as a copy of another show's episode.** The Upgrade window for Harvey Birdman S01E02
  offered "When Louis Met S01E02" as the other copy, because both shows had the same id and the same season and episode
  numbers. Episodes now match only when the show names agree (a year or country in the name is ignored, so Show and
  Show (2019) still match). That removes the false Upgrade and Duplicate pills and the risk of deleting another
  show's file from the window.
- Run a rescan (or any scan that finishes) once so the old false pills are recalculated.

## v2.6.4 — 2026-10-24 — Deleting a duplicate can no longer take the copy you keep

- **Fix for episodes lost when deleting a copy of a two-part (Multi) file twice.** The first try stopped with an error
  after it had already switched the episode to its other file, so the library and the disk disagreed. The second try
  then deleted that file. Deleting a copy now checks everything first and changes nothing when it refuses.
- **Delete from disk never removes a file that an episode in the library still uses as its own,** never removes a
  file another episode keeps as a second copy, and never deletes anything when the copy you keep is not on disk.

## v2.6.3 — 2026-10-24 — Deleting a copy of a two-part episode file works the first time

- **Deleting or removing one copy of a file that holds two episodes (Multi) from the Duplicate or Upgrade window no
  longer stops with "Another indexed episode uses the same file".** The copy now goes for both episodes together; an
  episode that has another file keeps it. Before, the first try was refused and only the second, after the other
  episode was gone, went through.

## v2.6.2 — 2026-10-24 — Movie versions get the same arrow as episode versions

- **Each version row under an opened movie now starts with the ↳ arrow,** as the version rows under an episode do.

## v2.6.1 — 2026-10-24 — A collapsed episode shows the pill of its other versions

- **An episode row with versions collapsed now shows the Upgrade available pill when any of its files is the weaker one,**
  as a collapsed movie row does. Before, only the episode's own file counted, so an episode whose second file was
  the weaker one showed no pill until you opened it.

## v2.6.0 — 2026-10-24 — Deleting one copy of an episode leaves the other in the library

- **Deleting (or removing) one copy of a duplicate episode from the Duplicate or Upgrade window no longer removes the
  whole episode.** When the episode's own file was the one deleted, its best other file now becomes the episode's file,
  so the episode stays in the tree with the copy you kept. Deleting the other file leaves the episode as it was.
  The show is read again so the row and its versions are right straight away.
- A normal Delete or Remove of an episode from the library is unchanged and still removes the episode.

## v2.5.9 — 2026-10-24 — An opened episode lists every version

- **Opening an episode with "2 versions available" now lists both files,** best first, the way an opened movie does.
  Before it listed only the second file, so the episode's own file never showed under it. The version rows also
  carry the episode's Added date. With Collapse versions off, each extra file still gets its own row under the episode.

## v2.5.8 — 2026-10-24 — The Unknown audio language pill clears after you set the language

- **Setting an audio or subtitle language on an episode or movie now clears the Unknown audio language pill straight
  away** on its row, and on the season and show above it. The file was changed and read again, but the list kept the
  flag it had before. The list rows are now read again after a language change, a default-track change and Update
  media info.

## v2.5.7 — 2026-10-24 — The Duplicate window lists a second file of an episode

- **Clicking a Duplicate pill on an episode no longer opens an empty window ("None").** An episode's duplicate is
  usually a second video file stored with that episode, and the window only looked at episode rows. It now lists the
  second file next to the episode so you can compare them.
- **Delete from disk and Remove from library work on that second file** (they failed before). Only that file goes; the
  episode stays. The flags on the show, season and episode update afterwards.
- "Not duplicates" is not offered when one of the copies is a second file of an episode.

## v2.5.6 — 2026-10-24 — Seasons show the Upgrade and Duplicate pills

- **A season row now carries the Upgrade available and Duplicate pills when any of its episodes does,** so the affected
  season can be found without opening every season. The Upgrade available and Duplicate filters match the season too.

## v2.5.5 — 2026-10-24 — Episode versions, and a show's Upgrade pill follows its episodes

- **A second video file of an episode is now shown as a version of that episode,** the way two files of one movie are.
  With **Collapse versions** on (Settings → Movies), the episode row has a caret and "2 versions available"; open it to
  see each file on its own row with its resolution, HDR, size and audio. With it off, every file has its own row under
  the episode. The weaker file carries the Upgrade pill. The setting now covers movies and episodes. Expand all and
  Collapse all open and close the versions too.
- **Clearing duplicate episodes now clears the show's and the season's Upgrade and Duplicate pills.** The episode rows
  updated but the show and season rows kept the old pill until the page was reloaded. They now follow their episodes,
  including for a show you have not opened.

## v2.5.4 — 2026-10-24 — An expired Trakt sign-in asks you to reconnect

- **Trakt refusing the saved refresh token (400 "invalid refresh token") no longer repeats an error every five
  minutes.** Curator forgets the dead tokens, keeps your Client ID and secret, stops the scheduled sync, and Settings →
  Trakt shows "Trakt sign-in expired. Connect again to resume syncing." Press Connect with Trakt to sign in again.
- A Trakt outage or network failure keeps the tokens and is logged as a one-line warning instead of a traceback.

## v2.5.3 — 2026-10-24 — Episode thumbnails are saved under the name the library looks for

- **A generated episode thumbnail is saved as `<video>-thumb.jpg`,** the name Kodi and the scan use. When the episode
  number in the database differed from the one in the file name (Lupin S04E01 stored as season 3), the generator wrote
  `<video>-S03E01-thumb.jpg` instead, and the library kept showing the old `<video>-thumb.jpg` (the green one). The
  episode mark is now added to the name only when one file holds several episodes. The scan's thumbnail generation
  follows the same rule.
- An older `…-S03E01-thumb.jpg` next to a file is left alone; it can be deleted.

## v2.5.2 — 2026-10-24 — A regenerated thumbnail shows at once

- **Local artwork is no longer cached for an hour by the browser.** Images from the library folders were sent with
  `max-age=3600`, so a thumbnail that was regenerated, or any image that was replaced, kept showing the old picture
  until the hour was up. This was why the Dolby Vision thumbnail still looked green after Curator had written a good
  one. The browser now checks each time and gets a short "not modified" answer when the file is unchanged.

## v2.5.1 — 2026-10-24 — Profile 5: plain seek first, grabs are logged

- **For Dolby Vision profile 5 the plain seek is tried before the scene-detect one.** That is the form that was run by
  hand on the real file and gave a normal picture; the scene filter in front of libplacebo is now only the second try.
- **Every frame grab writes its ffmpeg command and result to the container log** (`docker compose logs curator`), so
  a wrong thumbnail can be traced to the exact command.

## v2.5.0 — 2026-10-24 — Dolby Vision profile 5: the Trickplay add-on's chain

- **Profile 5 thumbnails use the filter chain from the Trickplay add-on** (read from its source): libplacebo uploads the
  frame itself, applies the Dolby Vision metadata with `hable` tone mapping and perceptual gamut mapping, and the
  scale comes after it. The earlier chain scaled first and went through `hwupload` and `hwdownload` by hand, and gave a
  green frame in testing. HDR grabs also write the JPEG tagged full-range BT.709, as the add-on does.
- **The dovi_tool route is back as the second choice,** tried only when libplacebo fails or gives a green frame. A green
  result from it is refused too.

## v2.4.9 — 2026-10-24 — A green Dolby Vision frame is never saved

- **The dovi_tool route for profile 5 is removed.** `dovi_tool -m 3` only rewrites the metadata; the picture stays in
  Dolby Vision's own colour space, so the result was still green. Profile 5 can only be shown correctly by libplacebo
  applying the Dolby Vision metadata.
- **A frame that comes out green on a Dolby Vision file is thrown away** (its average chroma is checked) and the grab
  reports why, instead of saving a wrong thumbnail. Other Dolby Vision profiles and HDR10 are unaffected.

## v2.4.8 — 2026-10-24 — Dolby Vision profile 5 thumbnails through dovi_tool

- **Profile 5 files now get a proper thumbnail without a GPU.** If libplacebo with Vulkan cannot render it, a short
  stream copy around the frame is converted with `dovi_tool -m 3` (profile 5 to 8.1) and then tone mapped to SDR with
  zscale. This is the method the Trickplay add-on uses. dovi_tool is already in the image.
- libplacebo is asked to apply the Dolby Vision metadata explicitly, and the converted path writes a full-range BT.709
  JPEG.

## v2.4.7 — 2026-10-24 — No green thumbnails for Dolby Vision profile 5

- **A profile 5 file is only rendered through libplacebo, never through the plain tone map.** Profile 5 has no HDR10
  base layer; without the Dolby Vision metadata its frame is all green or purple. Since v2.4.6 let the plain tone map
  finish, it wrote that green frame as a success when libplacebo (which needs a Vulkan device) could not run. Now the
  grab fails with a message that names libplacebo/Vulkan and ffmpeg's last line, and no wrong thumbnail is saved.
- If you still see the failure after rebuilding the image, the software Vulkan device is not working in the container;
  send the message and the next step is a Dolby Vision-aware render through dovi_tool.

## v2.4.6 — 2026-10-24 — HDR and Dolby Vision thumbnails: JPEG range

- **Tone-mapped thumbnails are written as full-range JPEG.** Newer ffmpeg refuses to write a limited-range frame to a
  JPEG ("Non full-range YUV is non-standard"), so every HDR and Dolby Vision grab ended with *ffmpeg could not extract a
  frame*. The chain now ends in `yuvj420p` and ffmpeg runs with `-strict unofficial`, as the Trickplay add-on does.
- **The colour probe no longer depends on ffprobe's `-show_entries` form,** which older ffprobe builds reject; the
  tag and Dolby Vision data now come from `-show_streams`.
- **The Docker image gets `libvulkan1` and `mesa-vulkan-drivers`,** so ffmpeg's libplacebo has a software Vulkan device
  for Dolby Vision profile 5 files (they have no HDR10 base layer). Rebuild the image to get it.

## v2.4.5 — 2026-10-24 — Thumbnail errors say why

- **When ffmpeg cannot get a frame, the message now names the kind of file (SDR, HDR, Dolby Vision) and ffmpeg's own
  last error line,** instead of only *ffmpeg could not extract a frame from this file*. This is to find out why a
  tone-mapped HDR/Dolby Vision grab fails on a given file.

## v2.4.4 — 2026-10-24 — Queue window no longer jumps

- **The current-work line at the top of the Queue window is always shown.** It used to appear while something was being
  scanned or updated and vanish when idle, which pushed the rest of the window up and down. It now reads *Idle* when
  nothing is running and keeps its height.

## v2.4.3 — 2026-10-24 — Stuck "counting seasons and episodes…"

- **The batch footer no longer stays on *counting seasons and episodes…*.** The message was cleared only when no later
  click on the master box (All or None) had happened, so ticking and unticking quickly left it on for good. Each
  counting pass now ends the message, and the footer repaints when the last one is done.

## v2.4.2 — 2026-10-24 — Refused actions wait in the queue

- **These no longer say "Wait for the running scan…". They queue, show in the Jobs window and run in turn:**
  file jobs (rename, extras, delete), Apply match, movie and show artwork download, and restoring or deleting a split
  source. A message says it was queued. When nothing else is running they start at once, as before.
- **Remux (Dolby Vision profile 8) and a single item's ratings refresh start at once** instead of being refused during
  a scan. The remux's follow-up deep scan still goes through the queue.
- The queue checks again every two seconds while a job waits, so a waiting job starts even if the job ahead of it did
  not report that it ended.
- Moves, splits and Fix Match already queued and still do.

## v2.4.1 — 2026-10-24 — Local edits no longer wait for scans

- **These run at once, whatever scan, scrape or file job is running:** tag rename, delete and apply; subtitle default-track
  edits; media-info refresh; season, episode and set artwork download. They only touch the database and the item's own
  files, so there is nothing to wait for.
- **Apply pending matches** no longer waits for a scan or file job. It only needs the scrape slot, and says so when a
  scrape is running.
- Movie and show artwork download still waits, because it starts a scrape. Moves, deletes, relocation, remux and
  restore keep their waits.

## v2.4.0 — 2026-10-24 — Language defaults: Save buttons

- **Each file has its own Save button** (MKV files), which sets the default tracks for that file only, using the tracks
  you clicked or the preferred ones. The list keeps its scroll position afterwards.
- **Save all moved next to Close** in the window header, so it is always in view.
- **Saving no longer waits for or is refused by a scan or file job.** It runs at once on its own worker. This was likely
  why Save all appeared to do nothing.
- **Only changes are written.** A file whose chosen track is already the single default (including unflagged first audio) is skipped, and the result says how many files changed.
- **A clicked track is readable.** The highlight is a soft tint with an outline and normal text colour instead of a
  bright fill with near-matching text.

## v2.3.9 — 2026-10-24 — Scrape log

- **Every scrape now leaves a log.** When a scrape finishes, stopped or failed ones included, its log is saved under
  config/logs as `…_<media>_scrape.log` (movies, TV, sets, episodes, seasons; ratings and artwork jobs too). The Scrape
  window has a *Saved scrapes* button that lists them, newest first, and opens one with Copy and Export. Before, the
  log was only in memory and was gone after the next scrape or a restart (only movie sets were kept).
- The newest *scan_log_keep* scrape logs per media are kept. Movie set scrapes now save as scrape logs rather than
  scan reports.

## v2.3.8 — 2026-10-24 — Fix Match waits in the queue

- **Fix Match is queued behind a running scan instead of being refused.** It stopped with *Wait for the running scan or
  file job to finish*. Now it takes its place in the Queue window as *Fix match*, with the other jobs. The new id is
  written when its turn comes, just before the scrape reads it, so the running scan cannot undo it. The message says it
  is queued. (A duplicate or upgrade mark that the new id causes is shown once the job has run, not at once.)

## v2.3.7 — 2026-10-24 — Sonarr is told about a merge

- **After a season merge, Sonarr is asked to rescan the show,** so it picks up the files and the two apps agree. The
  message after saving says so (*Saved. Sonarr was asked to rescan the show.*), and Curator then scans the show again
  when Sonarr is done (v2.3.6). Nothing is sent when Sonarr is not set up or the show has no TVDB id.
- **A merge no longer reports a failed .nfo write.** The season that was merged away was still being written; the show
  is written instead.

## v2.3.6 — 2026-10-24 — Scan after a Sonarr rescan

- **Asking Sonarr to rescan a show now also queues a scan in Curator.** Sonarr only tells Curator about files it adds or
  removes, so a rescan that changed numbers or paths left nothing in the queue and the library unchanged. Curator now
  waits until Sonarr has finished the rescan, then scans that show itself, with Sonarr's current numbers. The scan shows
  in the Queue window as *Scan of <show> after the Sonarr rescan*, and the message after the click says so.

## v2.3.5 — 2026-10-24 — Stale marks, ghost seasons and the rescan message

- **The Upgrade pill goes away when no other copy is stored.** Opening the pill said *No other copy is stored for this
  item* and cleared the Duplicate mark but left an Upgrade mark that is kept as a path, so the pill stayed. Both are
  cleared now.
- **A leftover season .nfo no longer brings back an empty season.** After the episodes of season 4 were numbered
  season 3, an old `season04.nfo` in the show folder made the scan create an empty *season 4*. With Sonarr set up, a
  season .nfo for a season Sonarr does not list is ignored, and the empty season it made is removed on the scan.
- **Rescanning a season or an episode reports the TV scan.** The answer came back with the movie scan's status, so the
  message read *Movie scan finished. 0 movies added …* with the numbers of an older movie scan.

## v2.3.4 — 2026-10-24 — Placeholder episodes

- **An episode that is only a placeholder is no longer treated as a copy.** After Sonarr replaced a file, the empty
  *Episode missing* row for it sat next to the new file, was listed in the Upgrade and Duplicate window as a copy with
  nothing in it, and made the new file look like a duplicate or an upgrade. Placeholders are now left out of those
  marks and that window, and any mark they carried is cleared.
- **A placeholder can be removed from the library again.** Delete tried to remove the placeholder's file path and
  stopped with *It is outside its library folder*. Placeholders have no file, so only the library entry is removed, and
  the window no longer offers *Delete from disk* for them.
- **Rescanning an episode that has no file now looks for it.** The episode rescan only read the stored file path, so on
  a placeholder it did nothing. It now looks in the show folder for the file carrying that number, by its name or by
  Sonarr. To bring back files that an earlier merge or removal lost, rescan the show.
- **Episodes in the Upgrade and Duplicate window show their thumb in 16:9** instead of a poster crop.

## v2.3.3 — 2026-10-24 — Merged episodes become copies, or fill the missing ones

- **Fixed: merging seasons, or moving an episode onto a number that is taken, did not work properly for the second
  file.** The query that stored it as a copy was refused by Postgres (*column "episode_id" is of type uuid but
  expression is of type text*), so no copy appeared and no Duplicate or Upgrade mark. It is fixed and was run against
  the real schema.
- **A file that lands on an episode that is only a placeholder now fills it.** Season 3 held *Episode missing*
  placeholders (from TheTVDB) with the same numbers as the files in Partie 4. The file now becomes that episode, which
  keeps its TheTVDB title and plot, loses the red *Episode missing* sash and takes the file's thumb. Only an episode
  that really has a file gets the file as a second copy. If an earlier merge left files attached as copies of
  placeholders, a normal scan of the show puts them right.

## v2.3.2 — 2026-10-23 — Merging seasons treats clashes as duplicates

- **A season merge no longer stops on episodes that exist in both seasons.** The same file stored under both numbers
  (a scan read it as S04E01 once and as S03E01 later) is one episode, and the extra row is dropped. The same episode
  number with a different file becomes a second copy of that episode, the way a scan stores a duplicate, so it shows
  up under the Duplicate and Upgrade marks and the duplicate tools like any other. The episode already in the
  target season stays the main one. Moving a single episode to a season that already has that episode number does
  the same.

## v2.3.1 — 2026-10-23 — Merge seasons when renumbering

- **Renumbering a season onto a number the show already has now warns and offers a merge.** Saving shows *Season 3
  already exists in this show* with a question, *Merge this season into it?*. Agreeing moves the episodes into that
  season, fills its empty title, plot, premiere date, year and artwork from this one, and removes this season. If both
  seasons have an episode with the same number, nothing is merged and the message names those episodes. A merge always
  moves the episodes, whatever the box says.

## v2.3.0 — 2026-10-23 — Edit season numbers

- **A season's number can be edited.** The season Edit window has a *Season number* field and a box, ticked by default,
  *Also change the season number of its N episodes*. Saved, the season (and its episodes, when ticked) move to the new
  number, the .nfo files are rewritten, and the season name moves with it. A number that already belongs to another
  season of the show is refused. Untick the box to renumber only the season.
- **An episode's season number can be edited** in the episode Edit window. The episode moves to that season, which is
  created when the show does not have it. An episode number that is already used in the target season is refused.
- **A scan keeps numbers set by hand.** Edited seasons and episodes are locked on their season number, so the next scan
  does not put them back to the number in the file name (or in Sonarr). The padlock unlocks them again. The files and
  season artwork on disk are not renamed.

## v2.2.2 — 2026-10-23 — Episode numbers follow Sonarr

- **A file named S04E01 that Sonarr and TheTVDB number S03E01 is now stored as S03E01.** When Sonarr is set up under
  Settings, Integrations, a TV scan asks it which episodes each file holds (matching the show by TVDB id, or by folder
  when it has none, through the path mappings) and uses those season and episode numbers in the library, in the
  generated .nfo files and for scraping, instead of the numbers in the file name. Multi-episode files follow Sonarr too.
  An existing .nfo that carries the old numbers is read under the new ones. A show that is stored with different numbers
  than Sonarr gives is rescanned even when nothing on disk changed, so Lupin corrects itself on the next scan. Without
  Sonarr, or when it cannot be reached, file names decide as before. The scan log says how many files of a show were
  numbered Sonarr's way. The files themselves are not renamed.

## v2.2.1 — 2026-10-23 — Episode thumbs from HDR and Dolby Vision files

- **Generated episode thumbs no longer come out purple, green or washed out for HDR sources.** Both the Generate thumb
  button and the scan job ran a plain ffmpeg grab. A shared generator now reads the file's colour tags and Dolby Vision
  side data: HDR10, HLG and Dolby Vision profiles 7 and 8 are tone mapped to SDR (BT.709), and profile 5, which has no
  HDR10 layer, is tried through libplacebo first when the container has Vulkan, then through the same tone mapping.
  SDR files are grabbed as before. Only the frame that is picked is tone mapped, so it is not slower to scan.
  Thumbs already made from HDR files stay as they are until they are deleted and generated again.

## v2.2.0 — 2026-10-23 — TV quality filter counts cover every show

- **The 4K, 1080p, P7 FEL, DV, HDR10+, HDR10, HLG and SDR filters in the TV list count every episode.** They only
  looked at episodes of shows you had opened, and the show rows carried no quality, so a library of thousands of
  episodes showed a handful. The server now sends per-show totals for each of them, a show matches when any episode on
  disk does, and the count adds those totals for shows that are not open, for example *140 shows, 3 212 episodes*.
- **The same goes for the other episode filters** (No IMDb rating, No subtitles, Missing English subtitles, Multi-audio,
  Unknown audio and subtitle language, No episode thumb, New, Multi-episode): their episode counts were also limited to
  opened shows.

## v2.1.9 — 2026-10-23 — Queue timers measure the job

- **The running timers in the Queue window now count the job itself.** A Library updates, Arr or ingest row showed the
  time since you opened the window, and started again from 0s when you came back. The server read the job's start time
  as UTC although the database stores it in its own time zone, so any time zone ahead of UTC gave a start in the
  future and a timer of zero. The elapsed time is now worked out by the database.

## v2.1.8 — 2026-10-23 — TV3 logo by country

- **Norwegian and Baltic shows on TV3 get the TV3 (Norway) logo.** A network called TV3 now uses `tv3-no.png` when the
  show's countries include Norway, Estonia, Latvia or Lithuania. Other TV3 shows keep their usual logo.

## v2.1.7 — 2026-10-23 — Provider ids on the info pane and in Edit

- **The info pane shows every provider id.** A row at the bottom of the poster, title and ratings block lists each id
  the item has, icon first, then the provider name and the number, with a bullet between them. Ids link to the
  provider's page where there is one. Movies, shows and episodes all get the row.
- **Provider ids can be edited.** The Edit window has a *Provider ids* field written like
  `tmdb=1022, tvdb=2405, imdb=tt0111161` (providers: imdb, tmdb, tvdb, trakt, tvmaze, anilist, ofdb, ofdbcc, wikidata).
  Removing an entry clears that id. Edited ids are locked, so scrapes keep them, and the .nfo is rewritten.

## v2.1.6 — 2026-10-23 — Narrow an Update ratings run

- **Update ratings can be limited to items with a low or thin score.** The window has a new box, *Only update items
  where the score stored for a ticked source has…*: a rating below N (1 by default), fewer than N votes, more than N
  votes, or no score yet. Nothing ticked updates everything; several ticked update an item that meets any of them. The
  check is made per ticked source against the score already stored (scores on other scales are compared out of 10),
  and only the sources that qualify are asked for that item. A missing score counts as a low rating and as few votes.
  Items that do not qualify are not touched, and the end line reads, for example, *412 updated, 3100 left out by the
  filter*. With a filter on, even a single item goes as a job.

## v2.1.5 — 2026-10-23 — Upload artwork without a TMDB id

- **An item with no TMDB id can still take artwork you upload.** Choosing artwork used to stop with *Scrape this show so
  it has a TMDB id* for a movie, show, season, episode or set without one, which also blocked uploading your own image.
  The picker now opens with no online images and the upload buttons.

## v2.1.4 — 2026-10-23 — Source list defaults

- **Open Film Database (ofdb.cc) is last in the default source order,** as the last resort for what the other sources
  left empty, and **OFDb (ofdb.de) is off by default** (it is mostly German information). This applies to new installs
  and to a list that was never saved. A list you have saved is left as it is: tick OFDb off and add Open Film Database
  at the bottom under Settings, Movies and TV, if you want the same.

## v2.1.3 — 2026-10-23 — Open Film Database (ofdb.cc) as a metadata source

- **New source: Open Film Database (ofdb.cc).** A free, open database with a JSON API and no key (not the German OFDb,
  and it has no scores). It is in the Movies and TV source lists as *Open Film Database* and is asked by id only (IMDb,
  then TMDB, then TheTVDB for shows). It fills what higher sources left empty: title, original title, plot, tagline,
  release date and year, genres, movie runtime, show status and network. Existing installs get it only when it is
  added under Settings. It appears in the connection status list as it is used.

## v2.1.2 — 2026-10-23 — A dead rating site is skipped, not hammered

- **A page source that stops answering is left alone for the rest of the run.** After 4 requests in a row to the same
  site (OFDb, Rotten Tomatoes, Metacritic) get no answer, the site is skipped until the run ends, with one clear
  message, instead of timing out for every title (15 s each) and sending more requests to a site that may have blocked
  this address. The next run tries again.

## v2.1.1 — 2026-10-23 — Thumbnail jobs say what they are doing

- **Generate thumbs is easier to follow.** The Jobs window now names the job (*Episode thumbnails*, not *File job*),
  shows which episode it is on and how many are done (*2/4*), and the log gets a line before each episode (which file a
  frame is taken from) and one after it with how many seconds it took.

## v2.1.0 — 2026-10-23 — Fix Match jobs show in the Jobs window

- **A Fix Match that has to wait is listed in the Jobs window.** It used a private waiting list that the window did not
  read, so several Fix Matches ran one after another without showing. They now join the same queue as other scrapes,
  labelled *Fix match* with the title, and can be removed from the queue there.

## v2.0.9 — 2026-10-23 — Fix Match refreshes every field

- **Fix Match now refreshes all metadata of the newly matched title.** The scrape that follows a Fix Match used the
  fields ticked for scans in Settings, so a field that was not ticked (year, original language, countries...) kept the
  value of the wrong match. It now refreshes every field except those you locked, with overwrite on. Ratings follow
  the usual rating sources.

## v2.0.8 — 2026-10-23 — Filter counts by kind, No poster for seasons

- **TV filter counts say what they count.** Each count in the TV filter bar and in More filters is split by kind, for
  example *12 shows, 340 episodes* or *3 seasons*, instead of one number that mixed shows, seasons and episodes.
- **No poster also finds seasons.** A season without a poster now matches, and with No poster alone, ticking shows
  ticks their seasons without a poster (never episodes).
- **Missing trailer is gone from the TV filters** (No trailer stays). Movies keep Missing trailer.

## v2.0.7 — 2026-10-23 — Unmatched counts shows only

- **The Unmatched filter on TV Shows counts shows, not episodes.** Seasons and episodes carry no database ids of their
  own, so every opened season and episode was counted as unmatched (almost 2000 for a handful of shows). Unmatched is now
  a show-only filter, like No poster: it lists the shows with no TMDB, IMDb or TVDB id and ticks none of their children.

## v2.0.6 — 2026-10-23 — No wall of "Show" in the scrape warning

- **The "needs a match" warning no longer lists "Show" hundreds of times.** For a selection of episodes or seasons whose
  show was not loaded in the list, every id counted as an unmatched show called *Show*. Those are now left out (the
  server judges them), and the warning lists at most 20 titles and then *and N more*.

## v2.0.5 — 2026-10-23 — Stay under Trakt's limit

- **Trakt's documented limit is 500 requests per 5 minutes** (one every 0.6 s), so requests are now spaced 0.65 s
  apart. A 429 waits for the `Retry-After` Trakt sends (up to 300 s); without one it backs off exponentially with
  jitter. An episode no longer looks up its show's Trakt id again for every episode: the id is remembered for the run,
  which halves the requests of a big episode run.

## v2.0.4 — 2026-10-23 — Trakt rate limits are waited out

- **Update ratings no longer fails whole runs on Trakt's "429 too many requests".** A 429 from any source is now waited
  out (up to 8 times, following the `Retry-After` the source sends, up to 90 seconds) before the request counts as
  failed, and the wait holds back every other request to that host. Trakt requests are also spaced 0.5 s apart instead of
  0.35 s. Large runs with only Trakt ticked are slower but finish. To go faster, tick the local IMDb data and leave
  Trakt out.

## v2.0.3 — 2026-10-23 — Ratings jobs say why items failed

- **The ratings summary names the main reason.** A run that ends with failures now reads, for example,
  *0 updated, 0 skipped, 142 failed. Why: No ratings came back… (142 items)*. The full list per item is in the results
  window under Failures.

## v2.0.2 — 2026-10-23 — Multi-episode files share the IMDb score

- **The later episodes of a multi-episode file take the first one's IMDb score.** IMDb lists a two-part episode once,
  on its first number, so a file such as `S02E21E22` gave episode 21 a score and left episode 22 with none. Update
  ratings and a scrape now give every episode of the file that has no IMDb score of its own the score (and votes) of the
  other episodes in the file: found in the local IMDb data first, then from a score already saved on one of them. An
  episode IMDb does rate on its own keeps its own score. Single-episode files are unchanged.

## v2.0.1 — 2026-10-23 — Scope boxes in the TV selection footer

- **Choose what the buttons work on.** On TV Shows the left side of the selection footer lists what is ticked, for
  example *20 shows · 40 seasons · 200 episodes*, and each count now has a box. Untick *shows* and *episodes* and every
  button (Scrape, Rescan, Edit, Update ratings, Artwork, .nfo, Rename, Subtitles, Lock, Processed, Move, Remove) works on
  the seasons only. The number above reads *40 / 260 items* (in scope / ticked) when part of the selection is out of
  scope, and plain *260* when all of it is in. All three are ticked by default and the scope resets when the selection is
  cleared. Buttons that need a kind (Edit shows, Theme songs, Move) appear only when that kind is in scope.
- **Artwork follows the scope.** Artwork now runs one job per ticked kind: the shows' own artwork, the seasons' artwork,
  and the episodes' thumbnails. Artwork for seasons only no longer touches the show or its episodes (new `art_levels` and
  season limit on artwork-only jobs).
- **Scrape:** a scraped show already covers its seasons and episodes, so with shows in scope only the shows are scraped.
  With only seasons and episodes in scope, a mixed selection still scrapes their shows; narrow the scope to one kind to
  scrape exactly that kind.

## v2.0.0 — 2026-10-23 — No 5000-item cut on batches

- **Batches are no longer cut at 5000.** The server silently kept only the first 5000 ids of any batch (Update ratings,
  Scrape, Lock, Remove/Delete, Processed/status, tags, and album field edits), so a larger selection was only partly
  processed. The cut is gone. A request over 500,000 ids is refused with a message instead of being trimmed.

## v1.9.9 — 2026-10-23 — Select all on TV is instant and follows the filter

- **One request instead of hundreds.** Ticking the box in the title bar (or a show) on TV Shows used to open every
  ticked show one by one to tick its seasons and episodes, which made *select all* very slow. The seasons and episodes
  now come from the server in one request (`POST /api/v1/tv/selection`). While it runs the footer says it is counting.
- **Only what the filter lists.** With a filter on, such as *No IMDb rating*, ticking a show picks only its episodes
  that match the filter and are on disk, and only the seasons that hold one. With no filter it picks every season and
  every episode on disk. This covers the quick and More filters (ratings, subtitles, audio languages, thumbs, NFO,
  lock, upgrade, duplicate, new, scrape and probe failures, resolution and HDR, multi-episode); Filters on the
  show or season only (no poster, trailer, theme) pick no episodes. For anything else, including column filters, the
  shows are opened and the same rule is applied to their episodes, as before but filtered.
- **Update ratings window:** a *Select / deselect all* box above the sources. It shows a dash when only some are ticked
  and leaves sources that are not set up alone.

## v1.9.8 — 2026-10-23 — One bin button in the selection footer

- **Remove and Delete are one button.** The selection footer (music and video) had two wide red buttons, *Remove from
  library* and *Delete from disk*. They are now a single red bin. It opens the same window as the bin on an item: Cancel,
  Remove from library, or Delete from disk, with the warning that deleting cannot be undone.

## v1.9.7 — 2026-10-23 — TV filters are exact for every show

- **No more false positives.** The TV filters that look at episodes (No IMDb rating, No subtitles, Missing English
  subtitles, Multi-audio, Unknown audio language, Unknown subtitle language, No episode thumb) used to keep any show
  whose episodes had not been loaded yet. The show list now carries, for each show, how many of its episodes lack each
  of those, so a show is listed only when it really has such an episode, and the counts in the filter list are real.
  An opened show is still checked episode by episode.
- **Missing episodes are ignored.** Episodes that are not on disk no longer make a show match these filters.
- **Fixed:** *Missing English subtitles* checked the show's own subtitle list instead of each episode's.

## v1.9.6 — 2026-10-23 — TV filters work from the show list

- **All TV filters are available at once.** The More filters list on TV Shows only offered an entry such as *No IMDb
  rating* after you had opened a show down to its episodes, because the counts ignored show and season rows. The counts
  now cover shows, seasons and the episodes of opened shows, and no entry is greyed out. A show whose episodes have not
  been loaded yet counts as a match for the episode-based filters (no rating, no subtitles, and so on), because it cannot
  be ruled out until it is opened.

## v1.9.5 — 2026-10-23 — Shorter selection footer

- **Grouped buttons.** The video selection footer was three rows tall and covered the last rows of the list. The small
  actions now sit in three menus: **Metadata** (Edit, Update ratings, Artwork, Write .nfo, Rename), **Media** (Subtitles,
  Trailers, Generate thumbs, Theme songs, Split episodes) and **Organize** (Lock, Processed, Move). Scrape, Rescan, Clear,
  Remove from library and Delete from disk stay in the row, so it is one row tall.
- **Wider footer.** The selection footer (music and video) now slides over the status pane as well, all the way up to the
  Scan engine button, instead of stopping at the status pane's edge.

## v1.9.4 — 2026-10-23 — Update ratings asks which sources to use

- **Source picker.** The right-click entry and the footer button **Update ratings** now open a window with a checkbox for
  every source: the local IMDb data, TMDB, OMDb, Trakt, Rotten Tomatoes, Metacritic, AniList and OFDb. A source that is
  not set up (no key, or not in the source list, or the IMDb data not built) is greyed out and says why. Only the ticked
  sources are asked; scores from sources you leave out are kept as they are. The choice is remembered in this browser,
  and the button is off until at least one source is ticked.
- It works for one item (updated on the spot), for a selection (one background job) and from the footer. The job log says
  which sources it used.
- Tests: `tests/test_imdb_data.py` (`RatingSourcePickerTests`); the older menu tests now describe the window.

## v1.9.3 — 2026-10-23 — An empty answer from Trakt is not an error

- **Trakt answered 204 (no content).** For a show it has no ratings for, Trakt replies with an empty body, which the
  client reported as *sent something that is not JSON*. An empty answer (HTTP 204, or a 200 with nothing in it) now means
  the source has nothing for that title. A real web page or broken reply is still an error, with its status and type.
- Tests: `tests/test_http_empty_answer.py`.

## v1.9.2 — 2026-10-23 — A two-disc movie lists both files and loses the title "CD2"

- **Both discs in the Filepath.** A movie stacked from several files (CD1 and CD2) showed only the first file under
  *Filepath*. It now lists every part, one path per line.
- **Title "CD2" is replaced.** A multi-disc movie that kept a disc folder's name as its title (from an old scan, or an
  .nfo written from that folder) kept it on every rescan, because the scan treated an unchanged movie as finished and
  carried the stored title over. A scan now never keeps a title that is only a disc name (CD1, Disc 2, Part 3…), uses the
  movie's name from its folder, and re-reads a stored movie that has such a title or lists different files than the
  folder holds, even in an incremental scan.
- Tests: `tests/test_part_folder_movies.py`.

## v1.9.1 — 2026-10-23 — Episode ratings no longer fail on Trakt, and one failing source no longer loses the rest

- **Episode ratings used the wrong id.** For an episode, Update ratings asked Trakt (and OMDb) with the episode's own
  IMDb id where they expect the show's id, so Trakt answered with a web page and every episode failed with *api.trakt.tv
  sent something that is not JSON*. It now uses the show's ids plus the season and episode number, and no longer stores
  the show's Trakt id on the episode.
- **A failing source no longer fails the item.** If TMDB, OMDb or Trakt gives an error, the scores from the other
  sources (and the local IMDb data) are still saved, and the job log adds a line saying which source was not used. An
  item fails only when no source returned anything.
- **Clearer error.** The *not JSON* message now says the HTTP status, the content type and the path, so a real outage or
  a block is easy to tell apart.
- Tests: `tests/test_imdb_data.py` (`TraktRatingsTests`).

## v1.9.0 — 2026-10-23 — The format badge on an album cover is readable

- **Cover badge contrast.** The format badge on the album cover (for example *FLAC 16/44.1*) had no background of its
  own, so it was hard to read on light covers. It now has a dark background with light text. The gold Hi-Res badge is
  unchanged.
- Tests: `tests/test_nfo_pill_clear.py`.

## v1.8.9 — 2026-10-23 — A movie in CD1 and CD2 folders is one movie again

- **Multi-disc movies in CD folders.** A movie whose parts sat in a CD1 folder (or whose rows were filed under `Cd1`
  and `Cd2`) showed up as *Cd1* and *Cd2*, and rescanning those rows did nothing: a rescan only looked inside the CD1
  folder, where the other part is not visible, and named the movie after that folder. A movie is now always filed under
  its release folder (the folder above CD1), named after it, with every part together, whether the parts are in one CD
  folder or in CD1 and CD2 folders (a lone disc folder stays as it is). Rescanning a row filed under a CD folder starts from the release
  folder, so the old *Cd1* and *Cd2* rows are replaced by one movie. A CD folder directly in the library root is left as
  it is.
- Tests: `tests/test_part_folder_movies.py`.

## v1.8.8 — 2026-10-23 — The upgrade window scrolls instead of overlapping

- **Upgrade available window.** When the comparison was taller than the window, its last rows (Audio, and so on) were
  drawn over the *Purge the old files…* option. The comparison now keeps its full height and the window scrolls.
- Writing an .nfo while a scan runs: the write itself was never blocked (the *written* message appears at once); the
  wait was the library reload that followed it, which v1.8.7 moved to the background.
- Tests: `tests/test_nfo_pill_clear.py`.

## v1.8.7 — 2026-10-23 — Every album gets its audio columns, and the purple NFO pill clears when the file is written

- **Audio columns for every album.** Only the oldest album of each artist showed Format, Quality, Bits, Sample rate and
  Bitrate. The list fills missing values as it loads, but it stopped after 2,500 albums per load and went through the
  library oldest album first, so each artist's first album was filled and the rest waited for the next load. It now fills
  every album it is about to show in one pass (the result is saved, so it happens once). The start-up fill also no
  longer sits behind the check for a rehome left running from the previous start.
- **Purple NFO pill clears right after a write.** Pressing **Write .nfo** in the NFO changes window of an album that is
  not the open one waited for a full library reload before it cleared the pill, and a reload can take minutes while a
  scan runs, so the pill stayed and the button kept spinning even though the file was already written. The pill is now
  cleared from the answer of the write itself, before anything slow, and the library reloads in the background. The
  artist .nfo window works the same way.
- Tests: `tests/test_nfo_pill_clear.py`.

## v1.8.6 — 2026-10-23 — Update ratings in the batch footer, the IMDb options are easy to find, and two layout fixes

- **Update ratings in the batch footer.** With movies ticked, or shows and episodes ticked, the footer has an **Update
  ratings (n)** button next to Edit. It always runs as a job (Jobs panel: *Movie ratings*, *TV ratings*, *Episode
  ratings*), even for one item, with the same local-IMDb-first rules as the right-click entry. Sets and seasons have no
  scores of their own, so they do not get it and are not counted.
- **IMDb options moved to Integrations.** The switch, the refresh interval, the user agent, Refresh now and Remove local
  copy were far down Settings, General. They are now under **Settings, Integrations, IMDb ratings from IMDb's own data
  files**. General and Schedules each show a short note with a link that jumps straight there. The interval is "refresh
  every N days", not a cron schedule, and the Schedules note says so.
- **Clear buttons no longer overlap** (Settings, Files: Video previews and Recognised text). Each cache has its own line
  with the button beside the text, in the same style as the other secondary buttons.
- **Music list no longer goes blank after a scan.** When a scan finished, the refresh could redraw the list for a scroll
  position the pane no longer had, leaving one row on screen until you scrolled. After every redraw the list now checks
  that the rows drawn are the ones at the position the pane really has and redraws them if not. It also redraws when the
  pane changes height (the scan banner going away) and when it is shown again after being hidden.
- Tests: footer button rules, the settings move and its pointers, the cache rows and the tree check in
  `tests/test_imdb_data.py`.

## v1.8.5 — 2026-10-23 — Update ratings works on several items, and uses the local IMDb data first

- **Batch Update ratings.** The right-click entry **Update ratings** was greyed out unless exactly one item was picked.
  It is now available for any number of movies, shows or episodes and shows the count: *Update ratings (12)*. Several
  items run as one background job (Jobs panel: *Movie ratings*, *TV ratings*, *Episode ratings*, with progress and Stop),
  queued behind a running scan like a scrape. When it ends it says, for example, *28 updated, 26 with the IMDb score from
  the local data, 2 skipped, 0 failed*. Locked items are skipped (not failed); items with nothing to look up are listed as
  failed with the reason. The lists and the open item reload when it finishes. One item still updates instantly.
- **Local IMDb data first.** For every update, one item or many, the IMDb score and vote count now come from the local copy
  when it has the title, and replace the one OMDb has cached. TMDB, Trakt and the Rotten Tomatoes and Metacritic page
  scrapers are still asked for their own scores. (Before, OMDb's live answer won and the copy only filled a gap; a full
  scrape still works that way.) With the switch off or the index not built, nothing changes.
- **Spares the OMDb limit.** In a batch, OMDb is skipped for an item when the local copy has its IMDb score and the item
  already has a Rotten Tomatoes or Metacritic score. Items that lack those still ask OMDb, so a first run fills them in. A
  single-item update always asks OMDb.
- Tests: batch rules (local first, OMDb spared, locked skipped, counts and summary, cancel, queue hand-off, route) and the
  menu wiring in `tests/test_imdb_data.py`; the old test that expected OMDb to win now expects the local score.

## v1.8.4 — 2026-10-23 — The audio columns of the music list fill in on their own, and the Columns menu lines up

- **Format, Quality, Bits, Sample rate and Bitrate were blank** for albums scanned before v1.8.3. They were meant to be
  filled in by a job a little after start, but that job sat behind two long catalogue jobs (original years and the
  album rehome), and a failure in either one stopped it. It now runs first, on its own, so a slow or failed job after it
  cannot hold it back.
- **The list fills blanks itself.** When the artist and album list loads (and when the library refreshes after a scan),
  any album that still has no audio values gets them right then, from the tracks already stored, and they are saved. It
  does up to 2,500 albums per load, gives up on rows another job has locked rather than making the list wait, and never
  fails the list. No rescan is needed.
- **Columns menu.** The checkboxes were different widths (the global input padding made them grow and shrink with the
  label), so they did not line up. Each is now the same 16 px box at the left of its cell, and the music menu is wider so
  names such as Release status stay on one line. The movie and TV Columns menus share the fix and are a little wider.
- Tests: the fill-while-reading rules (blank albums filled and saved, others left alone, the limit, locked rows, database
  errors, write order), the start-up order, and the menu rule, in `tests/test_album_audio.py` and
  `tests/test_music_columns.py`.

## v1.8.3 — 2026-10-23 — The music list gets a title bar, a master box and sortable, filterable columns

- **Title bar and master box.** The artist and album list now has a title bar like the movie and TV tables. The box
  in it ticks every album on screen, takes them out again, and shows a dash when only some are ticked. With a column
  filter on, it acts on the albums that are left, and ticks on albums the filter hides stay.
- **Columns** (button above the list): Status, Year, Type, Edition, Tracks, Length, **Format**, **Quality**, **Bits**,
  **Sample rate**, **Bitrate**, Match, Country, Label, Catalog no., Release status, Added, Modified, Processed, Cover, NFO
  and Path. They resize, move by dragging the name, and the choice, order, widths and sort are saved with the other
  layout choices on the server (`ui_state.json`). The pills that sat at the end of a row are now the Status column; the
  track count, edition, added date, flag and processed mark are columns too. Added, Processed and Edition still follow
  their switches under Settings, UI Elements. **Reset with Default columns** in the menu.
- **Sorting.** A click on a name sorts, a second click reverses. Albums are sorted inside each artist and the artists
  follow their best album (lowest when rising, highest when falling). Rows without a value come last either way. Quality
  sorts by the rank that decides Upgrade available (lossless before lossy, then bit depth, sample rate, bitrate). The
  *Sort by name / Latest added …* menu still works and clears a column sort when you pick from it.
- **Filtering.** The arrow beside a name lists the values with counts, with a find box. Picks in one column are "any of",
  columns together are "all of". An album with several formats is found under each (`FLAC/MP3` under both). Artists with
  no album left are hidden, and if nothing is left the list says so and offers **Clear the column filters**. *Clear
  filters* clears these too. All, None, the NEW / 100% / Partial / Unmatched buttons, keyboard moves and Export use the
  albums that are left.
- **Audio facts per album** are new stored values (`audio_format`, `audio_lossless`, `audio_bit_depth`,
  `audio_sample_rate`, `audio_bitrate` on `albums`), written by the scanner next to `quality_rank`. The weakest track gives
  the bit depth and sample rate (the same rule as the quality rank), and the bitrate is the average. Albums scanned before
  this version are filled in once, in small batches a little after start, with no rescan and no file access.
- A click on any cell of an album row opens the album, and right-click works on the whole row.
- Tests: `tests/test_album_audio.py` (summary rules, payload, backfill, scanner and schema wiring) and
  `tests/test_music_columns.py` (labels, sort, filters, master box, wiring) run the real code in node.

## v1.8.2 — 2026-10-23 — Master checkbox on TV shows and the batch footer in grid view work

- **TV list, master checkbox in the title bar.** Ticking it now checks every show on screen straight away. Before, the
  list waited until the seasons and episodes of every show had been fetched (one request each, so a minute or more
  on a big library), and the click looked like it did nothing. The next click on a single row then toggled the state
  that was already set, which is why everything except that row appeared selected, and why unticking all needed a
  click on a row first. The seasons and episodes now load in the background and the list repaints as they arrive.
  Clicking the master box again, **All**, **None**, or a single box while they load cancels the loading, and a show
  you untick in the meantime keeps its seasons and episodes unticked.
- The master box now shows a dash when only some rows are ticked, and it is ticked when every row that can be ticked
  is. Rows that cannot be ticked (missing episodes, rows still loading) no longer count, so the box could stay
  unticked after a full selection and the next click would tick again instead of clearing.
- The same immediate repaint applies to the single row boxes and to the Space key.
- **Grid view, movies, sets and TV.** Ticking a poster card did nothing: the card's wrapper swallowed the click
  before the page could see it, so no item was selected and the batch footer never slid up. Music uses a different
  handler, which is why it worked. The box now selects, the footer opens and shows the buttons for the selection.
  A click on the empty margin around the box still does not open the item.
- A ticked box no longer flips back to unticked a moment after the click.
- Tests: `tests/test_master_checkbox.py` runs the real selection code in node (checks first, children later,
  cancel, unticking while loading, header state) and guards the grid checkbox wrapper.

## v1.8.1 — 2026-10-23 — The user agent sent to IMDb can be changed

- **Settings, General, API credentials, IMDb data** has a new **User agent** box. It is the name that the requests to
  `datasets.imdbws.com` send. The default stays `Curator/<version> (+https://github.com/jonnypuma/curator)` and is shown
  in the box while it is empty. Type your own, for example the name an agreement or licence you hold with IMDb asks
  for, and it is sent on every request instead, both the check for new files and the downloads. **Use default**
  clears it (press **Save settings** to apply, like the time zone Reset).
- The saved name is cleaned so it is always a safe single-line header: plain printable ASCII, extra spaces folded, at
  most 200 characters. Anything else is dropped, so a pasted line break cannot add a header.
- `GET /api/v1/imdb-data` now reports both the name in use and the default.
- Asked whether **Refresh ratings** also uses the local IMDb copy: it does. On an episode it uses the copy first and
  does not ask OMDb. On a movie or show OMDb answers as before and the copy supplies the IMDb score when OMDb gave none.
  It is the only ratings button, so scrapes and that button share the same rule.

## v1.8.0 — 2026-10-23 — IMDb ratings and episode ids from IMDb's own data files (optional)

- New switch under **Settings, General, API credentials**: **Use IMDb's free datasets for ratings and episode details**.
  It is **off by default**. While it is off nothing is downloaded and no lookup uses the data. The section carries a note
  that IMDb offers these files for personal and non-commercial use only, links to IMDb's terms for the datasets and its
  licensing article, and says "Data from IMDb's non-commercial datasets, for personal use only."
- When it is on, Curator downloads three files from `datasets.imdbws.com` (ratings, episodes and basic title facts,
  about 290 MB), builds one searchable index of about 270 MB in the cache folder, and **deletes the downloaded files
  straight after**. A build takes a minute or two. It goes to a side file and replaces the old index in one step, so a
  failed or interrupted build keeps the old data. **Remove local copy** deletes the index, once the switch is off.
- Each install downloads for its own user, straight from IMDb. The request names the app, its version and the project
  in its user agent (`Curator/1.8.0 (+https://github.com/jonnypuma/curator)`). The files are never bundled in the image
  or the repository (`.gitignore` and `app/.dockerignore` now skip `*.tsv`, `*.tsv.gz`, `imdb.sqlite*`, `data` and
  `cache`), and Curator has no route that serves them. Each download is capped well above the real file size and checked
  for being complete. Nothing is fetched when there is less than 1.5 GB free in the cache folder.
- Files you put in `<data>/imdb` yourself (`title.ratings.tsv.gz`, `title.episode.tsv.gz`, `title.basics.tsv.gz`) are used
  for the build when they are newer than the refresh interval, so nothing is downloaded. Curator never changes or
  deletes them.
- **Refresh every 30 days** by default (7 to 365 in Settings). A background check runs quietly and downloads again only
  when the index is older than that, or when you press **Refresh now**. It first asks IMDb whether it has published
  anything new. After a failed update it waits a day before trying by itself. The update shows in the Jobs panel as
  *IMDb data*, and the status line in Settings shows the age, the size, what it holds and the last error.
- Scrapes use the copy only to fill gaps, so a live answer is never replaced:
  - A show scrape gives **every episode its own IMDb id and IMDb score**, with no web request. Before, an episode only
    got an IMDb score from OMDb in an episode-only scrape, one request each.
  - **Refresh ratings** on one episode uses the copy first and does not ask OMDb when the copy has the episode.
  - For movies and shows the copy is the last source. It supplies the IMDb score when OMDb gave none (no key, the daily
    limit, or an unknown title), and the title, original title, year, runtime and genres that no other source had.
    OMDb is still asked as before.
- README: new section **Where ratings come from**, with the IMDb data files and their limits.
- The settings keys are `imdb_data` and `imdb_refresh_days` under the video settings. New routes `GET`, `DELETE`
  `/api/v1/imdb-data` and `POST /api/v1/imdb-data/refresh`.

## v1.7.7 — 2026-10-23 — The Update yt-dlp button stands out, and About links to the project

- **Update yt-dlp** in the About window is now the filled accent-colour button used for main actions, a little larger,
  instead of the outlined one that blended into the table. While GitHub lists a newer yt-dlp release, the button also
  gets a soft ring around it, next to the "… is available" line. The ring goes away when the check says you are current,
  or after an update.
- About has a new **Project** row, right under Version, linking to <https://github.com/jonnypuma/curator>. It opens in
  a new tab. Links in that window now use the accent colour.

## v1.7.6 — 2026-10-22 — The README uses example addresses and names

- The README no longer shows one person's network. The Kodi path mapping section now uses example NFS addresses
  (`192.168.1.20`, `192.168.1.21` and `192.168.1.22`) and example mount names (`/media`, `/nas1/Media`, `/nas2/Media`
  and `/nas2/Media2`) in place of real hosts and NAS model names. The `CMM_ALLOWED_ORIGINS` example is now
  `http://192.168.1.50:4455`.
- Only the text changed. Nothing in the app behaves differently.

## v1.7.5 — 2026-10-22 — A Reset button for the schedule time zone

- **Settings, General, Time zone** has a **Reset** button beside the zone box. It clears the box so the schedules go
  back to the server's own zone, which is `CMM_TIMEZONE` and then `TZ` from docker-compose. The button's tooltip and
  the text under the box name that zone (for example Europe/Oslo).
- Reset only empties the box and says so in the status line. Press **Save settings** to apply it, the same as every
  other setting on the page. It does not save by itself.
- The button is greyed out while the box is empty, because there is nothing saved to reset, and it comes back as soon
  as a zone is typed or saved. Clearing the box by hand does the same thing as pressing it.
- Reset clears the saved zone rather than copying the server's name into the box, so a later change to `TZ` in
  docker-compose is still followed.

## v1.7.4 — 2026-10-22 — The schedule time zone can be set in Settings

- **Settings, General** has a new **Time zone** section with **Schedule time zone**. Type a zone name such as
  `Europe/Oslo` (the box suggests names as you type) and save. It is the clock that scheduled scans, library cleans
  and backups run by, and the time in backup file names. The "Times use …" line under each schedule shows the zone in
  use.
- Before this, the zone could only be set with `CMM_TIMEZONE` or `TZ` in docker-compose, and a change needed a restart.
  The order is now: the zone saved in Settings, then `CMM_TIMEZONE`, then `TZ`, then the system clock. Leave the box
  empty to keep following the server. The box shows the server's own zone as its placeholder, and the text under it
  names it.
- The saved zone takes effect at once. The schedules look it up every minute and remember it until settings.json
  changes, so there is no restart and no extra disk read on each tick.
- A name that is not a zone is refused when you save, with a message that gives an example. A bad name in the file
  itself is ignored, so it cannot stop the schedules.
- It is one zone for the whole server. It does not follow the browser or the person who set it, and a schedule keeps
  firing at the same clock time wherever you are. The container's own `TZ` still sets the logs and the database.
  Daylight saving changes are handled as before.

## v1.7.3 — 2026-10-22 — Media info files can be switched on and off in Settings, for movies and TV separately

- **Settings, Movies** has a new box under Writing: **Write a .cmm_mediainfo.xml media info file beside each movie**.
  **Settings, TV** has a new **Media info files** section with **Write a .cmm_mediainfo.xml media info file beside
  each episode**. Both are on by default. The file holds what the probe found, so a moved or renamed folder is not
  probed again.
- Until now this could only be switched off for everything at once, with the environment variable
  `CMM_WRITE_SIDECARS=0`, and a change needed a container restart. The boxes apply to the next file that is written,
  with no restart, and movies and TV are independent: you can keep the files for movies and stop them for TV, or the
  other way round.
- `CMM_WRITE_SIDECARS` still works as the starting value: with it set to `0`, both boxes start off until you save
  Settings, after which the boxes decide. It is read when Settings are loaded, so it is no longer fixed at startup.
- Turning a box off does not delete files that already exist. They stay, are still used to skip a probe, and still show
  in the Files section. A file is only left alone, never rewritten, while its box is off.
- This covers the media info file only. Writing `.nfo` files and artwork keeps its own boxes under Writing.

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
