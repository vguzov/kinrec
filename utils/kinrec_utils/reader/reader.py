import json
import numpy as np
from videoio import VideoReader, Uint16Reader, VideoWriter
from pathlib import Path
from typing import Union, List, Optional, Tuple, Dict
from loguru import logger

from .videoscroller import VideoScroller, Uint16Scroller
from .spatial import KinectSpatialOperator


class KinectTimestamps:
    NEWFORMAT_CONVERSION_MAP = {
        "color": "device_color_usec",
        "depth": "device_depth_usec",
        "system_color": "monotonic_color_nsec",
        "system_depth": "monotonic_depth_nsec"
    }

    def __init__(self, timestamps_path):
        timestamps = {k: np.asarray(v, dtype=np.int64) for k, v in
                      json.load(Path(timestamps_path).open()).items()}
        # If older version, convert it to the new format
        if 'color' in timestamps:
            timestamps = {self.NEWFORMAT_CONVERSION_MAP[k]: v for k, v in timestamps.items() if k in self.NEWFORMAT_CONVERSION_MAP}
        # Convert to numpy array in float64 seconds
        self.timestamps = {}
        for k, v in timestamps.items():
            self.timestamps[k[:-5]] = v.astype(np.float64) / (1e6 if k.endswith("usec") else 1e9)
        self.timestamps_offsets = {k: 0. for k, v in self.timestamps.items()}

    def __getitem__(self, item):
        return self.timestamps[item] + self.timestamps_offsets[item]

    @property
    def device_color(self):
        return self["device_color"]

    @property
    def device_depth(self):
        return self["device_depth"]

    @property
    def monotonic_color(self):
        return self["monotonic_color"]

    @property
    def monotonic_depth(self):
        return self["monotonic_depth"]

    @property
    def system_received(self):
        return self["system_received"]

    def set_offset(self, offset_name, offset):
        self.timestamps[offset_name] += offset


KinectID = str


