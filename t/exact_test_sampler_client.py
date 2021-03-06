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

from exact_test_sampler_pb2 import StatusRequest
from exact_test_sampler_pb2_grpc import ExactTestSamplerStub

SELF_DIR = os.path.dirname(os.path.abspath(__file__))
TOPLEVEL = os.path.abspath(SELF_DIR + "/../") + "/"
CONFIG_PATH = TOPLEVEL + ".sampler_servers.ini"
SECONDARY_CONFIG_PATH = TOPLEVEL + "sampler_servers.ini.dist"


CONNECTION_TIMEOUT = 5  # seconds


def parse_sampler_servers(path=CONFIG_PATH):
    config = configparser.ConfigParser()
    ret = []
    use_local = True
    inline_eval = True
    try:
        config.read(path)
        use_local = config.getboolean(
            "local_sampler_executor", "local_parallelism", fallback=True
        )
        inline_eval = config.getboolean(
            "local_sampler_executor", "inline_evaluation", fallback=True
        )
        for host in config:
            if host == "DEFAULT":
                continue
            if host == "local_sampler_executor":
                continue
            hostname = config.get(host, "hostname", fallback=host)
            ret.append((host, hostname + ":" + config.get(host, "port")))
    except FileNotFoundError:
        pass
    return ret, use_local, inline_eval


def _print_sampler_servers():
    path = CONFIG_PATH
    try:
        servers, *_ = parse_sampler_servers(path)
        if not servers:
            path = SECONDARY_CONFIG_PATH
            servers, *_ = parse_sampler_servers(path)
    except Exception as e:
        print("Exc: %s" % e)
        servers = []
    print("Found %i sampler servers in %s." % (len(servers), path))


_print_sampler_servers()


def get_sampler_servers(local_stub=None):
    """Parses the config file (or the fallback at the checked in location)
    to get a list of connection strings, and to determine whether local
    parallel evaluation is enabled.

    Returns a list of stubs for each configured connection, including
    local_stub`, the local parallel evaluation object, if provided
    and local parallelism is enabled (not explicitly disabled).

    As a second value, returns whether inline (single-threaded)
    evaluation is enabled.
    """
    ret = []
    # Disable remote connections in pytest.
    if "pytest" in sys.modules:
        return ([local_stub] if local_stub is not None else []), True
    servers, use_local, inline_eval = parse_sampler_servers()
    if not servers:
        servers, use_local, inline_eval = parse_sampler_servers(SECONDARY_CONFIG_PATH)
    if use_local and local_stub is not None:
        ret.append(local_stub)
    for name, connection_string in servers:
        try:
            channel = grpc.insecure_channel(connection_string)
            stub = ExactTestSamplerStub(channel)
            status = stub.status(StatusRequest(), timeout=CONNECTION_TIMEOUT)
            print(
                "Succesfully connected to %s @ %s (status=%s)."
                % (name, connection_string, status),
                file=sys.stderr,
            )
            ret.append(stub)
        except Exception as e:
            print(
                "Unabled to open connection %s to %s: %s."
                % (name, connection_string, e),
                file=sys.stderr,
            )
    return ret, inline_eval
