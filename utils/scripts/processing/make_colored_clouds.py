import numpy as np
import cv2
import json
import os
from sklearn.neighbors import KDTree
from scipy.interpolate import RectBivariateSpline
from skimage.color import rgb2gray
from argparse import ArgumentParser
from videoio import VideoReader, Uint16Reader, VideoWriter
from tqdm import tqdm
from multiprocessing import Pool
from pathlib import Path
from loguru import logger
from functools import partial


class KinectCalib:
    def __init__(self, calibration, pc_table):
        self.pc_table_ext = np.dstack([pc_table, np.ones(pc_table.shape[:2] + (1,), dtype=pc_table.dtype)])
        color2depth_R = np.array(calibration['color2depth']['R'])
        color2depth_t = np.array(calibration['color2depth']['t'])
        depth2color_R = np.array(calibration['depth2color']['R'])
        depth2color_t = np.array(calibration['depth2color']['t'])

        self.color2depth_R = color2depth_R
        self.color2depth_t = color2depth_t
        self.depth2color_R = depth2color_R
        self.depth2color_t = depth2color_t

        color_calib = calibration['color']
        self.image_size = (color_calib['width'], color_calib['height'])
        self.focal_dist = (color_calib['fx'], color_calib['fy'])
        self.center = (color_calib['cx'], color_calib['cy'])
        self.calibration_matrix = np.eye(3)
        self.calibration_matrix[0, 0], self.calibration_matrix[1, 1] = self.focal_dist
        self.calibration_matrix[:2, 2] = self.center
        self.dist_coeffs = np.array(color_calib['opencv'][4:])

    def undistort(self, img):
        return cv2.undistort(img, self.calibration_matrix, self.dist_coeffs)

    def project_points(self, points):
        return cv2.projectPoints(points[..., np.newaxis],
                                 np.zeros(3), np.zeros(3), self.calibration_matrix, self.dist_coeffs)[0].reshape(-1, 2)

    def dmap2pc(self, depth, return_mask=False):
        nanmask = depth == 0
        d = depth.copy().astype(np.float32) / 1000.
        d[nanmask] = np.nan
        pc = self.pc_table_ext * d[..., np.newaxis]
        validmask = np.isfinite(pc[:, :, 0])
        pc = pc[validmask]
        if return_mask:
            return pc, validmask
        return pc

    def pc2color(self, pointcloud, return_depth=False):
        pointcloud_color = np.matmul(pointcloud, self.depth2color_R.T) + self.depth2color_t
        projected_color_pc = self.project_points(pointcloud_color)
        if return_depth:
            return projected_color_pc, pointcloud_color[:, 2]
        return projected_color_pc

    def color_to_pc(self, colorpts, pc_depth, projected_color_pc=None, k=4, std=1.):
        def weight_func(x, std=1.):
            return np.exp(-x / (2 * std ** 2))

        if projected_color_pc is None:
            projected_color_pc = self.pc2color(pc_depth)
        tree = KDTree(projected_color_pc)
        dists, inds = tree.query(colorpts, k=k)
        weights = weight_func(dists, std=std)
        weights_sum = weights.sum(axis=1)
        w = weights / weights_sum[:, np.newaxis]
        pts_world = (pc_depth[inds.flatten(), :].reshape(-1, k, 3) * w[:, :, np.newaxis]).sum(axis=1)
        return pts_world

    def get_pc_colors(self, pointcloud, color_frame, projected_color_pc=None):
        if projected_color_pc is None:
            projected_color_pc = self.pc2color(pointcloud)
        pc_colors = np.ones_like(pointcloud)
        for i in range(3):
            spline = RectBivariateSpline(np.arange(color_frame.shape[0]), np.arange(color_frame.shape[1]),
                                         color_frame[:, :, i])

            pc_colors[:, i] = spline(projected_color_pc[:, 1], projected_color_pc[:, 0], grid=False)
        pc_colors /= 255.
        pc_colors = np.clip(pc_colors, 0, 1)
        return pc_colors


def process_frame(color_depth, kinect):
    color_frame, depth_frame = color_depth
    outframe = np.zeros(depth_frame.shape + (3,), dtype=np.uint8)
    pc, mask = kinect.dmap2pc(depth_frame, return_mask=True)
    pc_colors = kinect.get_pc_colors(pc, color_frame)
    outframe[mask] = (pc_colors * 255).astype(np.uint8)
    return outframe


def process_video(color_path: Path, depth_path: Path, calibration_dict: dict, pc_table: np.ndarray, output_path: Path, threads=None):
    kinect = KinectCalib(calibration_dict, pc_table)
    output_resolution = (calibration_dict['depth']['width'], calibration_dict['depth']['height'])
    kinect_process_frame = partial(process_frame, kinect=kinect)
    color_reader = VideoReader(color_path)
    depth_reader = Uint16Reader(depth_path)
    with VideoWriter(output_path, resolution=output_resolution) as vw, Pool(threads) as pool:
        for outframe in pool.imap(kinect_process_frame,
                                  zip(color_reader, tqdm(depth_reader))):
            vw.write(outframe)


def rreplace(s, old, new, occurrence):
    li = s.rsplit(old, occurrence)
    return new.join(li)


def process_seq(seqpath: Path, threads: int = None):
    kin_names = [os.path.splitext(os.path.basename(x))[0] for x in (seqpath / "depth").glob("*.mp4")]
    kin_ids = [x.split("_")[1] for x in kin_names]
    metadata = json.load(open(seqpath / "metadata.json"))
    logger.debug(f"Sequence kin ids: {kin_ids}")
    (seqpath / "depthcolor").mkdir(exist_ok=True)
    for ind, (kin_name, kin_id) in enumerate(zip(kin_names, kin_ids)):
        logger.info(f"Processing sequence {seqpath.name}: {ind + 1}/{len(kin_names)}")
        calibration_dict = metadata["participating_kinects"][kin_id]
        pc_table = np.load(seqpath / f"depth2pc_maps/{kin_name}.npz")[kin_id]
        color_path = seqpath / f"color/{kin_name}.mpeg"
        if not os.path.isfile(color_path):
            color_path = seqpath / f"color/{kin_name}.mp4"
        depth_path = seqpath / f"depth/{kin_name}.mp4"
        output_path = seqpath / f"depthcolor/{kin_name}.mp4"
        process_video(color_path, depth_path, calibration_dict, pc_table, output_path, threads=threads)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-s", "--seqpath", type=Path, required=True)
    parser.add_argument("-t", "--threads", type=int, default=None)

    args = parser.parse_args()

    process_seq(args.seqpath, threads=args.threads)
