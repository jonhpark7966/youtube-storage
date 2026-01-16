#!/usr/bin/env python3
"""
YouTube video processing pipeline.

Workflow:
1. Download metadata and extract video ID
2. Generate/translate subtitles (yt-subs-whisper-translate)
3. Burn in Korean subtitles (yt-burnin-upload)
4. Generate markdown notes (transcript-to-markdown)
5. Upload to YouTube (unlisted, Korean title/description)
6. Cleanup source video (optional)
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = REPO_ROOT.parent / "my-skills"
VIDEOS_DIR = REPO_ROOT / "videos"
CONFIG_DIR = REPO_ROOT / "config"
OAUTH_DIR = CONFIG_DIR / "oauth"
CLIENT_SECRET_PATH = OAUTH_DIR / "client_secret.json"
TOKEN_PATH = OAUTH_DIR / "token.json"

# Skill script paths
SUBS_SCRIPT = SKILLS_DIR / "yt-subs-whisper-translate" / "scripts" / "yt_subs_whisper_translate.py"
BURNIN_SCRIPT = SKILLS_DIR / "yt-burnin-upload" / "scripts" / "yt_burnin_upload.py"
MARKDOWN_SCRIPT = SKILLS_DIR / "transcript-to-markdown" / "scripts" / "transcript_to_markdown.py"


def setup_logging(log_path: Path) -> logging.Logger:
    """Setup logging to both file and console."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("process_video")
    logger.setLevel(logging.DEBUG)

    # File handler
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


def require_exe(name: str) -> str:
    """Check if executable exists in PATH."""
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable not found: {name}")
    return path


def run_command(cmd: list[str], logger: logging.Logger, capture: bool = False, stream_output: bool = False) -> str:
    """Run a command and log output.

    Args:
        cmd: Command to run
        logger: Logger instance
        capture: Return stdout as string (quiet mode)
        stream_output: Stream subprocess output to logger in real-time
    """
    logger.debug(f"Running: {' '.join(cmd)}")

    if capture:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            logger.error(f"Command failed: {proc.stderr}")
            raise RuntimeError(f"Command failed: {' '.join(cmd)}")
        return proc.stdout
    elif stream_output:
        # Stream output to logger for detailed tracking
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        output_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                logger.info(f"  | {line}")
                output_lines.append(line)
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed with code {proc.returncode}")
        return "\n".join(output_lines)
    else:
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed with code {proc.returncode}")
        return ""


def get_video_id(url: str, logger: logging.Logger) -> str:
    """Extract video ID from YouTube URL."""
    require_exe("yt-dlp")
    out = run_command(
        ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings", "--print", "%(id)s", "--skip-download", url],
        logger,
        capture=True,
    )
    video_id = out.strip().splitlines()[-1].strip()
    if not video_id:
        raise RuntimeError("Failed to extract video ID")
    logger.info(f"Video ID: {video_id}")
    return video_id


def download_metadata(url: str, output_path: Path, logger: logging.Logger) -> dict:
    """Download video metadata."""
    require_exe("yt-dlp")
    out = run_command(
        ["yt-dlp", "--no-playlist", "--quiet", "--no-warnings", "--dump-json", "--skip-download", url],
        logger,
        capture=True,
    )
    output_path.write_text(out, encoding="utf-8")
    logger.info(f"Metadata saved: {output_path}")
    return json.loads(out)


def step_subtitles(url: str, out_dir: Path, logger: logging.Logger, dry_run: bool = False) -> Path:
    """Step 1: Generate/translate subtitles."""
    logger.info("=" * 50)
    logger.info("Step 1: Generating subtitles...")

    cmd = [
        sys.executable,
        str(SUBS_SCRIPT),
        url,
        "--out-dir", str(out_dir),
    ]
    if dry_run:
        cmd.append("--dry-run")

    run_command(cmd, logger, stream_output=True)

    ko_srt = out_dir / "ko.srt"
    if not ko_srt.exists():
        raise RuntimeError(f"Korean subtitle not generated: {ko_srt}")

    logger.info(f"Subtitles generated: {ko_srt}")
    return ko_srt


def step_burnin(url: str, ko_srt: Path, out_dir: Path, logger: logging.Logger, dry_run: bool = False) -> Path:
    """Step 2: Burn in subtitles."""
    logger.info("=" * 50)
    logger.info("Step 2: Burning in subtitles...")

    cmd = [
        sys.executable,
        str(BURNIN_SCRIPT),
        url,
        "--ko-srt", str(ko_srt),
        "--out-dir", str(out_dir),
    ]
    if dry_run:
        cmd.append("--dry-run")

    run_command(cmd, logger, stream_output=True)

    burnin_mp4 = out_dir / "burnin.mp4"
    if not dry_run and not burnin_mp4.exists():
        raise RuntimeError(f"Burn-in video not generated: {burnin_mp4}")

    logger.info(f"Burn-in video: {burnin_mp4}")
    return burnin_mp4


