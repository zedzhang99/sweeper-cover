"""
SweeperCover Road Planner — 道路作业路线规划工具

加载卫星图 → 画道路 → 设定参数 → 自动分车 → 导出方案
"""

import sys, os, math, json

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDoubleSpinBox, QSpinBox, QGroupBox,
    QFormLayout, QStatusBar, QFileDialog, QMessageBox, QSplitter,
)
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, QFont,
    QPolygonF, QMouseEvent, QWheelEvent, QPainterPath,
)

# ─── 道路路径规划算法 ───

def plan_routes(road_paths, road_width, vehicle_width, num_vehicles, max_distance_per_vehicle_km):
    """
    沿道路路径规划多车作业路线。

    Args:
        road_paths: 道路路径列表，每个路径是 [(x,y),...]（世界坐标米）
        road_width: 道路宽度（米）
        vehicle_width: 车辆作业宽度（米）
        num_vehicles: 车辆数
        max_distance_per_vehicle_km: 每台车单趟最大距离（公里）

    Returns:
        routes: 每台车的路线信息列表
        total_length: 道路总长（米）
    """
    max_m = max_distance_per_vehicle_km * 1000

    # 计算每条路径的长度
    path_info = []
    for path in road_paths:
        length = 0
        for i in range(len(path) - 1):
            length += math.hypot(path[i+1][0] - path[i][0], path[i+1][1] - path[i][1])
        path_info.append({"points": path, "length": length})

    total_length = sum(p["length"] for p in path_info)

    # 计算需要的通行次数（覆盖全宽需要跑几趟）
    passes_needed = math.ceil(road_width / vehicle_width)

    # 每台车的目标距离
    target_per_vehicle = min(max_m, total_length / num_vehicles)

    # 贪心分配：按路径顺序依次分配给各车
    # 改进：支持将长路径分段分配给不同车辆
    vehicle_routes = [[] for _ in range(num_vehicles)]
    vehicle_dists = [0.0] * num_vehicles
    max_per_veh = target_per_vehicle

    for pi in range(len(road_paths)):
        path_len = path_info[pi]["length"]
        path_pts = path_info[pi]["points"]

        # 找当前总距离最小的车辆
        v = min(range(num_vehicles), key=lambda i: vehicle_dists[i])

        if vehicle_dists[v] + path_len <= max_per_veh or path_len <= max_per_veh * 0.3:
            # 整段分配给这台车
            vehicle_routes[v].append(pi)
            vehicle_dists[v] += path_len
        else:
            # 长路径需要分段：分配给多台车
            # 计算每台车还能装多少
            remaining_in_path = path_len
            seg_start = 0

            while remaining_in_path > 0.01:
                v = min(range(num_vehicles), key=lambda i: vehicle_dists[i])
                avail = max(0, max_per_veh - vehicle_dists[v])

                if remaining_in_path <= avail or avail <= 1:
                    # 剩余部分全给这台车
                    seg_end = len(path_pts) - 1
                    vehicle_routes[v].append(pi)
                    vehicle_dists[v] += remaining_in_path
                    remaining_in_path = 0
                else:
                    # 取一部分给这台车，剩下的继续
                    ratio = avail / path_len
                    seg_end = int(seg_start + ratio * (len(path_pts) - 1))
                    seg_end = max(seg_start + 1, min(seg_end, len(path_pts) - 1))
                    vehicle_routes[v].append(pi)
                    vehicle_dists[v] += avail
                    remaining_in_path -= avail
                    seg_start = seg_end

    # 构建 routes
    colors = ["#FF4444", "#4488FF", "#44CC44", "#FF8800", "#AA44FF"]
    routes = []
    for v in range(num_vehicles):
        routes.append({
            "vehicle_id": v + 1,
            "path_indices": vehicle_routes[v],
            "distance": vehicle_dists[v],
            "waypoints": [],
            "color": colors[v % len(colors)],
            "passes": passes_needed,
        })
        routes[v]["waypoints"] = _generate_vehicle_waypoints(
            road_paths, routes[v]["path_indices"],
            road_width, vehicle_width, passes_needed,
        )

    total_route_dist = sum(r["distance"] for r in routes)
    return routes, total_length


