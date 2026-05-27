#!/bin/bash
set -e

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "Error: git is not installed." >&2
    exit 1
fi

# Check if already a git repository
if [ -d ".git" ]; then
    echo "Git repository already initialized."
    exit 0
fi

# Initialize git repository
git init

# Add .gitignore if exists
if [ -f ".gitignore" ]; then
    git add .gitignore
fi

# Commit initial state
git commit -m "Initial commit"

echo "Git repository initialized with initial commit."
