"""
SweeperCover CLI — 交互式全覆盖路径规划工具

用法：
    python run.py                       # 交互模式
    python run.py --polygon-file area.txt --width 3.0    # 从文件读取多边形

多边形文件格式（area.txt）：
    x1 y1
    x2 y2
    x3 y3
    ...
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sweeper_cover import generate_zigzag, generate_zigzag_closed, plot_coverage


def read_polygon_file(path: str):
    """从文件读取多边形顶点"""
    points = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                x, y = float(parts[0]), float(parts[1])
                points.append((x, y))
    return points


def interactive_mode():
    print("\n🔄 SweeperCover — 全覆盖路径规划工具")
    print("-" * 40)

    # 输入多边形
    print("\n📐 请输入作业区域顶点坐标（每行 x y，空行结束）：")
    polygon = []
    while True:
        line = input("  > ").strip()
        if not line:
            if len(polygon) < 3:
                print("  ⚠ 至少需要 3 个顶点！继续输入：")
                continue
            break
        try:
            x, y = map(float, line.split())
            polygon.append((x, y))
        except ValueError:
            print("  ⚠ 格式错误，输入 x y 两个数字，用空格分隔")

    print(f"\n  ✅ 已录入 {len(polygon)} 个顶点")

    # 作业宽度
    while True:
        try:
            width = float(input("\n📏 车辆作业宽度（米）: "))
            if width <= 0:
                print("  ⚠ 宽度必须大于 0")
                continue
            break
        except ValueError:
            print("  ⚠ 请输入数字")

    # 扫描方向
    dir_input = input("\n🧭 扫描方向（horizontal=水平 / vertical=垂直，默认 horizontal）: ").strip()
    direction = dir_input if dir_input in ("horizontal", "vertical") else "horizontal"

    # 是否闭环
    closed_input = input("\n🔁 是否生成闭环路径（y/n，默认 n）: ").strip().lower()
    closed = closed_input in ("y", "yes")

    # 生成路径
    print("\n⏳ 正在生成路径...")
    if closed:
        path = generate_zigzag_closed(polygon, sweep_width=width, direction=direction)
    else:
        path = generate_zigzag(polygon, sweep_width=width, direction=direction)

    print(f"\n✅ 路径生成完成！")
    print(f"   路径点数: {len(path.waypoints)}")
    print(f"   路径总长: {path.total_length:.1f} 米")

    # 导出
    export = input("\n💾 导出路径到文件？(y/n, 默认 n): ").strip().lower()
    if export in ("y", "yes"):
        filename = input("   文件名（默认 coverage_path.txt）: ").strip()
        if not filename:
            filename = "coverage_path.txt"
        with open(filename, "w") as f:
            f.write("# sweeper-cover 生成的覆盖路径\n")
            f.write(f"# 总点数: {len(path.waypoints)}  总长度: {path.total_length:.1f}m\n")
            f.write(f"# 作业宽度: {width}m  方向: {direction}\n")
            f.write("# x y\n")
            for pt in path.waypoints:
                f.write(f"{pt[0]:.3f} {pt[1]:.3f}\n")
        print(f"   ✅ 已保存到 {os.path.abspath(filename)}")

    # 可视化
    show = input("\n📊 显示路径可视化？(y/n, 默认 y): ").strip().lower()
    if show != "n":
        save = input("   保存截图？输入文件名或回车跳过: ").strip()
        save_path = save if save else None
        plot_coverage(polygon, path, title="覆盖路径规划结果", save_path=save_path)


def main():
    parser = argparse.ArgumentParser(
        description="SweeperCover — 自动全覆盖路径规划工具"
    )
    parser.add_argument("--polygon-file", "-f", help="从文件读取多边形顶点")
    parser.add_argument("--width", "-w", type=float, help="作业宽度（米）")
    parser.add_argument("--direction", "-d", default="horizontal",
                        choices=["horizontal", "vertical"], help="扫描方向")
    parser.add_argument("--closed", "-c", action="store_true", help="生成闭环路径")
    parser.add_argument("--output", "-o", help="导出路径到文件")
    parser.add_argument("--no-plot", action="store_true", help="不显示图像")

    args = parser.parse_args()

    if args.polygon_file:
        polygon = read_polygon_file(args.polygon_file)
        if len(polygon) < 3:
            print("❌ 多边形至少需要 3 个顶点")
            sys.exit(1)

        width = args.width or 3.0

        if args.closed:
            path = generate_zigzag_closed(polygon, width, args.direction)
        else:
            path = generate_zigzag(polygon, width, args.direction)

        print(f"✅ 路径生成完成！")
        print(f"   点数: {len(path.waypoints)}")
        print(f"   总长: {path.total_length:.1f}m")

        if args.output:
            with open(args.output, "w") as f:
                f.write(f"# 总点数: {len(path.waypoints)}  总长度: {path.total_length:.1f}m\n")
                for pt in path.waypoints:
                    f.write(f"{pt[0]:.3f} {pt[1]:.3f}\n")
            print(f"   已保存到 {os.path.abspath(args.output)}")

        if not args.no_plot:
            plot_coverage(polygon, path, save_path=args.output.replace(".txt", ".png") if args.output else None)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
