"""
Post to an Instagram professional account via Meta's content publishing API.

Two auth flavours are supported, because they are genuinely different APIs
on different hosts:

  Instagram Business Login  (env: IG_ACCESS_TOKEN, IG_USER_ID)
      host: graph.instagram.com
      No licensed music. Meta's Audio API is explicitly unsupported here:
      "It is not supported on the Instagram API with Instagram Login."

  Instagram API with Facebook Login  (env: IG_FB_ACCESS_TOKEN, IG_FB_USER_ID)
      host: graph.facebook.com
      Unlocks the Audio API, so officially licensed music from Meta's
      catalogue can be attached to a Reel at container-creation time --
      i.e. at the exact moment we schedule/publish, with no re-render.

Whichever env pair is present wins. If both are present, Facebook Login is
preferred so audio keeps working. Override with IG_LOGIN_TYPE=instagram|facebook.

Env vars:
  IG_ACCESS_TOKEN / IG_USER_ID           (Instagram Business Login)
  IG_FB_ACCESS_TOKEN / IG_FB_USER_ID     (Facebook Login -- required for audio)
  IG_LOGIN_TYPE                          (optional: "instagram" or "facebook")

Usage:
  python post_instagram.py --caption "New dive video!" --media-path ./clip.mp4 --media-type reels
  python post_instagram.py --caption "New dive video!" --media-url https://.../clip.mp4 --media-type reels
  python post_instagram.py --caption "Sunset shot" --media-url https://.../photo.jpg --media-type image

  # attach licensed music (Facebook Login only) -- find ids with find_audio.py
  python post_instagram.py --caption "..." --media-url https://.../clip.mp4 \
      --media-type reels --audio-id 587784541076604 --audio-volume 25

Notes:
  - Images (--media-type image) MUST be a public URL Meta's servers can
    fetch -- Instagram's API has no direct-upload path for images.
  - Reels (--media-type reels) support --media-path: the local video file
    is uploaded directly to Meta via the resumable upload protocol, so no
    public hosting is needed. --media-url also works for reels if you'd
    rather host it yourself.
  - Video posts (reels) go through an async container: create -> upload
    (if local) -> poll status until FINISHED -> publish. This can take
    anywhere from a few seconds to a couple of minutes depending on video
    length.
  - Meta gives no way to preview a Reel with its attached audio before
    publishing, so the volume mix is committed blind. Defaults below keep
    music well under the already-mixed VO/SFX in our shorts.
"""
import argparse
import json
import os
import time
import requests
from common import env, log

IG_LOGIN_GRAPH_VERSION = "v19.0"
FB_LOGIN_GRAPH_VERSION = "v22.0"  # audio_configuration is documented from v22.0

# Our shorts ship with VO and SFX already mixed into the file, so catalogue
# music sits underneath as a bed rather than replacing anything.
DEFAULT_AUDIO_VOLUME = 25
DEFAULT_VIDEO_VOLUME = 100

POLL_INTERVAL_SECONDS = 5
POLL_MAX_ATTEMPTS = 60  # ~5 minutes


class IGTarget:
    """Resolved host + credentials for one Instagram auth flavour."""

    def __init__(self, login_type, base, token, user_id):
        self.login_type = login_type
        self.base = base
        self.token = token
        self.user_id = user_id

    @property
    def supports_audio(self):
        return self.login_type == "facebook"

    def __str__(self):
        return f"{self.login_type} login ({self.base})"


def resolve_target(login_type=None):
    """Pick an auth flavour from the environment.

    Explicit login_type (arg or IG_LOGIN_TYPE) wins; otherwise prefer
    Facebook Login when its credentials are present, since it is the only
    one that can attach licensed music.
    """
    # GitHub Actions passes unset vars/secrets as "", not as absent, so
    # normalise empty strings back to None rather than failing validation.
    login_type = login_type or os.environ.get("IG_LOGIN_TYPE") or None
    has_fb = bool(os.environ.get("IG_FB_ACCESS_TOKEN") and os.environ.get("IG_FB_USER_ID"))

    if login_type is None:
        login_type = "facebook" if has_fb else "instagram"
    if login_type not in ("facebook", "instagram"):
        raise ValueError(f"IG_LOGIN_TYPE must be 'facebook' or 'instagram', got {login_type!r}")

    if login_type == "facebook":
        return IGTarget(
            "facebook",
            f"https://graph.facebook.com/{FB_LOGIN_GRAPH_VERSION}",
            env("IG_FB_ACCESS_TOKEN"),
            env("IG_FB_USER_ID"),
        )
    return IGTarget(
        "instagram",
        f"https://graph.instagram.com/{IG_LOGIN_GRAPH_VERSION}",
        env("IG_ACCESS_TOKEN"),
        env("IG_USER_ID"),
    )


def build_audio_configuration(audio):
    """Turn an {audio_id, audio_volume, video_volume} dict into the API's
    JSON-encoded audio_configuration string. Returns None for no audio."""
    if not audio:
        return None
    audio_id = audio.get("audio_id")
    if not audio_id:
        raise ValueError("audio configuration requires an audio_id")

    config = {"audio_id": str(audio_id)}
    volumes = (
        ("audio_volume", audio.get("audio_volume", DEFAULT_AUDIO_VOLUME)),
        ("video_volume", audio.get("video_volume", DEFAULT_VIDEO_VOLUME)),
    )
    for name, value in volumes:
        if value is None:
            continue
        value = int(value)
        if not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100, got {value}")
        config[name] = value
    return json.dumps(config, separators=(",", ":"))


