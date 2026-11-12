import asyncio
from contextlib import ExitStack
import threading
from playwright.sync_api import expect
import pytest
from tests.browser.test_workspace import browser
from tests.server import running_app
from tests.collaborative_model import CollaborativeModel
from tests.scripted_model import ScriptedModel


@pytest.fixture
def collaborative_live(indexed):
    with ExitStack() as stack:
        def start(model=None):
            settings=indexed[0].model_copy(update={'test_environment':True})
            url=stack.enter_context(running_app(settings,model or CollaborativeModel()))
            return url,indexed[2].source
        yield start


def fill(page,url,path,mode='collaborative'):
    page.goto(url)
    page.get_by_label('本地仓库路径').fill(path)
    page.get_by_label('分析模式',exact=True).select_option(mode)
    page.get_by_label('研究问题').fill('Compare code and documentation')


def submit(page,url,path,mode='collaborative'):
    fill(page,url,path,mode)
    page.get_by_role('button',name='开始分析',exact=True).click()
    expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)


def test_collaborative_submit_shows_plan_and_citations(browser,collaborative_live):
    url,path=collaborative_live()
    page=browser.new_page(viewport={'width':1440,'height':1100})
    submit(page,url,path)
    expect(page.locator('#graph-summary')).to_be_visible()
    expect(page.locator('#subtask-list')).to_contain_text('代码调查')
    expect(page.locator('#subtask-list')).to_contain_text('文档调查')
    page.locator('#report-panel .citation').first.click()
    expect(page.locator('#evidence-detail')).to_be_visible()
    page.screenshot(path='test-results/collaborative-desktop.png',full_page=True)
    page.close()


def test_conflict_opens_code_and_document_sources(browser,collaborative_live):
    url,path=collaborative_live(CollaborativeModel(conflict=True))
    page=browser.new_page()
    fill(page,url,path)
    page.get_by_role('button',name='开始分析',exact=True).click()
    expect(page.locator('#task-status')).to_have_text('部分完成',timeout=15000)
    expect(page.locator('#report-panel')).to_contain_text('模型评审：冲突')
    for i,expected in [(0,'app.py'),(1,'README.md')]:
        page.locator('#report-panel .citation').nth(i).click()
        expect(page.locator('#evidence-location')).to_contain_text(expected)
    page.close()


def test_refresh_and_sse_resume_keep_subtasks_without_duplicates(browser,collaborative_live):
    url,path=collaborative_live()
    page=browser.new_page();submit(page,url,path)
    task_url=page.url
    page.reload()
    expect(page.locator('#task-status')).to_have_text('已完成')
    expect(page.locator('#subtask-list .subtask')).to_have_count(2)
    page.get_by_role('tab',name='调查过程').click()
    rows=page.locator('#event-list li').evaluate_all('rows=>rows.map(row=>row.dataset.sequence)')
    assert len(rows)==len(set(rows)) and page.url==task_url
    page.close()


def test_lost_response_retry_preserves_mode_and_one_task(browser,collaborative_live):
    url,path=collaborative_live()
    page=browser.new_page();lost=[]
    def route(r):
        if r.request.method=='POST' and not lost:
            lost.append(True);r.fetch();r.abort()
        else:r.continue_()
    page.route('**/tasks',route)
    fill(page,url,path);page.get_by_role('button',name='开始分析',exact=True).click()
    expect(page.locator('#error-message')).to_be_visible()
    page.reload()
    expect(page.get_by_label('分析模式',exact=True)).to_have_value('collaborative')
    page.get_by_role('button',name='开始分析',exact=True).click()
    expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)
    assert len(page.request.get(url+'/tasks').json())==1
    page.close()


def test_single_task_remains_compatible(browser,collaborative_live):
    url,path=collaborative_live(ScriptedModel())
    page=browser.new_page();submit(page,url,path,'single')
    expect(page.locator('#graph-summary')).to_be_hidden()
    expect(page.locator('#report-panel')).to_contain_text('Processor.run')
    page.close()


def test_cancel_does_not_launch_followup(browser,collaborative_live):
    entered,release=threading.Event(),threading.Event()
    class PausedPlanner(CollaborativeModel):
        def complete(self,messages,tools,max_output_tokens):
            if 'ROLE: planner' in messages[0]['content']:
                entered.set();release.wait(10)
            return super().complete(messages,tools,max_output_tokens)
    url,path=collaborative_live(PausedPlanner(followups=1))
    page=browser.new_page();fill(page,url,path)
    page.get_by_role('button',name='开始分析',exact=True).click()
    assert entered.wait(5)
    try:
        expect(page.locator('#task-status')).to_have_text('调查中')
        page.get_by_role('button',name='取消任务',exact=True).click()
    finally:release.set()
    expect(page.locator('#task-status')).to_have_text('已取消',timeout=15000)
    assert not page.request.get(page.url.split('/?')[0]+'/tasks').json()[0]['usage']['tool_calls']
    page.close()


@pytest.mark.parametrize('width',[320,390,736,1024])
def test_collaborative_mobile_has_no_overflow(browser,collaborative_live,width):
    url,path=collaborative_live()
    page=browser.new_page(viewport={'width':width,'height':950})
    submit(page,url,path)
    page.locator('#report-panel .citation').last.click()
    expect(page.locator('#evidence-code')).to_contain_text('Sample processor')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    if width==390:page.screenshot(path='test-results/collaborative-mobile.png',full_page=True)
    page.close()
