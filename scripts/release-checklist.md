# Captain macOS 发版清单

## 发版前

1. 确认 `main` 已合并待发版改动。
2. 运行 `bash scripts/release-preflight.sh`，全部通过后再继续。
3. 在 6 处同步版本号：`VERSION`、`pyproject.toml`、`desktop/package.json`、`desktop/src-tauri/tauri.conf.json`、`desktop/src-tauri/Cargo.toml`、内嵌 bundle（由 `macos:prepare-bundle` 复制）。

## 打包

```bash
cd desktop
CAPTAIN_MACOS_TARGETS="arm64 x86_64" npm run macos:package
npm run macos:release-assets
```

若已配置 Apple 证书，导出：

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: ..."
export NOTARY_APPLE_ID=...
export NOTARY_TEAM_ID=...
export NOTARY_PASSWORD=...   # 或 NOTARY_KEYCHAIN_PROFILE
```

## 发布

```bash
gh release create vX.Y.Z \
  release-assets/vX.Y.Z/Captain_X.Y.Z_arm64.dmg \
  release-assets/vX.Y.Z/Captain_X.Y.Z_x86_64.dmg \
  release-assets/vX.Y.Z/Captain_X.Y.Z_arm64.app.tar.gz \
  release-assets/vX.Y.Z/Captain_X.Y.Z_x86_64.app.tar.gz \
  release-assets/vX.Y.Z/SHA256SUMS.txt \
  release-assets/vX.Y.Z/latest.json \
  --title "Captain X.Y.Z" \
  --notes-file release-assets/vX.Y.Z/RELEASE_NOTES.md
```

## 发布后

1. 更新 [`landing/index.html`](../landing/index.html) 下载链接版本号。
2. 在干净 Mac 上验证：安装、首启引导、聊天、邮件连接器、关窗驻留、诊断页更新检查。
3. 如有下一版，验证 App 内自动更新与 `~/Library/Application Support/Captain` 数据保留。
