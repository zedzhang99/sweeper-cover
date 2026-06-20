"""
SweeperCover GUI — PyQt5 可视化全覆盖路径规划编辑器

使用流程：
  1. 加载地图图片（卫星图/现场照片）
  2. 画作业区域边界
  3. 画障碍物（树池/花坛/石柱等）
  4. 设定比例尺（画参考线，输入实际距离）
  5. 设定作业参数（宽度、方向）
  6. 生成覆盖路径
  7. 导出
"""

import sys, os, math, json

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDoubleSpinBox, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QInputDialog, QListWidget, QListWidgetItem,
    QSplitter, QFrame, QGroupBox, QFormLayout, QStatusBar,
    QScrollArea,
)
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, QFont,
    QPolygonF, QMouseEvent, QWheelEvent, QKeyEvent,
)

# ─── 导入核心算法 ───
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sweeper_cover.coverage import generate_zigzag, generate_zigzag_closed, CoveragePath


MODE_NONE = 0
MODE_DRAW_AREA = 1
MODE_DRAW_OBSTACLE = 2
MODE_SET_SCALE = 3


class MapCanvas(QWidget):
    """地图画布 — 显示底图 + 绘制多边形 + 路径"""
    status_msg = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # 底图
        self.map_image = None
        self.map_pixmap = None
        self.scale_x = 1.0  # 每像素对应多少米
        self.scale_y = 1.0
        self.scale_set = False

        # 绘图数据
        self.area_points = []      # 作业区域顶点（像素坐标）
        self.obstacles = []        # 障碍物列表，每个是顶点列表
        self.current_drawing = []  # 当前正在画的多边形

        # 路径
        self.path_segments = []     # 生成的路径点（米坐标）
        self.world_area = []        # 作业区域（米坐标）
        self.world_obstacles = []   # 障碍物（米坐标）

        # 模式
        self.mode = MODE_NONE
        self.scale_start = None

        # 参数
        self.sweep_width = 3.0
        self.direction = "horizontal"
        self.closed_loop = False

        # 交互
        self.drag_start = None
        self.offset_x = 0
        self.offset_y = 0
        self.zoom = 1.0
        self.hover_pos = None
        self.last_mouse_pos = None

        # 右键菜单位置
        self.mouse_scene_pos = None

    def set_mode(self, mode):
        self.mode = mode
        mode_names = {MODE_NONE: "就绪", MODE_DRAW_AREA: "画作业区域", 
                       MODE_DRAW_OBSTACLE: "画障碍物", MODE_SET_SCALE: "设定比例尺"}
        self.status_msg.emit(f"模式: {mode_names.get(mode, '?')}")

    def set_params(self, width, direction, closed):
        self.sweep_width = width
        self.direction = direction
        self.closed_loop = closed

    def load_map(self, path):
        self.map_image = QImage(path)
        if self.map_image.isNull():
            QMessageBox.warning(self, "错误", f"无法加载图片: {path}")
            return False
        self.map_pixmap = QPixmap.fromImage(self.map_image)
        self.area_points.clear()
        self.obstacles.clear()
        self.path_segments = []
        self.scale_set = False
        self.zoom = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.update()
        self.status_msg.emit(f"已加载地图: {os.path.basename(path)} ({self.map_image.width()}×{self.map_image.height()})")
        return True

    def pixel_to_world(self, px, py):
        """像素坐标 → 世界坐标（米）"""
        return (px * self.scale_x, py * self.scale_y)

    def world_to_pixel(self, wx, wy):
        """世界坐标（米）→ 像素坐标"""
        return (wx / self.scale_x, wy / self.scale_y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 背景
        painter.fillRect(self.rect(), QColor(240, 240, 240))

        # 变换
        painter.translate(self.offset_x, self.offset_y)
        painter.scale(self.zoom, self.zoom)

        # 底图
        if self.map_pixmap and not self.map_pixmap.isNull():
            painter.drawPixmap(0, 0, self.map_pixmap)

        # ─── 绘制作业区域 ───
        if self.area_points:
            poly = QPolygonF([QPointF(p[0], p[1]) for p in self.area_points])
            painter.setPen(QPen(QColor(0, 120, 255), 3 / self.zoom))
            painter.setBrush(QBrush(QColor(0, 120, 255, 30)))
            painter.drawPolygon(poly)

            # 顶点
            for p in self.area_points:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(0, 120, 255)))
                painter.drawEllipse(QPointF(p[0], p[1]), 5 / self.zoom, 5 / self.zoom)

        # ─── 绘制障碍物 ───
        for obs in self.obstacles:
            if len(obs) > 2:
                poly = QPolygonF([QPointF(p[0], p[1]) for p in obs])
                painter.setPen(QPen(QColor(255, 50, 50), 2 / self.zoom))
                painter.setBrush(QBrush(QColor(255, 50, 50, 40)))
                painter.drawPolygon(poly)

        # ─── 绘制当前正在画的多边形 ───
        if len(self.current_drawing) >= 2:
            painter.setPen(QPen(QColor(0, 200, 0, 180), 2 / self.zoom, Qt.DashLine))
            for i in range(len(self.current_drawing) - 1):
                x1, y1 = self.current_drawing[i]
                x2, y2 = self.current_drawing[i + 1]
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            # 当前点到鼠标
            if self.hover_pos and self.current_drawing:
                lx, ly = self.current_drawing[-1]
                painter.setPen(QPen(QColor(0, 200, 0, 100), 1 / self.zoom, Qt.DashLine))
                painter.drawLine(QPointF(lx, ly), QPointF(self.hover_pos[0], self.hover_pos[1]))
            # 点
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
            # 距离标注（像素）
            dist = math.hypot(hx - sx, hy - sy)
            painter.setPen(QPen(QColor(255, 165, 0)))
            painter.setFont(QFont("Arial", 12 / self.zoom))
            painter.drawText(QPointF((sx + hx) / 2, (sy + hy) / 2 - 10 / self.zoom),
                             f"{dist:.0f} px")

        # ─── 覆盖路径 ───
        if self.path_segments:
            # 先把世界坐标转回像素
            pixel_path = []
            for wx, wy in self.path_segments:
                px, py = self.world_to_pixel(wx, wy)
                pixel_path.append((px, py))

            if len(pixel_path) > 1:
                pen_style = Qt.DashLine if self.closed_loop else Qt.SolidLine
                painter.setPen(QPen(QColor(0, 200, 0), 2.5 / self.zoom, pen_style))
                for i in range(len(pixel_path) - 1):
                    x1, y1 = pixel_path[i]
                    x2, y2 = pixel_path[i + 1]
                    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

                # 起点/终点
                if pixel_path:
                    sx_p, sy_p = pixel_path[0]
                    ex_p, ey_p = pixel_path[-1]
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(QColor(0, 200, 0)))
                    painter.drawEllipse(QPointF(sx_p, sy_p), 6 / self.zoom, 6 / self.zoom)
                    painter.setBrush(QBrush(QColor(255, 0, 0)))
                    painter.drawEllipse(QPointF(ex_p, ey_p), 6 / self.zoom, 6 / self.zoom)

            # 路径信息
            total_m = sum(
                math.hypot(self.path_segments[i+1][0] - self.path_segments[i][0],
                           self.path_segments[i+1][1] - self.path_segments[i][1])
                for i in range(len(self.path_segments) - 1)
            )
            painter.setPen(QPen(QColor(0, 0, 0)))
            painter.setFont(QFont("Arial", 11 / self.zoom))
            info = f"路径: {len(self.path_segments)} 点, {total_m:.1f} m"
            if self.closed_loop:
                info += " [闭环]"
            painter.drawText(QPointF(10 / self.zoom, self.height() / self.zoom - 50 / self.zoom), info)

        # ─── 比例尺标注 ───
        if self.scale_set:
            painter.setPen(QPen(QColor(80, 80, 80)))
            painter.setFont(QFont("Arial", 10 / self.zoom))
            painter.drawText(QPointF(10 / self.zoom, self.height() / self.zoom - 20 / self.zoom),
                             f"比例尺: 1px = {self.scale_x:.3f}m")

    def mousePressEvent(self, event: QMouseEvent):
        pos = self._scene_pos(event)
        if not pos:
            return

        x, y = pos
        self.mouse_scene_pos = (x, y)

        if event.button() == Qt.LeftButton:
            if self.mode == MODE_DRAW_AREA:
                self.area_points.append((x, y))
                self.update()
                self.status_msg.emit(f"区域顶点 #{len(self.area_points)}: ({x:.0f}, {y:.0f})")

            elif self.mode == MODE_DRAW_OBSTACLE:
                self.current_drawing.append((x, y))
                self.update()
                self.status_msg.emit(f"障碍物顶点 #{len(self.current_drawing)}: ({x:.0f}, {y:.0f})")

            elif self.mode == MODE_SET_SCALE:
                if not self.scale_start:
                    self.scale_start = (x, y)
                    self.status_msg.emit("比例尺: 点击第二点")
                else:
                    # 计算像素距离
                    dx = x - self.scale_start[0]
                    dy = y - self.scale_start[1]
                    pixel_dist = math.hypot(dx, dy)
                    if pixel_dist < 5:
                        self.scale_start = None
                        self.status_msg.emit("距离太短，重新点击")
                        self.update()
                        return

                    # 弹出对话框输入实际距离
                    d, ok = QInputDialog.getDouble(self, "设定比例尺",
                        f"画线长度 = {pixel_dist:.0f} 像素\n对应实际多少米？",
                        50, 0.1, 10000, 2)
                    if ok and d > 0:
                        scale = d / pixel_dist
                        self.scale_x = scale
                        self.scale_y = scale
                        self.scale_set = True
                        self.status_msg.emit(f"比例尺设定: 1px = {scale:.4f}m ({d}m / {pixel_dist:.0f}px)")
                    self.scale_start = None
                    self.set_mode(MODE_NONE)
                    self.update()

            else:
                # 拖拽平移
                self.drag_start = (event.pos().x(), event.pos().y())

        elif event.button() == Qt.RightButton:
            if self.mode == MODE_DRAW_AREA and self.area_points:
                # 完成区域绘制
                if len(self.area_points) >= 3:
                    self.status_msg.emit(f"作业区域完成: {len(self.area_points)} 个顶点")
                    self.set_mode(MODE_NONE)
                else:
                    self.area_points.pop()
                    self.status_msg.emit("至少需要3个点")
                self.update()
            elif self.mode == MODE_DRAW_OBSTACLE:
                if len(self.current_drawing) >= 3:
                    self.obstacles.append(list(self.current_drawing))
                    self.status_msg.emit(f"障碍物添加完成: {len(self.current_drawing)} 个顶点")
                elif self.current_drawing:
                    self.status_msg.emit("至少需要3个点，已取消")
                self.current_drawing.clear()
                if self.mode == MODE_DRAW_OBSTACLE:
                    pass  # 继续画下一个障碍物
                self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
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

        self.last_mouse_pos = event.pos()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start = None

    def wheelEvent(self, event: QWheelEvent):
        # 滚轮缩放
        factor = 1.1
        if event.angleDelta().y() < 0:
            factor = 1 / factor
        self.zoom *= factor
        self.zoom = max(0.1, min(self.zoom, 50))
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            if self.current_drawing:
                self.current_drawing.clear()
                self.status_msg.emit("已取消当前绘制")
            elif self.mode == MODE_DRAW_OBSTACLE:
                self.set_mode(MODE_NONE)
            else:
                self.scale_start = None
                self.set_mode(MODE_NONE)
            self.update()
        elif event.key() == Qt.Key_Delete:
            if self.mode == MODE_DRAW_AREA and self.area_points:
                self.area_points.pop()
                self.status_msg.emit(f"删除最后一点, 剩余 {len(self.area_points)}")
                self.update()
            elif self.mode == MODE_DRAW_OBSTACLE and self.current_drawing:
                self.current_drawing.pop()
                self.update()
        elif event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
            if self.mode == MODE_DRAW_OBSTACLE and len(self.current_drawing) >= 3:
                self.obstacles.append(list(self.current_drawing))
                self.status_msg.emit(f"障碍物确认: {len(self.current_drawing)} 点")
                self.current_drawing.clear()
                self.update()

    def _scene_pos(self, event):
        """鼠标事件位置 → 场景坐标（像素）"""
        if not self.map_pixmap:
            return None
        sx = (event.pos().x() - self.offset_x) / self.zoom
        sy = (event.pos().y() - self.offset_y) / self.zoom
        if sx < 0 or sy < 0 or sx > self.map_pixmap.width() or sy > self.map_pixmap.height():
            return None
        return (sx, sy)

    def clear_all(self):
        self.area_points.clear()
        self.obstacles.clear()
        self.current_drawing.clear()
        self.path_segments = []
        self.scale_set = False
        self.scale_start = None
        self.set_mode(MODE_NONE)
        self.update()
        self.status_msg.emit("已清空")

    def generate_path(self):
        """生成覆盖路径"""
        if len(self.area_points) < 3:
            QMessageBox.warning(self, "提示", "请先画出作业区域")
            return
        if not self.scale_set:
            QMessageBox.warning(self, "提示", "请先设定比例尺")
            return

        # 转换到世界坐标（米）
        world_area = [self.pixel_to_world(p[0], p[1]) for p in self.area_points]
        world_obs = []
        for obs in self.obstacles:
            if len(obs) >= 3:
                world_obs.append([self.pixel_to_world(p[0], p[1]) for p in obs])

        # 生成路径
        try:
            if self.closed_loop:
                path = generate_zigzag_closed(
                    world_area, self.sweep_width, world_obs, self.direction
                )
            else:
                path = generate_zigzag(
                    world_area, self.sweep_width, world_obs, self.direction
                )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"路径生成失败:\n{e}")
            return

        self.path_segments = path.waypoints
        self.world_area = world_area
        self.world_obstacles = world_obs

        total_m = path.total_length
        info = f"✅ 路径生成: {len(path.waypoints)} 点, {total_m:.1f}m"
        if self.closed_loop:
            info += " [闭环]"
        self.status_msg.emit(info)
        self.update()

    def export_path(self):
        """导出路径到文件"""
        if not self.path_segments:
            QMessageBox.warning(self, "提示", "请先生成路径")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "导出路径", "coverage_path.txt",
            "文本文件 (*.txt);;所有文件 (*)"
        )
        if not path:
            return

        with open(path, "w") as f:
            f.write("# sweeper-cover 覆盖路径\n")
            f.write(f"# 作业区域顶点: {len(self.world_area)}\n")
            f.write(f"# 障碍物: {len(self.world_obstacles)}\n")
            f.write(f"# 路径点数: {len(self.path_segments)}\n")
            f.write(f"# 路径总长: {sum(math.hypot(self.path_segments[i+1][0]-self.path_segments[i][0], self.path_segments[i+1][1]-self.path_segments[i][1]) for i in range(len(self.path_segments)-1)):.2f}m\n")
            f.write(f"# 作业宽度: {self.sweep_width}m\n")
            f.write(f"# 扫描方向: {self.direction}\n")
            f.write(f"# 闭环: {'是' if self.closed_loop else '否'}\n")
            f.write(f"# 比例尺: 1px = {self.scale_x:.4f}m\n")
            f.write("# x(m) y(m)\n")
            for wx, wy in self.path_segments:
                f.write(f"{wx:.3f} {wy:.3f}\n")

        self.status_msg.emit(f"已导出: {path}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SweeperCover v0.2 — 全覆盖路径规划")
        self.setMinimumSize(1200, 800)

        # 中央部件
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # ─── 左侧控制面板 ───
        left_panel = QWidget()
        left_panel.setFixedWidth(220)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(8)

        # 工具栏
        btn_style = """
            QPushButton {
                padding: 8px; font-size: 13px; text-align: left;
                border: 1px solid #ccc; border-radius: 4px; background: #f8f8f8;
            }
            QPushButton:hover { background: #e8e8e8; }
            QPushButton:checked { background: #d0e8ff; border-color: #4096ff; }
        """

        self.btn_load = QPushButton("📂 加载地图")
        self.btn_load.setStyleSheet(btn_style)
        self.btn_load.clicked.connect(self._load_map)

        self.btn_area = QPushButton("📐 画作业区域")
        self.btn_area.setStyleSheet(btn_style)
        self.btn_area.setCheckable(True)
        self.btn_area.clicked.connect(lambda: self.canvas.set_mode(MODE_DRAW_AREA if self.btn_area.isChecked() else MODE_NONE))

        self.btn_obstacle = QPushButton("🚧 画障碍物")
        self.btn_obstacle.setStyleSheet(btn_style)
        self.btn_obstacle.setCheckable(True)
        self.btn_obstacle.clicked.connect(lambda: self.canvas.set_mode(MODE_DRAW_OBSTACLE if self.btn_obstacle.isChecked() else MODE_NONE))

        self.btn_scale = QPushButton("📏 设定比例尺")
        self.btn_scale.setStyleSheet(btn_style)
        self.btn_scale.clicked.connect(self._set_scale)

        self.btn_clear = QPushButton("🗑️ 清空")
        self.btn_clear.setStyleSheet(btn_style)
        self.btn_clear.clicked.connect(self.canvas.clear_all)

        self.btn_fit = QPushButton("🔍 适应窗口")
        self.btn_fit.setStyleSheet(btn_style)
        self.btn_fit.clicked.connect(self._fit_view)

        # ─── 参数设置 ───
        param_group = QGroupBox("作业参数")
        param_layout = QFormLayout(param_group)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 20.0)
        self.width_spin.setValue(3.0)
        self.width_spin.setSingleStep(0.1)
        self.width_spin.setSuffix(" m")
        self.width_spin.valueChanged.connect(self._update_params)
        param_layout.addRow("作业宽度:", self.width_spin)

        self.dir_combo = QComboBox()
        self.dir_combo.addItems(["horizontal (水平)", "vertical (垂直)"])
        self.dir_combo.currentIndexChanged.connect(self._update_params)
        param_layout.addRow("扫描方向:", self.dir_combo)

        self.closed_check = QCheckBox("生成闭环路径")
        self.closed_check.toggled.connect(self._update_params)
        param_layout.addRow(self.closed_check)

        # ─── 生成/导出按钮 ───
        self.btn_generate = QPushButton("▶ 生成路径")
        self.btn_generate.setStyleSheet("""
            QPushButton { padding: 10px; font-size: 14px; font-weight: bold;
                background: #4096ff; color: white; border: none; border-radius: 4px; }
            QPushButton:hover { background: #1677ff; }
        """)
        self.btn_generate.clicked.connect(self.canvas.generate_path)

        self.btn_export = QPushButton("💾 导出路径")
        self.btn_export.setStyleSheet("""
            QPushButton { padding: 8px; font-size: 13px;
                background: #52c41a; color: white; border: none; border-radius: 4px; }
            QPushButton:hover { background: #389e0d; }
        """)
        self.btn_export.clicked.connect(self.canvas.export_path)

        # 组装左侧面板
        left_layout.addWidget(self.btn_load)
        left_layout.addWidget(self.btn_area)
        left_layout.addWidget(self.btn_obstacle)
        left_layout.addWidget(self.btn_scale)
        left_layout.addSpacing(5)
        left_layout.addWidget(param_group)
        left_layout.addSpacing(5)
        left_layout.addWidget(self.btn_generate)
        left_layout.addWidget(self.btn_export)
        left_layout.addSpacing(5)
        left_layout.addWidget(self.btn_clear)
        left_layout.addWidget(self.btn_fit)
        left_layout.addStretch()

        # ─── 画布 ───
        self.canvas = MapCanvas()
        self.canvas.status_msg.connect(self._update_status)

        # ─── 右侧面板 ───
        right_panel = QWidget()
        right_panel.setFixedWidth(200)
        right_layout = QVBoxLayout(right_panel)

        info_group = QGroupBox("信息")
        info_layout = QVBoxLayout(info_group)
        self.info_label = QLabel("加载地图后开始规划")
        self.info_label.setWordWrap(True)
        info_layout.addWidget(self.info_label)
        right_layout.addWidget(info_group)

        right_layout.addStretch()

        # ─── 组装 ───
        layout.addWidget(left_panel)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(right_panel)

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪 — 加载地图开始")

    def _load_map(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择地图图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.tiff);;所有文件 (*)"
        )
        if path:
            self.canvas.load_map(path)
            self.info_label.setText(f"地图: {os.path.basename(path)}\n{self.canvas.map_image.width()}×{self.canvas.map_image.height()}px\n\n绘制区域 → 画障碍物 → 设比例尺 → 生成路径")

    def _set_scale(self):
        if not self.canvas.map_pixmap:
            QMessageBox.warning(self, "提示", "请先加载地图")
            return
        self.canvas.set_mode(MODE_SET_SCALE)
        for btn in [self.btn_area, self.btn_obstacle]:
            btn.setChecked(False)

    def _fit_view(self):
        if self.canvas.map_pixmap:
            pw = self.canvas.map_pixmap.width()
            ph = self.canvas.map_pixmap.height()
            cw = self.canvas.width()
            ch = self.canvas.height()
            self.canvas.zoom = min((cw - 40) / pw, (ch - 40) / ph)
            self.canvas.offset_x = (cw - pw * self.canvas.zoom) / 2
            self.canvas.offset_y = (ch - ph * self.canvas.zoom) / 2
            self.canvas.update()

    def _update_params(self):
        direction = "horizontal" if self.dir_combo.currentIndex() == 0 else "vertical"
        self.canvas.set_params(
            width=self.width_spin.value(),
            direction=direction,
            closed=self.closed_check.isChecked(),
        )

    def _update_status(self, msg):
        self.status.showMessage(msg, 5000)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
