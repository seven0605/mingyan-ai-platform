# 明琰AI平台

[![跨平台持续集成](https://github.com/seven0605/mingyan-ai-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/seven0605/mingyan-ai-platform/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-7c6bf6.svg)](LICENSE)

一个开源优先、本地运行的电脑端 AI 视频创作平台。界面运行在 macOS 或 Windows 的桌面浏览器中，本地服务负责保存项目数据；不需要安装独立桌面 App，也不以手机端为目标。

跨窗口继续开发时，先阅读 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)，再按其中的接续清单检查当前代码、数据与测试状态。

## 当前版本

- React + Vite 浏览器界面
- FastAPI 本地服务
- SQLite 项目持久化
- 新建项目、项目切换、创作阶段切换
- TXT 小说导入、原文编辑、章节统计与本地保存
- 本地结构初筛：人物候选、场景候选、章节剧情锚点
- AI 剧本策划：故事定位、人物关系、场次拆解和改编建议；结果保存到本地项目
- 逐场剧本生成：选择忠实/商业改编、单集时长和集数，按章节分批生成动作、对白、旁白与原文依据
- 剧本质量校验：校正对白朗读时长，标记目标时长偏差，并在失败时保留上一版结果
- 剧本定稿流程：逐条编辑内容与秒数、保存后重算时长；只有原文版本一致且每集进入 ±10 秒容差，才可人工确认并进入分镜
- 单集 AI 定稿：按集压缩时长并对照对应原文章节复核事实、道具、人物信息和来源标记；不合格时保留旧稿
- 工业级分镜：只读取已人工确认剧本，按场次自动拆成不超过 15 秒的连续镜头组，生成七维分镜、首帧顺接、空间锁定、声音与可复制视频提示词
- 分镜可靠性：按两组一批调用模型，整集时间码和必填结构全部通过后才写入 SQLite；失败不覆盖已保存分镜
- 分镜局部编辑：逐组修改叙事目的、连续性、表演、运镜、声音与提示词；权威时间码保持锁定，保存前由后端校验整集结构
- 一致性资产库：从已确认剧本和当前分镜整理角色、场景、物品，去重汇总出现场次与原文依据，并支持编辑、确认和本地持久化
- 资产标准：真人写实、国风 3D、手绘 3 渲 2、西方暗黑中世纪真人和维多利亚真人五种项目级视觉标准
- 中国古代服饰知识层：汉、唐、宋、明提供精细规则，其余朝代明确标记为资料待补，不伪造完整考据
- 确定性资产提示词编译：按角色、场景、物品生成结构化提示词，支持新旧对照、资料覆盖警告和明确应用
- 单人人物身份硬控：V2 起始终把该人物 V1 作为图像参考随请求提交，锁定同一张脸、骨相、年龄和身体比例；服装、配饰、发型与状态仍可变化
- 群演独立模板：按群体身份生成单张 16:9 全身群像，约束人数、性别分配、不同脸与不同服装，不套用单人物资产卡，也不继承某个角色的人脸参考
- OpenAI 兼容文本模型配置与连接测试；密钥保存在 macOS 钥匙串或 Windows 凭据管理器
- 不鸣AI TT Image 2.5 图像模型配置与免生图连接测试；接口地址和模型 ID 预填，图像密钥同样只进入系统凭据库
- 单资产参考图生成与版本管理：真人写实角色/物品使用 9:16、场景与群演使用 16:9 调用异步生图任务，成功结果下载到本机；支持历史缩略图、全屏大图预览、身份参考标记和主参考图选择，失败不覆盖旧图
- 批量资产生产预检：只允许选择已确认资产，逐项审查提示词，按本机历史费用估算消耗；明确确认后把提示词快照和生产清单保存到 SQLite，本步骤不调用生图接口
- 可恢复的资产生成队列：用户再次点击带“消耗额度”字样的按钮后顺序执行已确认清单；队列、服务商任务号、失败原因和执行次数保存到 SQLite，失败可重试，应用中断后可复用原任务号恢复
- 任务中心：按当前项目汇总真实资产生图历史与队列状态，显示排队、生成、完成、失败和可恢复状态；支持失败重试、队列恢复、筛选、刷新与结果大图预览
- macOS 与 Windows 启动脚本
- Docker Compose 运行方式
- GitHub Actions 的 macOS / Windows 构建与测试配置

项目数据默认保存在用户目录的 `.mingyan-ai/mingyan.sqlite3`，更新或替换源码不会覆盖这个数据库。API 密钥不会写入该数据库，也不会由设置接口回传给浏览器。生成 AI 剧本策划或逐场剧本时，已保存的小说正文会发送给用户在“API 设置”中配置的模型服务商。逐场剧本按集调用模型；分镜按小批次调用模型，以降低长篇输出中断概率。

## 系统要求

- Node.js 22 或更高版本
- Python 3.11 或更高版本
- Google Chrome、Microsoft Edge 或其他现代浏览器

脚本会优先使用 `pnpm`；未单独安装时会尝试通过 Node 自带的 Corepack 调用。

## macOS

首次使用：双击 `安装依赖-macOS.command`。

以后启动：双击 `启动明琰AI平台.command`。

## Windows

首次使用：双击 `安装依赖-Windows.cmd`。

以后启动：双击 `启动明琰AI平台-Windows.cmd`。

脚本只在当前用户目录和项目目录中创建环境与数据，通常不需要管理员权限。

## Docker（可选）

已安装 Docker Desktop 的用户可以运行：

```bash
docker compose up --build
```

然后打开 <http://127.0.0.1:4173/>。数据保存在名为 `mingyan-data` 的 Docker volume 中。

## 开发与测试

前端开发服务器：

```bash
pnpm install
pnpm dev:web
```

本地 API：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements-dev.txt
.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

macOS / Linux 运行测试：

```bash
pnpm typecheck
pnpm build
.venv/bin/python -m pytest server/tests
```

Windows 对应的虚拟环境 Python 路径是 `.venv\Scripts\python.exe`。

## 目录说明

- `src/`：浏览器前端
- `server/`：本地 API 与 SQLite 数据层
- `scripts/`：macOS / Windows 安装与启动脚本
- `.github/workflows/ci.yml`：跨平台持续集成
- `design/`：品牌与界面设计稿

## 下一阶段

接下来按功能闭环推进：原文输入 → AI 剧本 → 分镜 → 角色/场景资产 → 视频生成任务 → 成片导出。资产批量预检和可恢复生图队列已经打通，下一步接入视频生成任务与预览。

## 开源许可

源代码采用 [MIT License](LICENSE)。贡献方式参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

“明琰AI平台”“明琰科技”名称与 Logo 不包含在 MIT 授权中，具体见 [TRADEMARKS.md](TRADEMARKS.md)。
