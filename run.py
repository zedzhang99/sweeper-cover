#!/usr/bin/env python3
"""
SweeperCover — 自动全覆盖路径规划工具

运行方式：
    python3 run.py              # 启动 GUI（可视化编辑器）
    python3 run.py --cli        # 启动 CLI（交互式命令行）
    python3 run.py --demo       # 运行示例
"""

import sys
import os

# 确保能找到 sweeper_cover 包
sys.path.insert(0, os.path.dirname(__file__))


def main():
    if "--demo" in sys.argv:
        # 运行演示
        import matplotlib
        matplotlib.use("Agg")
        from examples.demo import main as demo_main
        demo_main()
    elif "--cli" in sys.argv:
        # CLI 交互模式
        from run_cli import interactive_mode
        interactive_mode()
    else:
        # 默认启动 GUI
        from PyQt5.QtWidgets import QApplication
        from sweeper_cover.gui import MainWindow
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        win = MainWindow()
        win.show()
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()
