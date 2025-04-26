import numpy as np
from videoio import VideoReader, Uint16Reader
from collections import OrderedDict
from pathlib import Path
from typing import Union, Tuple

class BaseScroller:
    DataReader = None
    def __init__(self, video_path: Union[Path, str], scrolling_thresh: int = 100, cache_size: int = 100, target_fps=60., output_resolution=None):
        self.reader_frame_ind = -1
        self.scrolling_thresh = scrolling_thresh
        self.current_frame = None
        self.video_path = video_path
        self.target_fps = target_fps
        self.output_resolution = output_resolution
        self.videoiter = iter(self.DataReader(video_path, output_resolution=self.output_resolution))
        self.frame_cache = OrderedDict()
        self.frame_cache_max_size = cache_size
        self._empty_frame = np.zeros(tuple(self.resolution)[::-1] + (3,), dtype=np.uint8)
        self._frame_limit = -1

    def reload_videoreader(self, frame_ind: int):
        # if self.target_fps is not None:
        #     viter_frame_ind = int(frame_ind*self.videoiter.fps/self.target_fps)
        # else:
        #     viter_frame_ind = frame_ind
        self.videoiter = iter(
            self.DataReader(self.video_path, start_frame=frame_ind, output_resolution=self.output_resolution))
        self.current_frame = self._empty_frame.copy()
        self.reader_frame_ind = frame_ind - 1

    def add_to_cache(self, frame_data: np.ndarray, frame_ind: int):
        if frame_ind in self.frame_cache:
            return
        if len(self.frame_cache) >= self.frame_cache_max_size:
            self.frame_cache.popitem(last=False)
        self.frame_cache[frame_ind] = frame_data

    def get_frame(self, query_frame_ind: int):
        if query_frame_ind in self.frame_cache:
            self.frame_cache.move_to_end(query_frame_ind)
            return self.frame_cache[query_frame_ind]
        if query_frame_ind < 0 or (0 <= self._frame_limit <= query_frame_ind):
            return self._empty_frame.copy()
        diff = query_frame_ind - self.reader_frame_ind
        if diff >= 0 and diff < self.scrolling_thresh:
            for _ in range(diff):
                try:
                    self.reader_frame_ind += 1
                    self.current_frame = next(self.videoiter)
                    self.add_to_cache(self.current_frame, self.reader_frame_ind)
                except StopIteration:
                    try:
                        # Try once again after reloading
                        self.reload_videoreader(query_frame_ind)
                        self.reader_frame_ind += 1
                        self.current_frame = next(self.videoiter)
                        self.add_to_cache(self.current_frame, self.reader_frame_ind)
                    except StopIteration:
                        if self._frame_limit >= 0:
                            self._frame_limit = min(self._frame_limit, self.reader_frame_ind)
                        else:
                            self._frame_limit = self.reader_frame_ind
                        self.current_frame = self._empty_frame.copy()
                        return self.current_frame
            self.add_to_cache(self.current_frame, self.reader_frame_ind)
            return self.current_frame
        else:
            self.reload_videoreader(query_frame_ind)
            self.current_frame = next(self.videoiter)
            self.reader_frame_ind += 1
        self.add_to_cache(self.current_frame, self.reader_frame_ind)
        return self.current_frame

    @property
    def fps(self) -> float:
        return self.videoiter.fps

    @property
    def resolution(self) -> Tuple[int, int]:
        return self.videoiter.resolution

class VideoScroller(BaseScroller):
    DataReader = VideoReader

class Uint16Scroller(BaseScroller):
    DataReader = Uint16Reader


