import time

from conftest import FIXTURES


def wait_job(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("导入作业超时")


def test_upload_returns_job_and_completes(admin, env):
    with open(FIXTURES / "desktop_basic.json", "rb") as f:
        r = admin.post("/api/imports", files={"file": ("result.json", f, "application/json")})
    assert r.status_code == 202
    job = wait_job(admin, r.json()["job_id"])
    assert job["state"] == "done", job
    assert job["result"]["chat_id"] == -1001234567890 and job["result"]["reacted"] == 4
    assert list((env.data_dir / "tmp").iterdir()) == []  # 临时文件已清理
    assert admin.get("/api/chats/-1001234567890/ranking").json()["total"] == 4


def test_upload_bad_file_reports_error(admin):
    r = admin.post("/api/imports", files={"file": ("x.json", b"not json", "application/json")})
    job = wait_job(admin, r.json()["job_id"])
    assert job["state"] == "failed" and "JSON" in job["error"]


def test_unknown_job_404(admin):
    assert admin.get("/api/jobs/nope").status_code == 404


def test_upload_requires_login(client):
    r = client.post("/api/imports", files={"file": ("x.json", b"{}", "application/json")})
    assert r.status_code == 401


def test_startup_cleans_leftover_uploads(env):
    from fastapi.testclient import TestClient
    from tgrank.app import create_app

    (env.data_dir / "tmp").mkdir(parents=True)
    (env.data_dir / "tmp" / "import-dead.json").write_text("{}")
    with TestClient(create_app(env)):
        assert list((env.data_dir / "tmp").iterdir()) == []
