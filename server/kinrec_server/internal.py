from typing import NamedTuple
from dataclasses import dataclass


@dataclass
class RecorderState:
    kinect_id: int = None
    status: str = "offline"  # "offline", "ready", "preview", "recording", "kin. not ready"
    free_space: int = 0  # in GB
    bat_power: int = 0  # 0..100


class RecordsEntry(NamedTuple):
    id: int = 0  # unique id, currently: timestamp of server time of the recording start
    date: int = 0  # timestamp of date
    name: str = ""  # name of the recorded sequence
    length: int = 0  # in seconds
    params: dict = None  # recording_params
    size: float = 0.0  # in MB
    status: str = ""  # Consistent (n/n) or Inconsistent (m/n, missing: k_i)
