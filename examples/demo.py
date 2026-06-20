"""
示例：在几个典型多边形区域中生成全覆盖路径。
运行方式：python examples/demo.py
"""

import sys
import os

# 把项目根目录加入 sys.path（方便直接运行）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sweeper_cover import generate_zigzag, generate_zigzag_closed, plot_coverage


def main():
    print("=" * 50)
    print("SweeperCover 演示 - 全覆盖路径规划")
    print("=" * 50)

    # ─── 示例1：矩形区域 ───
    print("\n[示例1] 矩形区域 30×20m，作业宽度 3m")
    rect = [(0, 0), (30, 0), (30, 20), (0, 20)]
    path = generate_zigzag(rect, sweep_width=3.0, direction="horizontal")
    print(f"  路径长度: {path.total_length:.1f}m, 点数: {len(path.waypoints)}")
    plot_coverage(rect, path, title="矩形区域 - 水平弓字形", save_path="demo_rect.png")

    # ─── 示例2：L形区域 ───
    print("\n[示例2] L形区域，作业宽度 2.5m")
    l_shape = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]
    path2 = generate_zigzag(l_shape, sweep_width=2.5, direction="horizontal")
    print(f"  路径长度: {path2.total_length:.1f}m, 点数: {len(path2.waypoints)}")
    plot_coverage(l_shape, path2, title="L形区域 - 水平弓字形", save_path="demo_lshape.png")

    # ─── 示例3：闭环路径 ───
    print("\n[示例3] 矩形区域 25×15m，闭环（可循环作业），作业宽度 2m")
    rect2 = [(5, 5), (30, 5), (30, 20), (5, 20)]
    path3 = generate_zigzag_closed(rect2, sweep_width=2.0, direction="vertical")
    print(f"  路径长度: {path3.total_length:.1f}m, 点数: {len(path3.waypoints)}")
    plot_coverage(rect2, path3, title="矩形区域 - 闭环循环作业", save_path="demo_closed.png")

    print("\n✅ 演示完成！图片已保存到当前目录。")


if __name__ == "__main__":
    main()
