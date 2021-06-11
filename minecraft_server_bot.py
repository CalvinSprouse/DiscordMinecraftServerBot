import shutil

from discord.ext import commands
from multiprocessing import freeze_support
from py_minecraft_server import ServerMaker, ServerLoader, ServerAlreadyExistsException
import argparse
import coloredlogs
import discord
import keyring
import logging
import os

# configure logger
logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
coloredlogs.install(level=logging.DEBUG)
file_handler = logging.FileHandler(filename="minecraft_server_bot.log", encoding="utf-8", mode="w")
file_handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler(file_handler)


class MinecraftServerManager(commands.Cog):
    def __init__(self, bot: commands.Bot, max_allowable_servers=5, server_save_location="SavedServers"):
        self.bot = bot
        self.max_allowable_servers = max_allowable_servers
        self.loaded_servers = {}
        self.server_save_location = os.path.abspath(server_save_location)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"Bot ready {self.bot.user.name}")
        for guild in self.bot.guilds:
            self.loaded_servers[self.get_guild_name(guild)] = None
        await self.bot.change_presence(activity=discord.Game(
            name='Undress me at https://github.com/CalvinSprouse/'))

    @commands.Cog.listener()
    async def on_message(self, message):
        # logger.info(f"Message from {message.author}: {message.content}")
        pass

    @commands.command()
    async def send_message(self, message: str, original_message: discord.Message):
        if not original_message.author.bot:
            await original_message.channel.send(message)

    @commands.command(aliases=["create", "create-server", "make"])
    async def create_server(self, command):
        logger.info(
            f"{command.message.author} is attempting to create a minecraft server on guild {command.guild.name}")
        logger.info(
            f"There are currently {self.get_server_count(command.guild)} servers for guild {command.guild.name}")
        try:
            # parse the commands and validate
            args = self.parse_command_args(command)
            assert len(args) == 2 or len(args) == 1

            server_name = args[0]

            jar_version = None
            if len(args) == 2:
                jar_version = args[1]

            # attempt to make the server
            try:
                if self.get_server_count(command.guild) < self.max_allowable_servers:
                    if not os.path.exists(os.path.join(self.get_guild_name(command.guild), server_name)):
                        try:
                            with ServerMaker(
                                    server_location=os.path.join(self.get_guild_save_location(command.guild), server_name),
                                    jar_version=jar_version) as maker:
                                maker.make_server()
                            logger.info(f"Server {server_name} created for guild {self.get_guild_name(command.guild)}")
                            await self.send_message(f"Server {server_name} created.", command)
                        except FileNotFoundError as e:
                            if "eula.txt" in e.filename:
                                logging.critical("Java version out of date please update Java")
                            shutil.rmtree(os.path.abspath(os.path.join(self.get_guild_save_location(command.guild), server_name)))
                    else:
                        logger.warning(
                            f"Server {server_name} already exists for guild {self.get_guild_name(command.guild)}")
                else:
                    logger.warning(
                        f"Guild {self.get_guild_name(command.guild)} has reached maximum servers {self.max_allowable_servers}")
            except ServerAlreadyExistsException:
                logger.warning(f"Guild {self.get_guild_name(command.guild)} already has a server named {server_name}")
        except AssertionError:
            logger.info(f"Message '{command.message.content}' from {command.message.author} is not formatted properly")

    @commands.command(aliases=["edit", "change", "edit-server"])
    async def edit_server(self, command):
        args = list(reversed(self.parse_command_args(command)))
        server = args.pop()
        try:
            with ServerLoader(os.path.join(self.get_guild_save_location(command.guild), server), 1) as editor:
                for arg in args:
                    logger.info(f"{command.guild.name}: {server}: {arg.split('=')[0]}={arg.split('=')[1]}")
                    editor.change_property(arg.split("=")[0], arg.split("=")[1])
        except AssertionError:
            logger.warning(f"Server {server} does not exist in guild {command.guild.name}")

    @commands.command(aliases=["run", "start", "start_server", "run-server", "start-server", "host"])
    async def run_server(self, command):
        args = self.parse_command_args(command)
        server = args[0]
        try:
            with ServerLoader(os.path.join(self.get_guild_save_location(command.guild), args[0]), args[1]) as server:
                server.start_server()
                self.loaded_servers[self.get_guild_name(command.guild)] = server
            await self.send_message(f"Server {server} running "
                                    f"on ip {self.loaded_servers[self.get_guild_name(command.guild)].get_external_ip()}",
                                    command)
        except AssertionError:
            logger.warning(f"Server {server} does not exist in guild {command.guild.name}")
        except IndexError:
            logger.warning(f"run_server [server] [mem_allocation in GB] command requires two inputs")

    @commands.command(aliases=["status", "server-status"])
    async def server_status(self, command):
        try:
            loaded_server = self.loaded_servers[self.get_guild_name(command.guild)]
            if loaded_server.is_running():
                await self.send_message(f"Server {loaded_server.get_server_name()} is running. "
                                        f"On IP {loaded_server.get_external_ip()}", command)
        except AttributeError:
            await self.send_message("No server running.", command)

    @commands.command(aliases=["list", "servers"])
    async def list_servers(self, command):
        try:
            await self.send_message(", ".join(os.listdir(self.get_guild_save_location(command.guild))), command)
        except discord.errors.HTTPException:
            await self.send_message("No servers", command)

    def get_server_count(self, guild: discord.Guild):
        return len(os.listdir(self.get_guild_save_location(guild)))

    def get_guild_save_location(self, guild: discord.Guild):
        os.makedirs(os.path.join(self.server_save_location, self.get_guild_name(guild)), exist_ok=True)
        return os.path.join(self.server_save_location, self.get_guild_name(guild))

    @staticmethod
    def parse_command_args(command):
        return command.message.content.strip().split()[1:]

    @staticmethod
    def get_guild_name(guild: discord.Guild):
        return guild.name.lower().replace(" ", "_")


if __name__ == "__main__":
    # needed for windows deployment
    freeze_support()
    
    # configure logger
    stream = logging.StreamHandler()
    stream.setLevel(logging.INFO)
    stream.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
    logger.addHandler(stream)

    # configure argument parser
    parser = argparse.ArgumentParser(description="Discord but that also runs minecraft servers")
    parser.add_argument("-t", "--token", help="Provide the bot token")
    parser.add_argument("-s", "--save-location", help="Provide the server save location as an absolute path")
    parser.add_argument("-n", "--max-servers", help="How many servers can each guild save", type=int)
    args = vars(parser.parse_args())

    service_name = os.path.basename(__file__)
    if args["token"]:
        keyring.set_password(service_name, "token", args["token"])
    if args["save_location"]:
        keyring.set_password(service_name, "save_location", args["save_location"])
    if args["max_servers"]:
        keyring.set_password(service_name, "max_servers", args["max_servers"])

    # configure client
    server_bot = commands.Bot(command_prefix="$")
    try:
        server_bot.add_cog(
            MinecraftServerManager(bot=server_bot,
                                   max_allowable_servers=int(keyring.get_password(service_name, "max_servers")),
                                   server_save_location=keyring.get_password(service_name, "save_location")))
        server_bot.run(keyring.get_password(service_name, "token"))
    except (TypeError, AttributeError):
        logging.critical("Please run first time configuration with 'minecraft_server_bot.exe"
                         "-t [discord_bot_token] -s [server_save_location] -n [max_number_of_servers]'")
