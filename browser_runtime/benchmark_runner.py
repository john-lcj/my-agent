"""Run the P5 browser benchmark against deterministic local pages."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from browser_runtime.benchmark import BrowserBenchmarkCase, benchmark_cases
from browser_runtime.kernel import BrowserContextKey, BrowserKernel, RemoteStateAssertion


FIXTURE_DOWNLOAD = b"captain-browser-benchmark\n"


@dataclass(frozen=True)
class BrowserBenchmarkResult:
    case_id: str
    category: str
    passed: bool
    evidence: str
    elapsed_ms: int
    high_impact: bool


class _FixtureHandler(BaseHTTPRequestHandler):
    server_version = "CaptainBenchmark/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        if self.path.startswith("/download"):
            self._send_bytes(
                FIXTURE_DOWNLOAD,
                content_type="text/plain",
                headers={"Content-Disposition": "attachment; filename=benchmark.txt"},
            )
            return
        self._send_text(self._page())

    def _send_text(self, body: str, status: int = HTTPStatus.OK) -> None:
        self._send_bytes(body.encode("utf-8"), status=status, content_type="text/html; charset=utf-8")

    def _send_bytes(
        self,
        body: bytes,
        *,
        status: int = HTTPStatus.OK,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _page(self) -> str:
        return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Captain Browser Benchmark</title>
  <script>
    function submitFixture(event) {
      event.preventDefault();
      document.querySelector("#status").textContent = "Saved successfully";
    }
    function rememberScope(value) {
      localStorage.setItem("scope", value);
      document.cookie = "scope=" + value + "; path=/; SameSite=Lax";
      document.querySelector("#scope-status").textContent = value;
    }
    window.addEventListener("DOMContentLoaded", () => {
      setTimeout(() => {
        document.querySelector("#delayed").textContent = "Delayed ready";
      }, 120);
      document.querySelector("#upload").addEventListener("change", (event) => {
        const file = event.target.files[0];
        document.querySelector("#upload-status").textContent = file ? file.name : "No file";
      });
    });
  </script>
</head>
<body>
  <main>
    <h1>Captain Browser Benchmark</h1>
    <form id="fixture-form" onsubmit="submitFixture(event)">
      <label for="email">Email</label>
      <input id="email" name="email" type="email">
      <label for="secret">Secret</label>
      <input id="secret" name="secret" type="password">
      <button type="submit">Save</button>
    </form>
    <p id="status">Waiting</p>
    <a href="/download" download>Download report</a>
    <label for="upload">Upload file</label>
    <input id="upload" type="file">
    <p id="upload-status">No file</p>
    <p id="delayed">Waiting for delayed content</p>
    <button id="remember-alpha" onclick="rememberScope('alpha')">Remember alpha</button>
    <button id="remember-beta" onclick="rememberScope('beta')">Remember beta</button>
    <p id="scope-status">No scope</p>
  </main>
</body>
</html>"""