class KinectRecording:
    alias: Dict[KinectID, int]
    ralias: Dict[int, KinectID]
    spatial_operators: Dict[KinectID, KinectSpatialOperator]
    timestamps: Dict[KinectID, KinectTimestamps]
    metadata: Dict

    def __init__(self, rec_dir, cache_size=100, cached_colored_pc=False):
        self.rec_dir = Path(rec_dir)
        self.color_dir = self.rec_dir / "color"
        self.depth_dir = self.rec_dir / "depth"
        self.depthcolor_dir = self.rec_dir / "depthcolor"
        self.metadata = json.load((self.rec_dir / "metadata.json").open())
        self.kinects = self.metadata['participating_kinects']
        self.timestamps = self.load_timestamps()
        self.alias = {k: v['alias'] for k, v in self.kinects.items()}
        self.ralias = {v['alias']: k for k, v in self.kinects.items()}
        self.spatial_operators = {}
        self.extrinsics = None
        if (self.rec_dir / "extrinsics.json").is_file():
            self.extrinsics = json.load((self.rec_dir / "extrinsics.json").open())
        for kinect_id, kinect_info in self.kinects.items():
            file_prefix = kinect_info['file_prefix']
            pc_table = np.load(self.rec_dir / f"depth2pc_maps/{file_prefix}.npz")
            pc_table = pc_table[list(pc_table.keys())[0]]
            self.spatial_operators[kinect_id] = KinectSpatialOperator(kinect_info, pc_table,
                                                            extrinsics=None if self.extrinsics is None else self.extrinsics["extrinsics"][kinect_id])
        # self.color_readers = None
        self.color_readers = {}
        self.depth_readers = {}
        for kinect_id, kinect_info in self.kinects.items():
            file_prefix = kinect_info['file_prefix']
            self.color_readers[kinect_id] = VideoScroller(self.color_dir / f"{file_prefix}.mp4", cache_size=cache_size)
            self.depth_readers[kinect_id] = Uint16Scroller(self.depth_dir / f"{file_prefix}.mp4", cache_size=cache_size)
        if cached_colored_pc:
            self.depthcolor_readers = {}
            for kinect_id, kinect_info in self.kinects.items():
                file_prefix = kinect_info['file_prefix']
                self.depthcolor_readers[kinect_id] = VideoScroller(self.depthcolor_dir / f"{file_prefix}.mp4", cache_size=cache_size)
        else:
            self.depthcolor_readers = None

    def load_timestamps(self):
        timestamps = {}
        for kinect_id, kinect_info in self.kinects.items():
            file_prefix = kinect_info['file_prefix']
            timestamps[kinect_id] = KinectTimestamps(self.rec_dir / f"times/{file_prefix}.json")
        return timestamps

    @staticmethod
    def find_closest_frame(timestamps, frame_timestamp) -> int:
        return np.argmin(np.abs(timestamps - frame_timestamp))

    def get_closest_frame_by_timestamp(self, kinect_id, timestamp_name, curr_frame_timestamp):
        kinect_timestamps = self.timestamps[kinect_id]
        kinect_frame_ind = self.find_closest_frame(kinect_timestamps[timestamp_name], curr_frame_timestamp)
        return kinect_frame_ind

    def _get_data_by_timestamp(self, data_readers, timestamp_name, frame_timestamp):
        frames = {}
        for kinect_id, kinect_info in self.kinects.items():
            kinect_frame_ind = self.get_closest_frame_by_timestamp(kinect_id, timestamp_name, frame_timestamp)
            reader = data_readers[kinect_id]
            frame = reader.get_frame(kinect_frame_ind)
            frames[kinect_id] = frame
        return frames

    def get_color_device_time(self, frame_timestamp):
        return self._get_data_by_timestamp(self.color_readers, "device_color", frame_timestamp)

    def get_color_system_received_time(self, frame_timestamp):
        return self._get_data_by_timestamp(self.color_readers, "system_received", frame_timestamp)

    def get_depth_device_time(self, frame_timestamp):
        return self._get_data_by_timestamp(self.depth_readers, "device_depth", frame_timestamp)

    def get_depth_system_received_time(self, frame_timestamp):
        return self._get_data_by_timestamp(self.depth_readers, "system_received", frame_timestamp)

    def get_pc_by_timestamp(self, timestamp_name, frame_timestamp, map2colorworld=False, map2global=False, return_color=False):
        pcs = {}
        if map2global and not map2colorworld:
            logger.warning("map2global without map2colorworld produces incorrect results as of now, setting map2colorworld to True")
            map2colorworld = True
        for kinect_id, kinect_info in self.kinects.items():
            kinect_frame_ind = self.get_closest_frame_by_timestamp(kinect_id, timestamp_name, frame_timestamp)
            reader = self.depth_readers[kinect_id]
            depth = reader.get_frame(kinect_frame_ind)
            pc, pc_validmask = self.spatial_operators[kinect_id].dmap2pc(depth, return_mask=True, map2colorworld=map2colorworld)
            if map2global:
                res_pc = self.spatial_operators[kinect_id].pc2global(pc)
            else:
                res_pc = pc
            if return_color:
                if self.depthcolor_readers is None:
                    logger.warning("No cached colored pointclouds loaded (initialize with cached_colored_pc=True to load), "
                                   "generating on the fly. This may be slow.")
                    color = self.color_readers[kinect_id].get_frame(kinect_frame_ind)
                    pc_colors = self.spatial_operators[kinect_id].compute_pc_colors(pc, color, map2colorworld=not map2colorworld)
                else:
                    depthcolor = self.depthcolor_readers[kinect_id].get_frame(kinect_frame_ind)
                    pc_colors = depthcolor[pc_validmask]
                pcs[kinect_id] = (res_pc, pc_colors)
            else:
                pcs[kinect_id] = res_pc
        return pcs

    def get_pc_device_time(self, frame_timestamp, map2colorworld=False, return_color=False, map2global=False):
        return self.get_pc_by_timestamp("device_color", frame_timestamp, map2colorworld, map2global, return_color)

    def set_device_time_offsets(self, *offsets):
        for kinect_alias, offset in zip(sorted(self.ralias.keys()), offsets):
            self.timestamps[self.ralias[kinect_alias]].set_offset("device_color", offset)
            self.timestamps[self.ralias[kinect_alias]].set_offset("device_depth", offset)