def step_markdown(ko_srt: Path, out_dir: Path, title: str, description: str, logger: logging.Logger, dry_run: bool = False) -> Path:
    """Step 3: Generate markdown notes."""
    logger.info("=" * 50)
    logger.info("Step 3: Generating markdown notes...")

    notes_md = out_dir / "notes.md"

    # Check for chapters in metadata
    meta_path = out_dir / "meta.json"
    chapters_arg = []
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("chapters"):
            chapters_path = out_dir / "chapters.json"
            chapters_path.write_text(json.dumps(meta["chapters"]), encoding="utf-8")
            chapters_arg = ["--chapters", str(chapters_path)]

    cmd = [
        sys.executable,
        str(MARKDOWN_SCRIPT),
        "--input", str(ko_srt),
        "--output", str(notes_md),
        "--title", title,
        "--description", description[:500] if description else "",
    ] + chapters_arg

    if dry_run:
        cmd.append("--dry-run")

    run_command(cmd, logger, stream_output=True)

    if not dry_run and not notes_md.exists():
        raise RuntimeError(f"Markdown notes not generated: {notes_md}")

    logger.info(f"Markdown notes: {notes_md}")
    return notes_md


def cleanup_source(out_dir: Path, logger: logging.Logger) -> None:
    """Remove source video to save space."""
    source_files = list(out_dir.glob("source.*"))
    for f in source_files:
        logger.info(f"Removing source file: {f}")
        f.unlink()


def translate_metadata(title: str, description: str, out_dir: Path, logger: logging.Logger, dry_run: bool = False) -> dict:
    """Translate title and description to Korean using Codex."""
    cache_path = out_dir / "metadata_ko.json"

    # Use cached translation if available
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("title") and cached.get("description"):
            logger.info("Using cached Korean metadata")
            return cached

    if dry_run:
        return {"title": title, "description": description}

    logger.info("Translating metadata to Korean...")

    prompt = (
        "Translate the following YouTube video metadata to Korean.\n"
        "Rules:\n"
        "- Preserve proper nouns, product names, and technical terms.\n"
        "- Do not add new content or commentary.\n"
        "- Output strict JSON with keys: title, description.\n\n"
        f"Title: {title}\n\n"
        f"Description:\n{description[:2000]}\n"
    )

    prompt_path = out_dir / "translate_metadata.prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    try:
        require_exe("codex")
        output_path = out_dir / "translate_metadata.response.json"
        cmd = ["codex", "exec", "--skip-git-repo-check", "-o", str(output_path), f"@file {prompt_path}"]
        run_command(cmd, logger)

        response = output_path.read_text(encoding="utf-8").strip()
        # Parse JSON from response
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1:
            result = json.loads(response[start:end + 1])
            cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
    except Exception as e:
        logger.warning(f"Translation failed: {e}. Using original metadata.")

    return {"title": title, "description": description}