def _apply_audio(target, data, audio, audio_name):
    """Add audio fields to a container-creation payload, refusing early if
    the resolved login flavour can't honour them."""
    audio_configuration = build_audio_configuration(audio)
    if audio_configuration:
        if not target.supports_audio:
            raise RuntimeError(
                "Licensed music was requested, but this run resolved to "
                f"{target}. Meta's Audio API is only available on the Instagram "
                "API with Facebook Login. Set IG_FB_ACCESS_TOKEN + IG_FB_USER_ID "
                "(scopes: instagram_basic, instagram_content_publish) and retry. "
                "Refusing to publish a music-less version, since publishing is "
                "not reversible."
            )
        data["audio_configuration"] = audio_configuration
        log(f"Attaching audio: {audio_configuration}")
    if audio_name:
        # Names the Reel's audio page. Meta only lets this be set once, either
        # here or later in the app -- it is not editable afterwards via the API.
        data["audio_name"] = audio_name


def create_hosted_container(target, caption, media_url, media_type, audio=None, audio_name=None):
    data = {"caption": caption, "access_token": target.token}
    if media_type == "image":
        data["image_url"] = media_url
    elif media_type == "reels":
        data["media_type"] = "REELS"
        data["video_url"] = media_url
        _apply_audio(target, data, audio, audio_name)
    else:
        raise ValueError(f"Unsupported media_type: {media_type}")

    resp = requests.post(f"{target.base}/{target.user_id}/media", data=data, timeout=60)
    resp.raise_for_status()
    return resp.json()["id"]


def create_resumable_container(target, caption, audio=None, audio_name=None):
    data = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "access_token": target.token,
    }
    _apply_audio(target, data, audio, audio_name)
    resp = requests.post(f"{target.base}/{target.user_id}/media", data=data, timeout=60)
    resp.raise_for_status()
    j = resp.json()
    return j["id"], j["uri"]


def upload_video_bytes(uri, token, media_path):
    file_size = os.path.getsize(media_path)
    with open(media_path, "rb") as f:
        video_bytes = f.read()
    headers = {
        "Authorization": f"OAuth {token}",
        "offset": "0",
        "file_size": str(file_size),
    }
    resp = requests.post(uri, headers=headers, data=video_bytes, timeout=600)
    resp.raise_for_status()
    j = resp.json()
    if not j.get("success"):
        raise RuntimeError(f"Resumable upload failed: {j}")


def wait_for_container(target, container_id):
    for attempt in range(POLL_MAX_ATTEMPTS):
        resp = requests.get(
            f"{target.base}/{container_id}",
            params={"fields": "status_code,status", "access_token": target.token},
            timeout=30,
        )
        resp.raise_for_status()
        info = resp.json()
        status = info.get("status_code")
        log(f"Container {container_id} status: {status} ({info.get('status')})")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Container processing failed: {info}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Container {container_id} did not finish processing in time")


def publish_container(target, container_id):
    resp = requests.post(
        f"{target.base}/{target.user_id}/media_publish",
        data={"creation_id": container_id, "access_token": target.token},
        timeout=60,
    )
    return resp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--caption", required=True)
    parser.add_argument("--media-url", default=None, help="Public URL for Meta to fetch")
    parser.add_argument("--media-path", default=None, help="Local video file (reels only)")
    parser.add_argument("--media-type", choices=["image", "reels"], required=True)
    parser.add_argument(
        "--login-type", choices=["instagram", "facebook"], default=None,
        help="Override auth flavour (default: auto-detect from env)"
    )
    parser.add_argument(
        "--audio-id", default=None,
        help="Licensed audio id from find_audio.py (Facebook Login, reels only)"
    )
    parser.add_argument("--audio-volume", type=int, default=None, help=f"0-100 (default {DEFAULT_AUDIO_VOLUME})")
    parser.add_argument("--video-volume", type=int, default=None, help=f"0-100 (default {DEFAULT_VIDEO_VOLUME})")
    parser.add_argument(
        "--audio-name", default=None,
        help="Name the Reel's audio page. Can only ever be set once."
    )
    args = parser.parse_args()

    if args.media_url and args.media_path:
        raise SystemExit("pass only one of --media-url or --media-path")
    if not args.media_url and not args.media_path:
        raise SystemExit("one of --media-url or --media-path is required")
    if args.media_path and args.media_type != "reels":
        raise SystemExit("--media-path (local upload) is only supported for --media-type reels")
    if args.audio_id and args.media_type != "reels":
        raise SystemExit("--audio-id is only supported for --media-type reels")

    audio = None
    if args.audio_id:
        audio = {"audio_id": args.audio_id}
        if args.audio_volume is not None:
            audio["audio_volume"] = args.audio_volume
        if args.video_volume is not None:
            audio["video_volume"] = args.video_volume

    target = resolve_target(args.login_type)
    log(f"Using {target}")

    if args.media_path:
        log(f"Creating resumable reels container and uploading {args.media_path}...")
        container_id, uri = create_resumable_container(target, args.caption, audio, args.audio_name)
        upload_video_bytes(uri, target.token, args.media_path)
        wait_for_container(target, container_id)
    else:
        log(f"Creating {args.media_type} container from URL: {args.media_url}")
        container_id = create_hosted_container(
            target, args.caption, args.media_url, args.media_type, audio, args.audio_name
        )
        if args.media_type == "reels":
            wait_for_container(target, container_id)

    log("Publishing...")
    resp = publish_container(target, container_id)

    if resp.status_code >= 300:
        log(f"FAILED ({resp.status_code}): {resp.text}")
        raise SystemExit(1)

    log(f"Success: {resp.json()}")


if __name__ == "__main__":
    main()
