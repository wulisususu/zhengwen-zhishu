import test from 'node:test'
import assert from 'node:assert/strict'

import {
  extractDocTasksFromMessage,
  extractDocumentOutlineParts,
  buildAssistantActionText,
  parseDocTaskMarkers,
  parseMessageMetadata,
  stripDocTaskMarkers,
} from './documentMessageState.mjs'

test('parseMessageMetadata returns parsed metadata object', () => {
  const message = {
    metadata_json: '{"doc_tasks":[{"task_id":"doc_1","status":"queued"}]}',
  }

  assert.deepEqual(parseMessageMetadata(message), {
    doc_tasks: [{ task_id: 'doc_1', status: 'queued' }],
  })
})

test('extractDocTasksFromMessage prefers metadata doc_tasks and falls back to legacy markers', () => {
  const message = {
    metadata_json: '{"doc_tasks":[{"task_id":"doc_1","status":"done"}]}',
    content: '正文[[DOC_TASK]]{"task_id":"doc_1","status":"queued"}[[/DOC_TASK]][[DOC_TASK]]{"task_id":"doc_2","status":"done"}[[/DOC_TASK]]',
  }

  assert.deepEqual(extractDocTasksFromMessage(message), [
    { task_id: 'doc_1', status: 'done' },
    { task_id: 'doc_2', status: 'done' },
  ])
})

test('parseDocTaskMarkers reads legacy embedded task payloads', () => {
  const content = 'abc[[DOC_TASK]]{"task_id":"legacy_1","status":"queued"}[[/DOC_TASK]]xyz'

  assert.deepEqual(parseDocTaskMarkers(content), [
    { task_id: 'legacy_1', status: 'queued' },
  ])
})

test('extractDocumentOutlineParts splits main body and outline section by marker', () => {
  const parts = extractDocumentOutlineParts(`
我将根据您的要求生成word
正在开始执行...

文档大纲预览：
月度运营分析报告

本报告总结核心指标。
1. 核心运营数据概览
2. 系统性能与稳定性分析
  `)

  assert.deepEqual(parts, {
    main: '我将根据您的要求生成word\n正在开始执行...',
    summary: '月度运营分析报告',
    body: '月度运营分析报告\n\n本报告总结核心指标。\n1. 核心运营数据概览\n2. 系统性能与稳定性分析',
  })
})

test('extractDocumentOutlineParts returns null when no outline marker exists', () => {
  assert.equal(extractDocumentOutlineParts('普通回答内容'), null)
})

test('stripDocTaskMarkers removes embedded legacy task payloads from visible text', () => {
  assert.equal(
    stripDocTaskMarkers('前文[[DOC_TASK]]{"task_id":"legacy_1"}[[/DOC_TASK]]后文'),
    '前文后文',
  )
})

test('buildAssistantActionText combines main body and outline body for message actions', () => {
  assert.equal(
    buildAssistantActionText('这是正文。', '文档大纲\n\n第一章 项目概述'),
    '这是正文。\n\n文档大纲\n\n第一章 项目概述',
  )
})

test('buildAssistantActionText avoids duplicating outline content already in main body', () => {
  assert.equal(
    buildAssistantActionText('文档大纲\n\n第一章 项目概述', '文档大纲\n\n第一章 项目概述'),
    '文档大纲\n\n第一章 项目概述',
  )
})
