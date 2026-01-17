"""Discord bot main entry point."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from .config import settings

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("youtube-storage-bot")


class YouTubeStorageBot(commands.Bot):
    """YouTube Storage Discord Bot."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            description="YouTube Storage Bot - Process and archive YouTube videos",
        )

    async def setup_hook(self):
        """Setup hook called on bot startup."""
        # Load cogs
        await self.load_extension("bot.cogs.youtube")
        logger.info("Loaded youtube cog")

        # Sync slash commands
        await self.tree.sync()
        logger.info("Synced slash commands")

    async def on_ready(self):
        """Called when bot is ready."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        if settings.allowed_channel_id:
            logger.info(f"Restricted to channel ID: {settings.allowed_channel_id}")
        else:
            logger.info("No channel restriction (commands work in all channels)")


async def main():
    """Main entry point."""
    if not settings.discord_token:
        logger.error("DISCORD_TOKEN not set in environment")
        return

    bot = YouTubeStorageBot()

    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
