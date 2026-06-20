"""
核心覆盖路径算法 — 支持障碍物避让的全覆盖路径规划。
"""

import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

Point = Tuple[float, float]
Polygon = List[Point]


@dataclass
class CoveragePath:
    """一条全覆盖路径"""
    waypoints: List[Point] = field(default_factory=list)
    is_closed: bool = False
    sweep_width: float = 1.0
    total_length: float = 0.0

    def compute_length(self) -> float:
        total = 0.0
        for i in range(len(self.waypoints) - 1):
            x1, y1 = self.waypoints[i]
            x2, y2 = self.waypoints[i + 1]
            total += math.hypot(x2 - x1, y2 - y1)
        self.total_length = total
        return total


def _line_intersection(p1: Point, p2: Point, p3: Point, p4: Point) -> Optional[Point]:
    """返回线段 p1-p2 与 p3-p4 的交点，无则 None"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-10:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _clip_line_to_polygon(p1: Point, p2: Point, polygon: Polygon) -> List[Tuple[Point, Point]]:
    """
    将一条线段裁剪到多边形内部。
    返回多边形内部的线段片段列表（可能有多个）。
    """
    intersections = []
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        pt = _line_intersection(p1, p2, a, b)
        if pt:
            intersections.append(pt)

    if not intersections:
        return []

    intersections.sort(key=lambda p: math.hypot(p[0] - p1[0], p[1] - p1[1]))

    # 成对取交点
    segments = []
    for i in range(0, len(intersections) - 1, 2):
        segments.append((intersections[i], intersections[i + 1]))
    return segments


_OBSTACLE_BUFFER = 0.15  # 障碍物外扩缓冲距离（米），防止路径贴边


def _subtract_segments(
    outer_segments: List[Tuple[Point, Point]],
    inner_segments: List[Tuple[Point, Point]],
) -> List[Tuple[Point, Point]]:
    """
    从 outer_segments 中减去 inner_segments 内的部分。
    每条 outer 线段与 inner 线段在同一条扫描线上做一维裁剪。
    用于实现障碍物裁剪：扫过的线减去障碍物内部的部分。
    """
    if not inner_segments:
        return outer_segments
    if not outer_segments:
        return []

    result = []
    for out_seg in outer_segments:
        (x1, y1), (x2, y2) = out_seg
        # 把内外线段投影到扫描线方向做裁剪
        # 两点的中点
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2

        # 确定扫线方向并投影到一维
        dx, dy = x2 - x1, y2 - y1
        if abs(dx) > abs(dy):
            # 水平扫线，按 x 投影
            o_start, o_end = min(x1, x2), max(x1, x2)
            gaps = [(o_start, o_end)]
            for (ix1, iy1), (ix2, iy2) in inner_segments:
                # 判断 inner 线段是否落在 outer 上（同一条扫线）
                iy = (iy1 + iy2) / 2
                if abs(iy - my) > 0.5:  # 不在同一条扫线上
                    continue
                i_start, i_end = min(ix1, ix2), max(ix1, ix2)
                # 裁剪（扩展障碍物边界，留出缓冲）
                new_gaps = []
                for gs, ge in gaps:
                    i_start_buf = i_start - _OBSTACLE_BUFFER
                    i_end_buf = i_end + _OBSTACLE_BUFFER
                    if i_start_buf >= ge or i_end_buf <= gs:
                        new_gaps.append((gs, ge))
                    else:
                        if gs < i_start_buf:
                            new_gaps.append((gs, i_start_buf))
                        if ge > i_end_buf:
                            new_gaps.append((i_end_buf, ge))
                gaps = new_gaps
            for gs, ge in gaps:
                result.append(((gs, my), (ge, my)))
        else:
            # 垂直扫线，按 y 投影，同样带缓冲
            o_start, o_end = min(y1, y2), max(y1, y2)
            gaps = [(o_start, o_end)]
            for (ix1, iy1), (ix2, iy2) in inner_segments:
                ix = (ix1 + ix2) / 2
                if abs(ix - mx) > 0.5:
                    continue
                i_start, i_end = min(iy1, iy2), max(iy1, iy2)
                new_gaps = []
                for gs, ge in gaps:
                    i_start_buf = i_start - _OBSTACLE_BUFFER
                    i_end_buf = i_end + _OBSTACLE_BUFFER
                    if i_start_buf >= ge or i_end_buf <= gs:
                        new_gaps.append((gs, ge))
                    else:
                        if gs < i_start_buf:
                            new_gaps.append((gs, i_start_buf))
                        if ge > i_end_buf:
                            new_gaps.append((i_end_buf, ge))
                gaps = new_gaps
            for gs, ge in gaps:
                result.append(((mx, gs), (mx, ge)))

    return result


def generate_zigzag(
    boundary: Polygon,
    sweep_width: float,
    obstacles: List[Polygon] = None,
    direction: str = "horizontal",
) -> CoveragePath:
    """
    在指定区域内生成弓字形全覆盖路径，自动避开障碍物。

    Args:
        boundary: 作业区域多边形，[(x1,y1), (x2,y2), ...]
        sweep_width: 车辆作业宽度（米）
        obstacles: 障碍物多边形列表，每个多边形 [(x1,y1), ...]
        direction: 'horizontal'（水平扫）或 'vertical'（垂直扫）

    Returns:
        CoveragePath 对象
    """
    obstacles = obstacles or []

    # 确保边界闭合
    if boundary[0] != boundary[-1]:
        boundary = boundary + [boundary[0]]
    obstacles = [o + [o[0]] if o[0] != o[-1] else o for o in obstacles]

    # 包围盒
    xs = [p[0] for p in boundary]
    ys = [p[1] for p in boundary]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    path = CoveragePath(sweep_width=sweep_width)

    # 生成扫描线
    sweep_lines = []
    if direction == "horizontal":
        y = min_y
        while y <= max_y:
            sweep_lines.append(y)
            y += sweep_width
        if sweep_lines and sweep_lines[-1] < max_y:
            sweep_lines.append(max_y)

        scan_segments = []
        for y_val in sweep_lines:
            # 裁剪到边界
            segs = _clip_line_to_polygon(
                (min_x - 2, y_val), (max_x + 2, y_val), boundary
            )
            if segs:
                # 减去障碍物内的部分
                obs_segs = []
                for obs in obstacles:
                    obs_segs.extend(
                        _clip_line_to_polygon((min_x - 2, y_val), (max_x + 2, y_val), obs)
                    )
                cleared = _subtract_segments(segs, obs_segs)
                for s in cleared:
                    scan_segments.append((s[0], s[1], y_val))
    else:
        x = min_x
        while x <= max_x:
            sweep_lines.append(x)
            x += sweep_width
        if sweep_lines and sweep_lines[-1] < max_x:
            sweep_lines.append(max_x)

        scan_segments = []
        for x_val in sweep_lines:
            segs = _clip_line_to_polygon(
                (x_val, min_y - 2), (x_val, max_y + 2), boundary
            )
            if segs:
                obs_segs = []
                for obs in obstacles:
                    obs_segs.extend(
                        _clip_line_to_polygon((x_val, min_y - 2), (x_val, max_y + 2), obs)
                    )
                cleared = _subtract_segments(segs, obs_segs)
                for s in cleared:
                    scan_segments.append((s[0], s[1], x_val))

    # 连接为 zigzag 路径
    waypoints = []
    for i, seg in enumerate(scan_segments):
        (x1, y1), (x2, y2), _ = seg
        if i % 2 == 0:
            waypoints.append((x1, y1))
            waypoints.append((x2, y2))
        else:
            waypoints.append((x2, y2))
            waypoints.append((x1, y1))

    path.waypoints = waypoints
    path.compute_length()
    return path


def generate_zigzag_closed(
    boundary: Polygon,
    sweep_width: float,
    obstacles: List[Polygon] = None,
    direction: str = "horizontal",
) -> CoveragePath:
    """生成闭环路径（终点回到起点，适合循环作业）"""
    path = generate_zigzag(boundary, sweep_width, obstacles, direction)
    if path.waypoints and len(path.waypoints) > 1:
        path.waypoints.append(path.waypoints[0])
        path.is_closed = True
        path.compute_length()
    return path
