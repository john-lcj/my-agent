# my-agent —— 常用命令快捷方式。运行 `make` 或 `make help` 查看全部。
.DEFAULT_GOAL := help
PY := .venv/bin/python

.PHONY: help setup web cli test eval docker-build docker-up docker-down docker-logs clean

help:  ## 显示本帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## 创建 .venv 并安装全部依赖(首次使用)
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -e ".[all]"
	@echo "✓ 安装完成。`make web` 启动网页,`make cli` 进终端对话。"

web:  ## 启动 Web 聊天界面 → http://127.0.0.1:8000
	$(PY) -m uvicorn server.app:app --host 127.0.0.1 --port 8000

cli:  ## 终端对话(MockLLM 零配置可跑)
	$(PY) main.py

test:  ## 跑回归测试
	$(PY) -m pytest -q tests/test_regression.py

eval:  ## 真实模型质量评测(需 DEEPSEEK_API_KEY,见 README)
	$(PY) -m eval.run_real --model deepseek-v4-flash

docker-build:  ## 构建 Docker 镜像
	docker build -t my-agent .

docker-up:  ## docker compose 后台启动(需 .env 里有 AGENT_API_TOKEN)
	docker compose up -d --build

docker-down:  ## 停止并移除容器
	docker compose down

docker-logs:  ## 查看容器日志
	docker compose logs -f

clean:  ## 清理缓存与构建产物
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	rm -rf build dist *.egg-info .pytest_cache