def _generate_vehicle_waypoints(all_paths, path_indices, road_width, vehicle_width, passes):
    """生成某台车的完整路径点（含多趟偏移）"""
    waypoints = []
    for pi in path_indices:
        path = list(all_paths[pi])
        if len(path) < 2:
            continue

        for lap in range(passes):
            # 计算偏移量：0 → 左侧，passes-1 → 右侧
            if passes == 1:
                offset = 0
            else:
                offset = -road_width/2 + (lap + 0.5) * (road_width / passes)
                offset = max(-road_width/2, min(road_width/2, offset))

            # 沿路径方向偏移生成路径点
            lap_pts = []
            for i in range(len(path)):
                if i == 0:
                    # 第一个点：沿路径方向偏移
                    dx = path[1][0] - path[0][0]
                    dy = path[1][1] - path[0][1]
                elif i == len(path) - 1:
                    # 最后一个点：沿上一个段的方向偏移
                    dx = path[-1][0] - path[-2][0]
                    dy = path[-1][1] - path[-2][1]
                else:
                    # 中间点：前后方向的平均
                    dx = path[i+1][0] - path[i-1][0]
                    dy = path[i+1][1] - path[i-1][1]

                length = math.hypot(dx, dy)
                if length < 0.01:
                    lap_pts.append(path[i])
                    continue

                # 法线方向（垂直方向，向左转90度）
                nx, ny = -dy / length, dx / length
                lap_pts.append((path[i][0] + nx * offset, path[i][1] + ny * offset))

            # 奇数趟反转方向（形成来回）
            if lap % 2 == 1:
                lap_pts.reverse()

            waypoints.extend(lap_pts)

    return waypoints


# ─── GUI ───

MODE_NONE = 0
MODE_DRAW_ROAD = 1
MODE_SET_SCALE = 2


