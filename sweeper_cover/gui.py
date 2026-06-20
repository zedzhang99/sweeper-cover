"""
SweeperCover GUI — PyQt5 全覆盖路径规划编辑器
v0.3 支持：撤销/重做、顶点编辑、保存加载、实时刷新、
路径平滑、多格式导出、自定义角度、测距、多区域
"""

import sys, os, math, json, copy

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QInputDialog, QListWidget, QListWidgetItem,
    QSplitter, QFrame, QGroupBox, QFormLayout, QStatusBar, QSlider,
    QScrollArea, QToolBar, QAction, QButtonGroup, QRadioButton,
)
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal, QLineF, QSize
from PyQt5.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, QFont,
    QPolygonF, QMouseEvent, QWheelEvent, QKeyEvent, QPainterPath,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sweeper_cover.coverage import generate_zigzag, generate_zigzag_closed

# ─── 模式常量 ───
MODE_NONE           = 0
MODE_DRAW_AREA      = 1
MODE_DRAW_OBSTACLE  = 2
MODE_SET_SCALE      = 3
MODE_EDIT_VERTEX    = 4   # 选中/拖拽顶点
MODE_RULER          = 5   # 测距
MODE_ADD_AREA       = 6   # 多区域

HIT_RADIUS = 8  # 顶点选中半径（像素）


class HistoryManager:
    """撤销/重做管理器"""
    def __init__(self):
        self._undo_stack = []
        self._redo_stack = []
        self._max_len = 50

    def snapshot(self, area_points, obstacles, areas):
        state = (
            copy.deepcopy(area_points),
            copy.deepcopy(obstacles),
            copy.deepcopy(areas),
        )
        self._undo_stack.append(state)
        self._redo_stack.clear()
        if len(self._undo_stack) > self._max_len:
            self._undo_stack.pop(0)

    def undo(self, area_points, obstacles, areas):
        if not self._undo_stack:
            return (area_points, obstacles, areas)
        self._redo_stack.append((copy.deepcopy(area_points), copy.deepcopy(obstacles), copy.deepcopy(areas)))
        return self._undo_stack.pop()

    def redo(self, area_points, obstacles, areas):
        if not self._redo_stack:
            return (area_points, obstacles, areas)
        self._undo_stack.append((copy.deepcopy(area_points), copy.deepcopy(obstacles), copy.deepcopy(areas)))
        return self._redo_stack.pop()

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()


def _smooth_turns(waypoints, turn_radius=2.0):
    """在路径的转弯处插入弧线，使路径平滑"""
    if len(waypoints) < 4:
        return waypoints
    smoothed = [waypoints[0]]
    for i in range(1, len(waypoints) - 1):
        p0 = waypoints[i - 1]
        p1 = waypoints[i]
        p2 = waypoints[i + 1]
        # 计算转角
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        d1 = math.hypot(*v1)
        d2 = math.hypot(*v2)
        if d1 < 0.01 or d2 < 0.01:
            smoothed.append(p1)
            continue
        # 归一化
        v1n = (v1[0] / d1, v1[1] / d1)
        v2n = (v2[0] / d2, v2[1] / d2)
        # 方向变化
        cross = v1n[0] * v2n[1] - v1n[1] * v2n[0]
        dot = v1n[0] * v2n[0] + v1n[1] * v2n[1]
        if dot > 0.95:  # 近乎直线
            smoothed.append(p1)
            continue
        actual_r = min(turn_radius, d1 * 0.5, d2 * 0.5)
        if actual_r < 0.3:
            smoothed.append(p1)
            continue
        # 插入弧线点（简单方案：在转角处加两个中间点）
        angle = math.acos(max(-1, min(1, dot)))
        steps = max(3, int(angle / 0.3))
        for s in range(1, steps):
            t = s / steps
            # Hermite 风格插值
            smoothed.append((
                p1[0] - v1n[0] * actual_r + (v1n[0] + v2n[0]) * actual_r * t,
                p1[1] - v1n[1] * actual_r + (v1n[1] + v2n[1]) * actual_r * t,
            ))
        smoothed.append(p1)
    smoothed.append(waypoints[-1])
    return smoothed


