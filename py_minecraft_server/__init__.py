"""
Next step: make custom exceptions
"""
from bs4 import BeautifulSoup
from multiprocessing import Process, freeze_support
import math
import os
import psutil
import re
import requests
import shutil
import socket
import subprocess
import time
import wget


class cd:
    def __init__(self, new_path):
        self.new_path = os.path.expanduser(new_path)

    def __enter__(self):
        self.saved_path = os.getcwd()
        os.chdir(self.new_path)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.saved_path)


class VersionException(Exception):
    def __init__(self, entered_version=None):
        self.entered_version = entered_version

    def get_user_input(self):
        return self.entered_version


class ServerAlreadyExistsException(Exception):
    def __init__(self, attempted_location=None):
        self.attempted_location = attempted_location

    def get_attempted_location(self):
        return self.attempted_location


class ServerLoader:
    def __init__(self, server_location: str, mem_allocation: float, _override=False, _auto_load=True):
        """
        Create a server loading device which will load the server isn't that great.
        :param server_location: the location of the server
        :param mem_allocation: the amount of memory in GB to allocate towards running the server
        :param _override: if you want to run the server with more than 75% of available RAM
        """
        # ensure the server exists
        self.server_location = os.path.abspath(server_location)
        self.server_name = os.path.basename(self.server_location)
        assert os.path.exists(self.server_location)

        # sets the memory allocation to no more than 3/4 the available ram UNLESS the user passes _override=True
        self.mem_allocation = mem_allocation
        if not _override:
            self.mem_allocation = min(mem_allocation, self.get_max_mem_allocation())

        # automatically preform a server properties load
        self.server_process = None
        self.properties = {}
        if _auto_load:
            self.load_server()

    def load_server(self):
        """
        Reads the properties from server.properties with ***dict comprehension***.
        """
        self.properties = {line.strip().split("=")[0]: line.strip().split("=")[1] for line in
                           open(os.path.join(self.server_location, "server.properties"), "r").readlines()
                           if not line.startswith("#")}

    def save_server(self):
        """
        More of my best friend ***dict comprehension*** here to write some lines with style and output to a file (song).
        """
        if not self.is_running():
            new_lines = [f"{key.split('=')[0]}={self.properties[key.split('=')[0]]}\n" if "=" in key else key
                         for key in open(os.path.join(self.server_location, "server.properties"), "r").readlines()]
            open(os.path.join(self.server_location, "server.properties"), "w").writelines(new_lines)

    def migrate_version(self, new_version: str):
        """
        Will download and replace the old .jar, may break the server.
        :param new_version: new version
        """
        if not self.is_running():
            try:
                old_version = self.get_current_version()
                ServerMaker.download_jar(self.server_location, f"minecraft_server.{new_version}.jar", new_version)
                os.remove(os.path.join(self.server_location, f"minecraft_server.{old_version}.jar"))
            except IndexError:
                ServerMaker.download_jar(self.server_location, f"minecraft_server.{new_version}.jar", new_version)

    def start_server(self):
        self.server_process = Process(target=self.run_server)
        self.server_process.start()
        return self.server_process

    def run_server(self):
        with cd(self.server_location):
            os.system(f"java -Xms{int(self.mem_allocation)}G -Xmx{int(self.mem_allocation)}G -jar minecraft_server.{self.get_current_version()}.jar")
        self.stop_server()

    def stop_server(self):
        try:
            self.server_process.close()
        except ValueError:
            pass
        self.save_server()

    def is_running(self):
        """
        Is the server currently running (cause multithreading maybe)
        :return: True or False
        """
        try:
            return self.server_process.is_alive()
        except ValueError:
            return False

    def get_process(self):
        return self.server_process

    def change_property(self, property_name: str, val):
        """
        Basically just self.properties[property_name] = val, one day I'll add some input validation.
        :param property_name: key
        :param val: val
        """
        if not self.is_running():
            self.properties[property_name] = val

    def set_properties(self, new_properties):
        """
        Overwrite the whole properties dict with one of your own, if you're into that
        :param new_properties: the dict to replace the old one.
        """
        if not self.is_running():
            self.properties = new_properties

    def set_mem_allocation(self, mem_allocation: float, _override=False):
        """
        Sets the RAM in GB with a max value of 0.75 available RAM. Pass _override=True to get around this
        :param mem_allocation: new RAM in GB
        :param _override: Do you know what you are doing?
        :return new RAM so you can see if it was overridden
        """
        if not self.is_running():
            self.mem_allocation = mem_allocation
            if not _override:
                self.mem_allocation = min(self.mem_allocation, self.get_max_mem_allocation())
            return self.get_mem_allocation()

    def get_properties(self):
        return self.properties

    def get_mem_allocation(self):
        return self.mem_allocation

    def get_server_name(self):
        return self.server_name

    def get_server_location(self):
        return self.server_location

    def get_current_version(self):
        """
        Analyzes the .jar file found in os.listdir() THERE BETTER ONLY BE ONE DON'T GO ADDING A SECOND
        :return: current version str
        """
        return re.search(r"minecraft_server.(?P<version>(.\d*)*).jar",
                         [jar for jar in os.listdir(self.server_location) if ".jar" in jar][0],
                         re.IGNORECASE).group("version")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __repr__(self):
        return f"Server: {self.server_name} running version {self.get_current_version()} with {self.get_mem_allocation()}GB of RAM"

    @staticmethod
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]

    @staticmethod
    def get_external_ip():
        return requests.get("https://api.ipify.org").text

    @staticmethod
    def get_max_mem_allocation():
        return int((psutil.virtual_memory().available / math.pow(10, 9)) * 0.75)


