"""Optional rtk command proxy — reduces LLM token consumption by filtering command output."""
import shutil
from functools import lru_cache


@lru_cache(maxsize=1)
def rtk_available() -> bool:
    return shutil.which("rtk") is not None


def wrap_cmd(cmd: list[str]) -> list[str]:
    """Prepend 'rtk' to cmd if rtk is available, otherwise return cmd unchanged."""
    if not rtk_available():
        return cmd
    return ["rtk"] + cmd
