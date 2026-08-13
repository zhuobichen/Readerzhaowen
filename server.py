# -*- coding: utf-8 -*-
"""
书架 + 阅读器 本地服务 (零第三方依赖, 仅使用 Python 标准库)

路由: 见 server/routes.py 顶部文档。

启动:  python server.py
默认端口 8769, 也可: python server.py 9000
"""
from server.app import main


if __name__ == "__main__":
    main()
