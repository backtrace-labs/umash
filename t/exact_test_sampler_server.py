"""Wraps exact_test_sampler.ExactTestSampler in a trivial gRPC server.

We currently only support listening on localhost, because secure gRPC
is annoying.  Use an ssh tunnel to actually distribute computation.
"""
import argparse
import concurrent
import logging
import grpc
import os

from exact_test_sampler import ExactTestSampler, ensure_pool
import exact_test_sampler_pb2_grpc as sampler_grpc


# We let the number of concurrent requests scale with the cpu count,
# up to MAX_CONCURRENT_REQUESTS: at some point, it stops making sense
# to timeslice a machine.  This also avoids spinning up too many
# Python threads when there's a lot of cores (e.g., on a 256-thread
# Xeon Phi).
MAX_CONCURRENT_REQUESTS = 32


def setup_server(port=None):
    num_requests = min(2 * os.cpu_count(), MAX_CONCURRENT_REQUESTS)
    server = grpc.server(
        concurrent.futures.ThreadPoolExecutor(max_workers=2 * num_requests),
        maximum_concurrent_rpcs=num_requests,
    )
    sampler_grpc.add_ExactTestSamplerServicer_to_server(ExactTestSampler(), server)

    listening_address = "localhost:0"
    if port is not None:
        listening_address = "localhost:%i" % port

    actual_port = server.add_secure_port(
        listening_address, grpc.local_server_credentials()
    )
    if actual_port == 0:
        raise Exception("Failed to open port %s for gRPC server." % port)
    return server, actual_port


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ExactTestSampler gRPC server.")
    parser.add_argument(
        "port",
        metavar="Port",
        type=int,
        nargs="?",
        help="Port for the gRPC server (picks one if not set).",
    )
    args = parser.parse_args()
    logging.basicConfig()

    # Make sure to spin up our worker pools before the gRPC server:
    # while we don't use gRPC in the workers, forking after creating
    # a server seems to be #unsupported:
    # https://github.com/grpc/grpc/issues/16001#issuecomment-433794991
    ensure_pool()
    server, actual_port = setup_server(args.port)
    print("ExactTestSampler listening on localhost:%i" % actual_port)
    server.start()
    server.wait_for_termination()
