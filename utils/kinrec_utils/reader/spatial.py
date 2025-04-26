import numpy as np
import cv2
from typing import Optional
from sklearn.neighbors import KDTree
from scipy.interpolate import RectBivariateSpline


class KinectSpatialOperator:
    def __init__(self, calibration, pc_table, extrinsics=None):
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

        if extrinsics is not None:
            if "color" in extrinsics:
                self.extrinsics_color_R = np.asarray(extrinsics["color"]["R"])
                self.extrinsics_color_t = np.asarray(extrinsics["color"]["t"])
            else:
                self.extrinsics_color_R = None
                self.extrinsics_color_t = None

    def undistort(self, img):
        return cv2.undistort(img, self.calibration_matrix, self.dist_coeffs)

    def project_points(self, points):
        return cv2.projectPoints(points[..., np.newaxis],
                                 np.zeros(3), np.zeros(3), self.calibration_matrix, self.dist_coeffs)[0].reshape(-1, 2)

    def dmap2pc(self, depth, return_mask=False, map2colorworld=False):
        nanmask = depth == 0
        d = depth.copy().astype(np.float32) / 1000.
        d[nanmask] = np.nan
        pc = self.pc_table_ext * d[..., np.newaxis]
        validmask = np.isfinite(pc[:, :, 0])
        pc = pc[validmask]
        if map2colorworld:
            pc = self.pc_depthworld2colorworld(pc)
        if return_mask:
            return pc, validmask
        return pc

    def pc_depthworld2colorworld(self, pc):
        return np.matmul(pc, self.depth2color_R.T) + self.depth2color_t

    def pc2color(self, pointcloud, return_depth=False, map2colorworld=True):
        if map2colorworld:
            pointcloud_color = self.pc_depthworld2colorworld(pointcloud)
        else:
            pointcloud_color = pointcloud
        projected_color_pc = self.project_points(pointcloud_color)
        if return_depth:
            return projected_color_pc, pointcloud_color[:, 2]
        return projected_color_pc

    def color2pc(self, colorpts: np.ndarray, pc_depth: np.ndarray, projected_color_pc: Optional[np.ndarray] = None, k: int = 4, std: float = 1.):
        """
        Function to map color points to 3D points. Computes color point depth from known depthmap and nearest neighbour with gaussian kernel weighting
        Args:
            colorpts: array of shape (N, 2) with color points to unproject
            pc_depth: unprojected depthmap from the same kinect
            projected_color_pc: cashed depth pointcloud projected to color plane from the same kinect (for speedup)
            k: how many nearest neighbors to use
            std: std of the gaussian kernel to use for weighting

        Returns:
            coordinates of points unprojected in 3D space
        """

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

    def compute_pc_colors(self, pointcloud: np.ndarray, color_frame: np.ndarray, projected_color_pc: Optional[np.ndarray] = None,
            map2colorworld=True) -> np.ndarray:
        """
        Compute colors for pointcloud from color frame
        Args:
            pointcloud: array of shape (N, 3) with 3D points
            color_frame: array of shape (H, W, 3) with color frame
            projected_color_pc: array of shape (N, 2) with projected pointcloud to color frame (for speedup)
            map2colorworld: whether to map pointcloud to color frame world before projecting (if projected points are not cached)

        Returns:
            np.ndarray: array of shape (N, 3) with colors for pointcloud
        """
        if projected_color_pc is None:
            projected_color_pc = self.pc2color(pointcloud, map2colorworld=map2colorworld)
        pc_colors = np.ones_like(pointcloud)
        for i in range(3):
            spline = RectBivariateSpline(np.arange(color_frame.shape[0]), np.arange(color_frame.shape[1]),
                                         color_frame[:, :, i])

            pc_colors[:, i] = spline(projected_color_pc[:, 1], projected_color_pc[:, 0], grid=False)
        pc_colors /= 255.
        pc_colors = np.clip(pc_colors, 0, 1)
        return pc_colors

    def pc2global(self, pc):
        """Transform pointcloud from local kinect coordinate system to global"""
        assert self.extrinsics_color_R is not None and self.extrinsics_color_t is not None, "No extrinsics loaded"
        return np.matmul(pc, self.extrinsics_color_R.T) + self.extrinsics_color_t

    def pc2local(self, pc):
        """Transform pointcloud from global kinect coordinate system to local"""
        assert self.extrinsics_color_R is not None and self.extrinsics_color_t is not None, "No extrinsics loaded"
        return np.matmul(pc - self.extrinsics_color_t, self.extrinsics_color_R)

