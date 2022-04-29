import logging
from typing import NamedTuple
from dataclasses import dataclass


@dataclass
class RecorderState:
    kinect_alias: int = None
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
    participating_kinects = tuple()


class KinectParams(NamedTuple):
    rgb_res: int = 1440
    depth_wfov: bool = False
    depth_binned: bool = False
    fps: int = 30
    sync: bool = False

    _rgb_res_str2val = {
        "1280x720": 720, "1920x1080": 1080, "2560x1440": 1440,
        "2048x1536": 1536, "3840x2160": 2160, "4096x3072": 3072
    }
    _rgb_res_val2str = {
        720: "1280x720", 1080: "1920x1080", 1440: "2560x1440",
        1536: "2048x1536", 2160: "3840x2160", 3072: "4096x3072"
    }
    _depth_mode_str2val = {
        # tuple is (WFOV, binned)
        "WFOV unbinned (1024x1024)": (True, False), "WFOV binned    (512x512)": (True, True),
        "NFOV unbinned  (640x576)": (False, False), "NFOV binned    (320x288)": (False, True)
    }
    _depth_mode_val2str = {
        # tuple is (WFOV, binned)
        (True, False): "WFOV unbinned (1024x1024)", (True, True): "WFOV binned    (512x512)",
        (False, False): "NFOV unbinned  (640x576)", (False, True): "NFOV binned    (320x288)"
    }
    _fps_range = [5, 10, 15, 30]


# Exceptions
class KinectNotReadyException(Exception):
    pass

class RecorderDisconnectedException(Exception):
    pass

#Logging
class ColoredFormatter(logging.Formatter):

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = '%(asctime)s:%(name)s:%(levelname)s::: %(message)s'

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._formatters = {level: logging.Formatter(log_fmt, datefmt='%H:%M:%S') for level, log_fmt in
                       self.FORMATS.items()}

    def format(self, record):
        formatter = self._formatters.get(record.levelno)
        return formatter.format(record)