def step_upload(
    video_path: Path,
    original_url: str,
    title_ko: str,
    description_ko: str,
    out_dir: Path,
    logger: logging.Logger,
    dry_run: bool = False,
) -> str | None:
    """Step 4: Upload video to YouTube."""
    logger.info("=" * 50)
    logger.info("Step 4: Uploading to YouTube...")

    if not video_path.exists():
        raise RuntimeError(f"Video file not found: {video_path}")

    # Check OAuth setup
    if not CLIENT_SECRET_PATH.exists():
        raise RuntimeError(
            f"OAuth not configured. Missing: {CLIENT_SECRET_PATH}\n"
            "Run: python3 scripts/auth_youtube.py"
        )

    # Build description with original link
    full_description = f"Original: {original_url}\n\n{description_ko}"

    if dry_run:
        logger.info(f"[DRY RUN] Would upload: {video_path}")
        logger.info(f"[DRY RUN] Title: {title_ko}")
        logger.info(f"[DRY RUN] Description preview: {full_description[:200]}...")
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as e:
        raise RuntimeError(
            "Missing Google API packages. Run:\n"
            "pip install google-auth-oauthlib google-api-python-client"
        ) from e

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    # Load or refresh credentials
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    youtube = build("youtube", "v3", credentials=creds)

    request_body = {
        "snippet": {
            "title": title_ko[:100],  # YouTube title limit
            "description": full_description[:5000],  # YouTube description limit
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False,
        },
    }

    logger.info(f"Uploading: {video_path.name}")
    logger.info(f"Title: {title_ko[:50]}...")

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media,
    )

    response = request.execute()
    video_id = response.get("id")
    upload_url = f"https://www.youtube.com/watch?v={video_id}"

    logger.info(f"Upload complete: {upload_url}")

    # Save upload info
    upload_info = {
        "video_id": video_id,
        "url": upload_url,
        "title": title_ko,
        "uploaded_at": datetime.now().isoformat(),
        "privacy": "unlisted",
    }
    upload_info_path = out_dir / "upload_info.json"
    upload_info_path.write_text(json.dumps(upload_info, ensure_ascii=False, indent=2), encoding="utf-8")

    return upload_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process YouTube video: subtitles, burn-in, markdown notes, and upload."
    )
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--out-dir", type=Path, help="Override output directory")
    parser.add_argument("--keep-source", action="store_true", help="Keep source video file")
    parser.add_argument("--skip-burnin", action="store_true", help="Skip burn-in step")
    parser.add_argument("--skip-markdown", action="store_true", help="Skip markdown generation")
    parser.add_argument("--no-upload", action="store_true", help="Skip YouTube upload (default: upload)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (skip external API calls)")
    args = parser.parse_args()

    # Get video ID and setup directories
    temp_logger = logging.getLogger("temp")
    temp_logger.addHandler(logging.StreamHandler())
    temp_logger.setLevel(logging.INFO)

    video_id = get_video_id(args.url, temp_logger)
    out_dir = args.out_dir or (VIDEOS_DIR / video_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Setup logging
    log_path = out_dir / "logs" / f"process_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = setup_logging(log_path)

    logger.info("=" * 50)
    logger.info(f"Processing: {args.url}")
    logger.info(f"Video ID: {video_id}")
    logger.info(f"Output directory: {out_dir}")
    logger.info("=" * 50)

    try:
        # Download metadata
        meta_path = out_dir / "meta.json"
        if not meta_path.exists():
            meta = download_metadata(args.url, meta_path, logger)
        else:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            logger.info("Using existing metadata")

        title = meta.get("title", "Untitled")
        description = meta.get("description", "")

        # Step 1: Subtitles
        ko_srt = out_dir / "ko.srt"
        if not ko_srt.exists():
            ko_srt = step_subtitles(args.url, out_dir, logger, args.dry_run)
        else:
            logger.info(f"Using existing subtitles: {ko_srt}")

        # Step 2: Burn-in
        if not args.skip_burnin:
            burnin_mp4 = out_dir / "burnin.mp4"
            if not burnin_mp4.exists():
                step_burnin(args.url, ko_srt, out_dir, logger, args.dry_run)
            else:
                logger.info(f"Using existing burn-in: {burnin_mp4}")

        # Step 3: Markdown notes
        if not args.skip_markdown:
            notes_md = out_dir / "notes.md"
            if not notes_md.exists():
                step_markdown(ko_srt, out_dir, title, description, logger, args.dry_run)
            else:
                logger.info(f"Using existing notes: {notes_md}")

        # Step 4: Upload to YouTube
        upload_url = None
        if not args.no_upload and not args.skip_burnin:
            burnin_mp4 = out_dir / "burnin.mp4"
            upload_info_path = out_dir / "upload_info.json"

            if upload_info_path.exists() and not args.dry_run:
                upload_info = json.loads(upload_info_path.read_text(encoding="utf-8"))
                upload_url = upload_info.get("url")
                logger.info(f"Already uploaded: {upload_url}")
            elif burnin_mp4.exists():
                # Translate metadata
                translated = translate_metadata(title, description, out_dir, logger, args.dry_run)
                title_ko = translated.get("title", title)
                description_ko = translated.get("description", description)

                upload_url = step_upload(
                    burnin_mp4,
                    args.url,
                    title_ko,
                    description_ko,
                    out_dir,
                    logger,
                    args.dry_run,
                )

        # Cleanup
        if not args.keep_source:
            cleanup_source(out_dir, logger)

        logger.info("=" * 50)
        logger.info("Processing complete!")
        logger.info(f"Output directory: {out_dir}")
        if upload_url:
            logger.info(f"Uploaded: {upload_url}")
        logger.info("=" * 50)

        # Print summary
        print("\n--- Summary ---")
        print(f"Video ID: {video_id}")
        print(f"Title: {title}")
        print(f"Output: {out_dir}")
        if upload_url:
            print(f"Uploaded: {upload_url}")
        print("\nGenerated files:")
        for f in sorted(out_dir.iterdir()):
            if f.is_file():
                print(f"  - {f.name}")

    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
