const DOC_TASK_MARKER_REGEX = /\[\[DOC_TASK\]\]([\s\S]*?)\[\[\/DOC_TASK\]\]/g
const OUTLINE_MARKER = '文档大纲预览：'

function cloneTask(task) {
  return task && typeof task === 'object' ? { ...task } : null
}

export function parseDocTaskMarkers(content) {
  const tasks = []
  for (const match of String(content || '').matchAll(DOC_TASK_MARKER_REGEX)) {
    try {
      const parsed = JSON.parse(match[1])
      if (parsed?.task_id) tasks.push(parsed)
    } catch {}
  }
  return tasks
}

export function parseMessageMetadata(message) {
  const raw = message?.metadata_json
  if (!raw) return {}
  if (typeof raw === 'object') return raw && !Array.isArray(raw) ? raw : {}
  try {
    const parsed = JSON.parse(String(raw))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

export function extractDocTasksFromMessage(message) {
  const metadata = parseMessageMetadata(message)
  const metadataTasks = Array.isArray(metadata.doc_tasks)
    ? metadata.doc_tasks.map(cloneTask).filter((task) => task?.task_id)
    : []
  const fallbackTasks = parseDocTaskMarkers(message?.content)
  const merged = []
  const seen = new Set()

  for (const task of [...metadataTasks, ...fallbackTasks]) {
    if (!task?.task_id || seen.has(task.task_id)) continue
    seen.add(task.task_id)
    merged.push(task)
  }

  return merged
}

function normalizeOutlineText(content) {
  return String(content || '')
    .replace(/\r\n/g, '\n')
    .trim()
}

export function extractDocumentOutlineParts(content) {
  const normalized = normalizeOutlineText(content)
  if (!normalized) return null

  const markerIndex = normalized.indexOf(OUTLINE_MARKER)
  if (markerIndex < 0) return null

  const main = normalized.slice(0, markerIndex).trim()
  const outlineBody = normalized.slice(markerIndex + OUTLINE_MARKER.length).trim()
  if (!outlineBody) return null

  const lines = outlineBody
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  const summary = lines[0] || '已生成文档大纲'

  return {
    main,
    summary,
    body: outlineBody,
  }
}

export function stripDocTaskMarkers(content) {
  return String(content || '').replace(DOC_TASK_MARKER_REGEX, '')
}

export function buildAssistantActionText(mainContent, outlineBody = '') {
  const main = String(mainContent || '').trim()
  const outline = String(outlineBody || '').trim()
  if (!main) return outline
  if (!outline) return main
  if (main === outline || main.includes(outline)) return main
  if (outline.includes(main)) return outline
  return `${main}\n\n${outline}`
}
