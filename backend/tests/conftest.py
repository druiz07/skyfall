import os

# Tests never touch Space-Track, even when .env holds real credentials.
os.environ["SKYFALL_SOURCE"] = "demo"
# No background zone warm-up: tests ask for exactly the zones they need.
os.environ["SKYFALL_WARMUP"] = "0"
