# Captain {{VERSION}}

## 下载

- Apple Silicon: `Captain_{{VERSION}}_arm64.dmg`
- Intel Mac: `Captain_{{VERSION}}_x86_64.dmg`
- 校验文件: `SHA256SUMS.txt`

## 本版重点

- macOS 桌面版: 内置后端与 Python runtime,首次启动自动初始化本机数据目录。
- 模型接入: 支持 OpenRouter、DeepSeek、OpenAI、Claude、Gemini、xAI、Groq、Qwen、Kimi、智谱、Perplexity。
- 本地安全: macOS App 优先把模型 Key、授权码、访问 token 存入 Keychain。
- 诊断能力: 设置页可打开日志、导出诊断包。

## 安装方式

1. 下载与你电脑匹配的 DMG。
2. 打开 DMG,将 `Captain.app` 拖入 Applications。
3. 首次启动后按引导配置授权码和模型 Key。

如果 macOS 提示无法检查开发者,请在系统设置的隐私与安全中允许打开。正式签名公证版发布后将减少该提示。

## 更新方式

- App 内进入 `设置 -> 关于 -> 检查并更新`。
- 如果 App 内更新不可用,可重新下载 DMG 覆盖安装。
- 用户数据保存在 `~/Library/Application Support/Captain`,覆盖安装不会删除数据。

## 已知限制

- 当前版本采用打开 GitHub Release 下载页的方式更新,不是静默自动更新。
- Windows 客户版适配暂缓,本次优先 macOS。

## 校验

下载后可在终端运行:

```bash
shasum -a 256 Captain_{{VERSION}}_arm64.dmg Captain_{{VERSION}}_x86_64.dmg
cat SHA256SUMS.txt
```
