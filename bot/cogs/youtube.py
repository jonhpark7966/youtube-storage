"""YouTube processing commands."""

from __future__ import annotations

import asyncio
import re

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from ..config import settings

# Step progress indicators
STEP_EMOJIS = {
    0: "⏳",  # Pending
    1: "📝",  # Subtitles
    2: "🎬",  # Burn-in
    3: "📄",  # Markdown
    4: "🌐",  # Web archive
}


def is_youtube_url(url: str) -> bool:
    """Check if URL is a valid YouTube URL."""
    patterns = [
        r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+",
        r"(?:https?://)?(?:www\.)?youtu\.be/[\w-]+",
    ]
    return any(re.match(p, url) for p in patterns)


def create_progress_embed(job: dict, processing: bool = True) -> discord.Embed:
    """Create a progress embed for the job."""
    status = job["status"]
    step = job["current_step"]
    step_name = job["step_name"]

    # Determine color
    if status == "completed":
        color = discord.Color.green()
    elif status == "failed":
        color = discord.Color.red()
    else:
        color = discord.Color.blue()

    embed = discord.Embed(
        title="🎥 YouTube Video Processing",
        color=color,
    )

    # Video info
    embed.add_field(
        name="Video",
        value=f"`{job['video_id']}`",
        inline=True,
    )

    # Status
    status_display = {
        "pending": "⏳ Pending",
        "running": "🔄 Processing",
        "completed": "✅ Completed",
        "failed": "❌ Failed",
    }
    embed.add_field(
        name="Status",
        value=status_display.get(status, status),
        inline=True,
    )

    # Progress bar
    if processing or status == "running":
        progress_parts = []
        for i in range(1, 5):
            if i < step:
                progress_parts.append("✅")
            elif i == step:
                progress_parts.append("🔄")
            else:
                progress_parts.append("⬜")
        progress_bar = " ".join(progress_parts)
        embed.add_field(
            name="Progress",
            value=f"{progress_bar}\n{STEP_EMOJIS.get(step, '⏳')} {step_name}",
            inline=False,
        )

    # Results (if completed)
    if status == "completed" and job.get("result"):
        result = job["result"]
        result_lines = []

        if result.get("upload_url"):
            result_lines.append(f"📺 [Uploaded Video]({result['upload_url']})")
        if result.get("pr_url"):
            result_lines.append(f"🔗 [Web Archive PR]({result['pr_url']})")

        if result_lines:
            embed.add_field(
                name="Results",
                value="\n".join(result_lines),
                inline=False,
            )

    # Error (if failed)
    if status == "failed" and job.get("error"):
        embed.add_field(
            name="Error",
            value=f"```{job['error'][:500]}```",
            inline=False,
        )

    return embed


class YouTubeCog(commands.Cog):
    """YouTube processing commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.http = httpx.AsyncClient(base_url=settings.api_base_url, timeout=30.0)

    async def cog_unload(self):
        await self.http.aclose()

    @app_commands.command(name="process", description="Process a YouTube video")
    @app_commands.describe(url="YouTube video URL to process")
    async def process(self, interaction: discord.Interaction, url: str):
        """Process a YouTube video."""
        # Check channel restriction
        if settings.allowed_channel_id and interaction.channel_id != settings.allowed_channel_id:
            await interaction.response.send_message(
                "❌ 이 명령은 지정된 채널에서만 사용 가능합니다.",
                ephemeral=True,
            )
            return

        # Validate URL
        if not is_youtube_url(url):
            await interaction.response.send_message(
                "❌ 유효한 YouTube URL을 입력해주세요.",
                ephemeral=True,
            )
            return

        # Defer response (processing takes time)
        await interaction.response.defer()

        try:
            # Call API to start processing
            response = await self.http.post("/api/youtube/process", json={"url": url})
            response.raise_for_status()
            data = response.json()
            job_id = data["job_id"]

            # Get initial job status
            job_response = await self.http.get(f"/api/jobs/{job_id}")
            job = job_response.json()

            # Send initial embed
            embed = create_progress_embed(job)
            message = await interaction.followup.send(embed=embed)

            # Poll for updates
            await self._poll_job_status(message, job_id)

        except httpx.HTTPError as e:
            await interaction.followup.send(f"❌ API 오류: {e}")
        except Exception as e:
            await interaction.followup.send(f"❌ 오류 발생: {e}")

    async def _poll_job_status(self, message: discord.Message, job_id: str):
        """Poll job status and update message."""
        poll_interval = 5  # seconds
        max_polls = 720  # 1 hour max

        for _ in range(max_polls):
            await asyncio.sleep(poll_interval)

            try:
                response = await self.http.get(f"/api/jobs/{job_id}")
                job = response.json()

                # Update embed
                embed = create_progress_embed(job, processing=job["status"] == "running")
                await message.edit(embed=embed)

                # Stop polling if job is done
                if job["status"] in ("completed", "failed"):
                    break

            except Exception:
                # Continue polling on error
                continue

    @app_commands.command(name="status", description="Check job status")
    @app_commands.describe(job_id="Job ID to check")
    async def status(self, interaction: discord.Interaction, job_id: str):
        """Check the status of a processing job."""
        await interaction.response.defer()

        try:
            response = await self.http.get(f"/api/jobs/{job_id}")
            if response.status_code == 404:
                await interaction.followup.send("❌ Job을 찾을 수 없습니다.")
                return

            job = response.json()
            embed = create_progress_embed(job, processing=job["status"] == "running")
            await interaction.followup.send(embed=embed)

        except httpx.HTTPError as e:
            await interaction.followup.send(f"❌ API 오류: {e}")

    @app_commands.command(name="jobs", description="List recent jobs")
    async def jobs(self, interaction: discord.Interaction):
        """List recent processing jobs."""
        await interaction.response.defer()

        try:
            response = await self.http.get("/api/jobs")
            jobs = response.json()

            if not jobs:
                await interaction.followup.send("📋 처리된 작업이 없습니다.")
                return

            # Show last 10 jobs
            jobs = sorted(jobs, key=lambda j: j["started_at"], reverse=True)[:10]

            embed = discord.Embed(
                title="📋 Recent Jobs",
                color=discord.Color.blue(),
            )

            for job in jobs:
                status_emoji = {
                    "pending": "⏳",
                    "running": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                }.get(job["status"], "❓")

                embed.add_field(
                    name=f"{status_emoji} {job['video_id']}",
                    value=f"ID: `{job['id']}`\nStatus: {job['status']}",
                    inline=True,
                )

            await interaction.followup.send(embed=embed)

        except httpx.HTTPError as e:
            await interaction.followup.send(f"❌ API 오류: {e}")


async def setup(bot: commands.Bot):
    """Setup function for the cog."""
    await bot.add_cog(YouTubeCog(bot))
