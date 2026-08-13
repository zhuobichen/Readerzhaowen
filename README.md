<p align="center">
  <img src="static/img/lingtai.png" width="120" height="120" alt="灵台" style="border-radius: 24px;">
</p>

<h1 align="center">灵台</h1>

<p align="center">
  <em>灵台，心之舍也。一隅静地，安放书卷与思绪。</em>
</p>

<p align="center">
  <a href="#功能"><img alt="功能" src="https://img.shields.io/badge/功能-书架·阅读·笔记·AI-blue?style=flat-square&color=8B7355"></a>
  <img alt="后端" src="https://img.shields.io/badge/后端-Python_标准库-green?style=flat-square&color=6B8E5A">
  <img alt="前端" src="https://img.shields.io/badge/前端-原生_JS_ESM-orange?style=flat-square&color=B5651D">
  <img alt="依赖" src="https://img.shields.io/badge/第三方依赖-零-brightgreen?style=flat-square&color=5B7C5A">
  <img alt="数据" src="https://img.shields.io/badge/数据-纯本地_不出站-success?style=flat-square&color=4A6B4A">
</p>

---

一个纯本地运行的电子书阅读器。书架、阅读、笔记与 AI 助手融为一体，所有数据留在你的电脑上，不依赖任何云服务。

## 功能

### 书架
- 支持 **PDF / EPUB / TXT / CBZ** 等格式，拖拽即可导入
- 分类管理：侧栏分类、拖拽归类、自定义排序
- 回收站：移出书架后 30 天内可恢复
- 笔记中心：跨书聚合所有笔记，点击跳转回原文

### 阅读器
- 三种模式：**左右翻页 · 上下分页 · 卷轴滚动**
- 章节目录导航（自动解析 PDF 大纲 / EPUB 目录）
- 进度记忆 · 缩放控制 · 主题切换（暗色 / 亮色护眼）
- 底部工具栏点击展开收起，图标附文字标签

### 笔记
- 每本书独立笔记，进入阅读时自动展开常驻侧栏
- 位置锚定：记录阅读进度与页码，点击跳回原文
- 快捷键 `Ctrl+Enter` 保存 · `Esc` 关闭

### AI 助手
- 接入 OpenAI 兼容接口（本地或远程均可）
- 上下文感知：AI 了解当前阅读的书籍与进度
- Agent 模式：多步任务自主执行（搜索资料、创建笔记、管理分类）
- 联网搜索下载书籍 · 沙箱代码执行
- 悬浮可拖拽面板，位置持久化

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | Python 标准库 `http.server` | 零第三方依赖 |
| 前端 | 原生 JS（ES Modules） | 无构建工具 |
| PDF | pdf.js | 本地化引入 |
| EPUB | epub.js | 本地化引入 |
| 压缩包 | JSZip | 本地化引入 |
| 存储 | 文件系统 + JSON | `data/library.json` |

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/zhuobichen/lingtai-reader.git
cd lingtai-reader

# 启动服务（无需安装任何依赖）
python server.py

# 打开浏览器访问
# http://localhost:8769
```

将书籍文件放入 `books/` 目录，或直接在网页中拖拽导入。

AI 助手需在设置中填入 API Key 后启用。

## 目录结构

```
lingtai-reader/
├── server.py              # 后端服务（单文件）
├── static/
│   ├── index.html         # 单页应用入口
│   ├── css/app.css        # 全局样式
│   ├── img/lingtai.png    # 应用图标
│   ├── js/
│   │   ├── app.js         # 路由与初始化
│   │   ├── bookshelf.js   # 书架渲染与交互
│   │   ├── reader.js      # 阅读器（PDF/EPUB/TXT/CBZ）
│   │   ├── notes.js       # 笔记面板
│   │   ├── ai.js          # AI 助手面板
│   │   ├── api.js         # 前端 API 封装
│   │   └── store.js       # 状态管理
│   └── vendor/            # 第三方库（本地化）
├── books/                 # 书籍文件目录
└── data/                  # 运行时数据
    ├── library.json       # 书籍元数据、笔记、进度、分类
    ├── ai_config.json     # AI 配置
    └── agent_memory.json  # Agent 记忆
```

## 贡献

代码贡献记录可通过 Git 历史查看：

```bash
git log --oneline
git shortlog -sne
```

## 许可

本项目仅供个人学习使用。
