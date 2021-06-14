from bs4 import BeautifulSoup
import aiohttp
import aiofiles
import coloredlogs
import logging
import math
import os
import psutil
import re
import requests
import socket
import shutil
import subprocess
import sys
import wget

# configure logger
coloredlogs.install(level=logging.DEBUG)
logging.basicConfig(
    format="%(asctime)s %(levelname)s:%(name)s: %(message)s",
    level=logging.DEBUG,
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("py-server")
logging.getLogger("asyncio").disabled = True


def get_jar_name(version: str) -> str:
    """Normalizes the jar naming scheme, returns minecraft_server.{version}.jar"""
    return f"minecraft_server.{version}.jar"


# custom exceptions
class ExceedMaxServerCountException(Exception):
    pass


class ServerNameTakenException(Exception):
    pass


class ServerDoesNotExistException(Exception):
    pass


class VersionException(Exception):
    pass


class NoServerLoadedException(Exception):
    pass


# classes
class ServerMaker:
    def __init__(self, save_location: str, max_servers: int = 5):
        """
        A server creation object that has a save location and can make servers.
        :param save_location: The base location for servers to be saved at.
        """
        self.server_location = os.path.abspath(save_location)
        os.makedirs(self.server_location, exist_ok=True)
        self.max_servers = max_servers
        if self.max_servers < 0:
            self.max_servers = abs(self.max_servers)
        elif self.max_servers == 0:
            self.max_servers = None
        logger.debug(self.__repr__())

    def get_number_of_servers(self) -> int:
        """ Get the number of servers already saved to this location. """
        return len(os.listdir(self.server_location))

    async def make_server(self, server_name: str, server_version: str = None, overwrite=False):
        """
        Creates a server from where the ServerMaker is operating (save_location).
        :param server_name: Name for the server/file.
        :param server_version: Specified version in format #.#.# if left blank will default to most up to date version.
        :param overwrite: If true will replace a server of the same name, otherwise will throw an error for duplicate names.
        """
        if not self.max_servers or self.max_servers > self.get_number_of_servers() or (
                any([server_name.lower() == file.lower() for file in os.listdir(self.server_location)]) and overwrite):
            server_save_location = os.path.join(self.server_location, server_name)
            logger.debug(f"Creating server {server_save_location}, v={server_version}, o={overwrite}")
            if os.path.exists(server_save_location):
                if overwrite:
                    logger.info(f"Removing {server_save_location} for overwrite")
                    shutil.rmtree(server_save_location)
                else:
                    raise ServerNameTakenException()
            os.makedirs(server_save_location, exist_ok=True)

            if not server_version:
                server_version = await self.get_current_minecraft_version()

            await self.download_jar(
                os.path.join(self.server_location, server_name, get_jar_name(server_version)),
                server_version)
            subprocess.run(f"java -Xms1G -Xmx1G -jar {get_jar_name(server_version)}",
                           stdout=subprocess.DEVNULL, cwd=server_save_location)
            eula_lines = open(os.path.join(server_save_location, "eula.txt"), "r").readlines()[:2] + ["eula=true\n"]
            open(os.path.join(server_save_location, "eula.txt"), "w").writelines(eula_lines)
            logger.debug(f"Eula accepted for server {server_name}")
        else:
            raise ExceedMaxServerCountException()

    @staticmethod
    async def fetch_html(url: str, session: aiohttp.ClientSession, **kwargs) -> str:
        """GET Request wrapper to fetch page html"""
        response = await session.request(method="GET", url=url, **kwargs)
        response.raise_for_status()
        logger.info(f"Got response {response.status} for {url}")
        # await session.close()
        text = await response.text()
        return text

    @staticmethod
    async def get_current_minecraft_version() -> str:
        """Retrieves the current minecraft version from minecraft.net"""
        response = await ServerMaker.fetch_html(r"https://www.minecraft.net/en-us/download/server",
                                                aiohttp.ClientSession())
        return re.search(r"minecraft_server.(?P<version>(.\d*)*).jar",
                         BeautifulSoup(response, "html.parser").find("div", {"class": "minecraft-version"}).find(
                             "a").text).group("version")

    @staticmethod
    async def download_jar(jar_save_location: str, jar_version: str):
        """Download a jar file from mcversions.net to a location"""
        response = await ServerMaker.fetch_html(url=f"https://mcversions.net/download/{jar_version}",
                                                session=aiohttp.ClientSession())
        try:
            download_link = [link for link in
                             BeautifulSoup(response,
                                           "html.parser").find("div", {"class": "downloads"}).find_all("a", href=True)
                             if "server" in link["download"]][0]["href"]
        except IndexError:
            raise VersionException()
        logger.debug(f"Downloading server jar from {download_link} to {jar_save_location}")
        wget.download(download_link, jar_save_location)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __repr__(self):
        return f"ServerMaker loc={self.server_location}, max={self.max_servers}"


class ServerLoader:
    def __init__(self, save_location: str):
        """
        A server loader loads a specific server from a save location and edits/runs it.
        :param save_location: The directory servers are saved to.
        """
        self.save_location = os.path.abspath(save_location)
        assert os.path.exists(self.save_location)

        self.server = None
        self.properties = None
        self.mem_allocation = None
        self.server_process = None
        self.server_location = None

        logger.debug(f"Created ServerLoader targeting {self.save_location}")

    async def load_server(self, server_name: str):
        """Set which server to look for from the server save location."""
        self.server = server_name
        self.server_location = os.path.join(self.save_location, server_name)
        if not os.path.exists(self.server_location):
            raise ServerDoesNotExistException()
        await self.load_properties()
        return self

    async def load_properties(self):
        """Load the properties into self.properties dict from server.properties"""
        if not self.load_server:
            raise NoServerLoadedException()
        properties_contents = await self.get_properties_file_lines()
        self.properties = {line.strip().split("=")[0]: line.strip().split("=")[1] for line in properties_contents
                           if not line.startswith("#")}

    async def save_server(self):
        """Overwrite the server.properties file to updated properties"""
        if not self.load_server:
            raise NoServerLoadedException()
        properties_contents = await self.get_properties_file_lines()
        async with aiofiles.open(os.path.join(self.server_location, "server.properties"), "w") as properties_file:
            await properties_file.writelines(
                [f"{key.split('=')[0]}={self.properties[key.split('=')[0]]}\n" if "=" in key else key for key in
                 properties_contents])
        logger.debug("Server changes saved")

    async def get_properties_file_lines(self) -> []:
        """Returns the file lines of the server.properties file"""
        if not self.load_server:
            raise NoServerLoadedException()
        async with aiofiles.open(os.path.join(self.server_location, "server.properties"), "r") as properties_file:
            properties_contents = await properties_file.readlines()
        return properties_contents

    def start_server(self, mem_allocation: int, stdout=None, gui=False):
        """Starts the server as a Popen saved to self.server_process"""
        if not self.load_server:
            raise NoServerLoadedException()
        if not stdout:
            stdout = subprocess.DEVNULL
        gui_str = "nogui"
        if gui:
            gui_str = ""
        self.set_mem_allocation(mem_allocation)

        logger.debug(f"Attempting to start server {self.server} with RAM {mem_allocation}")
        self.server_process = subprocess.Popen(
            f"java -Xms{self.mem_allocation}G -Xmx{self.mem_allocation}G "
            f"-jar {get_jar_name(self.get_current_version())} {gui_str}",
            cwd=self.server_location, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
        logger.debug(f"Server {self.server} started with {mem_allocation}GB on {self.get_ip()}")

    def stop_server(self):
        """If the server is running, stop it"""
        if self.is_running():
            try:
                self.get_process().communicate(input=b"stop", timeout=30)
            except subprocess.TimeoutExpired:
                logger.warning(f"Server {self.server} failed to respond to stop command, killing")
                self.get_process().kill()
            logger.debug(f"Server {self.server} stopped")

    def is_running(self):
        """Check if the self.server_process Process is alive"""
        return self.server_process is not None

    def get_process(self):
        """Returns a reference to self.server_process"""
        return self.server_process

    async def server_command(self, command: str):
        """Writes a command into the server"""
        if self.is_running():
            command = bytes(command.strip().encode("unicode-escape").decode() + "\n", "utf8")
            logger.debug(f"Running command to {self.server} {command}")
            # TODO: Capture output and return it and remove the empty wait
            self.get_process().stdin.write(command)
            self.get_process().stdin.flush()
            await asyncio.sleep(5)

    def set_mem_allocation(self, mem_allocation: int):
        """Sets the mem_allocation and ensures it's no more than 50% available RAM"""
        if not self.is_running():
            self.mem_allocation = min(mem_allocation, self.get_max_mem_allocation())

    async def set_property(self, property_name: str, property_val: str):
        """Change a property of self.properties"""
        if not self.is_running():
            self.properties[property_name] = property_val
            await self.save_server()
            logger.debug(f"Server property {property_name} changed to {property_val}")

    def get_property(self, property_name: str):
        """Return a property from self.properties"""
        return self.properties[property_name]

    def get_current_version(self):
        """Reads the current version from the server jar"""
        if not self.load_server:
            raise NoServerLoadedException()
        return re.search(r"minecraft_server.(?P<version>(.\d*)*).jar",
                         [jar for jar in os.listdir(self.server_location) if ".jar" in jar][0],
                         re.IGNORECASE).group("version")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_running():
            self.stop_server()

    def __repr__(self):
        return f"Server {self.server} version {self.get_current_version()} running? {self.is_running()}"

    @staticmethod
    def get_max_mem_allocation():
        """Returns the max available memory of the computer"""
        return int((psutil.virtual_memory().available / math.pow(10, 9)) * 0.5)

    @staticmethod
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]

    @staticmethod
    def get_external_ip():
        return requests.get("https://api.ipify.org").text

    @staticmethod
    def get_ip():
        return ServerLoader.get_local_ip(), ServerLoader.get_external_ip()


if __name__ == "__main__":
    import asyncio


    async def main():
        with ServerLoader("training") as loader:
            await loader.load_server("Test")
            loader.start_server(2, gui=True)
            await asyncio.sleep(15)
            await loader.server_command("help")


    asyncio.run(main())
