"""
核心覆盖路径算法：沿指定方向生成弓字形（zigzag）全覆盖路径。
"""

import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# 类型别名
Point = Tuple[float, float]
Polygon = List[Point]


@dataclass
class CoveragePath:
    """一条全覆盖路径"""
    waypoints: List[Point] = field(default_factory=list)
    is_closed: bool = False
    sweep_width: float = 1.0
    total_length: float = 0.0
    area_covered: float = 0.0

    def compute_length(self) -> float:
        total = 0.0
        for i in range(len(self.waypoints) - 1):
            x1, y1 = self.waypoints[i]
            x2, y2 = self.waypoints[i + 1]
            total += math.hypot(x2 - x1, y2 - y1)
        self.total_length = total
        return total


def _point_in_polygon(px: float, py: float, polygon: Polygon) -> bool:
    """射线法判断点是否在多边形内"""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi + 1e-10) + xi
        ):
            inside = not inside
        j = i
    return inside


def _line_intersection(p1: Point, p2: Point, p3: Point, p4: Point) -> Optional[Point]:
    """计算两条线段 (p1-p2) 和 (p3-p4) 的交点，无交点返回 None"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-10:
        return None  # 平行

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0 <= t <= 1 and 0 <= u <= 1:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _clip_segment_to_polygon(
    seg_start: Point, seg_end: Point, polygon: Polygon
) -> List[Point]:
    """
    将一条无限直线线段裁剪到多边形内部。
    返回多边形内部的线段片段（可能多个）。
    """
    intersections = []
    n = len(polygon)
    for i in range(n):
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n]
        pt = _line_intersection(seg_start, seg_end, p1, p2)
        if pt:
            intersections.append(pt)

    # 按距离排序
    if not intersections:
        return []

    intersections.sort(key=lambda p: math.hypot(p[0] - seg_start[0], p[1] - seg_start[1]))

    # 成对取交点（线段进入多边形→离开多边形）
    result = []
    for i in range(0, len(intersections) - 1, 2):
        result.append((intersections[i], intersections[i + 1]))

    return result


def generate_zigzag(
    polygon: Polygon,
    sweep_width: float,
    direction: str = "horizontal",
    start_from: str = "corner",
) -> CoveragePath:
    """
    在指定多边形区域内生成弓字形（zigzag）全覆盖路径。

    Args:
        polygon: 多边形顶点列表 [(x1,y1), (x2,y2), ...]（闭合或非闭合均可）
        sweep_width: 作业宽度（相邻两趟之间的间距，即车辆有效作业宽度）
        direction: 扫路方向，"horizontal"（水平）或 "vertical"（垂直）
        start_from: "corner"（角落起）或 "center"（中间起）

    Returns:
        CoveragePath 对象
    """
    # 确保多边形闭合
    if polygon[0] != polygon[-1]:
        polygon = polygon + [polygon[0]]

    # 计算包围盒
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    path = CoveragePath(sweep_width=sweep_width)

    # 生成扫描线
    if direction == "horizontal":
        scan_origin = min_y
        scan_end = max_y
        fixed_coords = []
        y = scan_origin
        while y <= scan_end:
            fixed_coords.append(y)
            y += sweep_width
        if fixed_coords[-1] < scan_end:
            fixed_coords.append(scan_end)

        segments = []
        for y in fixed_coords:
            segs = _clip_segment_to_polygon(
                (min_x - 1, y), (max_x + 1, y), polygon
            )
            for s in segs:
                segments.append((s[0], s[1], y))

    else:  # vertical
        scan_origin = min_x
        scan_end = max_x
        fixed_coords = []
        x = scan_origin
        while x <= scan_end:
            fixed_coords.append(x)
            x += sweep_width
        if fixed_coords[-1] < scan_end:
            fixed_coords.append(scan_end)

        segments = []
        for x in fixed_coords:
            segs = _clip_segment_to_polygon(
                (x, min_y - 1), (x, max_y + 1), polygon
            )
            for s in segs:
                segments.append((s[0], s[1], x))

    # 连接为 zigzag 路径
    waypoints = []
    for i, seg in enumerate(segments):
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
    polygon: Polygon,
    sweep_width: float,
    direction: str = "horizontal",
) -> CoveragePath:
    """
    生成闭环的全覆盖路径（终点自动回到起点，适合循环作业）。

    在 zigzag 末尾添加一个从终点到起点的连接段。
    """
    path = generate_zigzag(polygon, sweep_width, direction)

    if path.waypoints and len(path.waypoints) > 1:
        # 从终点回到起点
        start = path.waypoints[0]
        end = path.waypoints[-1]

        # 添加回程路径（沿边界或者直接直线回去）
        path.waypoints.append(start)
        path.is_closed = True
        path.compute_length()

    return path


def clip_path_to_polygon(
    path: CoveragePath, polygon: Polygon
) -> CoveragePath:
    """
    将路径限定在多边形内部（裁剪超出边界的部分）。
    如果路径已经都在多边形内，不做改变。
    """
    clipped = CoveragePath(sweep_width=path.sweep_width, is_closed=path.is_closed)
    for pt in path.waypoints:
        if _point_in_polygon(pt[0], pt[1], polygon):
            clipped.waypoints.append(pt)
    clipped.compute_length()
    return clipped
