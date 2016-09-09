#!/usr/bin/env bash

if [[ ! -z ${GEMFURY_REPO} ]]; then
  find dist -name "*.tar.gz" -exec curl -F package=@{} ${GEMFURY_REPO} \;
fi
