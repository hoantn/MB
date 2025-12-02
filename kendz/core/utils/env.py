# kendz/core/utils/env.py
import os
def get_env(name, default=None): return os.getenv(name, default)
