#!/usr/bin/env python3
"""
YouTube video processing pipeline.

Workflow:
1. Download metadata and extract video ID
2. Generate/translate subtitles (yt-subs-whisper-translate)
3. Burn in Korean subtitles + upload to YouTube (yt-burnin-upload)
4. Generate markdown notes (transcript-to-markdown)
5. Add to web archive via Claude CLI (notes-to-archive skill)
6. Cleanup source video (optional)

Note: Upload and metadata translation are handled by yt-burnin-upload skill.
Note: Web archive curation is handled by Claude CLI with notes-to-archive skill.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
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

# Web repo path
WEB_REPO_PATH = REPO_ROOT.parent / "web"

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


def step_burnin(
    url: str,
    ko_srt: Path,
    en_srt: Path,
    out_dir: Path,
    logger: logging.Logger,
    dry_run: bool = False,
    upload: bool = False,
) -> tuple[Path, str | None]:
    """Step 2: Burn in dual subtitles (Korean + English) and optionally upload to YouTube.

    Returns:
        Tuple of (burnin_mp4_path, upload_url or None)
    """
    logger.info("=" * 50)
    if upload:
        logger.info("Step 2: Burning in dual subtitles + uploading to YouTube...")
    else:
        logger.info("Step 2: Burning in dual subtitles...")

    cmd = [
        sys.executable,
        str(BURNIN_SCRIPT),
        url,
        "--ko-srt", str(ko_srt),
        "--en-srt", str(en_srt),
        "--out-dir", str(out_dir),
    ]

    if upload:
        if not CLIENT_SECRET_PATH.exists():
            raise RuntimeError(
                f"OAuth not configured. Missing: {CLIENT_SECRET_PATH}\n"
                "Run: python3 scripts/auth_youtube.py"
            )
        cmd.extend([
            "--upload",
            "--client-secret", str(CLIENT_SECRET_PATH),
            "--token", str(TOKEN_PATH),
        ])

    if dry_run:
        cmd.append("--dry-run")

    run_command(cmd, logger, stream_output=True)

    burnin_mp4 = out_dir / "burnin.mp4"
    if not dry_run and not burnin_mp4.exists():
        raise RuntimeError(f"Burn-in video not generated: {burnin_mp4}")

    # Check for upload info (created by yt-burnin-upload skill)
    upload_url = None
    upload_info_path = out_dir / "upload_info.json"
    if upload and upload_info_path.exists():
        try:
            upload_info = json.loads(upload_info_path.read_text(encoding="utf-8"))
            upload_url = upload_info.get("url")
            logger.info(f"Uploaded: {upload_url}")
        except Exception:
            pass

    logger.info(f"Burn-in video: {burnin_mp4}")
    return burnin_mp4, upload_url


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


def check_archive_exists(original_video_id: str, logger: logging.Logger) -> bool:
    """Check if archive already exists for this video."""
    archive_dir = WEB_REPO_PATH / "src" / "content" / "archive" / "ko"
    if not archive_dir.exists():
        return False

    for existing_file in archive_dir.glob("*.md"):
        try:
            content = existing_file.read_text(encoding="utf-8")
            if f'originalVideoId: "{original_video_id}"' in content:
                logger.info(f"Archive for video {original_video_id} already exists: {existing_file}")
                return True
        except Exception:
            continue
    return False


def step_add_to_web(
    out_dir: Path,
    original_video_id: str,
    logger: logging.Logger,
    dry_run: bool = False,
) -> str | None:
    """Step 4: Add to web archive using Claude CLI with notes-to-archive skill.

    Claude will:
    1. Read and curate the notes.md content
    2. Generate meaningful tags
    3. Create archive markdown file
    4. Git branch, commit, push, and create PR

    Returns:
        PR URL if created, None otherwise
    """
    logger.info("=" * 50)
    logger.info("Step 4: Adding to web archive via Claude...")

    # Check required files
    notes_path = out_dir / "notes.md"
    upload_info_path = out_dir / "upload_info.json"

    if not notes_path.exists():
        logger.warning(f"Notes not found: {notes_path}, skipping web archive")
        return None

    if not upload_info_path.exists():
        logger.warning(f"Upload info not found: {upload_info_path}, skipping web archive")
        return None

    # Check web repo exists
    if not WEB_REPO_PATH.exists():
        logger.warning(f"Web repo not found: {WEB_REPO_PATH}, skipping web archive")
        return None

    # Check if archive already exists
    if check_archive_exists(original_video_id, logger):
        return None

    if dry_run:
        logger.info(f"[DRY RUN] Would call Claude CLI to process: {out_dir}")
        return None

    # Call Claude CLI with notes-to-archive skill
    require_exe("claude")

    prompt = f"""Use the notes-to-archive skill to process the video folder and add it to the web archive.

Video folder: {out_dir}
Original video ID: {original_video_id}

