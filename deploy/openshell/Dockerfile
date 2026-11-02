# OpenJarvis agent image for OpenShell sandboxes (D-041).
#
# Built by scripts/build-openshell-image.sh, which stages the OpenJarvis
# wheel, a hash-locked requirements file and the Linux wheels it needs into
# build/, so the build itself needs no network. The build context
# is this directory only, so nothing else from the repository (or a .env)
# can end up in the image.
#
# The venv's python3 resolves to /usr/local/bin/python3.12; OpenShell network
# rules match that resolved path (openjarvis.sandbox.openshell_policy).
FROM docker.io/library/python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

# OpenShell refuses images without a "sandbox" user and group, and its
# supervisor needs iproute2 to create the sandbox's network namespace.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system sandbox \
    && useradd --system --gid sandbox --home-dir /sandbox --shell /bin/sh sandbox \
    && mkdir -p /sandbox \
    && chown sandbox:sandbox /sandbox

# Offline install from the staged, hash-checked wheels. The venv stays
# root-owned so a run cannot modify the installed code.
COPY build/ /tmp/openjarvis/
RUN python -m venv /sandbox/.venv \
    && /sandbox/.venv/bin/pip install --no-cache-dir --no-index \
        --find-links /tmp/openjarvis/wheels --require-hashes \
        -r /tmp/openjarvis/requirements.txt \
    && /sandbox/.venv/bin/pip install --no-cache-dir --no-index --no-deps \
        /tmp/openjarvis/*.whl \
    && rm -rf /tmp/openjarvis

USER sandbox
WORKDIR /sandbox
