import os
import socket
import threading
import time
from pathlib import Path
import pytest
import uvicorn
from playwright.sync_api import sync_playwright, expect
from repolens.api import create_app
from repolens.model_client import ProviderError
from tests.scripted_model import ScriptedModel


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("REPOLENS_BROWSER_EXECUTABLE") or None)
        yield browser
        browser.close()


@pytest.fixture
def live(indexed):
    servers = []
    def start(model=None):
        settings = indexed[0].model_copy(update={"test_environment": True})
        app = create_app(settings, model=model or ScriptedModel())
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        for _ in range(300):
            if server.started:
                break
            time.sleep(.01)
        assert server.started
        servers.append((server, thread))
        return f"http://127.0.0.1:{port}", indexed[2].source
    yield start
    for server, thread in servers:
        server.should_exit = True
        thread.join(10)


def submit(page, url, path):
    page.goto(url)
    expect(page.locator("#environment-banner")).to_contain_text("测试环境")
    page.get_by_label("本地仓库路径").fill(path)
    page.get_by_label("研究问题").fill("Where is status saved?")
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#task-status")).to_have_text("已完成", timeout=15000)


def test_submit_and_open_citation(browser, live):
    url, path = live()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    submit(page, url, path)
    page.locator("#report-panel .citation").first.click()
    expect(page.locator("#evidence-code")).to_contain_text('self.store.save(task_id, "running")')
    expect(page.locator("#evidence-location")).to_contain_text("app.py:9–11")
    page.screenshot(path="test-results/workspace-desktop.png", full_page=True)
    page.close()


def test_refresh_restores_task(browser, live):
    url, path = live()
    page = browser.new_page()
    submit(page, url, path)
    task_url = page.url
    page.reload()
    expect(page.locator("#task-status")).to_have_text("已完成")
    expect(page.locator("#report-panel")).to_contain_text("Processor.run")
    assert page.url == task_url and "task_id=" in task_url
    page.close()


@pytest.mark.parametrize("width", [320, 390, 736, 1024])
def test_mobile_view_has_no_horizontal_overflow(browser, live, width):
    url, path = live()
    page = browser.new_page(viewport={"width": width, "height": 900})
    submit(page, url, path)
    page.locator("#report-panel .citation").first.click()
    expect(page.locator("#evidence-code")).to_contain_text("self.store.save")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    if width == 390:
        page.screenshot(path="test-results/workspace-mobile.png", full_page=True)
    page.close()


def test_provider_error_is_visible(browser, live):
    class Offline:
        def complete(self, *args, **kwargs):
            raise ProviderError("provider_unavailable")
    url, path = live(Offline())
    page = browser.new_page()
    page.goto(url)
    page.get_by_label("本地仓库路径").fill(path)
    page.get_by_label("研究问题").fill("Question")
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#task-status")).to_have_text("失败", timeout=15000)
    expect(page.locator("#error-message")).to_contain_text("provider_unavailable")
    page.close()


def test_sse_disconnect_recovers_without_duplicate_events(browser, live):
    url, path = live()
    page = browser.new_page()
    blocked = []
    def route(request):
        if not blocked:
            blocked.append(True)
            request.abort()
        else:
            request.continue_()
    page.route("**/events*", route)
    submit(page, url, path)
    page.get_by_role("tab", name="调查过程").click()
    expect(page.locator("#event-list li")).not_to_have_count(0)
    sequences = page.locator("#event-list li").evaluate_all("rows => rows.map(x => x.dataset.sequence)")
    assert len(sequences) == len(set(sequences))
    assert blocked
    page.close()


def test_lost_submission_response_reuses_intent_after_refresh(browser, live):
    url, path = live()
    page = browser.new_page()
    lost = []
    def lose_first_response(route):
        if route.request.method == "POST" and not lost:
            lost.append(True)
            route.fetch()
            route.abort()
        else:
            route.continue_()
    page.route("**/tasks", lose_first_response)
    page.goto(url)
    page.get_by_label("本地仓库路径").fill(path)
    page.get_by_label("研究问题").fill("Where is status saved?")
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#error-message")).to_be_visible()
    page.reload()
    expect(page.get_by_label("本地仓库路径")).to_have_value(path)
    expect(page.get_by_label("研究问题")).to_have_value("Where is status saved?")
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#task-status")).to_have_text("已完成", timeout=15000)
    assert len(page.request.get(url + "/tasks").json()) == 1
    assert len(page.request.get(url + "/repositories").json()) == 2  # fixture plus one imported snapshot
    page.close()


def test_stale_evidence_response_cannot_overwrite_new_task(browser, live):
    url, path = live()
    page = browser.new_page()
    submit(page, url, path)
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        if (String(args[0]).startsWith('/evidence/')) await new Promise(r => setTimeout(r, 1800));
        return response;
      };
    }""")
    page.locator("#report-panel .citation").first.click()
    page.get_by_role("button", name="新建分析").click()
    page.get_by_label("研究问题").fill("Second question")
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#task-status")).to_have_text("已完成", timeout=15000)
    page.wait_for_timeout(2000)
    expect(page.locator("#evidence-detail")).to_be_hidden()
    expect(page.locator("#task-question")).to_have_text("Second question")
    page.close()
