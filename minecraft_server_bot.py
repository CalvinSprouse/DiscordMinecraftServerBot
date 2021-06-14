from async_minecraft_server import ServerLoader, ServerMaker
from discord.ext import commands
from multiprocessing import freeze_support
import argparse
import asyncio
import coloredlogs
import discord
import keyring
import logging
import os
import shutil
import sys

# configure logger
coloredlogs.install(level=logging.DEBUG)
logger = logging.getLogger("discord")


class MinecraftServerManager(commands.Cog):
    def __init__(self, bot: commands.Bot, max_allowable_servers: int = 5, server_save_location: str = "SavedServers"):
        self.bot = bot
        self.max_allowable_servers = max_allowable_servers
        self.server_save_location = os.path.abspath(server_save_location)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"Bot ready {self.bot.user.name}")
        for guild in self.bot.guilds:
            print(guild.id)


if __name__ == "__main__":
    # needed for windows
    freeze_support()

    # configure argument parsing
    service_name = os.path.basename(__file__)

    # configure client
    server_bot = commands.Bot(command_prefix="$")
    server_bot.add_cog(MinecraftServerManager(
        bot=server_bot,
        max_allowable_servers=5,
        server_save_location="SavedServers"
    ))
    server_bot.run(keyring.get_password(service_name, "token"))
