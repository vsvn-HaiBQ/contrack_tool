# Opt-in extension; build the existing backend image first. Existing Dockerfiles stay unchanged.
ARG BASE_IMAGE=contrack-tool-backend:local
FROM ${BASE_IMAGE}
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client default-jre-headless \
    && rm -rf /var/lib/apt/lists/*
# Tomcat binaries and application-specific configuration are operator-provided read-only mounts.
