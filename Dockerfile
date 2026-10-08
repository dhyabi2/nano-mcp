# The image an MCP directory builds in order to introspect this server.
#
# Glama -- which `punkpeye/awesome-mcp-servers` gates its listing on -- asks for
# a Dockerfile and then does one thing with it: start the container and speak
# JSON-RPC over stdio until it has an answer to `tools/list`. Their bot states
# the whole bar in one line: "we only need the server to start and respond to
# introspection requests". `tools/directory_handshake.py` runs exactly that
# exchange, and `tests/test_directory_handshake.py` runs it against the same
# command this file starts, so the image and the suite cannot drift apart.
FROM python:3.11-slim

# Nothing is compiled here, on purpose. ed25519-blake2b-fork -- the one C
# extension in the dependency set -- publishes manylinux and musllinux wheels
# for cp38 through cp314, so this base resolves the whole tree from wheels. The
# reflex of apt-get installing gcc first would only make the image slower to
# build and larger for a directory to pull.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY . /src

# The declared dependencies, resolved from scratch -- not a pinned list. The
# `test` workflow's own comment says why, and it was written about this package:
# `mcp>=1.0` was satisfiable by a version that cannot import the server, so
# pinning the builder's versions is how an image goes green on a commit whose
# declaration cannot start the thing it installs.
RUN pip install .

# stdio is the transport an MCP host speaks, so the container has to stay
# attached to its stdin: `docker run -i`, never `-d`.
#
# No NANO_PAYMENT_MASTER_SECRET is baked in and none is generated. Unconfigured,
# the server still starts and lists every tool -- which is all a directory's
# check needs -- and the address-deriving tools refuse, naming the variable to
# set. A stand-in secret would derive payment addresses whose private keys die
# with the container, and XNO sent to one of those is unrecoverable by anyone.
CMD ["nano-mcp"]
