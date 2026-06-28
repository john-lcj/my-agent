"""测试能力路由：specs_for() 按任务文本返回正确子集。"""
import pytest
from capabilities.routing import route, ALWAYS_INCLUDE


def _make_specs(names: list[str]) -> list[dict]:
    return [{"name": n, "description": n, "schema": {}, "risk": 0} for n in names]


ALL_CAPS = [
    "plan.update", "memory.remember", "memory.recall",
    "fs.read", "fs.list", "fs.write", "fs.search",
    "web.search", "web.fetch", "http.request", "exa.search",
    "shell.run", "skill.scaffold",
    "browser.open", "browser.click", "browser.fill",
    "image.generate", "image.ocr", "vision.see",
    "calendar.add", "calendar.list",
    "schedule.create", "schedule.list", "schedule.delete",
    "git.read", "git.commit",
    "monitor.create", "monitor.list",
    "goal.set", "goal.list",
    "notify.email",
    "wechat.format",
    "secret.save", "secret.list",
    "program.remember", "program.list",
    "gui.control",
    "suggest.add", "suggest.list",
    "skill.外贸助手", "skill.写报告",
]
ALL_SPECS = _make_specs(ALL_CAPS)


def names(specs):
    return {s["name"] for s in specs}


class TestAlwaysInclude:
    def test_core_caps_always_present(self):
        result = names(route("你好", ALL_SPECS))
        for cap in ALWAYS_INCLUDE:
            assert cap in result, f"{cap} 应始终包含"

    def test_skills_always_present(self):
        result = names(route("你好", ALL_SPECS))
        assert "skill.外贸助手" in result
        assert "skill.写报告" in result

    def test_specialized_caps_excluded_without_keywords(self):
        result = names(route("你好，帮我想个主意", ALL_SPECS))
        # 无关键词时，这些专用能力不应出现
        assert "browser.open" not in result
        assert "image.generate" not in result
        assert "calendar.add" not in result
        assert "git.read" not in result
        assert "wechat.format" not in result


class TestKeywordRouting:
    def test_browser_keyword(self):
        result = names(route("帮我登录网站", ALL_SPECS))
        assert "browser.open" in result
        assert "browser.click" in result
        assert "browser.fill" in result

    def test_image_keyword_chinese(self):
        result = names(route("帮我生成一张图片", ALL_SPECS))
        assert "image.generate" in result

    def test_image_keyword_english(self):
        result = names(route("generate an image for me", ALL_SPECS))
        assert "image.generate" in result

    def test_vision_ocr_keyword(self):
        result = names(route("帮我识别图里的文字 ocr", ALL_SPECS))
        assert "vision.see" in result
        assert "image.ocr" in result

    def test_calendar_keyword(self):
        result = names(route("在日历里添加一个会议", ALL_SPECS))
        assert "calendar.add" in result

    def test_schedule_keyword(self):
        result = names(route("每天定时执行这个任务", ALL_SPECS))
        assert "schedule.create" in result

    def test_git_keyword(self):
        result = names(route("帮我 git commit 一下", ALL_SPECS))
        assert "git.read" in result
        assert "git.commit" in result

    def test_monitor_keyword(self):
        result = names(route("帮我监控这个网址的变化", ALL_SPECS))
        assert "monitor.create" in result

    def test_wechat_keyword(self):
        result = names(route("帮我写一篇公众号推文", ALL_SPECS))
        assert "wechat.format" in result

    def test_notify_email_keyword(self):
        result = names(route("帮我发邮件通知一下", ALL_SPECS))
        assert "notify.email" in result

    def test_secret_keyword(self):
        result = names(route("帮我保存这个密码", ALL_SPECS))
        assert "secret.save" in result

    def test_gui_keyword(self):
        result = names(route("帮我控制桌面", ALL_SPECS))
        assert "gui.control" in result


class TestReduction:
    def test_simple_task_has_fewer_specs(self):
        """简单问候触发的 specs 比全量少。"""
        routed = route("你好", ALL_SPECS)
        assert len(routed) < len(ALL_SPECS)

    def test_complex_task_may_expand(self):
        """多关键词任务可激活更多能力。"""
        simple = route("查一下天气", ALL_SPECS)
        complex_ = route("登录网站下载图片并发邮件，然后 git commit", ALL_SPECS)
        assert len(complex_) >= len(simple)

    def test_empty_text_returns_always_include_plus_skills(self):
        result = names(route("", ALL_SPECS))
        for cap in ALWAYS_INCLUDE:
            assert cap in result
        assert "skill.外贸助手" in result


class TestRegistryIntegration:
    def test_specs_for_method_exists(self):
        from capabilities.base import CapabilityRegistry
        from capabilities.tools.fs import ReadFile
        from capabilities.tools.plan import PlanUpdate
        reg = CapabilityRegistry([ReadFile(), PlanUpdate()])
        result = reg.specs_for("帮我读一个文件")
        assert any(s["name"] == "fs.read" for s in result)
        assert any(s["name"] == "plan.update" for s in result)
