from contextlib import ExitStack
import asyncio
import threading
import httpx
import pytest
from playwright.sync_api import expect
from repolens.github_client import GitHubClient
from tests.browser.test_workspace import browser
from tests.github_fixtures import COMMIT, GitHubFixture, public_dns, response
from tests.scripted_model import ScriptedModel
from tests.server import running_app


@pytest.fixture
def github_live(indexed):
    with ExitStack() as stack:
        def start(handler=None):
            settings = indexed[0].model_copy(update={"test_environment": True})
            fixture = handler or GitHubFixture()
            factory = lambda settings: GitHubClient(settings, transport=httpx.MockTransport(fixture), resolve_host=public_dns)
            return stack.enter_context(running_app(settings, ScriptedModel(), github_client_factory=factory))
        yield start


def fill(page, url):
    page.goto(url)
    page.get_by_label("仓库来源", exact=True).select_option("github")
    page.get_by_label("GitHub 仓库地址", exact=True).fill("https://github.com/example/demo")
    page.get_by_label("分支、标签或 commit（可选）", exact=True).fill("feature/parser")
    page.get_by_label("研究问题").fill("Where is status saved?")


def submit(page, url):
    fill(page, url)
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#task-status")).to_have_text("已完成", timeout=15000)


def test_github_submit_opens_commit_bound_evidence(browser, github_live):
    page = browser.new_page(viewport={"width":1440,"height":1000})
    submit(page, github_live())
    expect(page.locator("#repository-label")).to_contain_text("https://github.com/example/demo")
    page.locator("#report-panel .citation").first.click()
    expect(page.locator("#evidence-code")).to_contain_text("self.store.save")
    link = page.get_by_role("link", name="在 GitHub 查看固定版本源码")
    expect(link).to_have_attribute("href", f"https://github.com/example/demo/blob/{COMMIT}/app.py#L9-L11")
    page.screenshot(path="test-results/github-workspace-desktop.png", full_page=True)
    page.close()


def test_github_ref_survives_refresh_retry(browser, github_live):
    url = github_live()
    page = browser.new_page()
    lost = []
    def lose_response(route):
        if route.request.method == "POST" and not lost:
            lost.append(True)
            route.fetch()
            route.abort()
        else:
            route.continue_()
    page.route("**/tasks", lose_response)
    fill(page, url)
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#error-message")).to_be_visible(timeout=15000)
    page.reload()
    expect(page.get_by_label("仓库来源", exact=True)).to_have_value("github")
    expect(page.get_by_label("分支、标签或 commit（可选）", exact=True)).to_have_value("feature/parser")
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#task-status")).to_have_text("已完成", timeout=15000)
    assert len(page.request.get(url + "/tasks").json()) == 1
    assert len(page.request.get(url + "/repositories").json()) == 2
    page.close()


def test_github_provider_import_errors_are_visible(browser, github_live):
    page = browser.new_page()
    fill(page, github_live(lambda request: response(429)))
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#error-message")).to_contain_text("github_rate_limited", timeout=15000)
    page.close()


def test_source_switch_clears_inapplicable_fields(browser, github_live):
    page = browser.new_page()
    fill(page, github_live())
    page.get_by_label("仓库来源", exact=True).select_option("local")
    assert page.locator("#github-url").input_value() == ""
    assert page.locator("#github-ref").input_value() == ""
    expect(page.get_by_label("本地仓库路径")).to_be_enabled()
    assert page.locator("#github-url").is_disabled()
    page.close()


def test_request_fields_are_locked_during_github_import(browser,github_live):
    gate=threading.Event()
    fixture=GitHubFixture()
    async def handler(request):
        if request.url.host=="codeload.github.com":
            while not gate.is_set():
                await asyncio.sleep(.01)
        return fixture(request)
    page=browser.new_page()
    fill(page,github_live(handler))
    page.get_by_role("button",name="开始分析",exact=True).click()
    try:
        expect(page.get_by_label("仓库来源",exact=True)).to_be_disabled()
        expect(page.get_by_label("GitHub 仓库地址",exact=True)).to_be_disabled()
        expect(page.get_by_label("研究问题")).to_be_disabled()
    finally:
        gate.set()
    expect(page.locator("#task-status")).to_have_text("已完成",timeout=15000)
    expect(page.get_by_label("仓库来源",exact=True)).to_be_enabled()
    page.close()


@pytest.mark.parametrize("width", [320,390,736,1024])
def test_github_mobile_has_no_horizontal_overflow(browser, github_live, width):
    page = browser.new_page(viewport={"width":width,"height":900})
    url=github_live()
    fill(page, url)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("button", name="开始分析", exact=True).click()
    expect(page.locator("#task-status")).to_have_text("已完成", timeout=15000)
    page.locator("#report-panel .citation").first.click()
    expect(page.locator("#evidence-code")).to_contain_text("self.store.save")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width==390:
        page.screenshot(path="test-results/github-workspace-mobile.png", full_page=True)
    page.close()
