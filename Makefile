# my-agent —— 常用命令快捷方式。运行 `make` 或 `make help` 查看全部。
.DEFAULT_GOAL := help
PY := .venv/bin/python

.PHONY: help setup config update web cli test cov eval compare browser docker-build docker-up docker-down docker-logs clean

help:  ## 显示本帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## 创建 .venv 并安装全部依赖(首次使用)
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -e ".[all]"
	@echo "✓ 依赖装好了。下一步跑 `make config` 配置 key,再 `make web` 启动。"

config:  ## 配置向导(交互式填 .env:模型/文生图/搜索/令牌)
	$(PY) scripts/setup_wizard.py

update:  ## 同步更新:拉最新代码 + 更新依赖 + 重启(其它电脑用)
	bash scripts/update.sh

web:  ## 启动 Web 聊天界面 → http://127.0.0.1:8000
	$(PY) -m uvicorn server.app:app --host 127.0.0.1 --port 8000

cli:  ## 终端对话(MockLLM 零配置可跑)
	$(PY) main.py

test:  ## 跑回归测试
	$(PY) -m pytest -q tests/test_regression.py

cov:  ## 跑全套测试 + 覆盖率报告(需 pip install -e ".[dev]")
	$(PY) -m pytest tests/ -q \
		--cov=core --cov=capabilities --cov=memory --cov=governance --cov=llm --cov=server --cov=skills \
		--cov-report=term-missing:skip-covered

eval:  ## 真实模型质量评测(40 用例,需 DEEPSEEK_API_KEY)
	$(PY) scripts/run_evals.py

compare:  ## 多模型对照评测(flash vs pro,出质量×延迟表)
	$(PY) scripts/compare_models.py

browser:  ## 安装浏览器自动化能力(Playwright 包 + Chromium 内核,装进 .venv)
	$(PY) -m pip install playwright
	$(PY) -m playwright install chromium
	@echo "✓ 浏览器能力就绪。重启服务后 browser.* 可用:"
	@echo "  lsof -ti:8000 | xargs kill -9 2>/dev/null; make web"

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