@contextlib.contextmanager
def _fixture_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _run_case(case: BrowserBenchmarkCase, page, context, base_url: str, tmpdir: Path, kernel: BrowserKernel) -> str:
    page.goto(base_url)
    if case.category == "navigation":
        page.get_by_role("heading", name="Captain Browser Benchmark").wait_for()
        return page.title()
    if case.category == "form_fill":
        page.get_by_label("Email").fill(f"{case.case_id}@example.test")
        page.get_by_label("Secret").fill("benchmark-secret")
        return page.locator("#email").input_value()
    if case.category == "form_submit":
        page.get_by_label("Email").fill("submit@example.test")
        page.get_by_label("Secret").fill("benchmark-secret")
        page.get_by_role("button", name="Save").click()
        page.get_by_text("Saved successfully").wait_for()
        return page.locator("#status").text_content() or ""
    if case.category == "downloads":
        with page.expect_download() as download_info:
            page.get_by_role("link", name="Download report").click()
        download = download_info.value
        target = tmpdir / f"{case.case_id}.txt"
        download.save_as(str(target))
        return hashlib.sha256(target.read_bytes()).hexdigest()
    if case.category == "uploads":
        source = tmpdir / f"{case.case_id}.txt"
        source.write_text("upload benchmark\n", encoding="utf-8")
        page.get_by_label("Upload file").set_input_files(str(source))
        page.get_by_text(source.name).wait_for()
        return page.locator("#upload-status").text_content() or ""
    if case.category == "delays":
        page.get_by_text("Delayed ready").wait_for()
        return page.locator("#delayed").text_content() or ""
    if case.category == "isolation":
        other = context.browser.new_context()
        try:
            left = context.new_page()
            right = other.new_page()
            left.goto(base_url)
            right.goto(base_url)
            left.get_by_role("button", name="Remember alpha").click()
            right.get_by_role("button", name="Remember beta").click()
            left_value = left.evaluate("localStorage.getItem('scope')")
            right_value = right.evaluate("localStorage.getItem('scope')")
            if (left_value, right_value) != ("alpha", "beta"):
                raise AssertionError(f"context leakage: {left_value!r}, {right_value!r}")
            return f"{left_value}/{right_value}"
        finally:
            other.close()
    if case.category == "takeover":
        key = BrowserContextKey("benchmark-owner", "local-account", "p5", case.case_id)
        waiting = kernel.takeover(key, "high impact browser action")
        resumed = kernel.takeover(key, "", resume=True)
        if waiting["state"] != "waiting_for_owner" or resumed["state"] != "resumed":
            raise AssertionError("takeover did not resume")
        return resumed["state"]
    if case.category == "failures":
        try:
            page.locator("#does-not-exist").wait_for(timeout=150)
        except Exception as exc:  # Playwright raises TimeoutError from its own package.
            return type(exc).__name__
        raise AssertionError("missing selector unexpectedly appeared")
    if case.category == "verification":
        page.get_by_label("Email").fill("verify@example.test")
        page.get_by_label("Secret").fill("benchmark-secret")
        page.get_by_role("button", name="Save").click()
        assertion = RemoteStateAssertion(
            case.case_id,
            expected_url=f"{base_url}/",
            required_text=("Saved successfully",),
            forbidden_text=("Unhandled", "Traceback"),
        )
        passed, message = assertion.verify(url=page.url, text=page.text_content("body") or "")
        if not passed:
            raise AssertionError(message)
        return "remote state verified"
    raise ValueError(f"Unsupported benchmark category: {case.category}")


def run_benchmark(*, headless: bool = True) -> dict[str, object]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised by deployment environment.
        raise RuntimeError("Playwright is not installed in this Python environment") from exc

    results: list[BrowserBenchmarkResult] = []
    with tempfile.TemporaryDirectory(prefix="captain-browser-benchmark-") as raw_tmp:
        tmpdir = Path(raw_tmp)
        kernel = BrowserKernel(str(tmpdir / "browser.db"), str(tmpdir / "trace.jsonl"))
        with _fixture_server() as base_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                context = browser.new_context(accept_downloads=True)
                try:
                    page = context.new_page()
                    for case in benchmark_cases():
                        start = time.perf_counter()
                        try:
                            evidence = _run_case(case, page, context, base_url, tmpdir, kernel)
                            results.append(BrowserBenchmarkResult(
                                case.case_id, case.category, True, evidence, _elapsed_ms(start), case.high_impact,
                            ))
                        except Exception as exc:  # noqa: BLE001 - benchmark must report every case.
                            results.append(BrowserBenchmarkResult(
                                case.case_id, case.category, False, f"{type(exc).__name__}: {exc}",
                                _elapsed_ms(start), case.high_impact,
                            ))
                finally:
                    context.close()
            finally:
                browser.close()

    total = len(results)
    passed = sum(result.passed for result in results)
    unattended = [result for result in results if not result.high_impact]
    supervised = [result for result in results if result.high_impact]
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "success_rate": passed / total if total else 0.0,
        "unattended_total": len(unattended),
        "unattended_passed": sum(result.passed for result in unattended),
        "unattended_success_rate": (
            sum(result.passed for result in unattended) / len(unattended) if unattended else 0.0
        ),
        "supervised_total": len(supervised),
        "supervised_passed": sum(result.passed for result in supervised),
        "supervised_success_rate": (
            sum(result.passed for result in supervised) / len(supervised) if supervised else 0.0
        ),
        "results": [asdict(result) for result in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Captain browser benchmark.")
    parser.add_argument("--headed", action="store_true", help="Run Chromium with a visible browser window.")
    args = parser.parse_args(argv)
    summary = run_benchmark(headless=not args.headed)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
