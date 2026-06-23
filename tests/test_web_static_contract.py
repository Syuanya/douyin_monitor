from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_web_deployment_files_exist():
    required = [
        "app/web/server.py",
        "app/web/context.py",
        "app/web/static/index.html",
        "app/web/static/app.js",
        "app/web/static/styles.css",
        "requirements-web.txt",
        "Dockerfile.web",
        "docker-compose.web.yml",
        "deploy/linux/douyin-monitor-web.service",
        "deploy/linux/nginx.conf",
        "deploy/linux/install_web.sh",
        "docs/WEB_LINUX_DEPLOYMENT.md",
    ]
    missing = [name for name in required if not (ROOT / name).exists()]
    assert not missing


def test_web_api_contains_auth_and_batch_import_endpoints():
    source = (ROOT / "app/web/server.py").read_text(encoding="utf-8")
    assert "DOUYIN_MONITOR_WEB_TOKEN" in source
    assert "/api/import/preview" in source
    assert "/api/import/file/commit" in source
    assert "/api/monitor/check-all" in source
    assert "/api/parse/stream" in source


def test_web_docs_warn_against_public_plain_http():
    doc = (ROOT / "docs/WEB_LINUX_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "HTTPS" in doc
    assert "Token" in doc
    assert "不建议把 8080 端口直接暴露到公网" in doc


def test_web_admin_pages_are_registered():
    html = (ROOT / "app/web/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    server = (ROOT / "app/web/server.py").read_text(encoding="utf-8")
    for tab in [
        "diagnostics", "cookies", "queue", "batchjobs", "media", "storage",
        "logs", "risk", "notifications", "updates", "access", "backups",
    ]:
        assert f'data-tab="{tab}"' in html
        assert f'id="{tab}"' in html
    for endpoint in [
        "/api/diagnostics", "/api/cookies", "/api/download-queue",
        "/api/batch-jobs", "/api/media-library", "/api/storage",
        "/api/logs", "/api/network-risk", "/api/notifications",
        "/api/updates", "/api/access", "/api/backups",
    ]:
        assert endpoint in server
    assert "loadDiagnostics" in js
    assert "loadMediaLibrary" in js


def test_web_pwa_files_exist():
    assert (ROOT / "app/web/static/manifest.webmanifest").exists()
    assert (ROOT / "app/web/static/sw.js").exists()