class MapCanvas(QWidget):
    status_msg = pyqtSignal(str)
    path_changed = pyqtSignal(object)  # 路径生成时发送

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # 地图
        self.map_image = None
        self.map_pixmap = None
        self.map_path = ""
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.scale_set = False

        # 绘图数据：支持多区域
        self.areas = []           # 多个作业区域 [[(x,y),...], ...]
        self.current_area_idx = 0 # 当前编辑的区域索引
        self.area_points = []     # 当前区域的顶点（和 areas[current_area_idx] 同步）
        self.obstacles = []       # 障碍物列表
        self.current_drawing = [] # 当前正在画的多边形

        # 路径
        self.path_waypoints = []
        self.world_area = []
        self.world_obstacles = []
        self.path_smooth = False
        self.turn_radius = 2.0

        # 交互状态
        self.mode = MODE_NONE
        self.scale_start = None
        self.drag_start = None
        self.offset_x = 0
        self.offset_y = 0
        self.zoom = 1.0
        self.hover_pos = None

        # 选中
        self.selected_vertex_idx = -1   # 当前选中的顶点索引
        self.selected_obstacle_idx = -1 # 当前选中的障碍物索引
        self.selected_area_idx = -1     # 当前选中的区域索引
        self.dragging_vertex = False
        self._vertex_original = None

        # 测距
        self.ruler_points = []

        # 参数
        self.sweep_width = 3.0
        self.direction = "horizontal"
        self.custom_angle = 0  # 自定义角度（度）
        self.closed_loop = False

        # 历史
        self.history = HistoryManager()

    # ═══ 模式切换 ═══
    def set_mode(self, mode):
        old_mode = self.mode
        self.mode = mode
        names = {
            MODE_NONE: "就绪", MODE_DRAW_AREA: "画作业区域(左键加点,右键完成)",
            MODE_DRAW_OBSTACLE: "画障碍物(左键加点,右键完成,回车确认)",
            MODE_SET_SCALE: "设定比例尺(点击两点,输入实际距离)",
            MODE_EDIT_VERTEX: "编辑模式(拖拽顶点,点击选中障碍物按Delete删除)",
            MODE_RULER: "测距(点击两点)",
            MODE_ADD_AREA: "添加作业区域",
        }
        if mode == MODE_EDIT_VERTEX:
            pass  # 不重置选中
        else:
            self.selected_vertex_idx = -1
            self.selected_obstacle_idx = -1
        self.ruler_points.clear()
        self.update()
        self.status_msg.emit(names.get(mode, "?"))

    # ═══ 参数设置 ═══
    def set_params(self, width, direction, closed, custom_angle=0, smooth=False, turn_radius=2.0):
        changed = (self.sweep_width != width or self.direction != direction or
                   self.closed_loop != closed or self.custom_angle != custom_angle or
                   self.path_smooth != smooth or self.turn_radius != turn_radius)
        self.sweep_width = width
        self.direction = direction
        self.closed_loop = closed
        self.custom_angle = custom_angle
        self.path_smooth = smooth
        self.turn_radius = turn_radius
        if changed and self.path_waypoints:
            self.generate_path()

    # ═══ 地图 ═══
    def load_map(self, path):
        self.map_image = QImage(path)
        if self.map_image.isNull():
            QMessageBox.warning(self, "错误", f"无法加载图片: {path}")
            return False
        self.map_pixmap = QPixmap.fromImage(self.map_image)
        self.map_path = path
        self.areas.clear()
        self.obstacles.clear()
        self.area_points = []
        self.current_area_idx = 0
        self.path_waypoints = []
        self.scale_set = False
        self.history.clear()
        self.zoom = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.update()
        self.status_msg.emit(f"已加载: {os.path.basename(path)} ({self.map_image.width()}×{self.map_image.height()})")
        return True

    # ═══ 坐标转换 ═══
    def pixel_to_world(self, px, py):
        return (px * self.scale_x, py * self.scale_y)

    def world_to_pixel(self, wx, wy):
        return (wx / self.scale_x, wy / self.scale_y)

    def _scene_pos(self, event):
        sx = (event.pos().x() - self.offset_x) / self.zoom
        sy = (event.pos().y() - self.offset_y) / self.zoom
        return (sx, sy)

    def _find_nearest_vertex(self, x, y, threshold=None):
        """查找最近的顶点（像素坐标）"""
        t = (HIT_RADIUS / self.zoom) if threshold is None else threshold
        best = -1
        best_d = t
        for i, (vx, vy) in enumerate(self.area_points):
            d = math.hypot(x - vx, y - vy)
            if d < best_d:
                best_d = d
                best = i
        return best

    def _find_nearest_obstacle(self, x, y):
        """查找最近的障碍物"""
        t = HIT_RADIUS / self.zoom
        best = -1
        best_d = t
        for oi, obs in enumerate(self.obstacles):
            for vx, vy in obs:
                d = math.hypot(x - vx, y - vy)
                if d < best_d:
                    best_d = d
                    best = oi
        return best

    # ═══ 核心逻辑 ═══
    def _save_history(self):
        self.history.snapshot(self.area_points, self.obstacles, self.areas)

    def undo(self):
        self.area_points, self.obstacles, self.areas = self.history.undo(
            self.area_points, self.obstacles, self.areas)
        self.update()
        self.status_msg.emit("撤销")

    def redo(self):
        self.area_points, self.obstacles, self.areas = self.history.redo(
            self.area_points, self.obstacles, self.areas)
        self.update()
        self.status_msg.emit("重做")

    def delete_selected(self):
        if self.selected_obstacle_idx >= 0 and self.selected_obstacle_idx < len(self.obstacles):
            self._save_history()
            del self.obstacles[self.selected_obstacle_idx]
            self.selected_obstacle_idx = -1
            self.update()
            self.status_msg.emit("已删除障碍物")
            self.generate_path()

    def clear_all(self):
        self.areas.clear()
        self.area_points = []
        self.obstacles.clear()
        self.current_drawing.clear()
        self.path_waypoints = []
        self.scale_set = False
        self.scale_start = None
        self.selected_vertex_idx = -1
        self.selected_obstacle_idx = -1
        self.history.clear()
        self.set_mode(MODE_NONE)
        self.update()
        self.status_msg.emit("已清空")

    def generate_path(self, smooth=None):
        if len(self.area_points) < 3 and not self.areas:
            # 如果 areas 不为空但 area_points 为空，取最后一个区域
            if self.areas:
                self.area_points = list(self.areas[-1])
            if len(self.area_points) < 3:
                return
        if not self.scale_set:
            self.status_msg.emit("⚠️ 请先设定比例尺")
            return
        if len(self.area_points) < 3:
            return

        # 收集所有区域
        all_areas = list(self.areas) if self.areas else [self.area_points]

        world_waypoints = []
        for area_pts in all_areas:
            if len(area_pts) < 3:
                continue
            world_area = [self.pixel_to_world(p[0], p[1]) for p in area_pts]
            world_obs = []
            for obs in self.obstacles:
                if len(obs) >= 3:
                    world_obs.append([self.pixel_to_world(p[0], p[1]) for p in obs])

            try:
                if self.direction == "custom":
                    # 自定义角度：旋转坐标系后生成再转回来
                    angle_rad = math.radians(self.custom_angle)
                    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
                    # 将区域旋转到水平方向
                    rot_area = [(x * cos_a + y * sin_a, -x * sin_a + y * cos_a) for x, y in world_area]
                    rot_obs = [[(x * cos_a + y * sin_a, -x * sin_a + y * cos_a) for x, y in o] for o in world_obs]
                    if self.closed_loop:
                        p = generate_zigzag_closed(rot_area, self.sweep_width, rot_obs, "horizontal")
                    else:
                        p = generate_zigzag(rot_area, self.sweep_width, rot_obs, "horizontal")
                    # 转回来
                    pts = [(x * cos_a - y * sin_a, x * sin_a + y * cos_a) for x, y in p.waypoints]
                else:
                    if self.closed_loop:
                        p = generate_zigzag_closed(world_area, self.sweep_width, world_obs, self.direction)
                    else:
                        p = generate_zigzag(world_area, self.sweep_width, world_obs, self.direction)
                    pts = list(p.waypoints)
                world_waypoints.extend(pts)
            except Exception as e:
                self.status_msg.emit(f"路径生成错误: {e}")
                return

        # 平滑
        if smooth if smooth is not None else self.path_smooth:
            world_waypoints = _smooth_turns(world_waypoints, self.turn_radius)

        self.path_waypoints = world_waypoints
        self.world_area = [self.pixel_to_world(p[0], p[1]) for p in self.area_points]
        self.world_obstacles = [[self.pixel_to_world(p[0], p[1]) for p in o] for o in self.obstacles]

        total = 0
        for i in range(len(world_waypoints) - 1):
            total += math.hypot(world_waypoints[i+1][0] - world_waypoints[i][0],
                                world_waypoints[i+1][1] - world_waypoints[i][1])
        info = f"路径: {len(world_waypoints)} 点, {total:.1f}m"
        if self.closed_loop: info += " [闭环]"
        if self.path_smooth: info += " [平滑]"
        self.status_msg.emit(info)
        self.path_changed.emit(self.path_waypoints)
        self.update()

    # ═══ 绘制 ═══
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(48, 48, 48))
        painter.translate(self.offset_x, self.offset_y)
        painter.scale(self.zoom, self.zoom)

        # 底图
        if self.map_pixmap and not self.map_pixmap.isNull():
            painter.drawPixmap(0, 0, self.map_pixmap)

        # ─── 所有作业区域 ───
        for ai, area in enumerate(self.areas):
            if len(area) < 2: continue
            poly = QPolygonF([QPointF(p[0], p[1]) for p in area])
            # 当前编辑的区域高亮
            if ai == self.current_area_idx and self.areas:
                painter.setPen(QPen(QColor(0, 180, 255), 3 / self.zoom))
                painter.setBrush(QBrush(QColor(0, 120, 255, 25)))
            else:
                painter.setPen(QPen(QColor(100, 100, 255), 2 / self.zoom))
                painter.setBrush(QBrush(QColor(100, 100, 255, 15)))
            painter.drawPolygon(poly)

        # 当前区域顶点
        if self.mode in (MODE_DRAW_AREA, MODE_EDIT_VERTEX, MODE_NONE):
            for i, (vx, vy) in enumerate(self.area_points):
                is_sel = (i == self.selected_vertex_idx)
                painter.setPen(QPen(QColor(0, 255, 100) if is_sel else QColor(0, 180, 255), 2 / self.zoom))
                painter.setBrush(QBrush(QColor(0, 255, 100, 200) if is_sel else QColor(0, 180, 255, 200)))
                r = 6 / self.zoom if is_sel else 4 / self.zoom
                painter.drawEllipse(QPointF(vx, vy), r, r)

        # ─── 障碍物 ───
        for oi, obs in enumerate(self.obstacles):
            if len(obs) > 2:
                poly = QPolygonF([QPointF(p[0], p[1]) for p in obs])
                is_sel = (oi == self.selected_obstacle_idx)
                c = QColor(255, 80, 80) if is_sel else QColor(255, 50, 50)
                painter.setPen(QPen(c, 2.5 / self.zoom))
                painter.setBrush(QBrush(QColor(255, 50, 50, 40)))
                painter.drawPolygon(poly)
                if is_sel:
                    # 选中框
                    painter.setPen(QPen(QColor(255, 200, 0), 2 / self.zoom, Qt.DashLine))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPolygon(poly)
                # 顶点
                for vx, vy in obs:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(c))
                    painter.drawEllipse(QPointF(vx, vy), 3 / self.zoom, 3 / self.zoom)

        # ─── 当前绘制 ───
        if len(self.current_drawing) >= 2:
            painter.setPen(QPen(QColor(0, 200, 0, 180), 2 / self.zoom, Qt.DashLine))
            for i in range(len(self.current_drawing) - 1):
                x1, y1 = self.current_drawing[i]
                x2, y2 = self.current_drawing[i + 1]
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            if self.hover_pos and self.current_drawing:
                lx, ly = self.current_drawing[-1]
                painter.setPen(QPen(QColor(0, 200, 0, 100), 1 / self.zoom, Qt.DashLine))
                painter.drawLine(QPointF(lx, ly), QPointF(self.hover_pos[0], self.hover_pos[1]))
            for p in self.current_drawing:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(0, 200, 0)))
                painter.drawEllipse(QPointF(p[0], p[1]), 4 / self.zoom, 4 / self.zoom)

        # ─── 比例尺参考线 ───
        if self.scale_start and self.hover_pos:
            sx, sy = self.scale_start
            hx, hy = self.hover_pos
            painter.setPen(QPen(QColor(255, 165, 0), 3 / self.zoom))
            painter.drawLine(QPointF(sx, sy), QPointF(hx, hy))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 165, 0)))
            painter.drawEllipse(QPointF(sx, sy), 6 / self.zoom, 6 / self.zoom)
            painter.drawEllipse(QPointF(hx, hy), 6 / self.zoom, 6 / self.zoom)
            dist = math.hypot(hx - sx, hy - sy)
            painter.setPen(QPen(QColor(255, 165, 0)))
            painter.setFont(QFont("Arial", 12 / self.zoom))
            painter.drawText(QPointF((sx + hx) / 2, (sy + hy) / 2 - 12 / self.zoom),
                             f"{dist:.0f} px")

        # ─── 测距 ───
        if self.mode == MODE_RULER:
            for i in range(0, len(self.ruler_points), 2):
                if i + 1 >= len(self.ruler_points): break
                x1, y1 = self.ruler_points[i]
                x2, y2 = self.ruler_points[i + 1]
                painter.setPen(QPen(QColor(255, 200, 0), 2.5 / self.zoom, Qt.DashLine))
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                # 距离标注
                dist_px = math.hypot(x2 - x1, y2 - y1)
                if self.scale_set:
                    dist_m = dist_px * self.scale_x
                    label = f"{dist_m:.2f} m"
                else:
                    label = f"{dist_px:.0f} px"
                painter.setPen(QPen(QColor(255, 200, 0)))
                painter.setFont(QFont("Arial", 11 / self.zoom))
                painter.drawText(QPointF((x1 + x2) / 2, (y1 + y2) / 2 - 10 / self.zoom), label)
                # 端点
                for pt in [(x1, y1), (x2, y2)]:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(QColor(255, 200, 0)))
                    painter.drawEllipse(QPointF(pt[0], pt[1]), 5 / self.zoom, 5 / self.zoom)
            if len(self.ruler_points) % 2 == 1 and self.hover_pos:
                lx, ly = self.ruler_points[-1]
                hx, hy = self.hover_pos
                painter.setPen(QPen(QColor(255, 200, 0, 120), 1.5 / self.zoom, Qt.DashLine))
                painter.drawLine(QPointF(lx, ly), QPointF(hx, hy))

        # ─── 路径 ───
        if self.path_waypoints:
            pixel_path = [self.world_to_pixel(wx, wy) for wx, wy in self.path_waypoints]
            if len(pixel_path) > 1:
                pen_style = Qt.DashLine if self.closed_loop else Qt.SolidLine
                painter.setPen(QPen(QColor(0, 255, 100), 2.5 / self.zoom, pen_style))
                path = QPainterPath()
                path.moveTo(pixel_path[0][0], pixel_path[0][1])
                for i in range(1, len(pixel_path)):
                    path.lineTo(pixel_path[i][0], pixel_path[i][1])
                painter.drawPath(path)

                if pixel_path:
                    sx_p, sy_p = pixel_path[0]
                    ex_p, ey_p = pixel_path[-1]
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(QColor(0, 255, 100)))
                    painter.drawEllipse(QPointF(sx_p, sy_p), 6 / self.zoom, 6 / self.zoom)
                    painter.setBrush(QBrush(QColor(255, 50, 50)))
                    painter.drawEllipse(QPointF(ex_p, ey_p), 6 / self.zoom, 6 / self.zoom)

        # ─── HUD ───
        painter.setPen(QPen(QColor(200, 200, 200)))
        painter.setFont(QFont("Monospace", 10))
        y = 20 / self.zoom
        if self.scale_set:
            painter.drawText(QPointF(10 / self.zoom, y), f"比例: 1px = {self.scale_x:.3f}m")
            y += 16 / self.zoom
        if self.path_waypoints:
            total = sum(math.hypot(self.path_waypoints[i+1][0] - self.path_waypoints[i][0],
                                    self.path_waypoints[i+1][1] - self.path_waypoints[i][1])
                       for i in range(len(self.path_waypoints) - 1))
            painter.drawText(QPointF(10 / self.zoom, y), f"路径: {len(self.path_waypoints)} 点, {total:.1f}m")
            y += 16 / self.zoom
        painter.drawText(QPointF(10 / self.zoom, y),
                         f"区域: {len(self.areas) if self.areas else 1}  障碍物: {len(self.obstacles)}  缩放: {self.zoom:.1f}x")

    # ═══ 鼠标/键盘 ═══
    def mousePressEvent(self, event):
        pos = self._scene_pos(event)
        if not pos:
            self.drag_start = (event.pos().x(), event.pos().y())
            return
        x, y = pos

        if event.button() == Qt.LeftButton:
            if self.mode == MODE_DRAW_AREA:
                self._save_history()
                self.area_points.append((x, y))
                self.update()
                self.status_msg.emit(f"顶点 #{len(self.area_points)}: ({x:.0f}, {y:.0f})")

            elif self.mode == MODE_DRAW_OBSTACLE:
                self.current_drawing.append((x, y))
                self.update()
                self.status_msg.emit(f"障碍物顶点 #{len(self.current_drawing)}: ({x:.0f}, {y:.0f})")

            elif self.mode == MODE_SET_SCALE:
                if not self.scale_start:
                    self.scale_start = (x, y)
                    self.status_msg.emit("比例尺: 再点第二点")
                else:
                    dx = x - self.scale_start[0]
                    dy = y - self.scale_start[1]
                    px_dist = math.hypot(dx, dy)
                    if px_dist < 5:
                        self.scale_start = None
                        self.status_msg.emit("距离太短")
                        self.update()
                        return
                    d, ok = QInputDialog.getDouble(self, "比例尺",
                        f"画线 {px_dist:.0f} px\n对应实际多少米？", 50, 0.1, 10000, 2)
                    if ok and d > 0:
                        self.scale_x = d / px_dist
                        self.scale_y = d / px_dist
                        self.scale_set = True
                        self.status_msg.emit(f"比例尺: 1px = {self.scale_x:.4f}m")
                    self.scale_start = None
                    self.set_mode(MODE_NONE)
                    self.update()

            elif self.mode == MODE_EDIT_VERTEX:
                # 先检查是否点击了障碍物
                oi = self._find_nearest_obstacle(x, y)
                if oi >= 0:
                    self.selected_obstacle_idx = oi
                    self.selected_vertex_idx = -1
                    self.status_msg.emit(f"选中障碍物 #{oi+1}")
                    self.update()
                    return
                # 检查是否点击了顶点
                vi = self._find_nearest_vertex(x, y)
                if vi >= 0:
                    self.selected_vertex_idx = vi
                    self.selected_obstacle_idx = -1
                    self.dragging_vertex = True
                    self._vertex_original = (self.area_points[vi][0], self.area_points[vi][1])
                    self.status_msg.emit(f"选中顶点 #{vi+1}, 拖拽移动")
                    self.update()
                    return
                self.selected_vertex_idx = -1
                self.selected_obstacle_idx = -1
                self.update()

            elif self.mode == MODE_RULER:
                self.ruler_points.append((x, y))
                if len(self.ruler_points) % 2 == 0:
                    x1, y1 = self.ruler_points[-2]
                    x2, y2 = self.ruler_points[-1]
                    dist_px = math.hypot(x2 - x1, y2 - y1)
                    if self.scale_set:
                        dist_m = dist_px * self.scale_x
                        self.status_msg.emit(f"距离: {dist_m:.2f}m ({dist_px:.0f}px)")
                    else:
                        self.status_msg.emit(f"距离: {dist_px:.0f} px (设比例尺后显示米)")
                self.update()

            elif self.mode == MODE_ADD_AREA:
                self._save_history()
                if self.area_points and len(self.area_points) >= 3:
                    self.areas.append(list(self.area_points))
                    self.current_area_idx = len(self.areas)
                self.area_points = [(x, y)]
                self.mode = MODE_DRAW_AREA
                self.update()
                self.status_msg.emit(f"新区域 #{len(self.areas)+1} 顶点 #1")

            else:
                self.drag_start = (event.pos().x(), event.pos().y())

        elif event.button() == Qt.RightButton:
            if self.mode == MODE_DRAW_AREA:
                if len(self.area_points) >= 3:
                    self._save_history()
                    # 完成当前区域
                    self.areas.append(list(self.area_points))
                    self.current_area_idx = len(self.areas) - 1
                    self.status_msg.emit(f"区域完成: {len(self.area_points)} 顶点")
                    if self.scale_set:
                        self.generate_path()
                    self.set_mode(MODE_NONE)
                elif self.area_points:
                    self.area_points.pop()
                    self.status_msg.emit("至少3个点")
                self.update()

            elif self.mode == MODE_DRAW_OBSTACLE:
                if len(self.current_drawing) >= 3:
                    self._save_history()
                    self.obstacles.append(list(self.current_drawing))
                    self.status_msg.emit(f"障碍物 #{len(self.obstacles)}: {len(self.current_drawing)} 顶点")
                    self.current_drawing.clear()
                    if self.scale_set:
                        self.generate_path()
                elif self.current_drawing:
                    self.current_drawing.clear()
                    self.status_msg.emit("取消")
                self.update()

    def mouseMoveEvent(self, event):
        pos = self._scene_pos(event)
        if pos:
            self.hover_pos = pos

        # 拖拽顶点
        if self.dragging_vertex and self.selected_vertex_idx >= 0 and pos:
            idx = self.selected_vertex_idx
            old_x, old_y = self.area_points[idx]
            self.area_points[idx] = (pos[0], pos[1])
            self.update()

        # 拖拽平移
        if self.drag_start and not self.dragging_vertex:
            dx = event.pos().x() - self.drag_start[0]
            dy = event.pos().y() - self.drag_start[1]
            self.offset_x += dx
            self.offset_y += dy
            self.drag_start = (event.pos().x(), event.pos().y())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.dragging_vertex and self.selected_vertex_idx >= 0:
                self.dragging_vertex = False
                # 只在确实移动了时才保存历史
                if self._vertex_original:
                    idx = self.selected_vertex_idx
                    if (self.area_points[idx][0] != self._vertex_original[0] or
                        self.area_points[idx][1] != self._vertex_original[1]):
                        self._save_history()
                        if self.scale_set:
                            self.generate_path()
                self._vertex_original = None
            self.drag_start = None

    def wheelEvent(self, event):
        factor = 1.1
        if event.angleDelta().y() < 0:
            factor = 1 / factor
        self.zoom *= factor
        self.zoom = max(0.1, min(self.zoom, 50))
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.current_drawing:
                self.current_drawing.clear()
                self.status_msg.emit("取消绘制")
            elif self.mode in (MODE_SET_SCALE, MODE_RULER):
                self.set_mode(MODE_NONE)
            elif self.mode in (MODE_DRAW_AREA, MODE_DRAW_OBSTACLE):
                self.set_mode(MODE_NONE)
            else:
                self.scale_start = None
                self.ruler_points.clear()
                self.set_mode(MODE_NONE)
            self.update()

        elif event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            if self.mode == MODE_DRAW_AREA and self.area_points:
                self.area_points.pop()
                self.update()
            elif self.mode == MODE_DRAW_OBSTACLE and self.current_drawing:
                self.current_drawing.pop()
                self.update()
            elif self.selected_obstacle_idx >= 0:
                self.delete_selected()

        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.mode == MODE_DRAW_OBSTACLE and len(self.current_drawing) >= 3:
                self._save_history()
                self.obstacles.append(list(self.current_drawing))
                self.status_msg.emit(f"障碍物确认: {len(self.current_drawing)} 点")
                self.current_drawing.clear()
                if self.scale_set:
                    self.generate_path()
                self.update()
            elif self.mode == MODE_DRAW_AREA and len(self.area_points) >= 3:
                self._save_history()
                self.areas.append(list(self.area_points))
                self.current_area_idx = len(self.areas) - 1
                self.status_msg.emit(f"区域确认: {len(self.area_points)} 顶点")
                if self.scale_set:
                    self.generate_path()
                self.set_mode(MODE_NONE)
                self.update()

        elif event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            if event.modifiers() & Qt.ShiftModifier:
                self.redo()
            else:
                self.undo()
        elif event.key() == Qt.Key_Y and event.modifiers() & Qt.ControlModifier:
            self.redo()

    # ═══ 保存/加载 ═══
    def save_project(self, path):
        data = {
            "version": "0.3",
            "map_path": self.map_path,
            "areas": self.areas,
            "obstacles": self.obstacles,
            "scale_set": self.scale_set,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "params": {
                "sweep_width": self.sweep_width,
                "direction": self.direction,
                "custom_angle": self.custom_angle,
                "closed_loop": self.closed_loop,
                "path_smooth": self.path_smooth,
                "turn_radius": self.turn_radius,
            },
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "zoom": self.zoom,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.status_msg.emit(f"项目已保存: {os.path.basename(path)}")

    def load_project(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 加载地图
        if data.get("map_path") and os.path.exists(data["map_path"]):
            self.load_map(data["map_path"])
        self.areas = data.get("areas", [])
        self.obstacles = data.get("obstacles", [])
        self.scale_set = data.get("scale_set", False)
        self.scale_x = data.get("scale_x", 1.0)
        self.scale_y = data.get("scale_y", 1.0)
        p = data.get("params", {})
        self.sweep_width = p.get("sweep_width", 3.0)
        self.direction = p.get("direction", "horizontal")
        self.custom_angle = p.get("custom_angle", 0)
        self.closed_loop = p.get("closed_loop", False)
        self.path_smooth = p.get("path_smooth", False)
        self.turn_radius = p.get("turn_radius", 2.0)
        self.offset_x = data.get("offset_x", 0)
        self.offset_y = data.get("offset_y", 0)
        self.zoom = data.get("zoom", 1.0)
        if self.areas:
            self.area_points = list(self.areas[-1])
            self.current_area_idx = len(self.areas) - 1
        self.history.clear()
        self.update()
        self.status_msg.emit(f"已加载项目: {os.path.basename(path)}")
        return True

    def export_path(self, path, fmt="txt"):
        if not self.path_waypoints:
            QMessageBox.warning(self, "提示", "请先生成路径")
            return
        if fmt == "txt":
            with open(path, "w") as f:
                f.write("# sweeper-cover coverage path\n")
                total = sum(math.hypot(self.path_waypoints[i+1][0] - self.path_waypoints[i][0],
                                       self.path_waypoints[i+1][1] - self.path_waypoints[i][1])
                          for i in range(len(self.path_waypoints) - 1))
                f.write(f"# total_length: {total:.2f}m points: {len(self.path_waypoints)}\n")
                f.write(f"# sweep_width: {self.sweep_width}m\n")
                f.write("# x(m) y(m)\n")
                for wx, wy in self.path_waypoints:
                    f.write(f"{wx:.3f} {wy:.3f}\n")
        elif fmt == "csv":
            with open(path, "w") as f:
                f.write("x,y\n")
                for wx, wy in self.path_waypoints:
                    f.write(f"{wx:.3f},{wy:.3f}\n")
        elif fmt == "json":
            total = sum(math.hypot(self.path_waypoints[i+1][0] - self.path_waypoints[i][0],
                                   self.path_waypoints[i+1][1] - self.path_waypoints[i][1])
                      for i in range(len(self.path_waypoints) - 1))
            data = {
                "version": "0.3",
                "total_length": round(total, 2),
                "num_points": len(self.path_waypoints),
                "sweep_width": self.sweep_width,
                "closed_loop": self.closed_loop,
                "path": [(round(x, 3), round(y, 3)) for x, y in self.path_waypoints],
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        self.status_msg.emit(f"已导出: {os.path.basename(path)} ({fmt})")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SweeperCover v0.3 — 全覆盖路径规划")
        self.setMinimumSize(1300, 850)

        # ─── 中央部件 ───
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # ═══ 先创建画布 ═══
        self.canvas = MapCanvas()
        self.canvas.status_msg.connect(self._update_status)
        self.canvas.path_changed.connect(self._on_path_changed)

        # ═══ 左侧面板 ═══
        left = QWidget()
        left.setFixedWidth(230)
        lv = QVBoxLayout(left)
        lv.setSpacing(4)
        lv.setContentsMargins(6, 6, 6, 6)

        btn = "QPushButton{padding:6px;font-size:12px;text-align:left;border:1px solid #555;border-radius:3px;background:#3a3a3a;color:#ddd;} QPushButton:hover{background:#4a4a4a;} QPushButton:checked{background:#1a5a8a;border-color:#4096ff;color:#fff;}"
        btn_p = "QPushButton{padding:8px;font-size:13px;font-weight:bold;border:none;border-radius:3px;} QPushButton:hover{opacity:0.9;}"

        # ─── 文件 ───
        self._add_btn(lv, btn, "📂 加载地图", self._load_map, False)
        self._add_btn(lv, btn, "💾 保存项目", self._save_project, False)
        self._add_btn(lv, btn, "📂 加载项目", self._load_project, False)
        lv.addSpacing(4)

        # ─── 绘图模式 ───
        self.btn_area = self._add_btn(lv, btn, "📐 画作业区域", lambda: self._set_mode(MODE_DRAW_AREA), True)
        self.btn_obstacle = self._add_btn(lv, btn, "🚧 画障碍物", lambda: self._set_mode(MODE_DRAW_OBSTACLE), True)
        self.btn_edit = self._add_btn(lv, btn, "✏️ 编辑顶点", lambda: self._set_mode(MODE_EDIT_VERTEX), True)
        self.btn_add_area = self._add_btn(lv, btn, "➕ 多区域", lambda: self._set_mode(MODE_ADD_AREA), False)
        lv.addSpacing(4)

        # ─── 工具 ───
        self.btn_scale = self._add_btn(lv, btn, "📏 比例尺", self._start_scale, False)
        self.btn_ruler = self._add_btn(lv, btn, "📐 测距", lambda: self._set_mode(MODE_RULER), True)
        self.btn_clear = self._add_btn(lv, btn, "🗑️ 清空", self.canvas.clear_all, False)
        self.btn_fit = self._add_btn(lv, btn, "🔍 适应窗口", self._fit_view, False)
        lv.addSpacing(6)

        # ─── 参数 ───
        pg = QGroupBox("参数")
        pg.setStyleSheet("QGroupBox{color:#aaa;border:1px solid #555;border-radius:3px;margin-top:8px;padding-top:12px;font-size:11px;} QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
        pf = QFormLayout(pg)
        pf.setSpacing(3)
        pf.setContentsMargins(6, 10, 6, 6)

        self.ws = QDoubleSpinBox()
        self.ws.setRange(0.5, 20); self.ws.setValue(3.0); self.ws.setSingleStep(0.1); self.ws.setSuffix(" m")
        self.ws.valueChanged.connect(lambda: self.canvas.set_params(self.ws.value(), self._dir(), self._closed(), self.ca.value(), self.smooth_cb.isChecked(), self.tr.value()))
        pf.addRow("宽度:", self.ws)

        self.dc = QComboBox()
        self.dc.addItems(["horizontal", "vertical", "自定义角度"])
        self.dc.currentIndexChanged.connect(lambda: (self.ca.setEnabled(self.dc.currentIndex() == 2), self._params_changed()))
        pf.addRow("方向:", self.dc)

        self.ca = QSpinBox()
        self.ca.setRange(0, 359); self.ca.setValue(0); self.ca.setSuffix("°")
        self.ca.setEnabled(False)
        self.ca.valueChanged.connect(self._params_changed)
        pf.addRow("角度:", self.ca)

        self.cl_cb = QCheckBox("闭环")
        self.cl_cb.toggled.connect(self._params_changed)
        pf.addRow(self.cl_cb)

        self.smooth_cb = QCheckBox("平滑转弯")
        self.smooth_cb.toggled.connect(lambda: (self.tr.setEnabled(self.smooth_cb.isChecked()), self._params_changed()))
        pf.addRow(self.smooth_cb)

        self.tr = QDoubleSpinBox()
        self.tr.setRange(0.5, 10); self.tr.setValue(2.0); self.tr.setSingleStep(0.5); self.tr.setSuffix(" m")
        self.tr.setEnabled(False)
        self.tr.valueChanged.connect(self._params_changed)
        pf.addRow("转弯半径:", self.tr)

        lv.addWidget(pg)

        # ─── 生成/导出 ───
        self.btn_gen = QPushButton("▶ 生成路径")
        self.btn_gen.setStyleSheet(f"{btn_p}background:#4096ff;color:#fff;")
        self.btn_gen.clicked.connect(self.canvas.generate_path)
        lv.addWidget(self.btn_gen)

        self.btn_exp = QPushButton("💾 导出路径")
        self.btn_exp.setStyleSheet(f"{btn_p}background:#52c41a;color:#fff;")
        self.btn_exp.clicked.connect(self._export_path)
        lv.addWidget(self.btn_exp)

        lv.addStretch()

        # ─── 右侧信息面板 ───
        right = QWidget()
        right.setFixedWidth(200)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 6, 6, 6)

        ig = QGroupBox("信息")
        ig.setStyleSheet(pg.styleSheet())
        iv = QVBoxLayout(ig)
        self.info = QLabel("加载地图开始")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#bbb;font-size:11px;")
        iv.addWidget(self.info)
        rv.addWidget(ig)

        self.export_fmt = QComboBox()
        self.export_fmt.addItems(["txt (x y)", "csv (x,y)", "json"])
        rv.addWidget(QLabel("导出格式:"))
        rv.addWidget(self.export_fmt)
        rv.addStretch()

        # ─── 组装 ───
        layout.addWidget(left)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(right)

        # 状态栏
        self.sb = QStatusBar()
        self.sb.setStyleSheet("QStatusBar{background:#2d2d2d;color:#888;} QStatusBar::item{border:none;}")
        self.setStatusBar(self.sb)
        self.sb.showMessage("就绪 — v0.3   Ctrl+Z撤销  Ctrl+Shift+Z/Ctrl+Y重做")

    def _add_btn(self, layout, style, text, slot, checkable):
        b = QPushButton(text)
        b.setStyleSheet(style)
        if checkable:
            b.setCheckable(True)
            b.clicked.connect(lambda checked, btn=b: slot() if checked else self.canvas.set_mode(MODE_NONE))
        else:
            b.clicked.connect(slot)
        layout.addWidget(b)
        return b

    def _dir(self):
        idx = self.dc.currentIndex()
        if idx == 2: return "custom"
        return self.dc.currentText()

    def _closed(self):
        return self.cl_cb.isChecked()

    def _params_changed(self):
        d = "custom" if self.dc.currentIndex() == 2 else self.dc.currentText()
        self.canvas.set_params(self.ws.value(), d, self.cl_cb.isChecked(),
                               self.ca.value(), self.smooth_cb.isChecked(), self.tr.value())

    def _set_mode(self, mode):
        for b in [self.btn_area, self.btn_obstacle, self.btn_edit, self.btn_ruler]:
            b.setChecked(False)
        self.canvas.set_mode(mode)

    def _load_map(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择地图", "", "图片 (*.png *.jpg *.jpeg *.bmp *.tiff);;所有文件 (*)")
        if p and self.canvas.load_map(p):
            self.info.setText(f"地图: {os.path.basename(p)}\n{self.canvas.map_image.width()}×{self.canvas.map_image.height()}px")

    def _save_project(self):
        p, _ = QFileDialog.getSaveFileName(self, "保存项目", "project.json", "JSON (*.json)")
        if p: self.canvas.save_project(p)

    def _load_project(self):
        p, _ = QFileDialog.getOpenFileName(self, "加载项目", "", "JSON (*.json)")
        if p and self.canvas.load_project(p):
            self.ws.setValue(self.canvas.sweep_width)
            self.cl_cb.setChecked(self.canvas.closed_loop)
            self.smooth_cb.setChecked(self.canvas.path_smooth)
            self.tr.setValue(self.canvas.turn_radius)
            if self.canvas.direction == "custom":
                self.dc.setCurrentIndex(2)
                self.ca.setValue(self.canvas.custom_angle)
            else:
                self.dc.setCurrentText(self.canvas.direction)
            self.info.setText(f"项目: {os.path.basename(p)}\n{len(self.canvas.areas)} 区域, {len(self.canvas.obstacles)} 障碍物")

    def _start_scale(self):
        if not self.canvas.map_pixmap:
            QMessageBox.warning(self, "提示", "请先加载地图"); return
        for b in [self.btn_area, self.btn_obstacle, self.btn_edit, self.btn_ruler]:
            b.setChecked(False)
        self.canvas.set_mode(MODE_SET_SCALE)

    def _fit_view(self):
        if self.canvas.map_pixmap:
            pw, ph = self.canvas.map_pixmap.width(), self.canvas.map_pixmap.height()
            cw, ch = self.canvas.width(), self.canvas.height()
            self.canvas.zoom = min((cw - 40) / pw, (ch - 40) / ph)
            self.canvas.offset_x = (cw - pw * self.canvas.zoom) / 2
            self.canvas.offset_y = (ch - ph * self.canvas.zoom) / 2
            self.canvas.update()

    def _export_path(self):
        fmt = ["txt", "csv", "json"][self.export_fmt.currentIndex()]
        ext = {"txt": ".txt", "csv": ".csv", "json": ".json"}
        p, _ = QFileDialog.getSaveFileName(self, "导出路径", f"coverage_path{ext[fmt]}",
                                            f"*.{fmt};;所有文件 (*)")
        if p: self.canvas.export_path(p, fmt)

    def _update_status(self, msg):
        self.sb.showMessage(msg, 5000)

    def _on_path_changed(self, waypoints):
        total = sum(math.hypot(waypoints[i+1][0] - waypoints[i][0],
                               waypoints[i+1][1] - waypoints[i][1])
                   for i in range(len(waypoints) - 1)) if waypoints else 0
        if self.canvas.scale_set:
            self.info.setText(f"路径: {len(waypoints)} 点\n长度: {total:.1f} m\n"
                             f"区域: {len(self.canvas.areas) if self.canvas.areas else 1}\n"
                             f"障碍物: {len(self.canvas.obstacles)}\n"
                             f"闭环: {'是' if self.canvas.closed_loop else '否'}")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # 深色主题
    app.setStyleSheet("""
        QMainWindow, QWidget { background: #2b2b2b; color: #ccc; }
        QGroupBox { color: #aaa; }
        QLabel { color: #bbb; }
        QComboBox, QDoubleSpinBox, QSpinBox { background: #3a3a3a; color: #ddd; border: 1px solid #555; padding: 2px; }
        QCheckBox { color: #ccc; }
        QStatusBar { background: #2d2d2d; color: #888; }
        QListWidget { background: #3a3a3a; color: #ddd; border: 1px solid #555; }
    """)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
