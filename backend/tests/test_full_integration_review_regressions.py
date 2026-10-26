"""Fresh-review findings, each reproduced before its implementation fix."""
import io
import threading
import zipfile
import pytest
from test_gov_basic_api import app_client, create, action
from test_gov_policy_integration import policy_client, link
from test_gov_gongwen_integration import report


def test_policy_revoked_while_node_runs_blocks_approval(policy_client, monkeypatch):
    from app.gov import proofread
    client,tokens,_,library,policy,cid=policy_client
    library.verify(policy['id'],status='current',note='测试',fields={},verifier='reviewer')
    doc=create(client,tokens['writer'])
    doc=link(client,tokens['writer'],doc,[cid]).json()['data']
    doc=action(client,tokens['writer'],doc,'submit').json()['data']
    def node(draft):
        library.verify(policy['id'],status='abolished',note='审校期间废止',fields={},verifier='reviewer')
        return report()
    monkeypatch.setattr(proofread,'run_review',node)
    response=action(client,tokens['reviewer'],doc,'approve')
    assert response.status_code==409
    assert client.get(f"/api/v1/gov/documents/{doc['id']}",headers=tokens['writer']).json()['data']['status']=='pending'


def test_policy_guard_blocks_updates_until_approval_commit(policy_client):
    _,_,_,library,policy,_=policy_client
    entered=threading.Event();finished=threading.Event()
    def writer():
        entered.set();library.verify(policy['id'],status='abolished',note='修改',fields={},verifier='reviewer');finished.set()
    with library.store.approval_guard():
        worker=threading.Thread(target=writer);worker.start();assert entered.wait(1)
        assert not finished.wait(.1)
    worker.join(3);assert finished.is_set()


def test_indented_heading_keeps_ids_and_does_not_double_number():
    from app.gov.proofread import notice
    from app.services.gongwen.converter import build_spec
    from app.services.gongwen.rules import check_numbering
    draft=notice('test-id',{'docType':'notice','title':'测试','body':'  一、工作安排\n　 三、责任分工','fields':{},'signDate':''})
    spec,index=build_spec(draft)
    assert [c['text'] for c in spec['components'] if c['type']=='h1']==['工作安排','责任分工']
    gaps=check_numbering(draft)
    assert len(gaps)==1 and gaps[0].anchor=='test-id-p1'


def test_internal_export_retains_undertaker_and_partial_banji(app_client):
    from app.services.gongwen.settings import load_settings
    if not (load_settings().kit_path/'bin/gongwen.js').exists():pytest.skip('real kit required')
    client,tokens,_=app_client
    doc=create(client,tokens['writer'],fields={'recipient':'各单位','issuer':'测试办公室','undertaker':'数据安全处'},banji={'copyTo':['已填写的抄送单位'],'printer':'已填写的印发机关','printDate':''})
    result=client.post(f"/api/v1/gov/documents/{doc['id']}/export",headers=tokens['writer'],json={'kind':'internal_draft'})
    assert result.status_code==200,result.text
    with zipfile.ZipFile(io.BytesIO(result.content)) as z:
        xml=z.read('word/document.xml').decode()
        assert '数据安全处' in xml and '已填写的抄送单位' in xml and '已填写的印发机关' in xml
        assert '待补充：印发日期' in xml
        assert '本次审校发现严重问题' not in xml
