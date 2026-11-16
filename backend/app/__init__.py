"""Animal Kingdom backend application package."""

import os

# Embedding model is cached locally; block all outbound HF/transformers network calls.
# Must run before any third-party import: langchain_core pulls in transformers ->
# huggingface_hub, which reads these flags once at import time.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
