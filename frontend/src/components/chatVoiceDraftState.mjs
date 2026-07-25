export function createChatVoiceDraftState() {
  return {
    taskId: '',
    revisionId: 0,
    provisionalText: '',
    committedSentenceText: '',
    finalText: '',
    rawTranscript: '',
    status: '',
  }
}

function cloneVoiceDraft(voiceDraft) {
  return { ...createChatVoiceDraftState(), ...(voiceDraft || {}) }
}

export function buildStreamingAssistantText({ streamingText, voiceDraft }) {
  const draft = cloneVoiceDraft(voiceDraft)
  if (draft.finalText) return String(draft.finalText)
  const assembled = `${draft.committedSentenceText || ''}${draft.provisionalText || ''}`.trim()
  if (assembled) return assembled
  return String(streamingText || '')
}

export function applyVoiceChunk(voiceDraft, payload) {
  const next = cloneVoiceDraft(voiceDraft)
  const nextRevision = Number(payload?.revision_id || 0)
  if (nextRevision && nextRevision <= Number(next.revisionId || 0)) {
    return voiceDraft
  }

  next.taskId = String(payload?.task_id || next.taskId || '')
  next.revisionId = nextRevision || Number(next.revisionId || 0)
  next.status = String(payload?.stage || 'chunk')

  if (payload?.stage === 'sentence_fix') {
    next.committedSentenceText = String(payload?.text || next.committedSentenceText || '')
    next.provisionalText = ''
    return next
  }

  next.provisionalText = String(payload?.text || next.provisionalText || '')
  return next
}

export function applyVoiceDone(voiceDraft, payload) {
  const next = cloneVoiceDraft(voiceDraft)
  const nextRevision = Number(payload?.revision_id || 0)
  if (nextRevision && nextRevision <= Number(next.revisionId || 0)) {
    return voiceDraft
  }

  next.taskId = String(payload?.task_id || next.taskId || '')
  next.revisionId = nextRevision || Number(next.revisionId || 0)
  next.finalText = String(payload?.transcript || next.finalText || '')
  next.rawTranscript = String(payload?.raw_transcript || next.rawTranscript || '')
  next.provisionalText = ''
  next.committedSentenceText = String(next.finalText || next.committedSentenceText || '')
  next.status = String(payload?.status || 'completed')
  return next
}
