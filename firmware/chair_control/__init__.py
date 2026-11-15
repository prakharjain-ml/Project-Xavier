"""chair_control package: lets other code do `from chair_control import Chair` from the project root."""
from .chair import Chair, DEFAULT_MAX_SPEED, DEFAULT_PORT

__all__ = ["Chair", "DEFAULT_MAX_SPEED", "DEFAULT_PORT"]
