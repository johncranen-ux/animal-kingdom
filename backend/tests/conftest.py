import os

# Use only locally cached HuggingFace models — avoids SSL cert failures on this machine.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
