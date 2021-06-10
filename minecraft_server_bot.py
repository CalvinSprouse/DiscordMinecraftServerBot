from decouple import config
from discord.ext import commands
from py_minecraft_server import ServerMaker
import discord
import logging
import os

# configure logger
logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(filename="minecraft_server_bot.log", encoding="utf-8", mode="w")
file_handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler(file_handler)


class MinecraftServerManager(commands.Cog):
    def __init__(self, bot: commands.Bot, max_allowable_servers=5, relative_server_save_location="SavedServers"):
        self.bot = bot
        self.max_allowable_servers = max_allowable_servers
        self.server_loader = None
        self.server_save_location = os.path.abspath(relative_server_save_location)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"Bot ready {self.bot.user.name}")

    @commands.Cog.listener()
    async def on_message(self, message):
        logger.info(f"Message from {message.author}: {message.content}")

    @commands.command(aliases=["create", "create-server"])
    async def create_server(self, command):
        logger.info(f"{command.message.author} is attempting to create minecraft server on guild {command.guild.name}")
        logger.info(f"There are currently {self.get_server_count(command.guild)} servers for guild {command.guild.name}")
        try:
            # parse the commands
            args = command.message.content.split()
            assert len(args) == 3 or len(args) == 2
            server_name = args[1]
            jar_version = None
            if len(args) == 3:
                jar_version = args[2]

            # attempt to make the server
            try:
                if self.get_server_count(command.guild) < self.max_allowable_servers:
                    if not os.path.exists(os.path.join(self.get_guild_name(command.guild), server_name)):
                        with ServerMaker(server_location=os.path.join(self.get_guild_save_location(command.guild), server_name),
                                         jar_version=jar_version) as maker:
                            maker.make_server()
                        logging.info(f"Server {server_name} created for guild {self.get_guild_name(command.guild)}")
                    else:
                        logging.warning(f"Server {server_name} already exists for guild {self.get_guild_name(command.guild)}")
                else:
                    logging.warning(f"Guild {self.get_guild_name(command.guild)} has reached maximum servers {self.max_allowable_servers}")
            except AttributeError:
                logging.warning(f"Guild {self.get_guild_name(command.guild)} already has a server named {server_name}")
        except AssertionError:
            logging.info(f"Message '{command.message.content}' from {command.message.author} is not formatted properly")

    def get_server_count(self, guild: discord.Guild):
        return len(os.listdir(self.get_guild_save_location(guild)))

    def get_guild_name(self, guild: discord.Guild):
        return guild.name.lower().replace(" ", "_")

    def get_guild_save_location(self, guild: discord.Guild):
        os.makedirs(os.path.join(self.server_save_location, self.get_guild_name(guild)), exist_ok=True)
        return os.path.join(self.server_save_location, self.get_guild_name(guild))


if __name__ == "__main__":
    # configure client
    server_bot = commands.Bot(command_prefix="$")
    server_bot.add_cog(MinecraftServerManager(bot=server_bot))
    server_bot.run(config("TOKEN"))
