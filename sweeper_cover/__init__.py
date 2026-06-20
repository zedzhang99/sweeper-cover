"""
sweeper-cover — 自动全覆盖路径规划工具

用于环卫车、扫地车等场景：给定一个作业区域（多边形），
自动生成 zigzag（弓字形）全覆盖路径，支持障碍物避让和闭环循环作业。
"""

__version__ = "0.2.0"

from .coverage import (
    generate_zigzag,
    generate_zigzag_closed,
    CoveragePath,
)
from .visualize import plot_coverage

__all__ = [
    "generate_zigzag",
    "generate_zigzag_closed",
    "CoveragePath",
    "plot_coverage",
]
