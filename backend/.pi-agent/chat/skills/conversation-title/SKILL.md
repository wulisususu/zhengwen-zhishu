---
name: conversation-title
description: Use when producing chat or document page history titles, display titles, card titles, document filenames, or compact title hints from a long user request.
---

# Conversation Title

This skill controls compact titles for the left history list, document cards, and generated file names.

The Chat page and Document page are already separate frontend entry points. Do not use this skill to route between chat, Word, PPT, Excel, or knowledge-base workflows. Only refine the visible title string for the current page.

## Core Rule

Turn a long user request into a short noun phrase.

Preferred length:

* Chinese: 4-10 characters
* Mixed Chinese/English: keep the visible title within 12 characters when possible
* English: 2-5 words

The title must preserve the core object and document type or topic. It must not copy the full first sentence.

## Remove Noise

Remove leading or trailing request verbs and filler:

* 请
* 帮我
* 给我
* 我要
* 我想
* 根据以下
* 编写
* 写一份
* 生成
* 创建
* 输出
* 做一个
* 支持
* 要求
* 包含

Remove detailed parameters from the title:

* dates and times unless they are the core topic
* long requirement lists
* deployment environment
* model names
* full chapter lists
* emails, contacts, task status, IDs, or URLs

## Format

For chat history titles:

* output only the compact title
* no punctuation at the end
* no markdown
* no quotation marks

For document card titles or filenames:

* use the same compact noun phrase
* append `.docx` only when a filename is required
* keep the filename base within 10 Chinese characters when possible

## Examples

| User request | Good title | Bad title |
| --- | --- | --- |
| 我要开发一个AI文档生成平台，支持聊天、Word、PPT、Excel | AI文档平台 | 我要开发一个AI文档生成平台 |
| 根据以下情况生成事故调查报告，事件：机房网络中断 | 事故调查报告 | 根据以下情况生成事故调查报告 |
| 编写《智慧城市一卡通平台建设项目投标文件（技术部分）》 | 一卡通投标 | 智慧城市一卡通平台建设项目投标文件技术部分 |
| 请为智慧停车管理平台编写数据库设计说明书 | 停车库设计 | 请为智慧停车管理平台编写数据库设计说明书 |
| 生成完整的软件需求规格说明书（SRS） | SRS说明书 | 生成完整的软件需求规格说明书 |

## Interaction With Tools

When a tool accepts `title`, `filename`, `document_title`, `display_title`, `history_title`, or a similar title-like argument, pass the refined title, not the raw user request.

If the current runtime has no title-update tool, still use this rule for any title-like tool argument that does exist. Do not announce title refinement in user-facing content.
