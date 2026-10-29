#!/bin/zsh
# ./run.sh            -> MetalMate from source
# ./run.sh practice   -> the practice board on its own
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && ./.venv/bin/python -m pip install -q -r requirements.txt || exit 1
fi
if [ "$1" = "practice" ]; then
  exec ./.venv/bin/python -m metalmate.practice
fi
exec ./.venv/bin/python -m metalmate
