import pytest

from app.docs_pipeline.core import _hallucination_guard
from app.docs_pipeline.nodes import _assemble_final_md, _normalize_section_content


def test_hallucination_guard_returns_findings_without_inline_audit_marker():
    content = "夫子庙距离南京站约10公里，建议结合当天交通安排。"

    result = _hallucination_guard(content)

    assert result["risk_level"] in {"low", "medium", "high"}
    assert result["findings"]
    assert result["content"] == content
    assert "[审核标记" not in result["content"]


def test_assemble_final_md_adds_top_level_chapter_numbers():
    state = {
        "polished_title": "南京7月旅游攻略",
        "generated_chapters": [
            {"idx": 1, "heading": "南京概况与气候", "content": "正文"},
            {"idx": 2, "heading": "第2章 必游景点推荐", "content": "正文"},
        ],
    }

    final_md = _assemble_final_md(state)

    assert "## 第1章 南京概况与气候" in final_md
    assert "## 第2章 必游景点推荐" in final_md
    assert "## 第2章 第2章" not in final_md


def test_normalize_section_content_numbers_markdown_subheadings():
    content = "### 交通方式简介\n正文\n### 公交线路图与使用指南\n正文"

    normalized = _normalize_section_content(content, 6)

    assert "### 6.1 交通方式简介" in normalized
    assert "### 6.2 公交线路图与使用指南" in normalized

from app.docs_pipeline.nodes import _quality_check_chapter


def test_normalize_section_content_promotes_h4_and_renumbers_duplicates():
    content = "### 4.1 整体架构设计\n正文\n#### 4.1 前端用户界面\n正文\n4.2 关键技术选择\n正文"

    normalized = _normalize_section_content(content, 4)

    assert "####" not in normalized
    assert "### 4.1 整体架构设计" in normalized
    assert "### 4.2 前端用户界面" in normalized
    assert "### 4.3 关键技术选择" in normalized


@pytest.mark.xfail(
    strict=False,
    reason="规格遗留：_quality_check_chapter 目前只做承诺降级 + too_short，未实现 meta-narrative 段落剔除",
)
def test_quality_check_removes_meta_narrative_section_before_streaming():
    chapter = {
        "idx": 1,
        "total": 6,
        "heading": "第1章 绪论",
        "content": "### 1.1 项目背景\n实质内容。\n### 1.3 接下来章节结构\n接下来的章节将详细阐述项目背景、目标与意义。",
        "fallback": False,
        "risk_level": "none",
        "risk_findings": [],
    }

    checked = _quality_check_chapter(chapter)

    assert "接下来章节结构" not in checked["content"]
    assert "接下来的章节将" not in checked["content"]
    assert "meta_narrative_removed" in checked["quality_flags"]


@pytest.mark.xfail(
    strict=False,
    reason="规格遗留：_quality_check_chapter 未实现高风险内容拦截（blocked/quality_blocked_high_risk）",
)
def test_quality_check_blocks_high_risk_content_before_streaming():
    chapter = {
        "idx": 6,
        "total": 6,
        "heading": "第6章 案例分析",
        "content": "### 6.1 案例一\n响应速度从30秒缩短至15秒，准确率从85%提升至90%。",
        "fallback": False,
        "risk_level": "high",
        "risk_findings": [{"risk_type": "百分比", "matched": "85%"}],
    }

    checked = _quality_check_chapter(chapter)

    assert checked["blocked"] is True
    assert "quality_blocked_high_risk" in checked["quality_flags"]
    assert "响应速度从30秒缩短至15秒" not in checked["content"]
    assert "需人工核实" in checked["content"]


def test_quality_check_flags_short_content_without_blocking():
    chapter = {
        "idx": 5,
        "total": 6,
        "heading": "第5章 实施与验证",
        "content": "### 5.1 实施过程\n内容过短。",
        "fallback": False,
        "risk_level": "none",
        "risk_findings": [],
    }

    checked = _quality_check_chapter(chapter, min_chars=80)

    assert checked["blocked"] is False
    assert "too_short" in checked["quality_flags"]

from app.docs_pipeline.nodes import _build_global_thread, _summarize_chapter_for_bridge, _build_section_messages


def test_build_global_thread_is_short_and_uses_outline_progression():
    outline = {
        "sections": [
            {"heading": "第1章 背景分析"},
            {"heading": "第2章 应用场景"},
            {"heading": "第3章 基础设施"},
            {"heading": "第4章 实施验证"},
        ]
    }

    thread = _build_global_thread("泰州移动公司的低空经济未来规划", outline)

    assert "泰州移动公司的低空经济未来规划" in thread
    assert "背景分析" in thread
    assert "实施验证" in thread
    assert len(thread) <= 120


def test_summarize_chapter_for_bridge_is_short_and_strips_headings():
    content = "### 1.1 背景分析\n低空经济规划需要先明确区域资源、产业基础与通信能力。\n第二段更长内容。"

    summary = _summarize_chapter_for_bridge(content)

    assert "###" not in summary
    assert "低空经济规划" in summary
    assert len(summary) <= 90


def test_build_section_messages_adds_short_global_and_previous_context():
    messages = _build_section_messages(
        topic="泰州移动公司的低空经济未来规划",
        idx=2,
        total=6,
        heading="第2章 应用场景规划",
        key_points="围绕低空巡检、应急通信、物流协同展开。",
        gen_prompt="请承接规划基础，写应用场景。",
        global_thread="全文主线：泰州移动公司的低空经济未来规划按背景 -> 场景 -> 基建递进。",
        prev_summary="上一章明确了低空经济规划需要结合区域资源与通信能力。",
    )

    system = messages[0]["content"]
    assert "全文主线" in system
    assert "上一章结论" in system
    assert "上一章明确了" in system
    assert len(system) < 900
from app.docs_pipeline.nodes import _downgrade_unsupported_commitments


def test_normalize_section_content_strips_mixed_double_numbering():
    content = "### 1.1 1. 背景介绍\n正文\n### 1.2 二、问题分析\n正文"

    normalized = _normalize_section_content(content, 1)

    assert "### 1.1 背景介绍" in normalized
    assert "### 1.2 问题分析" in normalized
    assert "1.1 1." not in normalized
    assert "二、" not in normalized


@pytest.mark.xfail(
    strict=False,
    reason="规格遗留：_quality_check_chapter 未实现跨章小节剔除（cross_chapter_sections_removed）",
)
def test_quality_check_removes_cross_chapter_outline_sections():
    chapter = {
        "idx": 2,
        "total": 6,
        "heading": "第2章 问题分析",
        "content": "### 2.1 问题分析\n本章分析问题。\n### 2.2 方案设计\n这里串到了方案。\n### 2.3 保障措施\n这里串到了保障。",
        "fallback": False,
        "risk_level": "none",
        "risk_findings": [],
    }

    checked = _quality_check_chapter(chapter, min_chars=20)

    assert "本章分析问题" in checked["content"]
    assert "方案设计" not in checked["content"]
    assert "保障措施" not in checked["content"]
    assert "cross_chapter_sections_removed" in checked["quality_flags"]


def test_downgrade_unsupported_enterprise_commitments():
    content = "泰州移动公司将设立专项基金，并与航空公司合作，成为全国领先的低空经济发展示范区之一。"

    downgraded, changed, _risk_count = _downgrade_unsupported_commitments(content)

    assert changed is True
    assert "将设立专项基金" not in downgraded
    assert "与航空公司合作" not in downgraded
    assert "成为全国领先" not in downgraded
    assert "可评估" in downgraded or "需结合" in downgraded
