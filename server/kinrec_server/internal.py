import logging
import numpy as np
from typing import NamedTuple, Optional, Dict
from dataclasses import dataclass
from colorama import init as colorama_init, Fore


@dataclass
class RecorderState:
    kinect_alias: int = None
    kinect_id: int = None
    status: str = "offline"  # "offline", "ready", "preview", "recording", "kin. not ready"
    free_space: int = 0  # in GB
    bat_power: int = 0  # 0..100
    bat_plugged: bool = False


@dataclass
class KinectParams:
    rgb_res: int = 1536
    depth_wfov: bool = False
    depth_binned: bool = False
    fps: int = 30
    sync: bool = True
    sync_master_id: Optional[str] = None

    @classmethod
    def from_dict(cls, pdict: dict):
        self = cls(rgb_res=pdict['resolution'],
                   depth_wfov=pdict['wfov'],
                   depth_binned=pdict['binned'],
                   fps=pdict['fps'],
                   sync=pdict['sync_mode'] != "none")
        return self

    def to_dict(self) -> dict:
        params_dict = {'resolution': self.rgb_res,
                       'wfov': self.depth_wfov,
                       'binned': self.depth_binned,
                       'fps': self.fps,
                       'sync': self.sync}
        if self.sync_master_id is not None:
            params_dict['master_id'] = self.sync_master_id
        return params_dict

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


@dataclass
class CameraParameters:
    cx: float
    cy: float
    fx: float
    fy: float
    k1: float
    k2: float
    k3: float
    k4: float
    k5: float
    k6: float
    p1: float
    p2: float
    width: int
    height: int
    cam2world: Optional[Dict[str, np.ndarray]]

    _intr_param_names = ['fx', 'fy', 'cx', 'cy', 'k1', 'k2', 'p1', 'p2', 'k3', 'k4', 'k5', 'k6', 'height', 'width']
    _opencv_param_names = ['fx', 'fy', 'cx', 'cy', 'k1', 'k2', 'p1', 'p2', 'k3', 'k4', 'k5', 'k6']

    @classmethod
    def from_dict(cls, params_dict: dict):
        params = {k: v for k, v in params_dict.items() if k in cls._intr_param_names}
        if "cam2world" in params_dict:
            params["cam2world"] = cls._extrinsics_from_dict(params_dict["cam2world"])
        else:
            params["cam2world"] = None
        return cls(**params)

    @staticmethod
    def _extrinsics_from_dict(extr_dict: dict):
        cam2world = {k: np.array(extr_dict[k], dtype=np.float64) for k in ["R", "t"]}
        return cam2world

    def to_dict(self, with_opencv: bool = True) -> dict:
        params_dict = {k: getattr(self, k) for k in self._intr_param_names}
        if self.cam2world is not None:
            params_dict["cam2world"] = self._extrinsics_to_dict()
        if with_opencv:
            params_dict["opencv"] = [params_dict[x] for x in self._opencv_param_names]
        return params_dict

    def _extrinsics_to_dict(self):
        extr_dict = {k: self.cam2world[k].tolist() for k in ["R", "t"]}
        return extr_dict


@dataclass
class KinectCalibration:
    color: CameraParameters
    depth: CameraParameters
    color2depth_R: np.ndarray
    depth2color_R: np.ndarray
    color2depth_t: np.ndarray
    depth2color_t: np.ndarray
    raw: str

    @classmethod
    def from_dict(cls, calib_dict):
        color_calib = CameraParameters.from_dict(calib_dict["color"])
        depth_calib = CameraParameters.from_dict(calib_dict["depth"])
        self = cls(color=color_calib, depth=depth_calib,
                   color2depth_R=np.array(calib_dict["color2depth"]["R"]),
                   color2depth_t=np.array(calib_dict["color2depth"]["t"]),
                   depth2color_R=np.array(calib_dict["depth2color"]["R"]),
                   depth2color_t=np.array(calib_dict["depth2color"]["t"]),
                   raw=calib_dict["raw"])
        return self

    def to_dict(self, with_opencv=True):
        calib_dict = {"color": self.color.to_dict(with_opencv),
                      "depth": self.depth.to_dict(with_opencv),
                      "color2depth": {"R": self.color2depth_R.tolist(),
                                      "t": self.color2depth_t.tolist()},
                      "depth2color": {"R": self.depth2color_R.tolist(),
                                      "t": self.depth2color_t.tolist()},
                      "raw": self.raw}
        return calib_dict


@dataclass
class RecordsEntry:
    id: int = 0  # unique id, currently: timestamp of server time of the recording start
    date: int = 0  # timestamp of date
    name: str = ""  # name of the recorded sequence
    length: float = 0  # in seconds
    params: KinectParams = None  # recording_params
    size: int = 0  # in bytes
    status: str = ""  # Consistent (n/n) or Inconsistent (m/n, missing: k_i)
    participating_kinects: Dict[str, KinectCalibration] = None

    @classmethod
    def from_dict(cls, recording_info: dict):
        recording_id = recording_info["id"]
        recording_params = KinectParams.from_dict(recording_info["kinect_calibration"]["params"])
        recording = cls(id=recording_id, name=recording_info["name"],
                        date=recording_info["server_time"], length=recording_info["duration"],
                        size=recording_info["size"], params=recording_params,
                        participating_kinects={x: None for x in recording_info["participating_kinects"]})
        return recording

    def to_dict(self):
        entry_dict = {"id": self.id, "name": self.name, "server_time": self.date, "duration": self.length,
                      "size": self.size, "status": self.status, "params": self.params.to_dict(),
                      "participating_kinects": {k: v.to_dict() for k, v in self.participating_kinects.items()}}
        return entry_dict


# Exceptions
class KinectNotReadyException(Exception):
    pass


class RecorderDisconnectedException(Exception):
    pass


# Logging
colorama_init()


class ColoredFormatter(logging.Formatter):
    format = '%(asctime)s:%(name)s:%(levelname)s::: %(message)s'

    FORMATS = {
        logging.DEBUG: Fore.LIGHTWHITE_EX + format + Fore.RESET,
        logging.INFO: format,
        logging.WARNING: Fore.YELLOW + format + Fore.RESET,
        logging.ERROR: Fore.RED + format + Fore.RESET,
        logging.CRITICAL: Fore.LIGHTRED_EX + format + Fore.RESET
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._formatters = {level: logging.Formatter(log_fmt, datefmt='%H:%M:%S') for level, log_fmt in
                            self.FORMATS.items()}

    def format(self, record):
        formatter = self._formatters.get(record.levelno)
        return formatter.format(record)
