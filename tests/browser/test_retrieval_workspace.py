from contextlib import ExitStack
import pytest
from playwright.sync_api import expect
from tests.browser.test_workspace import browser
from tests.server import running_app
from tests.test_retrieval_http import config
from tests.retrieval_services import RetrievalServices,RetrievalModel


@pytest.fixture
def retrieval_live(indexed):
    settings=config(indexed[0].data_dir.parent).model_copy(update={'test_environment':True})
    fixtures=RetrievalServices(settings)
    with running_app(settings,RetrievalModel(),retrieval_factory=lambda s,db:fixtures.service(db)) as url:
        yield url,indexed[2].source,fixtures


def fill(page,url,path):
    page.goto(url);page.get_by_label('本地仓库路径').fill(path)
    page.get_by_label('检索方式',exact=True).select_option('hybrid')
    page.get_by_label('启用重排',exact=True).check()
    page.get_by_label('研究问题').fill('Where is state saved?')


def test_hybrid_builds_index_and_followup_inherits_policy(browser,retrieval_live):
    url,path,fixtures=retrieval_live;page=browser.new_page()
    fill(page,url,path);page.get_by_role('button',name='开始分析',exact=True).click()
    expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)
    expect(page.locator('#retrieval-label')).to_contain_text('混合检索 · 重排')
    page.locator('#report-panel .citation').first.click();expect(page.locator('#evidence-detail')).to_be_visible()
    page.get_by_label('沿用同一快照继续追问').fill('Explain status storage')
    page.get_by_role('button',name='追问').click()
    expect(page.locator('#task-question')).to_have_text('Explain status storage')
    expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)
    tasks=page.request.get(url+'/tasks').json()
    assert len(tasks)==2 and all(t['retrieval_mode']=='hybrid' and t['rerank'] for t in tasks)
    assert len({t['snapshot_id'] for t in tasks})==1
    page.close()


def test_hybrid_lost_response_retry_keeps_one_index_and_task(browser,retrieval_live):
    url,path,fixtures=retrieval_live;page=browser.new_page();lost=[]
    def route(r):
        if r.request.method=='POST' and not lost:lost.append(True);r.fetch();r.abort()
        else:r.continue_()
    page.route('**/tasks',route);fill(page,url,path)
    page.get_by_role('button',name='开始分析',exact=True).click();expect(page.locator('#error-message')).to_be_visible()
    page.reload();expect(page.get_by_label('检索方式',exact=True)).to_have_value('hybrid')
    expect(page.get_by_label('启用重排',exact=True)).to_be_checked()
    page.get_by_role('button',name='开始分析',exact=True).click()
    expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)
    assert len(page.request.get(url+'/tasks').json())==1
    assert len([p for p,b in fixtures.calls if p.endswith('/create')])==1
    page.close()


@pytest.mark.parametrize('width',[320,390,736,1024])
def test_retrieval_controls_mobile_layout(browser,retrieval_live,width):
    url,path,_=retrieval_live;page=browser.new_page(viewport={'width':width,'height':950})
    fill(page,url,path)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.get_by_role('button',name='开始分析',exact=True).click()
    expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    if width==390:page.screenshot(path='test-results/hybrid-mobile.png',full_page=True)
    page.close()
