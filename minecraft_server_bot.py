from py_minecraft_server.async_server import *
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
            self.g_user_server_starter[str(guild.id)] = {}

        # TODO: Configure status setter and find useful things to do with it

    @commands.Cog.listener()
    async def on_message(self, message):
        logger.info(
            f"{message.author.name} calling '{message.content}' "
            f"from {message.guild.name} channel {message.channel}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Send helps on errors"""

        # prevents local commands from being here
        if hasattr(ctx.command, "on_error"):
            return

        # check for original error or keep passed version
        error = getattr(error, "original", error)

        if isinstance(error, (commands.CommandNotFound,)):
            return
        elif isinstance(error, commands.DisabledCommand):
            await self.send_guild_text_message(f"{ctx.command} has been disabled", ctx.channel)
        elif isinstance(error, commands.NoPrivateMessage):
            try:
                await ctx.author.send(f"{ctx.command} cannot be used in Private Messages")
            except discord.HTTPException:
                pass
        elif isinstance(error, commands.BadArgument):
            if ctx.command.qualified_name == "tag list":  # check if cmd being invoked is 'tag list'
                await self.send_guild_text_message(f"I could not find that member please try again", ctx.channel)
        elif isinstance(error, discord.ext.commands.MissingRequiredArgument):
            await ctx.command.help()

    @commands.command(aliases=["create", "create-server"],
                      help="Creates a server using the MakeServer class",
                      brief="Make a server <server_name: str> <version: str>")
    @commands.guild_only()
    async def create_server(self, ctx, server_name: str, version: str):
        async with ctx.channel.typing():
            if not version:
                version = await ServerMaker.get_current_minecraft_version()

            try:
                await self.g_server_maker[str(ctx.guild.id)].make_server(server_name=server_name,
                                                                         server_version=version,
                                                                         overwrite=True)
            except ExceedMaxServerCountException:
                await self.send_guild_text_message(f"This server has exceeded the maximum number of servers "
                                                   f"({self.g_server_maker[str(ctx.guild.id)].max_servers}).",
                                                   ctx.channel)
            except ServerNameTakenException:
                # TODO: Add user query to overwrite, call separate delete function, recall this function
                await self.send_guild_text_message(f"This name ({server_name}) is already taken.", ctx.guild)

            await self.send_guild_text_message(
                f"Created server {self.g_server_maker[str(ctx.guild.id)].get_number_of_servers()}"
                f"/{self.g_server_maker[str(ctx.guild.id)].max_servers} "
                f"{server_name} running on v{version}", ctx.channel)

    @commands.command(aliases=["list", "list-servers"], help="Lists all servers available to the guild",
                      brief="List guilds servers")
    @commands.guild_only()
    async def list_servers(self, ctx):
        server_string = "\n".join([f"{num + 1}. {server}" for num, server in enumerate(
            os.listdir(os.path.join(self.server_save_location, str_to_key(ctx.guild.name))))])
        await self.send_guild_text_message(
            f"{ctx.guild.name} Servers:\n{server_string}\nOf {self.g_server_maker[str(ctx.guild.id)].max_servers}",
            ctx.channel)

    @commands.command(aliases=["run", "launch", "start", "run-server", "start-server", "launch-server", "run_server",
                               "launch_server"], help="Starts a server of server_name with RAM mem_allocation in GB",
                      brief="Starts a server <server_name: str> <mem_allocation: int> (GB)")
    @commands.guild_only()
    async def start_server(self, ctx, server_name: str, mem_allocation: int):
        async with ctx.channel.typing():
            await self.g_server_loader[str(ctx.guild.id)].load_server(server_name)
            self.g_server_loader[str(ctx.guild.id)].start_server(mem_allocation,
                                                                 gui=ctx.author.id == 390731132796272651)
            # enables the GUI for me

            # TODO: Find better way to either use roles or user verification for running server
            # save details to ensure only the starter can stop the server
            self.g_user_server_starter[str(ctx.guild.id)] = {}
            self.g_user_server_starter[str(ctx.guild.id)]["user_id"] = ctx.message.author.id
            self.g_user_server_starter[str(ctx.guild.id)]["secret"] = ctx.message.id

            # notify the channel the server now exits
            await self.send_guild_text_message(
                f"Server {server_name} started on {self.g_server_loader[str(ctx.guild.id)].get_ip()}",
                ctx.channel)

    @commands.command(aliases=["stop", "stop-server"], help="Stops the currently running server",
                      brief="Stops the guilds server")
    @commands.guild_only()
    async def stop_server(self, ctx, secret: str = None):
        if self.g_server_loader[str(ctx.guild.id)].is_running():
            if self.g_user_server_starter[str(ctx.guild.id)]["secret"] == secret or \
                    self.g_user_server_starter[str(ctx.guild.id)]["user_id"] == ctx.message.author.id:
                self.g_server_loader[str(ctx.guild.id)].stop_server()
                await self.send_guild_text_message(f"Server stopped.", ctx.channel)
        else:
            await self.send_guild_text_message(f"No server running from this guild.", ctx.channel)

    @commands.command(aliases=["set", "change"], help="Change a property in a server",
                      brief="Change server property <server_name: str> <property_name: str> <value: str>")
    @commands.guild_only()
    async def set_property(self, ctx, server_name: str, property_name: str, value: str):
        if not self.g_server_loader[str(ctx.guild.id)].is_running():
            with self.g_server_loader[str(ctx.guild.id)] as loader:
                await loader.load_server(server_name)
                await loader.set_property(property_name, value)
        else:
            await self.send_guild_text_message("Cannot edit while a server is running", ctx.channel)

    @commands.command(aliases=["command", "server-command"], help="Runs a server command on the current active guild "
                                                                  "server as if you were on the console",
                      brief="Runs a command [*command_args]", enabled=False)
    @commands.guild_only()
    async def server_command(self, ctx, *command_args):
        if self.g_server_loader[str(ctx.guild.id)].is_running():
            await self.g_server_loader[str(ctx.guild.id)].server_command(" ".join(command_args))
        else:
            await self.send_guild_text_message("No server running to send command to", ctx.channel)

    @commands.command(aliases=["status", "server-status"], help="Gives status of servers on the guild, if any are"
                                                                "running or not", brief="Are servers running?")
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


# TODO: Add documentation and create readme examples
if __name__ == "__main__":
    # needed for windows
    freeze_support()

    # configure argument parsing
    parser = argparse.ArgumentParser(description="Discord bot that also runs minecraft servers")
    parser.add_argument("-t", "--token", help="Provide the token for the bot from discord")
    parser.add_argument("-s", "--save-location", help="Provide the server save location for all guilds")
    parser.add_argument("-n", "--max-servers", help="How many servers can each guild save", type=int)
    args = vars(parser.parse_args())
    service_name = os.path.basename(__file__).replace(".py", "_discord")

    # apply passed values
    for arg_key, arg_val in args.items():
        if arg_val:
            keyring.set_password(service_name, arg_key, arg_val)

    # check for missing values
    has_all_values = True
    if not keyring.get_password(service_name, "max_servers"):
        logger.error("Missing value max_servers please run [name].exe -n [max_servers] replacing [max_servers] with the"
                     "number of servers each guild is allowed to save. (Only need to do this once)")
        has_all_values = False
    if not keyring.get_password(service_name, "save_location"):
        logger.error("Missing value save_location please run [name].exe -s [save_location] replacing [save_location] "
                     "with the location the bot should save all servers too. (Only need to do this once)")
        has_all_values = False
    if not keyring.get_password(service_name, "token"):
        logger.error("Missing value token please run [name].exe -t [token] replacing [token] with the bot token found "
                     "on the discord developer portal (Only need to do this once)")
        has_all_values = False

    # configure client
    if has_all_values:
        server_bot = commands.Bot(command_prefix="$")
        server_bot.add_cog(MinecraftServerManager(
            bot=server_bot,
            max_allowable_servers=int(keyring.get_password(service_name, "max_servers")),
            server_save_location=keyring.get_password(service_name, "save_location")
        ))
        server_bot.run(keyring.get_password(service_name, "token"))
