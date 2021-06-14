import async_minecraft_server
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

# configure logger
coloredlogs.install(level=logging.DEBUG)
logger = logging.getLogger("discord")


def str_to_key(string: str):
    return string.strip().lower().replace(" ", "_")


class MinecraftServerManager(commands.Cog):
    def __init__(self, bot: commands.Bot, max_allowable_servers: int = 5, server_save_location: str = "SavedServers"):
        # global variables
        self.bot = bot
        self.max_allowable_servers = max_allowable_servers
        self.server_save_location = os.path.abspath(server_save_location)

        # guild specific variables
        self.g_server_loader = {}
        self.g_server_maker = {}
        self.g_user_server_starter = {}

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"Bot ready {self.bot.user.name}")
        # define guild specific variables
        for guild in self.bot.guilds:
            guild_save_location = os.path.join(self.server_save_location, str_to_key(guild.name))
            self.g_server_maker[str(guild.id)] = ServerMaker(guild_save_location, self.max_allowable_servers)
            self.g_server_loader[str(guild.id)] = ServerLoader(guild_save_location)
        # set status

    @commands.Cog.listener()
    async def on_message(self, message):
        logger.info(
            f"{message.author.name} calling '{message.content}' "
            f"from {message.guild.name} channel {message.channel}")

    @commands.command(aliases=["create", "create-server"])
    @commands.guild_only()
    async def create_server(self, ctx, server_name: str, version: str):
        try:
            async with ctx.channel.typing():
                # parse args

                if not version:
                    version = await ServerMaker.get_current_minecraft_version()

                # make server
                try:
                    await self.g_server_maker[str(ctx.guild.id)].make_server(server_name=server_name,
                                                                             server_version=version,
                                                                             overwrite=True)
                except async_minecraft_server.ExceedMaxServerCountException:
                    await self.send_guild_text_message(f"This server has exceeded the maximum number of servers "
                                                       f"({self.g_server_maker[str(ctx.guild.id)].max_servers}).",
                                                       ctx.channel)
                except async_minecraft_server.ServerNameTakenException:
                    # TODO: Add user query to overwrite, call separate delete function, recall this function
                    await self.send_guild_text_message(f"This name ({server_name}) is already taken.", ctx.guild)

                await self.send_guild_text_message(
                    f"Created server {self.g_server_maker[str(ctx.guild.id)].get_number_of_servers()}"
                    f"/{self.g_server_maker[str(ctx.guild.id)].max_servers} "
                    f"{server_name} running on v{version}", ctx.channel)
        except AssertionError:
            await ctx.send_help()

    @commands.command(aliases=["list", "list-servers"])
    @commands.guild_only()
    async def list_servers(self, ctx):
        server_string = "\n".join([f"{num + 1}. {server}" for num, server in enumerate(
            os.listdir(os.path.join(self.server_save_location, str_to_key(ctx.guild.name))))])
        await self.send_guild_text_message(
            f"{ctx.guild.name} Servers:\n{server_string}\nOf {self.g_server_maker[str(ctx.guild.id)].max_servers}",
            ctx.channel)

    @commands.command(aliases=["run", "launch", "start", "run-server", "start-server",
                               "launch-server", "run_server", "launch_server"])
    @commands.guild_only()
    async def start_server(self, ctx, server_name: str, mem_allocation: int):
        try:
            async with ctx.channel.typing():
                assert server_name and mem_allocation
                # start server
                await self.g_server_loader[str(ctx.guild.id)].load_server(server_name)
                self.g_server_loader[str(ctx.guild.id)].start_server(mem_allocation, gui=ctx.author.id == 390731132796272651)
                # save details to ensure only the starter can stop the server
                self.g_user_server_starter[str(ctx.guild.id)] = {}
                self.g_user_server_starter[str(ctx.guild.id)]["user_id"] = ctx.message.author.id
                self.g_user_server_starter[str(ctx.guild.id)]["secret"] = ctx.message.id
                # notify the channel the server now exits
                await self.send_guild_text_message(
                    f"Server {server_name} started on {self.g_server_loader[str(ctx.guild.id)].get_ip()}",
                    ctx.channel)
        except AssertionError:
            ctx.send_help()

    @commands.command(aliases=["stop", "stop-server"])
    @commands.guild_only()
    async def stop_server(self, ctx, secret: str = None):
        if self.g_server_loader[str(ctx.guild.id)].is_running():
            if self.g_user_server_starter[str(ctx.guild.id)]["secret"] == secret or \
                    self.g_user_server_starter[str(ctx.guild.id)]["user_id"] == ctx.message.author.id:
                self.g_server_loader[str(ctx.guild.id)].stop_server()
                await self.send_guild_text_message(f"Server stopped.", ctx.channel)
        else:
            await self.send_guild_text_message(f"No server running from this guild.", ctx.channel)

    @commands.command(aliases=["set", "change"])
    @commands.guild_only()
    async def set_property(self, ctx, server: str, key: str, val: str):
        if not self.g_server_loader[str(ctx.guild.id)].is_running():
            with self.g_server_loader[str(ctx.guild.id)] as loader:
                await loader.load_server(server)
                await loader.set_property(key, val)
        else:
            await self.send_guild_text_message("Cannot edit while a server is running", ctx.channel)

    @commands.command(aliases=["command", "server-command"])
    @commands.guild_only()
    async def server_command(self, ctx, *command_args):
        if self.g_server_loader[str(ctx.guild.id)].is_running():
            await self.g_server_loader[str(ctx.guild.id)].server_command(" ".join(command_args))
        else:
            await self.send_guild_text_message("No server running to send command to", ctx.channel)

    @commands.command(aliases=["status", "server-status"])
    @commands.guild_only()
    async def server_status(self, ctx):
        if self.g_server_loader[str(ctx.guild.id)].is_running():
            await self.send_guild_text_message(f"{self.g_server_loader[str(ctx.guild.id)].server} running on "
                                               f"{self.g_server_loader[str(ctx.guild.id)].get_ip()}", ctx.channel)
        else:
            await self.send_guild_text_message(f"No server running", ctx.channel)

    async def send_guild_text_message(self, message: str, channel: discord.TextChannel):
        logger.debug(f"Sending message '{message}' to {channel}")
        await channel.send(message)


# TODO: Add proper improper arg handling (give everything a default value and handle the errors inside the func)
if __name__ == "__main__":
    # needed for windows
    freeze_support()

    # configure argument parsing
    # TODO: Parsing for tokens/settings and initial configuration
    service_name = os.path.basename(__file__)

    # configure client
    server_bot = commands.Bot(command_prefix="$")
    server_bot.add_cog(MinecraftServerManager(
        bot=server_bot,
        max_allowable_servers=5,
        server_save_location="SavedServers"
    ))
    server_bot.run(keyring.get_password(service_name, "token"))
