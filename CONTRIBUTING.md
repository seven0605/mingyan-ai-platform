# 参与贡献

感谢参与明琰AI平台。当前项目面向 macOS 与 Windows 电脑浏览器，不以手机端为开发目标。

## 开发流程

1. 从最新 `main` 分支开始，并保持改动范围单一。
2. 不提交 API 密钥、小说原文、SQLite 数据库、生成图片或其他用户私有数据。
3. 完成改动后运行：

   ```bash
   pnpm typecheck
   pnpm build
   python -m pytest server/tests
   ```

4. 界面改动还需要在桌面 Chrome 或 Edge 中验证核心路径和控制台日志。
5. 同步更新 `PROJECT_STATUS.md`、`ROADMAP.md` 或 `design/qa-ledger.md` 中受影响的状态。

## 提交与合并请求

- 提交信息应说明用户可见的结果，例如 `feat: add deterministic asset prompt preview`。
- 一个合并请求只处理一个明确目标，不顺带重构无关代码。
- 请在说明中列出验证命令、人工验证路径和已知限制。

## 品牌资产

源代码采用 MIT 许可证，项目名称与 Logo 适用 [`TRADEMARKS.md`](TRADEMARKS.md) 中的单独说明。
