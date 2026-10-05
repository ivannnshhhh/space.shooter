import importlib


MODULES = [
    "settings",
    "camera",
    "hand_tracking",
    "player",
    "enemy",
    "boss",
    "bullet",
    "explosion",
    "particle",
    "ui",
    "game",
]


for name in MODULES:
    importlib.import_module(name)
