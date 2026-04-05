# Sssnakey Bot

Sssnakey is a defensive, survival-first BeatMyBot bot written in Python. It prioritizes staying alive, avoiding traps, and only taking risky routes when food pressure is high.

## What It Does

The bot reads the game state from standard input and outputs a JSON response with two fields:

- move: one of UP, DOWN, LEFT, or RIGHT
- shed: a boolean flag used by the engine when the bot decides it is worth shedding

Its decision-making focuses on:

- avoiding walls, trees, snake bodies, and the outer boundary
- preferring moves with more reachable space and fewer dead-end risks
- treating poison apples as last-resort options
- favoring closer, higher-value apples when hunger becomes urgent
- staying away from the opponent head and its immediate threat zone
- occasionally choosing active blocking or shedding plays when the board state makes that safe

## Files

- [bot.py](bot.py) contains the full strategy and the runtime entrypoint.
- [config.json](config.json) defines the bot name and container command.
- [Dockerfile](Dockerfile) builds the runtime image used by the engine.
- [requirements.txt](requirements.txt) is intentionally empty unless you add dependencies.

## Run Locally

The bot is configured to run with Python 3.12 using the command defined in [config.json](config.json):

python -u bot.py

If you want to test it manually, run it from this folder and feed it the game state JSON on standard input. The bot prints a single JSON response per turn.

## Docker

The included [Dockerfile](Dockerfile) uses python:3.12-slim, copies the bot into /bot, installs requirements if present, and starts the bot in unbuffered mode.

To build and test it with the rest of the project, use the repo-level scripts described in the main [README.md](../../README.md).

## Strategy Notes

Sssnakey is designed to survive long games instead of taking reckless fights. It uses a mix of flood-fill space estimation, apple scoring, hunger thresholds, and opponent proximity checks to rank safe moves. When energy gets low, it switches into emergency food-seeking behavior and relaxes some growth-avoidance rules.

If you change the strategy, keep the output contract stable:

- read one JSON game state per line from stdin
- write one JSON object per turn to stdout
- keep the response keys compatible with the engine

## Dependencies

There are no third-party dependencies at the moment. If you add any, update [requirements.txt](requirements.txt) and rebuild the Docker image.
