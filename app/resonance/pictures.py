import base64
import io
import logging
import os

from resonance.settings import load as load_settings

logger = logging.getLogger(__name__)


def embed_track(path):
    embed_tracks([path])


def embed_tracks(paths):
    """Write folder.jpg into each track once. A track that already has that picture is left alone."""
    cfg = load_settings()
    if not cfg.get("embed_artwork"):
        return
    jpeg = None
    for path in paths or []:
        if not path or not os.path.isfile(path):
            continue
        if jpeg is None:
            folder = _folder_jpg(path)
            if not folder:
                return
            jpeg = _resized_jpeg(folder, int(cfg.get("embed_max_px") or 1000))
            if not jpeg:
                return
        try:
            if _embedded_jpeg(path) == jpeg:
                continue
            _embed(path, jpeg)
        except Exception:
            logger.info("embed art skipped for %s", path, exc_info=True)


def _folder_jpg(path):
    directory = os.path.dirname(path)
    for _step in range(3):
        candidate = os.path.join(directory, "folder.jpg")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return ""


def _resized_jpeg(path, max_edge):
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        if max_edge > 0:
            image.thumbnail((max_edge, max_edge))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()


def _embed(path, jpeg):
    import mutagen
    from mutagen.flac import Picture

    lowered = path.lower()
    if lowered.endswith(".mp3"):
        from mutagen.id3 import APIC, ID3, ID3NoHeaderError

        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpeg))
        tags.save(path)
        return
    if lowered.endswith(".flac"):
        from mutagen.flac import FLAC

        audio = FLAC(path)
        picture = _picture(jpeg)
        audio.clear_pictures()
        audio.add_picture(picture)
        audio.save()
        return
    if lowered.endswith((".ogg", ".opus")):
        audio = mutagen.File(path)
        if audio is None:
            return
        encoded = base64.b64encode(_picture(jpeg).write()).decode("ascii")
        audio["metadata_block_picture"] = [encoded]
        audio.save()
        return
    if lowered.endswith((".m4a", ".mp4", ".m4b")):
        from mutagen.mp4 import MP4, MP4Cover

        audio = MP4(path)
        audio["covr"] = [MP4Cover(jpeg, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()


def _embedded_jpeg(path):
    lowered = path.lower()
    if lowered.endswith(".mp3"):
        from mutagen.id3 import ID3, ID3NoHeaderError

        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            return b""
        pics = tags.getall("APIC")
        return pics[0].data if pics else b""
    if lowered.endswith(".flac"):
        from mutagen.flac import FLAC

        pics = FLAC(path).pictures
        return pics[0].data if pics else b""
    if lowered.endswith((".ogg", ".opus")):
        import mutagen

        audio = mutagen.File(path)
        if audio is None:
            return b""
        encoded = (audio.get("metadata_block_picture") or [None])[0]
        if not encoded:
            return b""
        from mutagen.flac import Picture

        return Picture(base64.b64decode(encoded)).data
    if lowered.endswith((".m4a", ".mp4", ".m4b")):
        from mutagen.mp4 import MP4

        covers = MP4(path).get("covr") or []
        return bytes(covers[0]) if covers else b""
    return None


def _picture(jpeg):
    from mutagen.flac import Picture

    picture = Picture()
    picture.type = 3
    picture.mime = "image/jpeg"
    picture.data = jpeg
    return picture
