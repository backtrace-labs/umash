"""This module is responsible for reading the `.sampler_servers.ini`
configuration file, and establishing gRPC connections to each endpoint
listed in that file.  If that file is empty, we also read
`sampler_servers.ini.dist`.

Each entry has the form

[upstream_name]
hostname = hostname # defaults to upstream_name
port = 12345 # or some other port

"""
import configparser
import grpc
import os
import sys

from exact_test_sampler_pb2_grpc import ExactTestSamplerStub

SELF_DIR = os.path.dirname(os.path.abspath(__file__))
TOPLEVEL = os.path.abspath(SELF_DIR + "/../") + "/"
CONFIG_PATH = TOPLEVEL + ".sampler_servers.ini"
SECONDARY_CONFIG_PATH = TOPLEVEL + "sampler_servers.ini.dist"


def parse_sampler_servers(path=CONFIG_PATH):
    config = configparser.ConfigParser()
    ret = []
    try:
        config.read(path)
        for host in config:
            if host == "DEFAULT":
                continue
            hostname = host
            if "hostname" in config[host]:
                hostname = config[host]["hostname"]
            ret.append(hostname + ":" + config[host]["port"])
    except FileNotFoundError:
        pass
    return ret


def _print_sampler_servers():
    try:
        servers = parse_sampler_servers()
        if not servers:
            servers = parse_sampler_servers(SECONDARY_CONFIG_PATH)
    except Exception as e:
        print("Exc: %s" % e)
        servers = []
    print("Found %i sampler servers in %s." % (len(servers), CONFIG_PATH))


_print_sampler_servers()


def get_sampler_servers():
    ret = []
    # Disable remote connections in pytest.
    if "pytest" in sys.modules:
        return ret
    servers = parse_sampler_servers()
    if not servers:
        servers = parse_sampler_servers(SECONDARY_CONFIG_PATH)
    for connection_string in servers:
        try:
            channel = grpc.insecure_channel(connection_string)
            ret.append(ExactTestSamplerStub(channel))
        except Exception as e:
            print(
                "Unabled to open connection to %s: %s." % (connection_string, e),
                file=sys.stderr,
            )
    return ret
