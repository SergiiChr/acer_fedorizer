#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec /usr/bin/python3 -m control_center "$@"