class ServerMaker:
    def __init__(self, server_location: str, jar_version=None, overwrite=False):
        # define location and create it if it doesn't exist
        self.server_location = os.path.abspath(server_location)
        if overwrite and os.path.exists(self.server_location):
            shutil.rmtree(self.server_location)
        if not os.path.exists(server_location):
            os.makedirs(self.server_location, exist_ok=True)
            self.jar_version = jar_version
            if not jar_version:
                self.jar_version = self.get_current_minecraft_version()
            self.jar_name = f"minecraft_server.{self.jar_version}.jar"
        else:
            raise ServerAlreadyExistsException(server_location)

    def make_server(self):
        self.download_jar(self.server_location, self.jar_name, self.jar_version)
        with cd(self.server_location):
            subprocess.run(f"java -Xms1G -Xmx1G -jar {self.jar_name}")
            eula_lines = open("eula.txt", "r").readlines()[:2] + ["eula=true\n"]
            open("eula.txt", "w").writelines(eula_lines)
        return self

    def get_number_of_servers(self):
        """
        :return: The number of servers adjacent to the current server
        """
        return os.listdir(os.path.basename(self.server_location))

    def get_server_location(self):
        return self.server_location

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @staticmethod
    def download_jar(jar_save_location: str, jar_save_name: str, jar_version: str):
        """
        Goes to the depth of the web to expose my computer to virus'.
        """
        try:
            download_link = [link for link in
                             BeautifulSoup(requests.get(f"https://mcversions.net/download/{jar_version}").content,
                                           "html.parser").find_all("a", href=True)
                             if "server" in link["href"] and "mojang" in link["href"]][0]
            wget.download(download_link["href"], os.path.join(jar_save_location, jar_save_name))
        except IndexError:
            raise VersionException(jar_version)

    @staticmethod
    def get_current_minecraft_version():
        return re.search(r"minecraft_server.(?P<version>(.\d*)*).jar",
                         BeautifulSoup(requests.get(r"https://www.minecraft.net/en-us/download/server").content,
                                       "html.parser").find("div", {"class": "minecraft-version"}).
                         find("a").text, re.IGNORECASE).group("version")


if __name__ == "__main__":
    # needed for windows
    freeze_support()

    ServerMaker("training", overwrite=True).make_server()
    with ServerLoader("training", 10) as loader:
        loader.start_server()
        while loader.is_running():
            print("AGONY")
            time.sleep(1)
        print("RELEASE")
