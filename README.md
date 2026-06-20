# SweeperCover 🧹

> 自动全覆盖路径规划工具 — 专为无人驾驶环卫车、扫地车等场景设计

给定一个作业区域（多边形），自动生成弓字形（zigzag）全覆盖路径，
支持水平/垂直扫描、闭环循环作业、路径可视化。

## 解决的问题

到现场部署无人驾驶环卫车时，做路线规划总是很头疼：

- **录图路线**：怎么跑最短的路线，把整个区域环境录全
- **作业路线**：已知作业区域后，怎么让车不漏扫、不重复、还能闭环循环

这个工具用数学方法帮你自动算出来。

## 快速上手

```bash
# 1. 安装依赖
pip install matplotlib

# 2. 运行示例
python examples/demo.py

# 3. 交互模式 —— 输入你的区域，生成路径
python run.py
```

### 从文件加载多边形

创建一个 `area.txt`：

```
# 区域顶点坐标 (x y)
0 0
30 0
30 20
0 20
```

然后运行：

```bash
python run.py --polygon-file area.txt --width 3.0 --closed
```

## 示例效果

| 矩形区域 | L形区域 | 闭环路径 |
|---------|---------|---------|
| 水平弓字形全覆盖 | 不规则区域同样适用 | 终点回起点，可循环 |
| ![矩形](docs/images/demo_rect.png) | ![L形](docs/images/demo_lshape.png) | ![闭环](docs/images/demo_closed.png) |

## 功能

- [x] 多边形区域内 zigzag 全覆盖路径生成
- [x] 水平 / 垂直扫描方向
- [x] 闭环路径（循环作业）
- [x] 路径可视化（matplotlib）
- [x] 交互式 CLI
- [x] 路径导出为坐标文件
- [ ] 转弯半径约束（平滑路径）
- [ ] 障碍物自动避让
- [ ] 录图路线优化（最短路径覆盖）
- [ ] 支持导入实际地图数据
- [ ] Web 图形界面

## 项目结构

```
sweeper-cover/
├── sweeper_cover/          ← 核心算法库
│   ├── __init__.py
│   ├── coverage.py         ← 全覆盖路径生成算法
│   └── visualize.py        ← 可视化模块
├── examples/               ← 示例脚本
│   └── demo.py
├── run.py                  ← 交互式 CLI 工具
├── requirements.txt        ← 依赖
├── README.md               ← 项目说明（就是本文件）
├── LICENSE                 ← 开源许可证
└── .gitignore              ← Git 忽略规则
```

## 依赖

- Python 3.8+
- matplotlib（可视化）

## 许可证

MIT License — 你可以随意使用、修改、分发。
