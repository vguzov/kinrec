from typing import NamedTuple


class RecorderState(NamedTuple):
    kinect_id: int = None
    status: str = "offline"  # "offline", "ready", "preview", "recording", "kin. not ready"
    free_space: int = 0  # in GB
    bat_power: int = 0  # 0..100
