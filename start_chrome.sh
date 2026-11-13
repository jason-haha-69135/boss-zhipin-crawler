#!/usr/bin/env bash
set -euo pipefail

PORT=9222
PROFILE_DIR="$HOME/.chrome-boss-poc-profile"

echo "正在以远程调试模式 (端口: ${PORT}) 启动 Chrome..."
echo "个人配置目录: ${PROFILE_DIR}"
echo "请在打开的浏览器中访问 https://www.zhipin.com 并完成扫码/短信登录。"

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port="${PORT}" \
  --user-data-dir="${PROFILE_DIR}" \
  "https://www.zhipin.com/shenzhen/"
