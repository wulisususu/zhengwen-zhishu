"""公文起草：模型正文是否合格（app.gongwen.service._too_thin）。

回归：真实联调中模型把要点全部写成「（一）小标题。正文……」（二级段落），
611 字的完整正文被判为「只有标题」，退回骨架稿。
"""
from app.gongwen.schema import BodyPara
from app.gongwen.service import _too_thin


def test_body_written_as_level_two_points_is_not_thin():
    paras = [
        BodyPara("为做好小微企业首次贷款贴息申报工作，现就有关事项通知如下。", 0),
        BodyPara("一、提高思想认识", 1),
        BodyPara("（一）充分认识政策意义。首次贷款贴息是缓解小微企业融资难的重要举措，各区要摆上重要位置。", 2),
        BodyPara("（二）准确把握政策要求。要严格对照申请条件审核把关，防止政策执行走偏。", 2),
        BodyPara("二、明确重点任务", 1),
        BodyPara("（一）抓紧组织申报受理。各区金融工作部门要明确受理渠道和办理时限，指导企业准备材料。", 2),
        BodyPara("（二）严格审核把关。要逐户核实企业登记注册、经营年限、信用状况和贷款用途。", 2),
    ]
    assert not _too_thin(paras)


def test_headings_only_is_thin():
    paras = [
        BodyPara("为做好小微企业首次贷款贴息申报工作，根据有关部署要求，现就有关事项通知如下，请认真贯彻执行。", 0),
        BodyPara("一、提高思想认识", 1),
        BodyPara("（一）充分认识政策意义", 2),
        BodyPara("（二）准确把握政策要求", 2),
        BodyPara("二、明确重点任务", 1),
        BodyPara("（一）抓紧组织申报受理", 2),
        BodyPara("（二）严格审核把关", 2),
        BodyPara("三、加强组织保障", 1),
        BodyPara("（一）压实工作责任", 2),
        BodyPara("（二）加强政策宣传", 2),
        BodyPara("特此通知。", 0),
    ]
    assert _too_thin(paras)


def test_prompts_forbid_inventing_facts_like_the_document_generator():
    """回归：真实联调中「请示」在没有给出任何数据时编出了贷款额、预算缺口等数字。"""
    from app.gongwen import service

    messages = service._build_messages({"doc_type": "请示", "subject": "调整贴息资金预算"}, service.build_ir({"doc_type": "请示"}))
    for prompt in (messages[0]["content"], service.REPAIR_PROMPT):
        assert "【待补充】" in prompt and "不得编造" in prompt
