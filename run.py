#!/usr/bin/env python3
"""
SweeperCover — 道路作业路线规划 & 全覆盖路径规划

运行方式：
    python3 run.py                       # 启动道路规划器（推荐，全新简洁版）
    python3 run.py --area                # 启动区域规划器（旧版）
    python3 run.py --demo                # 运行示例
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))


def main():
    if "--area" in sys.argv:
        # 旧版区域规划
        from PyQt5.QtWidgets import QApplication
        from sweeper_cover.gui import MainWindow
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        win = MainWindow()
        win.show()
        sys.exit(app.exec_())
    elif "--demo" in sys.argv:
        import matplotlib
        matplotlib.use("Agg")
        from examples.demo import main as demo_main
        demo_main()
    else:
        # 默认：道路规划器（简洁版）
        from PyQt5.QtWidgets import QApplication
        from sweeper_cover.road_planner import main as planner_main
        planner_main()


if __name__ == "__main__":
    main()
