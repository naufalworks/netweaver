#!/bin/bash
set -e

# Run tests
python -m pytest tests/ -v

# Commit
if [ ! -d ".git" ]; then
  git init
fi
git add -A
git commit -m "Initial commit: NetWeaver Daemon"