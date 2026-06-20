"""
可视化模块 — 用 matplotlib 显示区域多边形和生成的覆盖路径。
"""

import matplotlib.pyplot as plt
from typing import List, Tuple, Optional
from .coverage import CoveragePath, Polygon


def plot_coverage(
    polygon: Polygon,
    path: CoveragePath,
    title: str = "Coverage Path Planning",
    show_swath: bool = True,
    save_path: Optional[str] = None,
    lang: str = "en",
) -> None:
    """
    Draw the area polygon + coverage path.

    Args:
        polygon: List of polygon vertices
        path: Generated coverage path
        title: Chart title
        show_swath: Whether to show individual sweep swaths
        save_path: If provided, save image to this path
        lang: "en" for English, "zh" for Chinese (requires CJK fonts)
    """
    fig, ax = plt.subplots(1, 1, figsize=(10, 8))

    # Close polygon for drawing
    if polygon[0] != polygon[-1]:
        poly_draw = polygon + [polygon[0]]
    else:
        poly_draw = polygon

    poly_x = [p[0] for p in poly_draw]
    poly_y = [p[1] for p in poly_draw]

    # Labels
    L = dict(
        en=dict(
            area="Work Area", boundary="Boundary", path="Coverage Path",
            start="Start", end="End",
            pts="Points", length="Length", width="Swath Width",
            closed="Closed", yes="Yes", no="No",
        ),
        zh=dict(
            area="作业区域", boundary="区域边界", path="覆盖路径",
            start="起点", end="终点",
            pts="路径点数", length="路径总长", width="作业宽度",
            closed="是否闭环", yes="是", no="否",
        ),
    )
    l = L.get(lang, L["en"])

    # Draw area
    ax.fill(poly_x, poly_y, alpha=0.08, color="blue", label=l["area"])
    ax.plot(poly_x, poly_y, "b-", linewidth=1.5, label=l["boundary"])

    # Draw coverage path
    if path.waypoints:
        wx = [p[0] for p in path.waypoints]
        wy = [p[1] for p in path.waypoints]

        line_style = "g-" if not path.is_closed else "g--"
        ax.plot(wx, wy, line_style, linewidth=1.2, label=l["path"])

        ax.scatter([wx[0]], [wy[0]], color="green", s=80, marker="o", zorder=5, label=l["start"])
        ax.scatter([wx[-1]], [wy[-1]], color="red", s=80, marker="x", zorder=5, label=l["end"])

        # Direction arrows
        arrow_interval = max(1, len(path.waypoints) // 20)
        for i in range(0, len(path.waypoints) - 1, arrow_interval):
            dx = path.waypoints[i + 1][0] - path.waypoints[i][0]
            dy = path.waypoints[i + 1][1] - path.waypoints[i][1]
            length = (dx**2 + dy**2) ** 0.5
            if length > 0.01:
                ax.annotate(
                    "",
                    xy=path.waypoints[i + 1],
                    xytext=path.waypoints[i],
                    arrowprops=dict(
                        arrowstyle="->",
                        color="green",
                        lw=0.8,
                        alpha=0.5,
                    ),
                )

    # Info box
    info_text = (
        f"{l['pts']}: {len(path.waypoints)}\n"
        f"{l['length']}: {path.total_length:.1f} m\n"
        f"{l['width']}: {path.sweep_width:.1f} m\n"
        f"{l['closed']}: {l['yes'] if path.is_closed else l['no']}"
    )
    ax.text(
        0.02, 0.98, info_text,
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
    )

    ax.set_title(title, fontsize=14)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150)
        print(f"Image saved: {save_path}")

    plt.show()
