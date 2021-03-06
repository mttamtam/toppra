"""
"""
import numpy as np

from ..constants import TINY
from toppra.interpolator import SplineInterpolator, AbstractGeometricPath
import toppra.interpolator as interpolator

import logging

logger = logging.getLogger(__name__)


class ParameterizationAlgorithm(object):
    """Base class for all parameterization algorithms.

    All algorithms should have three attributes: `constraints`, `path`
    and `gridpoints` and also implement the method
    `compute_parameterization`.

    Parameters
    ----------
    constraint_list: list of `Constraint`
    path: `AbstractGeometricPath`
        The geometric path, or the trajectory to parameterize.
    gridpoints: array, optional
        If not given, automatically generate a grid with 100 steps.
    """

    def __init__(self, constraint_list, path, gridpoints=None):
        self.constraints = constraint_list  # Attr
        self.path = path  # Attr
        self._problem_data = {}
        # Handle gridpoints
        if gridpoints is None:
            gridpoints = interpolator.propose_gridpoints(path, max_err_threshold=1e-3)
            logger.info(
                "No gridpoint specified. Automatically choose a gridpoint. See `propose_gridpoints`."
            )

        if (
            path.path_interval[0] != gridpoints[0]
            or path.path_interval[1] != gridpoints[-1]
        ):
            raise ValueError("Invalid manually supplied gridpoints.")
        self.gridpoints = np.array(gridpoints)
        self._N = len(gridpoints) - 1  # Number of stages. Number of point is _N + 1
        for i in range(self._N):
            if gridpoints[i + 1] <= gridpoints[i]:
                logger.fatal("Input gridpoints are not monotonically increasing.")
                raise ValueError("Bad input gridpoints.")

    @property
    def problem_data(self):
        """Dict[str, Any]: Intermediate data obtained while solving the problem."""
        return self._problem_data

    def compute_parameterization(self, sd_start, sd_end):
        """Compute a path parameterization.

        If fail, whether because there is no valid parameterization or
        because of numerical error, the arrays returns should contain
        np.nan.


        Parameters
        ----------
        sd_start: float
            Starting path velocity. Must be positive.
        sd_end: float
            Goal path velocity. Must be positive.
        return_data: bool, optional
            If is True, also return matrix K which contains the controllable sets.

        Returns
        -------
        sdd_vec: (_N,) array or None
            Path accelerations.
        sd_vec: (_N+1,) array None
            Path velocities.
        v_vec: (_N,) array or None
            Auxiliary variables.
        K: (N+1, 2) array
            Return the controllable set if `return_data` is True.

        """
        raise NotImplementedError

    def compute_trajectory(self, sd_start=0, sd_end=0, return_data=False):
        """Compute the resulting joint trajectory and auxilliary trajectory.

        If parameterization fails, return a tuple of None(s).

        Parameters
        ----------
        sd_start: float
            Starting path velocity.
        sd_end: float
            Goal path velocity.
        return_data: bool, optional
            If true, return a dict containing the internal data.

        Returns
        -------
        :class:`.AbstractGeometricPath`
            Time-parameterized joint position trajectory. If unable to
            parameterize, return None.
        :class:`.AbstractGeometricPath`
            Time-parameterized auxiliary variable trajectory. If
            unable to parameterize or if there is no auxiliary
            variable, return None.

        """
        sdd_grid, sd_grid, v_grid, K = self.compute_parameterization(
            sd_start, sd_end, return_data=True
        )

        # fail condition: sd_grid is None, or there is nan in sd_grid
        if sd_grid is None or np.isnan(sd_grid).any():
            return None, None

        # Gridpoint time instances
        t_grid = np.zeros(self._N + 1)
        skip_ent = []
        for i in range(1, self._N + 1):
            sd_average = (sd_grid[i - 1] + sd_grid[i]) / 2
            delta_s = self.gridpoints[i] - self.gridpoints[i - 1]
            if sd_average > TINY:
                delta_t = delta_s / sd_average
            else:
                delta_t = 5  # If average speed is too slow.
            t_grid[i] = t_grid[i - 1] + delta_t
            if delta_t < TINY:  # if a time increment is too small, skip.
                skip_ent.append(i)
        t_grid = np.delete(t_grid, skip_ent)
        scaling = self.gridpoints[-1] / self.path.duration
        gridpoints = np.delete(self.gridpoints, skip_ent) / scaling
        q_grid = self.path.eval(gridpoints)

        traj_spline = SplineInterpolator(
            t_grid,
            q_grid,
            (
                (1, self.path(0, 1) * sd_start),
                (1, self.path(self.path.duration, 1) * sd_end),
            ),
        )

        if v_grid.shape[1] == 0:
            v_spline = None
        else:
            v_grid_ = np.zeros((v_grid.shape[0] + 1, v_grid.shape[1]))
            v_grid_[:-1] = v_grid
            v_grid_[-1] = v_grid[-1]
            v_grid_ = np.delete(v_grid_, skip_ent, axis=0)
            v_spline = SplineInterpolator(t_grid, v_grid_)

        self._problem_data.update(
            {"sdd": sdd_grid, "sd": sd_grid, "v": v_grid, "K": K, "v_traj": v_spline}
        )
        if self.path.waypoints is not None:
            t_waypts = np.interp(self.path.waypoints[0], gridpoints, t_grid)
            self._problem_data.update({"t_waypts": t_waypts})

        return traj_spline
