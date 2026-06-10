import os

os.environ.setdefault("SECRET_KEY", "tests-only-secret-key-with-more-than-32-characters")
os.environ.setdefault("TOKEN_ISSUER", "mps-server")
os.environ.setdefault("TOKEN_AUDIENCE", "nanoclaw-client")
