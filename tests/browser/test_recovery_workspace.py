from pathlib import Path
import pytest
from playwright.sync_api import expect
from tests.browser.test_workspace import browser
from tests.server import running_app
from tests.scripted_model import ScriptedModel
from tests.test_task_recovery import interrupted


@pytest.fixture
def recovery_live(indexed):
    settings=indexed[0].model_copy(update={'test_environment':True})
    task_id,_=interrupted((settings,*indexed[1:]))
    with running_app(settings,ScriptedModel()) as url:yield url,task_id


def test_recovery_button_restores_same_task_and_budget(browser,recovery_live):
    url,task_id=recovery_live;page=browser.new_page(viewport={'width':1440,'height':1100});page.goto(url+'/?task_id='+task_id)
    expect(page.get_by_role('button',name='恢复任务',exact=True)).to_be_visible()
    expect(page.locator('#error-message')).to_be_hidden()
    expect(page.locator('#recovery-info')).to_contain_text('原始截止时间')
    page.get_by_role('button',name='恢复任务',exact=True).click()
    expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)
    expect(page.locator('#recovery-info')).to_contain_text('执行轮次 2')
    assert page.request.get(url+'/tasks/'+task_id).json()['usage']['model_calls']==3
    assert len(page.request.get(url+'/tasks').json())==1
    page.screenshot(path='test-results/recovery-desktop.png',full_page=True);page.close()


def test_lost_resume_response_and_refresh_do_not_start_third_attempt(browser,recovery_live):
    url,task_id=recovery_live;page=browser.new_page();lost=[]
    def route(r):
        if not lost:lost.append(True);r.fetch();r.abort()
        else:r.continue_()
    page.route('**/resume',route);page.goto(url+'/?task_id='+task_id)
    page.get_by_role('button',name='恢复任务',exact=True).click()
    expect(page.locator('#error-message')).to_be_visible();page.reload()
    expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)
    task=page.request.get(url+'/tasks/'+task_id).json();assert task['attempt']==2 and task['usage']['model_calls']==3
    page.close()


@pytest.mark.parametrize('width',[320,390,736,1024])
def test_recovery_mobile_has_no_overflow(browser,recovery_live,width):
    url,task_id=recovery_live;page=browser.new_page(viewport={'width':width,'height':950});page.goto(url+'/?task_id='+task_id)
    expect(page.get_by_role('button',name='恢复任务',exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.get_by_role('button',name='恢复任务',exact=True).click();expect(page.locator('#task-status')).to_have_text('已完成',timeout=15000)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    if width==390:page.screenshot(path='test-results/recovery-mobile.png',full_page=True)
    page.close()
