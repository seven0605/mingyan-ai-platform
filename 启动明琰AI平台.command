#!/bin/zsh
project_dir="$(cd "$(dirname "$0")" && pwd)"
exec "$project_dir/scripts/start-macos.sh"