Instructions:
1. Read notes.md, upload_info.json, and meta.json from the video folder
2. Curate the content (select important points, don't copy everything)
3. IMPORTANT: Preserve timestamps in [MM:SS] format for each bullet point (e.g., "[01:23] 내용...")
   - Timestamps are essential for users to jump to specific parts of the video
   - Every bullet point should start with its timestamp
4. Generate meaningful tags based on content
5. Create archive markdown file in web/src/content/archive/ko/
6. Use a short, descriptive filename (e.g., topic-name.md, not the full title)
7. Create git branch, commit, push, and create PR
8. After done, output the PR URL

Web repo path: {WEB_REPO_PATH}
"""

    logger.info("Calling Claude CLI...")

    try:
        # Run Claude in print mode for non-interactive execution
        proc = subprocess.run(
            [
                "claude",
                "-p",  # Print mode (non-interactive)
                "--allowedTools", "Read", "Write", "Edit", "Bash", "Glob", "Grep",
                "--dangerously-skip-permissions",  # Allow file operations
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            cwd=str(WEB_REPO_PATH),  # Run in web repo directory
        )

        if proc.returncode != 0:
            logger.error(f"Claude CLI failed: {proc.stderr}")
            return None

        output = proc.stdout
        logger.info("Claude CLI completed")

        # Try to extract PR URL from output
        pr_url = None
        for line in output.split("\n"):
            if "github.com" in line and "/pull/" in line:
                # Extract URL from line
                import re
                match = re.search(r'https://github\.com/[^\s]+/pull/\d+', line)
                if match:
                    pr_url = match.group(0)
                    break

        if pr_url:
            logger.info(f"Created PR: {pr_url}")
        else:
            logger.info("Claude completed but PR URL not found in output")
            # Log full output for debugging
            logger.debug(f"Claude output:\n{output}")

        return pr_url

    except subprocess.TimeoutExpired:
        logger.error("Claude CLI timed out after 10 minutes")
        return None
    except Exception as e:
        logger.error(f"Failed to run Claude CLI: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process YouTube video: subtitles, burn-in, markdown notes, upload, and add to web."
    )
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--out-dir", type=Path, help="Override output directory")
    parser.add_argument("--keep-source", action="store_true", help="Keep source video file")
    parser.add_argument("--skip-burnin", action="store_true", help="Skip burn-in step")
    parser.add_argument("--skip-markdown", action="store_true", help="Skip markdown generation")
    parser.add_argument("--no-upload", action="store_true", help="Skip YouTube upload (default: upload)")
    parser.add_argument("--no-add-to-web", action="store_true", help="Skip adding to web archive (default: add to web)")
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
        en_srt = out_dir / "en.srt"
        if not ko_srt.exists() or not en_srt.exists():
            step_subtitles(args.url, out_dir, logger, args.dry_run)
        else:
            logger.info(f"Using existing subtitles: {ko_srt}, {en_srt}")

        # Step 2: Burn-in (+ optional upload via yt-burnin-upload skill)
        upload_url = None
        if not args.skip_burnin:
            burnin_mp4 = out_dir / "burnin.mp4"
            upload_info_path = out_dir / "upload_info.json"
            do_upload = not args.no_upload

            # Check if already uploaded
            if upload_info_path.exists() and not args.dry_run:
                upload_info = json.loads(upload_info_path.read_text(encoding="utf-8"))
                upload_url = upload_info.get("url")
                if upload_url:
                    logger.info(f"Already uploaded: {upload_url}")
                    do_upload = False  # Skip upload, but still do burn-in if needed

            if not burnin_mp4.exists():
                burnin_mp4, new_upload_url = step_burnin(
                    args.url, ko_srt, en_srt, out_dir, logger, args.dry_run, upload=do_upload
                )
                if new_upload_url:
                    upload_url = new_upload_url
            else:
                logger.info(f"Using existing burn-in: {burnin_mp4}")

        # Step 3: Markdown notes
        if not args.skip_markdown:
            notes_md = out_dir / "notes.md"
            if not notes_md.exists():
                step_markdown(ko_srt, out_dir, title, description, logger, args.dry_run)
            else:
                logger.info(f"Using existing notes: {notes_md}")

        # Step 4: Add to web archive (default: enabled)
        pr_url = None
        if not args.no_add_to_web:
            pr_url = step_add_to_web(out_dir, video_id, logger, args.dry_run)

        # Cleanup
        if not args.keep_source:
            cleanup_source(out_dir, logger)

        logger.info("=" * 50)
        logger.info("Processing complete!")
        logger.info(f"Output directory: {out_dir}")
        if upload_url:
            logger.info(f"Uploaded: {upload_url}")
        if pr_url:
            logger.info(f"PR created: {pr_url}")
        logger.info("=" * 50)

        # Print summary
        print("\n--- Summary ---")
        print(f"Video ID: {video_id}")
        print(f"Title: {title}")
        print(f"Output: {out_dir}")
        if upload_url:
            print(f"Uploaded: {upload_url}")
        if pr_url:
            print(f"PR: {pr_url}")
        print("\nGenerated files:")
        for f in sorted(out_dir.iterdir()):
            if f.is_file():
                print(f"  - {f.name}")

    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