class RoadCanvas(QWidget):
    status_msg = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(900, 650)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # 地图
        self.map_pixmap = None
        self.map_path = ""

        # 比例尺
        self.scale_x = 1.0
        self.scale_set = False
        self.scale_start = None

        # 绘制的道路（像素坐标）
        self.road_paths = []        # 多条道路路径
        self.current_drawing = []   # 当前正在画的路径

        # 规划结果
        self.routes = []
        self.world_roads = []

        # 参数
        self.road_width = 6.0
        self.vehicle_width = 1.09
        self.num_vehicles = 2
        self.max_distance = 5.0

        # 交互
        self.mode = MODE_NONE
        self.zoom = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.drag_start = None
        self.hover_pos = None

    def set_mode(self, mode):
        self.mode = mode
        names = {
            MODE_NONE: "就绪",
            MODE_DRAW_ROAD: "画道路: 左键加点, 右键完成一段",
            MODE_SET_SCALE: "比例尺: 点击两点, 输入实际米数",
        }
        self.status_msg.emit(names.get(mode, ""))

    def load_map(self, path):
        img = QImage(path)
        if img.isNull():
            return False
        self.map_pixmap = QPixmap.fromImage(img)
        self.map_path = path
        self.road_paths.clear()
        self.current_drawing.clear()
        self.routes = []
        self.scale_set = False
        self.zoom = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.update()
        self.status_msg.emit(f"已加载: {os.path.basename(path)} ({img.width()}×{img.height()})")
        return True

    def px_to_world(self, px, py):
        return (px * self.scale_x, py * self.scale_y)

    def world_to_px(self, wx, wy):
        return (wx / self.scale_x, wy / self.scale_x)

    def _scene_pos(self, event):
        sx = (event.pos().x() - self.offset_x) / self.zoom
        sy = (event.pos().y() - self.offset_y) / self.zoom
        return (sx, sy)

    # ═══ 生成规划 ═══
    def generate_plan(self):
        if not self.scale_set:
            self.status_msg.emit("⚠️ 请先设定比例尺")
            return
        if not self.road_paths:
            self.status_msg.emit("⚠️ 请先画道路")
            return

        # 转换到世界坐标
        world_roads = []
        for path in self.road_paths:
            world_roads.append([self.px_to_world(p[0], p[1]) for p in path])

        self.world_roads = world_roads

        routes, total_len = plan_routes(
            world_roads, self.road_width, self.vehicle_width,
            self.num_vehicles, self.max_distance,
        )
        self.routes = routes

        info = f"道路总长: {total_len:.1f}m | "
        for r in routes:
            info += f"车{r['vehicle_id']}: {r['distance']:.1f}m ({len(r['path_indices'])}段)  "
        self.status_msg.emit(info)
        self.update()

    def export_plan(self, path):
        if not self.routes:
            self.status_msg.emit("请先生成规划")
            return

        with open(path, "w", encoding="utf-8") as f:
            f.write("# SweeperCover 道路作业路线规划\n")
            f.write(f"# 道路总长: {sum(r['distance'] for r in self.routes):.1f}m\n")
            f.write(f"# 道路宽度: {self.road_width}m  车辆宽度: {self.vehicle_width}m\n")
            f.write(f"# 车辆数: {self.num_vehicles}\n\n")

            for r in self.routes:
                f.write(f"--- 车{r['vehicle_id']} ---\n")
                f.write(f"路线长度: {r['distance']:.1f}m\n")
                f.write(f"通行趟数: {r['passes']}\n")
                f.write(f"路段数: {len(r['path_indices'])}\n")
                f.write("x(m),y(m)\n")
                for wx, wy in r["waypoints"]:
                    f.write(f"{wx:.3f},{wy:.3f}\n")
                f.write("\n")

        self.status_msg.emit(f"已导出: {os.path.basename(path)}")

    # ═══ 绘制 ═══
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(42, 42, 42))
        painter.translate(self.offset_x, self.offset_y)
        painter.scale(self.zoom, self.zoom)

        if self.map_pixmap and not self.map_pixmap.isNull():
            painter.drawPixmap(0, 0, self.map_pixmap)

        # 已完成的道路
        for path in self.road_paths:
            if len(path) < 2:
                continue
            pts = [QPointF(p[0], p[1]) for p in path]
            painter.setPen(QPen(QColor(255, 200, 50), 4 / self.zoom, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])
            # 端点
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 200, 50)))
            for p in [pts[0], pts[-1]]:
                painter.drawEllipse(p, 4 / self.zoom, 4 / self.zoom)

        # 当前绘制
        if len(self.current_drawing) >= 1:
            pts = [QPointF(p[0], p[1]) for p in self.current_drawing]
            painter.setPen(QPen(QColor(0, 220, 255), 3 / self.zoom, Qt.DashLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])
            if self.hover_pos and self.current_drawing:
                lx, ly = self.current_drawing[-1]
                painter.setPen(QPen(QColor(0, 220, 255, 100), 1.5 / self.zoom, Qt.DashLine))
                painter.drawLine(QPointF(lx, ly), QPointF(self.hover_pos[0], self.hover_pos[1]))
            for p in pts:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(0, 220, 255)))
                painter.drawEllipse(p, 4 / self.zoom, 4 / self.zoom)

        # 比例尺参考
        if self.scale_start and self.hover_pos:
            sx, sy = self.scale_start
            hx, hy = self.hover_pos
            painter.setPen(QPen(QColor(255, 165, 0), 2 / self.zoom))
            painter.drawLine(QPointF(sx, sy), QPointF(hx, hy))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 165, 0)))
            painter.drawEllipse(QPointF(sx, sy), 5 / self.zoom, 5 / self.zoom)
            painter.drawEllipse(QPointF(hx, hy), 5 / self.zoom, 5 / self.zoom)
            dist = math.hypot(hx - sx, hy - sy)
            painter.setPen(QPen(QColor(255, 165, 0)))
            painter.setFont(QFont("Arial", 11 / self.zoom))
            painter.drawText(QPointF((sx + hx) / 2, (sy + hy) / 2 - 10 / self.zoom), f"{dist:.0f} px")

        # 规划结果
        for r in self.routes:
            if not r["waypoints"]:
                continue
            color = QColor(r["color"])
            pts = [QPointF(self.world_to_px(wx, wy)[0], self.world_to_px(wx, wy)[1])
                   for wx, wy in r["waypoints"]]
            painter.setPen(QPen(color, 3 / self.zoom))
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i], pts[i + 1])
            # 起点
            if pts:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(pts[0], 6 / self.zoom, 6 / self.zoom)

        # HUD
        painter.setPen(QPen(QColor(180, 180, 180)))
        painter.setFont(QFont("Monospace", 10))
        y = 20 / self.zoom
        if self.scale_set:
            painter.drawText(QPointF(10 / self.zoom, y), f"比例: 1px = {self.scale_x:.3f}m")
            y += 16 / self.zoom
        painter.drawText(QPointF(10 / self.zoom, y),
                         f"道路: {len(self.road_paths)}段  缩放: {self.zoom:.1f}x")

    # ═══ 鼠标/键盘 ═══
    def mousePressEvent(self, event):
        pos = self._scene_pos(event)
        if not pos or not self.map_pixmap:
            self.drag_start = (event.pos().x(), event.pos().y())
            return
        x, y = pos

        if event.button() == Qt.LeftButton:
            if self.mode == MODE_DRAW_ROAD:
                self.current_drawing.append((x, y))
                self.update()
                self.status_msg.emit(f"路径点 #{len(self.current_drawing)}: ({x:.0f}, {y:.0f})")

            elif self.mode == MODE_SET_SCALE:
                if not self.scale_start:
                    self.scale_start = (x, y)
                    self.status_msg.emit("比例尺: 再点第二点")
                else:
                    dx, dy = x - self.scale_start[0], y - self.scale_start[1]
                    px_dist = math.hypot(dx, dy)
                    if px_dist < 5:
                        self.scale_start = None
                        self.update()
                        return
                    d, ok = QInputDialog.getDouble(self, "比例尺",
                        f"画线 {px_dist:.0f}px\n对应实际多少米？", 50, 0.1, 10000, 2)
                    if ok and d > 0:
                        self.scale_x = d / px_dist
                        self.scale_set = True
                        self.status_msg.emit(f"比例尺: 1px = {self.scale_x:.4f}m ({d}m/{px_dist:.0f}px)")
                    self.scale_start = None
                    self.mode = MODE_NONE
                    self.update()

            else:
                self.drag_start = (event.pos().x(), event.pos().y())

        elif event.button() == Qt.RightButton:
            if self.mode == MODE_DRAW_ROAD:
                if len(self.current_drawing) >= 2:
                    self.road_paths.append(list(self.current_drawing))
                    self.status_msg.emit(f"道路 #{len(self.road_paths)} 完成: {len(self.current_drawing)} 点")
                    self.current_drawing.clear()
                else:
                    self.current_drawing.clear()
                    self.status_msg.emit("取消")
                self.update()

    def mouseMoveEvent(self, event):
        pos = self._scene_pos(event)
        if pos:
            self.hover_pos = pos
        if self.drag_start:
            dx = event.pos().x() - self.drag_start[0]
            dy = event.pos().y() - self.drag_start[1]
            self.offset_x += dx
            self.offset_y += dy
            self.drag_start = (event.pos().x(), event.pos().y())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start = None

    def wheelEvent(self, event):
        f = 1.1
        if event.angleDelta().y() < 0:
            f = 1 / f
        self.zoom = max(0.1, min(self.zoom * f, 50))
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.current_drawing.clear()
            self.scale_start = None
            self.mode = MODE_NONE
            self.update()
            self.status_msg.emit("取消")
        elif event.key() == Qt.Key_Backspace or event.key() == Qt.Key_Delete:
            if self.current_drawing:
                self.current_drawing.pop()
                self.update()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SweeperCover — 道路作业路线规划")
        self.setMinimumSize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.canvas = RoadCanvas()
        self.canvas.status_msg.connect(self._on_status)

        # ─── 侧边栏 ───
        side = QWidget()
        side.setFixedWidth(240)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(8, 8, 8, 8)
        sv.setSpacing(6)

        btn = "QPushButton{padding:7px;font-size:12px;border:1px solid #555;border-radius:3px;background:#3a3a3a;color:#ddd;text-align:left;} QPushButton:hover{background:#4a4a4a;}"

        self.b_load = QPushButton("📂 加载地图")
        self.b_load.setStyleSheet(btn)
        self.b_load.clicked.connect(self._load)

        self.b_draw = QPushButton("✏️ 画道路")
        self.b_draw.setStyleSheet(btn)
        self.b_draw.setCheckable(True)
        self.b_draw.clicked.connect(lambda c: self.canvas.set_mode(MODE_DRAW_ROAD if c else MODE_NONE))

        self.b_scale = QPushButton("📏 比例尺")
        self.b_scale.setStyleSheet(btn)
        self.b_scale.clicked.connect(self._start_scale)

        self.b_fit = QPushButton("🔍 适应窗口")
        self.b_fit.setStyleSheet(btn)
        self.b_fit.clicked.connect(self._fit)

        self.b_clear = QPushButton("🗑️ 清空道路")
        self.b_clear.setStyleSheet(btn)
        self.b_clear.clicked.connect(self._clear)

        sv.addWidget(self.b_load)
        sv.addWidget(self.b_draw)
        sv.addWidget(self.b_scale)
        sv.addWidget(self.b_fit)
        sv.addWidget(self.b_clear)

        # ─── 参数 ───
        pg = QGroupBox("作业参数")
        pg.setStyleSheet("QGroupBox{color:#aaa;border:1px solid #555;border-radius:3px;margin-top:8px;padding-top:14px;font-size:11px;} QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}")
        pf = QFormLayout(pg)
        pf.setSpacing(4)
        pf.setContentsMargins(8, 12, 8, 8)

        self.w_road = QDoubleSpinBox()
        self.w_road.setRange(1, 30); self.w_road.setValue(6); self.w_road.setSuffix(" m")
        pf.addRow("道路宽度:", self.w_road)

        self.w_veh = QDoubleSpinBox()
        self.w_veh.setRange(0.3, 5); self.w_veh.setValue(1.09); self.w_veh.setSuffix(" m")
        pf.addRow("车辆宽度:", self.w_veh)

        self.n_veh = QSpinBox()
        self.n_veh.setRange(1, 10); self.n_veh.setValue(2)
        pf.addRow("车辆数:", self.n_veh)

        self.max_dist = QDoubleSpinBox()
        self.max_dist.setRange(0.5, 20); self.max_dist.setValue(5); self.max_dist.setSuffix(" km")
        pf.addRow("单趟上限:", self.max_dist)

        sv.addWidget(pg)

        # ─── 规划 & 导出 ───
        self.b_plan = QPushButton("▶ 生成方案")
        self.b_plan.setStyleSheet("QPushButton{padding:10px;font-size:14px;font-weight:bold;background:#4096ff;color:#fff;border:none;border-radius:3px;} QPushButton:hover{background:#1677ff;}")
        self.b_plan.clicked.connect(self._plan)

        self.b_export = QPushButton("💾 导出方案")
        self.b_export.setStyleSheet("QPushButton{padding:8px;font-size:13px;background:#52c41a;color:#fff;border:none;border-radius:3px;} QPushButton:hover{background:#389e0d;}")
        self.b_export.clicked.connect(self._export)

        sv.addSpacing(8)
        sv.addWidget(self.b_plan)
        sv.addWidget(self.b_export)
        sv.addStretch()

        # ─── 信息面板 ───
        info_g = QGroupBox("规划结果")
        info_g.setStyleSheet(pg.styleSheet())
        info_v = QVBoxLayout(info_g)
        self.info_label = QLabel("加载地图→画道路→设比例尺→规划")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color:#bbb;font-size:11px;")
        info_v.addWidget(self.info_label)
        sv.addWidget(info_g)

        # 组装
        layout.addWidget(side)
        layout.addWidget(self.canvas, 1)

        self.sb = QStatusBar()
        self.sb.setStyleSheet("QStatusBar{background:#2d2d2d;color:#888;}")
        self.setStatusBar(self.sb)
        self.sb.showMessage("就绪 —— 沿着非机动车道画线，一键出方案")

    def _load(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择地图", "", "图片 (*.png *.jpg *.jpeg)")
        if p and self.canvas.load_map(p):
            self._fit()

    def _start_scale(self):
        if not self.canvas.map_pixmap:
            QMessageBox.warning(self, "提示", "请先加载地图"); return
        self.b_draw.setChecked(False)
        self.canvas.set_mode(MODE_SET_SCALE)

    def _fit(self):
        if self.canvas.map_pixmap:
            pw, ph = self.canvas.map_pixmap.width(), self.canvas.map_pixmap.height()
            cw, ch = self.canvas.width(), self.canvas.height()
            self.canvas.zoom = min((cw - 40) / pw, (ch - 40) / ph)
            self.canvas.offset_x = (cw - pw * self.canvas.zoom) / 2
            self.canvas.offset_y = (ch - ph * self.canvas.zoom) / 2
            self.canvas.update()

    def _clear(self):
        self.canvas.road_paths.clear()
        self.canvas.routes = []
        self.canvas.update()
        self.info_label.setText("道路已清空")
        self.sb.showMessage("已清空道路", 3000)

    def _plan(self):
        self.canvas.road_width = self.w_road.value()
        self.canvas.vehicle_width = self.w_veh.value()
        self.canvas.num_vehicles = self.n_veh.value()
        self.canvas.max_distance = self.max_dist.value()
        self.canvas.generate_plan()

        # 更新信息面板
        if self.canvas.routes:
            text = f"道路总长: {sum(r['distance'] for r in self.canvas.routes):.0f}m\n"
            for r in self.canvas.routes:
                text += f"\n● 车{r['vehicle_id']}: {r['distance']:.0f}m"
                text += f"\n  趟数: {r['passes']}"
                text += f"\n  颜色: {r['color']}"
            self.info_label.setText(text)

    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "导出方案", "road_plan.txt", "文本文件 (*.txt)")
        if p:
            self.canvas.export_plan(p)

    def _on_status(self, msg):
        self.sb.showMessage(msg, 5000)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMainWindow{background:#2b2b2b;color:#ccc;}
        QWidget{color:#ccc;}
        QGroupBox{color:#aaa;}
        QLabel{color:#bbb;}
        QDoubleSpinBox,QSpinBox{background:#3a3a3a;color:#ddd;border:1px solid #555;padding:2px;}
        QStatusBar{background:#2d2d2d;color:#888;}
    """)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
