-- Resonance library schema. Applied on every startup; statements are idempotent.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$ BEGIN
    CREATE TYPE release_type AS ENUM ('album', 'single', 'ep', 'compilation', 'live', 'unknown');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE asset_status AS ENUM ('NEW', 'PROCESSED', 'IGNORED');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS artists (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    musicbrainz_artist_id UUID,
    type VARCHAR(50) DEFAULT 'Group',
    biography TEXT,
    genres TEXT[] DEFAULT ARRAY[]::TEXT[],
    status asset_status DEFAULT 'NEW',
    path TEXT NOT NULL UNIQUE,
    has_nfo BOOLEAN DEFAULT FALSE,
    has_artwork BOOLEAN DEFAULT FALSE,
    artwork_width INT,
    artwork_height INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS albums (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    musicbrainz_release_group_id UUID,
    musicbrainz_release_id UUID,
    release_year INT,
    total_discs INT DEFAULT 1,
    total_tracks INT DEFAULT 0,
    duration_seconds INT DEFAULT 0,
    type release_type DEFAULT 'album',
    edition VARCHAR(100),
    review TEXT,
    status asset_status DEFAULT 'NEW',
    path TEXT NOT NULL UNIQUE,
    has_nfo BOOLEAN DEFAULT FALSE,
    has_artwork BOOLEAN DEFAULT FALSE,
    artwork_width INT,
    artwork_height INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tracks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    album_id UUID REFERENCES albums(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    musicbrainz_track_id UUID,
    musicbrainz_release_group_id UUID,
    disc_number INT DEFAULT 1,
    track_number INT NOT NULL,
    duration_seconds INT DEFAULT 0,
    file_format VARCHAR(10) NOT NULL,
    sample_rate INT,
    bit_depth INT,
    file_path TEXT NOT NULL UNIQUE,
    tag_completeness_percent INT DEFAULT 0,
    lyrics_type VARCHAR(10) DEFAULT 'none',
    tags JSONB DEFAULT '{}'::jsonb,
    artist_name VARCHAR(255),
    album_name VARCHAR(255),
    genre VARCHAR(255),
    year INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_disc_track UNIQUE (album_id, disc_number, track_number) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS artwork_pool (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    album_id UUID REFERENCES albums(id) ON DELETE CASCADE,
    artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
    asset_type VARCHAR(50) NOT NULL,
    source_url TEXT NOT NULL,
    local_path TEXT,
    resolution VARCHAR(20),
    file_size_bytes BIGINT,
    is_selected BOOLEAN DEFAULT FALSE,
    source_provider VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT artwork_subject CHECK (album_id IS NOT NULL OR artist_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS scan_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    message TEXT,
    processed INT DEFAULT 0,
    total INT DEFAULT 0,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);

ALTER TABLE artists ADD COLUMN IF NOT EXISTS has_nfo BOOLEAN DEFAULT FALSE;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS nfo_digest TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS has_artwork BOOLEAN DEFAULT FALSE;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS artwork_width INT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS artwork_height INT;

ALTER TABLE albums ADD COLUMN IF NOT EXISTS has_nfo BOOLEAN DEFAULT FALSE;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS nfo_digest TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS has_artwork BOOLEAN DEFAULT FALSE;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS artwork_width INT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS artwork_height INT;

ALTER TABLE tracks ADD COLUMN IF NOT EXISTS musicbrainz_release_group_id UUID;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '{}'::jsonb;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS artist_name VARCHAR(255);
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS album_name VARCHAR(255);
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS genre VARCHAR(255);
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS year INT;

CREATE INDEX IF NOT EXISTS idx_albums_release_id ON albums(musicbrainz_release_id);
ALTER TABLE albums DROP CONSTRAINT IF EXISTS albums_musicbrainz_release_id_key;
DROP INDEX IF EXISTS albums_musicbrainz_release_id_key;
CREATE INDEX IF NOT EXISTS idx_artists_status ON artists(status);
CREATE INDEX IF NOT EXISTS idx_artists_name ON artists(lower(name));
CREATE INDEX IF NOT EXISTS idx_albums_status ON albums(status);
CREATE INDEX IF NOT EXISTS idx_albums_artist ON albums(artist_id);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album_id) INCLUDE (disc_number, track_number);
CREATE INDEX IF NOT EXISTS idx_artwork_album ON artwork_pool(album_id);
CREATE INDEX IF NOT EXISTS idx_artwork_artist ON artwork_pool(artist_id);

ALTER TABLE tracks ADD COLUMN IF NOT EXISTS bitrate INT;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS inode BIGINT;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS mtime_ns BIGINT;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS file_size BIGINT;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS acoustid_score INT;

ALTER TABLE albums ADD COLUMN IF NOT EXISTS match_tier VARCHAR(20) DEFAULT 'unmatched';
ALTER TABLE albums ADD COLUMN IF NOT EXISTS match_ratio INT DEFAULT 0;

ALTER TABLE artists ADD COLUMN IF NOT EXISTS formed TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS origin TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS years_active TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS website TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS sortname TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS gender TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS disambiguation TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS style TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS mood TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS instruments TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS died TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS disbanded TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS discogs_url TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS wikipedia_url TEXT;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS name_custom BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS biography_checked_at TIMESTAMP;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS metadata_checked_at TIMESTAMP;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS biography_custom BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS genres_custom BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS genres_from_tags BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS type_custom BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS folder_aliases TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE albums ADD COLUMN IF NOT EXISTS review_checked_at TIMESTAMP;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS title_custom BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE scan_jobs ADD COLUMN IF NOT EXISTS phase TEXT;
ALTER TABLE scan_jobs ADD COLUMN IF NOT EXISTS mode TEXT;
ALTER TABLE scan_jobs ADD COLUMN IF NOT EXISTS log TEXT;
ALTER TABLE scan_jobs ADD COLUMN IF NOT EXISTS result JSONB;

CREATE TABLE IF NOT EXISTS batch_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    message TEXT,
    processed INT DEFAULT 0,
    total INT DEFAULT 0,
    log TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);

ALTER TABLE batch_jobs ADD COLUMN IF NOT EXISTS rolled_back BOOLEAN DEFAULT FALSE;

ALTER TABLE tracks ADD COLUMN IF NOT EXISTS audio_flag VARCHAR(20);

ALTER TABLE albums ADD COLUMN IF NOT EXISTS mood TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS style TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS theme TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS allmusic_url TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS allmusic_rating NUMERIC(3,1);
ALTER TABLE albums ADD COLUMN IF NOT EXISTS allmusic_user_rating NUMERIC(3,1);
ALTER TABLE albums ADD COLUMN IF NOT EXISTS allmusic_votes INT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS label TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS boxset BOOLEAN DEFAULT FALSE;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS path_role VARCHAR(20) DEFAULT 'library';
ALTER TABLE albums ADD COLUMN IF NOT EXISTS quality_rank BIGINT DEFAULT 0;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS upgrade_source_id UUID REFERENCES albums(id) ON DELETE SET NULL;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS duplicate_release BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS original_year INT;

CREATE TABLE IF NOT EXISTS loaded_matches (
    album_id UUID PRIMARY KEY REFERENCES albums(id) ON DELETE CASCADE,
    proposal JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS artwork_undo (
    subject_kind VARCHAR(12) NOT NULL,
    subject_id UUID NOT NULL,
    asset_type VARCHAR(40) NOT NULL,
    target_path TEXT NOT NULL,
    cache_path TEXT NOT NULL,
    previous_art_id UUID,
    next_art_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (subject_kind, subject_id)
);
CREATE TABLE IF NOT EXISTS video_art_extra (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind VARCHAR(12) NOT NULL,
    item_id UUID NOT NULL,
    art_kind VARCHAR(40) NOT NULL,
    path TEXT NOT NULL,
    origin VARCHAR(12) NOT NULL,
    width INT,
    height INT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS video_art_extra_item ON video_art_extra (kind, item_id, art_kind);
ALTER TABLE albums ADD COLUMN IF NOT EXISTS cue_image BOOLEAN DEFAULT FALSE;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS gap_present INT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS gap_expected INT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS country VARCHAR(8);
ALTER TABLE albums ADD COLUMN IF NOT EXISTS catalog TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS barcode TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS release_status TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS release_group VARCHAR(40);
ALTER TABLE albums ADD COLUMN IF NOT EXISTS genres TEXT[];

ALTER TABLE tracks ADD COLUMN IF NOT EXISTS fingerprint_hash TEXT;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS acoustid_recording_id UUID;

ALTER TABLE artists ADD COLUMN IF NOT EXISTS discography JSONB;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS discography_fetched_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS expected_tracks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    album_id UUID REFERENCES albums(id) ON DELETE CASCADE,
    disc_number INT DEFAULT 1,
    track_number INT NOT NULL,
    title TEXT,
    recording_id UUID,
    duration_seconds INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dismissed_duplicates (
    track_a UUID NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    track_b UUID NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    PRIMARY KEY (track_a, track_b)
);

CREATE TABLE IF NOT EXISTS dismissed_album_duplicates (
    album_a UUID NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    album_b UUID NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    PRIMARY KEY (album_a, album_b),
    CHECK (album_a <> album_b)
);

CREATE TABLE IF NOT EXISTS tag_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id UUID REFERENCES batch_jobs(id) ON DELETE CASCADE,
    track_id UUID,
    file_path TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    inode BIGINT,
    mtime_ns BIGINT,
    file_size BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_moves (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id UUID REFERENCES batch_jobs(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    dest_path TEXT NOT NULL,
    inode BIGINT,
    mtime_ns BIGINT,
    file_size BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS work_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'idle',
    message TEXT,
    processed INT DEFAULT 0,
    total INT DEFAULT 0,
    log TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);

-- Subtitles the user confirmed as in sync (Sync OK in the sync window). The mark only counts while
-- the file still has the modification time it had then.
CREATE TABLE IF NOT EXISTS subtitle_sync_marks (
    path TEXT PRIMARY KEY,
    mtime DOUBLE PRECISION NOT NULL,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

UPDATE artwork_pool SET asset_type = 'discart' WHERE asset_type = 'cdart';
UPDATE artwork_pool SET asset_type = 'fanart' WHERE asset_type = 'backdrop';
UPDATE artwork_pool SET asset_type = 'tray' WHERE asset_type = 'sleeve';

-- Curator video library: movies, movie sets, TV shows, seasons and episodes.
-- One video_files row per file on disk holds the probe results (ffprobe, MediaInfo, dovi_tool).

CREATE TABLE IF NOT EXISTS video_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path TEXT NOT NULL UNIQUE,
    media_kind VARCHAR(10) NOT NULL,
    size_bytes BIGINT,
    mtime DOUBLE PRECISION,
    probed_at TIMESTAMP,
    probe_error TEXT,
    container VARCHAR(40),
    duration_seconds INT,
    bitrate_mbps NUMERIC(9, 2),
    video_bitrate_mbps NUMERIC(9, 2),
    video_codec VARCHAR(20),
    video_profile VARCHAR(40),
    width INT,
    height INT,
    resolution VARCHAR(10),
    fps NUMERIC(8, 3),
    aspect_ratio VARCHAR(10),
    bit_depth INT,
    hdr_format VARCHAR(16),
    hdr_secondary VARCHAR(16),
    is_hybrid BOOLEAN DEFAULT FALSE,
    dovi_profile VARCHAR(8),
    dovi_el_type VARCHAR(4),
    dovi_bl_compat VARCHAR(4),
    max_cll VARCHAR(20),
    max_fall VARCHAR(20),
    is_3d BOOLEAN DEFAULT FALSE,
    video_source VARCHAR(20),
    source_format VARCHAR(20),
    edition VARCHAR(80),
    chapters INT DEFAULT 0,
    audio_tracks JSONB NOT NULL DEFAULT '[]'::jsonb,
    subtitle_tracks JSONB NOT NULL DEFAULT '[]'::jsonb,
    external_subtitles JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movie_sets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    tmdb_collection_id TEXT,
    overview TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path TEXT NOT NULL UNIQUE,
    root TEXT NOT NULL,
    folder TEXT NOT NULL,
    file_id UUID REFERENCES video_files(id) ON DELETE SET NULL,
    parts TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    disc_format VARCHAR(10),
    title TEXT NOT NULL,
    original_title TEXT,
    sort_title TEXT,
    year INT,
    edition TEXT,
    tagline TEXT,
    outline TEXT,
    plot TEXT,
    runtime_minutes INT,
    mpaa TEXT,
    premiered TEXT,
    genres TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    countries TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    studios TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    directors TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    writers TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    actors JSONB NOT NULL DEFAULT '[]'::jsonb,
    ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    imdb_id TEXT,
    tmdb_id TEXT,
    ratings JSONB NOT NULL DEFAULT '{}'::jsonb,
    rating NUMERIC(4, 2),
    votes INT,
    top250 INT,
    set_id UUID REFERENCES movie_sets(id) ON DELETE SET NULL,
    trailer TEXT,
    playcount INT DEFAULT 0,
    last_played TEXT,
    date_added TEXT,
    nfo_path TEXT,
    nfo_mtime DOUBLE PRECISION,
    artwork JSONB NOT NULL DEFAULT '{}'::jsonb,
    status asset_status DEFAULT 'NEW',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS movies_root_idx ON movies (root);
CREATE INDEX IF NOT EXISTS movies_set_idx ON movies (set_id);

CREATE TABLE IF NOT EXISTS tv_shows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path TEXT NOT NULL UNIQUE,
    root TEXT NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT,
    sort_title TEXT,
    year INT,
    plot TEXT,
    outline TEXT,
    show_status TEXT,
    premiered TEXT,
    mpaa TEXT,
    runtime_minutes INT,
    genres TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    studios TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    actors JSONB NOT NULL DEFAULT '[]'::jsonb,
    ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    imdb_id TEXT,
    tmdb_id TEXT,
    tvdb_id TEXT,
    ratings JSONB NOT NULL DEFAULT '{}'::jsonb,
    rating NUMERIC(4, 2),
    votes INT,
    season_names JSONB NOT NULL DEFAULT '{}'::jsonb,
    nfo_path TEXT,
    nfo_mtime DOUBLE PRECISION,
    artwork JSONB NOT NULL DEFAULT '{}'::jsonb,
    status asset_status DEFAULT 'NEW',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS tv_shows_root_idx ON tv_shows (root);

CREATE TABLE IF NOT EXISTS tv_seasons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    show_id UUID NOT NULL REFERENCES tv_shows(id) ON DELETE CASCADE,
    season_number INT NOT NULL,
    path TEXT,
    title TEXT,
    artwork JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (show_id, season_number)
);

CREATE TABLE IF NOT EXISTS tv_episodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    show_id UUID NOT NULL REFERENCES tv_shows(id) ON DELETE CASCADE,
    season_id UUID NOT NULL REFERENCES tv_seasons(id) ON DELETE CASCADE,
    season_number INT NOT NULL,
    episode_number INT NOT NULL,
    path TEXT NOT NULL,
    file_id UUID REFERENCES video_files(id) ON DELETE SET NULL,
    title TEXT,
    plot TEXT,
    aired TEXT,
    runtime_minutes INT,
    directors TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    writers TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    ratings JSONB NOT NULL DEFAULT '{}'::jsonb,
    rating NUMERIC(4, 2),
    playcount INT DEFAULT 0,
    nfo_path TEXT,
    nfo_mtime DOUBLE PRECISION,
    artwork JSONB NOT NULL DEFAULT '{}'::jsonb,
    status asset_status DEFAULT 'NEW',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (show_id, season_number, episode_number)
);

CREATE INDEX IF NOT EXISTS tv_episodes_season_idx ON tv_episodes (season_id);
CREATE INDEX IF NOT EXISTS tv_episodes_path_idx ON tv_episodes (path);

-- Phase 3: scraping, locks and inline edits.
ALTER TABLE movies ADD COLUMN IF NOT EXISTS pending_match JSONB;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS pending_match JSONB;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS locked_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE movies ADD COLUMN IF NOT EXISTS languages TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE movies ADD COLUMN IF NOT EXISTS original_language TEXT;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS scrape_language TEXT;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS preferred_source TEXT;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS preferred_art TEXT;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS producers TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE movies ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMP;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS scrape_source TEXT;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS scrape_error TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS locked_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS tagline TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS countries TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS original_language TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS scrape_language TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS preferred_source TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS preferred_art TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS episode_order TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS trailer TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMP;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS scrape_source TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS scrape_error TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS directors TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS tmdb_episode_count INT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS tmdb_episode_numbers INT[] NOT NULL DEFAULT ARRAY[]::INT[];
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS plot TEXT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS premiered TEXT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS trailer TEXT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS locked_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS preferred_source TEXT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS preferred_art TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS locked_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS scrape_language TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS preferred_source TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS preferred_art TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS votes INT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS guest_stars JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMP;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS scrape_error TEXT;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS artwork JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS folder TEXT;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS nfo_path TEXT;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMP;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS scrape_error TEXT;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS parts_synced_at TIMESTAMP;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS status asset_status;
UPDATE movie_sets s SET status = CASE
    WHEN EXISTS (SELECT 1 FROM movies m WHERE m.set_id = s.id AND m.status = 'NEW') THEN 'NEW'::asset_status
    ELSE 'PROCESSED'::asset_status
END
WHERE s.status IS NULL;
ALTER TABLE movie_sets ALTER COLUMN status SET DEFAULT 'NEW';
UPDATE movie_sets SET status = 'NEW' WHERE status IS NULL;

CREATE TABLE IF NOT EXISTS movie_set_parts (
    set_id UUID NOT NULL REFERENCES movie_sets(id) ON DELETE CASCADE,
    tmdb_id TEXT NOT NULL,
    title TEXT NOT NULL,
    year INT,
    release_date TEXT,
    overview TEXT,
    poster TEXT,
    PRIMARY KEY (set_id, tmdb_id)
);

-- Webhook queue. One row per folder waiting for the debounce timer; it survives restarts.
CREATE TABLE IF NOT EXISTS ingest_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key TEXT NOT NULL UNIQUE,
    media VARCHAR(10) NOT NULL,
    source VARCHAR(20) NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL,
    files TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    removed BOOLEAN NOT NULL DEFAULT FALSE,
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    events INT NOT NULL DEFAULT 1,
    status VARCHAR(12) NOT NULL DEFAULT 'queued',
    first_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    last_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    started_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingest_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    received_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    source VARCHAR(20) NOT NULL,
    event_type TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    outcome VARCHAR(20) NOT NULL,
    message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ingest_events_received ON ingest_events (received_at DESC);

-- Library scans and ARR / Kodi work. A row left running is put back to waiting on startup.
CREATE TABLE IF NOT EXISTS work_queue (
    id UUID PRIMARY KEY,
    lane VARCHAR(8) NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    source VARCHAR(20) NOT NULL DEFAULT '',
    priority INT NOT NULL DEFAULT 10,
    status VARCHAR(12) NOT NULL DEFAULT 'queued',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    started_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_work_queue_pick ON work_queue (lane, status, priority, created_at);
ALTER TABLE work_queue ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;
ALTER TABLE ingest_queue ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS work_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lane VARCHAR(8) NOT NULL,
    received_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    source VARCHAR(20) NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    outcome VARCHAR(20) NOT NULL,
    message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_work_events_lane ON work_events (lane, received_at DESC);

CREATE TABLE IF NOT EXISTS video_scrape_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    media VARCHAR(10) NOT NULL,
    scope TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    message TEXT,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS video_scan_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    media VARCHAR(10) NOT NULL,
    mode VARCHAR(20) NOT NULL,
    roots TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    status VARCHAR(20) NOT NULL,
    message TEXT,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

-- Phase 7: Trakt watched sync, tag manager, analytics.
ALTER TABLE movies ADD COLUMN IF NOT EXISTS duplicate_release BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS upgrade_source_id UUID REFERENCES movies(id) ON DELETE SET NULL;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS duplicate_release BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS upgrade_source_id UUID REFERENCES tv_episodes(id) ON DELETE SET NULL;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS upgrade_copy_path TEXT;
CREATE TABLE IF NOT EXISTS video_dismissed_duplicates (
    kind TEXT NOT NULL,
    left_id UUID NOT NULL,
    right_id UUID NOT NULL,
    PRIMARY KEY (kind, left_id, right_id)
);

CREATE TABLE IF NOT EXISTS episode_copies (
    episode_id UUID NOT NULL REFERENCES tv_episodes(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    file_id UUID REFERENCES video_files(id) ON DELETE SET NULL,
    PRIMARY KEY (episode_id, path)
);

ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS last_played TEXT;
ALTER TABLE video_files ALTER COLUMN video_source TYPE VARCHAR(40);
ALTER TABLE video_files ALTER COLUMN source_format TYPE VARCHAR(40);
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS stereo_mode VARCHAR(12);
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS release_group VARCHAR(40);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS certifications JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS certifications JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS mpaa TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS certifications JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE artists ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS status asset_status DEFAULT 'NEW';
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS year INT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS nfo_path TEXT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS nfo_mtime DOUBLE PRECISION;

ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_imdb NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_tmdb NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_rt NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_rt_audience NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_metacritic NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_metacritic_user NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_trakt NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_anilist NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_ofdb NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS rating_tvdb NUMERIC(6, 2);
ALTER TABLE movies ADD COLUMN IF NOT EXISTS anilist_id TEXT;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS ofdb_id TEXT;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS trakt_id TEXT;

ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_imdb NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_tmdb NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_rt NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_rt_audience NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_metacritic NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_metacritic_user NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_trakt NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_anilist NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_ofdb NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS rating_tvdb NUMERIC(6, 2);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS anilist_id TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS ofdb_id TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS trakt_id TEXT;

ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_imdb NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_tmdb NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_rt NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_rt_audience NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_metacritic NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_metacritic_user NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_trakt NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_anilist NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_ofdb NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS rating_tvdb NUMERIC(6, 2);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS anilist_id TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS ofdb_id TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS trakt_id TEXT;

DO $$
DECLARE
    item text;
BEGIN
    FOREACH item IN ARRAY ARRAY['movies', 'tv_shows', 'tv_episodes']
    LOOP
        EXECUTE format($sql$
            UPDATE %I SET
                rating_imdb = CASE WHEN ratings #>> '{imdb,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{imdb,value}')::numeric ELSE rating_imdb END,
                rating_tmdb = CASE WHEN ratings #>> '{themoviedb,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{themoviedb,value}')::numeric ELSE rating_tmdb END,
                rating_rt = CASE WHEN ratings #>> '{tomatometerallcritics,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{tomatometerallcritics,value}')::numeric ELSE rating_rt END,
                rating_rt_audience = CASE WHEN ratings #>> '{tomatometeravguseraudience,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{tomatometeravguseraudience,value}')::numeric ELSE rating_rt_audience END,
                rating_metacritic = CASE WHEN ratings #>> '{metacritic,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{metacritic,value}')::numeric ELSE rating_metacritic END,
                rating_metacritic_user = CASE WHEN ratings #>> '{metacriticuser,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{metacriticuser,value}')::numeric ELSE rating_metacritic_user END,
                rating_trakt = CASE WHEN ratings #>> '{trakt,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{trakt,value}')::numeric ELSE rating_trakt END,
                rating_anilist = CASE WHEN ratings #>> '{anilist,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{anilist,value}')::numeric ELSE rating_anilist END,
                rating_ofdb = CASE WHEN ratings #>> '{ofdb,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{ofdb,value}')::numeric ELSE rating_ofdb END,
                rating_tvdb = CASE WHEN ratings #>> '{tvdb,value}' ~ '^[0-9]+(\.[0-9]+)?$' THEN (ratings #>> '{tvdb,value}')::numeric ELSE rating_tvdb END,
                anilist_id = COALESCE(NULLIF(ids->>'anilist', ''), anilist_id),
                ofdb_id = COALESCE(NULLIF(ids->>'ofdb', ''), ofdb_id),
                trakt_id = COALESCE(NULLIF(ids->>'trakt', ''), trakt_id)
            WHERE ratings <> '{}'::jsonb OR ids <> '{}'::jsonb
        $sql$, item);
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS movies_tags_idx ON movies USING GIN (tags);
CREATE INDEX IF NOT EXISTS tv_shows_tags_idx ON tv_shows USING GIN (tags);

-- Episodes that share one video file. Empty for a file that holds a single episode.
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS file_span JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Parked multi-episode source left beside a lossless split, and the name it had before.
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS split_source TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS split_original TEXT;

-- A title sent to Radarr or Sonarr before any video file is on disk.
ALTER TABLE movies ADD COLUMN IF NOT EXISTS wanted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS wanted BOOLEAN NOT NULL DEFAULT FALSE;

-- An episode the season listing includes when no video file is on disk yet.
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS missing BOOLEAN NOT NULL DEFAULT FALSE;

-- Fingerprint of the database fields last written into the NFO, or first seen.
ALTER TABLE movies ADD COLUMN IF NOT EXISTS nfo_digest TEXT;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS nfo_digest TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS nfo_digest TEXT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS nfo_digest TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS nfo_digest TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS user_rating NUMERIC(4, 1);
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS display_season INT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS display_episode INT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS resume_position DOUBLE PRECISION;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS resume_total DOUBLE PRECISION;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS user_rating NUMERIC(4, 1);
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS top250 INT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS playcount INT DEFAULT 0;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS last_played TEXT;

-- Average time per scan stage, so a later scan can estimate the stages still ahead.
CREATE TABLE IF NOT EXISTS scan_phase_stats (
    media TEXT NOT NULL,
    phase TEXT NOT NULL,
    runs INT NOT NULL DEFAULT 0,
    items BIGINT NOT NULL DEFAULT 0,
    seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_items INT NOT NULL DEFAULT 0,
    last_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (media, phase)
);

ALTER TABLE movies ADD COLUMN IF NOT EXISTS english_title TEXT;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS english_title TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS english_title TEXT;
ALTER TABLE tv_episodes ADD COLUMN IF NOT EXISTS original_title TEXT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS sort_title TEXT;
ALTER TABLE tv_seasons ADD COLUMN IF NOT EXISTS ids JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS movies_file_idx ON movies (file_id);
CREATE INDEX IF NOT EXISTS tv_episodes_file_idx ON tv_episodes (file_id);
CREATE INDEX IF NOT EXISTS video_files_media_kind_idx ON video_files (media_kind);

-- A named view of one library. Movies, TV, and music each keep their own names.
-- A tag on a movie or TV filter is written into the .nfo at the end of a scan.
CREATE TABLE IF NOT EXISTS saved_filters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    media TEXT NOT NULL,
    name TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    tag TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (media, name)
);

-- Schema migration version tracker.
-- Records applied schema version and SHA256 checksum so container restarts skip re-evaluating statements.
CREATE TABLE IF NOT EXISTS schema_version (
    version INT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── 2026-10-18 ─────────────────────────────────────────────────────────────

-- BUG 3: track the real folder mtime so incremental scans use wall-clock time
-- rather than the DB updated_at timestamp (which is always "now").
ALTER TABLE movies   ADD COLUMN IF NOT EXISTS folder_mtime TIMESTAMPTZ;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS folder_mtime TIMESTAMPTZ;

-- BUG 2: explicit missing-state for movies / shows whose root is offline or
-- whose folder was removed (replaces silent pruning).
ALTER TABLE movies   ADD COLUMN IF NOT EXISTS missing_since TIMESTAMPTZ;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS missing_since TIMESTAMPTZ;

-- SPEED 9: text_pattern_ops indexes speed up LIKE 'prefix%' queries used by
-- the UI search and the scanner path-lookup helpers.
CREATE INDEX IF NOT EXISTS movies_folder_tpo   ON movies   (folder   text_pattern_ops);
CREATE INDEX IF NOT EXISTS movies_title_tpo    ON movies   (title    text_pattern_ops);
CREATE INDEX IF NOT EXISTS tv_shows_path_tpo  ON tv_shows (path     text_pattern_ops);
CREATE INDEX IF NOT EXISTS tv_shows_title_tpo  ON tv_shows (title    text_pattern_ops);
CREATE INDEX IF NOT EXISTS albums_path_tpo     ON albums   (path     text_pattern_ops);
CREATE INDEX IF NOT EXISTS artists_path_tpo    ON artists  (path     text_pattern_ops);
CREATE INDEX IF NOT EXISTS artists_name_tpo    ON artists  (name     text_pattern_ops);

-- Repair any non-array JSONB values in array-typed columns. A probe that half-failed could
-- leave None in subtitle_tracks / external_subtitles / audio_tracks, which was then stored
-- as JSON null and broke analytics' jsonb_array_length. The writer is now guarded; this
-- normalises rows written before that guard was in place. (chapters is INT, not an array.)
UPDATE video_files
   SET subtitle_tracks = '[]'::jsonb
 WHERE subtitle_tracks IS NULL OR jsonb_typeof(subtitle_tracks) IS DISTINCT FROM 'array';
UPDATE video_files
   SET external_subtitles = '[]'::jsonb
 WHERE external_subtitles IS NULL OR jsonb_typeof(external_subtitles) IS DISTINCT FROM 'array';
UPDATE video_files
   SET audio_tracks = '[]'::jsonb
 WHERE audio_tracks IS NULL OR jsonb_typeof(audio_tracks) IS DISTINCT FROM 'array';

ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE movie_sets ADD COLUMN IF NOT EXISTS locked_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE artists ADD COLUMN IF NOT EXISTS locked_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE albums ADD COLUMN IF NOT EXISTS locked_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

-- Prune safety: rows a scan left in place because removing them would have broken a limit.
ALTER TABLE albums ADD COLUMN IF NOT EXISTS prune_held BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS prune_held BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS prune_held BOOLEAN NOT NULL DEFAULT FALSE;

-- The same band in the folders of two library paths is two artist entries and both carry the
-- MusicBrainz artist id, so the id is no longer unique. Entries with different names still may not share it.
ALTER TABLE artists DROP CONSTRAINT IF EXISTS artists_musicbrainz_artist_id_key;
CREATE INDEX IF NOT EXISTS artists_musicbrainz_artist_id_idx ON artists (musicbrainz_artist_id);

-- Whether a trailer and a theme song file is on disk next to a movie or show, so the library list can filter on it
-- without looking at the disk for every row. NULL means not checked yet, or the folder could not be reached.
ALTER TABLE movies ADD COLUMN IF NOT EXISTS has_local_trailer BOOLEAN;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS has_local_theme BOOLEAN;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS has_local_trailer BOOLEAN;
ALTER TABLE tv_shows ADD COLUMN IF NOT EXISTS has_local_theme BOOLEAN;

-- What the library list shows for an album: the formats on disk, the bit depth and sample rate of the weakest
-- track, the mean bitrate and whether every track is lossless. The scanner keeps them next to quality_rank. NULL
-- means not worked out yet; albums scanned before these columns existed are filled in after start.
ALTER TABLE albums ADD COLUMN IF NOT EXISTS audio_format TEXT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS audio_lossless BOOLEAN;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS audio_bit_depth INT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS audio_sample_rate INT;
ALTER TABLE albums ADD COLUMN IF NOT EXISTS audio_bitrate INT;

-- Quality badges for library queue history rows: resolution, codecs and HDR for video, format and bit depth for music.
ALTER TABLE work_events ADD COLUMN IF NOT EXISTS quality JSONB NOT NULL DEFAULT '[]'::jsonb;

-- The file size when the default audio and subtitle tracks were last set by hand. The automatic switch to the
-- original language leaves the file alone while its size still matches, so a replaced file is handled again.
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS user_default_size BIGINT;

-- The recycle bin: files and folders deleted from disk wait in .curator-trash inside their library folder.
CREATE TABLE IF NOT EXISTS trash_items (
    id UUID PRIMARY KEY,
    original_path TEXT NOT NULL,
    trash_path TEXT NOT NULL,
    root TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    kind VARCHAR(20) NOT NULL DEFAULT '',
    is_dir BOOLEAN NOT NULL DEFAULT FALSE,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    deleted_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trash_items_deleted ON trash_items (deleted_at);

-- Video integrity check (ffmpeg decode): the result and the file size and mtime it was taken for.
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS integrity VARCHAR(10);
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS integrity_errors JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS integrity_mode VARCHAR(8);
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS integrity_checked_at TIMESTAMP;
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS integrity_size BIGINT;
ALTER TABLE video_files ADD COLUMN IF NOT EXISTS integrity_mtime DOUBLE PRECISION;

-- A saved movie or TV filter can also be written as a Kodi smart playlist.
ALTER TABLE saved_filters ADD COLUMN IF NOT EXISTS playlist BOOLEAN NOT NULL DEFAULT FALSE;

-- Disk space per library folder, one row per day, for the growth chart in the disk space dashboard.
CREATE TABLE IF NOT EXISTS disk_usage_history (
    day DATE NOT NULL,
    root TEXT NOT NULL,
    kind VARCHAR(20) NOT NULL DEFAULT '',
    total_bytes BIGINT NOT NULL DEFAULT 0,
    free_bytes BIGINT NOT NULL DEFAULT 0,
    library_bytes BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (day, root)
);

-- Resume points for movies, kept in sync with the players (episodes already have these columns).
ALTER TABLE movies ADD COLUMN IF NOT EXISTS resume_position DOUBLE PRECISION;
ALTER TABLE movies ADD COLUMN IF NOT EXISTS resume_total DOUBLE PRECISION;

-- Collections Curator made (or took over) in Jellyfin, Emby or Plex, so it only ever changes those.
CREATE TABLE IF NOT EXISTS player_collections (
    player VARCHAR(10) NOT NULL,
    name TEXT NOT NULL,
    remote_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (player, name)
);

-- Music videos (Kodi's music video library). Each row is one video file.
CREATE TABLE IF NOT EXISTS music_videos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path TEXT NOT NULL UNIQUE,
    root TEXT NOT NULL,
    folder TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    year INT,
    genres TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    plot TEXT NOT NULL DEFAULT '',
    director TEXT NOT NULL DEFAULT '',
    file_id UUID REFERENCES video_files(id) ON DELETE SET NULL,
    nfo_path TEXT,
    playcount INT NOT NULL DEFAULT 0,
    last_played TEXT,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS music_videos_root_idx ON music_videos (root);

-- Activity history: what Curator deleted, restored, renamed, moved or changed, and why.
CREATE TABLE IF NOT EXISTS activity_history (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    action VARCHAR(40) NOT NULL,
    kind VARCHAR(20) NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_activity_history_action ON activity_history (action);

ALTER TABLE music_videos ADD COLUMN IF NOT EXISTS thumb_path TEXT;
ALTER TABLE music_videos ADD COLUMN IF NOT EXISTS resume_position DOUBLE PRECISION;
ALTER TABLE music_videos ADD COLUMN IF NOT EXISTS resume_total DOUBLE PRECISION;

-- "musicvideos" is 11 characters: a database that created disk_usage_history with VARCHAR(10) is widened.
ALTER TABLE disk_usage_history ALTER COLUMN kind TYPE VARCHAR(20);

-- Music tracks keep a play count and a last played time, for the player watched sync.
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS playcount INT NOT NULL DEFAULT 0;
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS last_played TEXT;
-- What the library and a player (or one of a player's users) agreed on at the last watched sync: a count that has
-- fallen since is an unwatch.
CREATE TABLE IF NOT EXISTS player_sync_state (
    player TEXT NOT NULL,
    path_key TEXT NOT NULL,
    plays INT NOT NULL DEFAULT 0,
    last_played TEXT,
    PRIMARY KEY (player, path_key)
);

-- Two artist folders marked "not the same artist": the Duplicate pill leaves that pair out.
CREATE TABLE IF NOT EXISTS dismissed_artist_twins (
    artist_a UUID NOT NULL,
    artist_b UUID NOT NULL,
    PRIMARY KEY (artist_a, artist_b)
);

-- The path of one imported item, from the webhook to each player's library update (curator/journey.py).
CREATE TABLE IF NOT EXISTS ingest_journeys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key TEXT NOT NULL,
    media VARCHAR(10) NOT NULL DEFAULT '',
    source VARCHAR(20) NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    events INT NOT NULL DEFAULT 1,
    stages JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(12) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);
CREATE INDEX IF NOT EXISTS ingest_journeys_key ON ingest_journeys (key, status);
CREATE INDEX IF NOT EXISTS ingest_journeys_updated ON ingest_journeys (updated_at DESC);

-- One album's Duplicate window looks up the albums that share a recording or a fingerprint with it, and deleting an
-- album clears the upgrade marks that point at it: without these, both read every track or album in the library.
CREATE INDEX IF NOT EXISTS idx_tracks_acoustid_recording ON tracks (acoustid_recording_id) WHERE acoustid_recording_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tracks_fingerprint_hash ON tracks (fingerprint_hash) WHERE fingerprint_hash IS NOT NULL AND fingerprint_hash <> '';
CREATE INDEX IF NOT EXISTS idx_albums_upgrade_source ON albums (upgrade_source_id) WHERE upgrade_source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dismissed_duplicates_b ON dismissed_duplicates (track_b);
-- v3.6.6: the music Corrupt pill and filter look up tracks Audit audio found corrupt.
CREATE INDEX IF NOT EXISTS idx_tracks_corrupt ON tracks (album_id) WHERE audio_flag = 'corrupt';
-- v3.6.7: lookups by provider id (webhooks, wanted rows, the Movie sets list's missing parts, Radarr) and the
-- "changed since" reads a scan's list refresh makes on the two large tables.
CREATE INDEX IF NOT EXISTS movies_tmdb_idx ON movies (tmdb_id) WHERE tmdb_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS movies_imdb_idx ON movies (imdb_id) WHERE imdb_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS tv_shows_tvdb_idx ON tv_shows (tvdb_id) WHERE tvdb_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS tv_shows_tmdb_idx ON tv_shows (tmdb_id) WHERE tmdb_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS albums_updated_idx ON albums (updated_at);
CREATE INDEX IF NOT EXISTS tv_episodes_updated_idx ON tv_episodes (updated_at);
-- The copy windows and duplicate marks compare trimmed ids (copies._movie_peer_where, _episode_peer_where).
CREATE INDEX IF NOT EXISTS movies_tmdb_trim_idx ON movies (btrim(tmdb_id));
CREATE INDEX IF NOT EXISTS tv_shows_tvdb_trim_idx ON tv_shows (btrim(tvdb_id));
-- v3.7.2: Undo Fix Match. One snapshot per movie or show, taken just before Fix Match writes the new ids: the rows as
-- JSON (to_jsonb) and the folder of copied artwork and .nfo files (curator/video/match_undo.py). Kept 7 days.
CREATE TABLE IF NOT EXISTS match_undo (
    item_id UUID PRIMARY KEY,
    kind VARCHAR(10) NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    taken_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
    data JSONB NOT NULL DEFAULT '{}'::jsonb
);
-- v3.7.3: a saved movie or TV filter can run an action on a schedule (curator/video/filter_actions.py).
ALTER TABLE saved_filters ADD COLUMN IF NOT EXISTS action TEXT;
ALTER TABLE saved_filters ADD COLUMN IF NOT EXISTS action_every TEXT NOT NULL DEFAULT 'off';
ALTER TABLE saved_filters ADD COLUMN IF NOT EXISTS action_hour INT NOT NULL DEFAULT 3;
ALTER TABLE saved_filters ADD COLUMN IF NOT EXISTS action_weekday INT NOT NULL DEFAULT 0;
ALTER TABLE saved_filters ADD COLUMN IF NOT EXISTS action_last_day TEXT;
ALTER TABLE saved_filters ADD COLUMN IF NOT EXISTS action_last_result TEXT;

-- The call a webhook made, kept with its row in Recent webhooks (Show call) so an unknown or ignored one can be read.
ALTER TABLE ingest_events ADD COLUMN IF NOT EXISTS payload JSONB;

-- Finished file jobs (rename, subtitles, Clean artwork and the rest) with their log, for the Jobs panel's Recent list.
CREATE TABLE IF NOT EXISTS job_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lane VARCHAR(20) NOT NULL DEFAULT 'Files',
    kind VARCHAR(60) NOT NULL DEFAULT '',
    label VARCHAR(200) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    log TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMP,
    finished_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);
CREATE INDEX IF NOT EXISTS job_history_finished ON job_history (finished_at DESC);

-- Online artwork the user banned in the artwork window: never suggested, never picked by Clean artwork or a scrape.
CREATE TABLE IF NOT EXISTS art_bans (
    url TEXT PRIMARY KEY,
    item_kind VARCHAR(10) NOT NULL DEFAULT '',
    item_id UUID,
    art_kind VARCHAR(20) NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);

-- Why an item went to the recycle bin (the job or the action that deleted it), shown in the recycle bin window.
ALTER TABLE trash_items ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT '';
