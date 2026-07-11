from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_model_picker_only_uses_ready_models_and_waits_for_switch():
    js = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    assert "filter(m => m.available === true)" in js
    assert "waitForWsReady(12000)" in js
    assert "modelSwitchFailed" in js


def test_artifact_links_are_repeatable_and_binary_files_have_actions():
    js = (ROOT / "frontend/app.boot.js").read_text(encoding="utf-8")
    assert "_ARTIFACT_RE.lastIndex = 0" in js
    assert "dataset.linkified" not in js
    assert "/api/artifact/file?path=" in js
    assert "/api/artifact/open" in js
    assert "artifactActionBar" in js


def test_markdown_artifact_links_open_inside_captain():
    js = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    assert 'class="artifact-link"' in js
    assert 'data-path="${escAttr(raw)}"' in js


def test_attachments_do_not_duplicate_paths_and_overlays_close_consistently():
    app = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    boot = (ROOT / "frontend/app.boot.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert 'id="file-inp" style="display:none" multiple' in html
    assert "if (inp && !isImage) inp.value = ref + inp.value" not in boot
    assert "closeArtifactsBrowser()" in app
    assert "closeArtifact()" in app
    assert "ws.readyState !== 1 || !_wsReady" in app
