// docs_pipeline v3 — standalone frontend
const API_BASE = '/api/v1';

let appState = {
  phase: 'input',
  chapters: [],
  downloadInfo: null,
};

function $(id) { return document.getElementById(id); }

async function startGenerate() {
  const input = $('topic-input');
  const btn = $('btn-generate');
  const userInput = input.value.trim();

  if (userInput.length < 5) {
    input.style.borderColor = '#e04040';
    setTimeout(function () { input.style.borderColor = ''; }, 1500);
    return;
  }

  appState.phase = 'generating';
  appState.chapters = [];
  $('stage-input').classList.add('hidden');
  $('stage-generating').classList.remove('hidden');
  $('stage-done').classList.add('hidden');
  $('outline-card').classList.add('hidden');
  $('outline-card').innerHTML = '';
  $('content-stream').innerHTML = '';
  $('download-card').classList.add('hidden');
  $('progress-banner').textContent = '';
  $('progress-footer').textContent = '';
  btn.disabled = true;

  try {
    var response = await fetch(API_BASE + '/docs-pipeline/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_input: userInput }),
    });

    if (!response.ok) {
      var err = {};
      try { err = await response.json(); } catch (e) {}
      showFallback(err.detail || '服务繁忙，请稍后重试');
      return;
    }

    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    var currentEvent = '';

    while (true) {
      var chunk = await reader.read();
      if (chunk.done) break;

      buffer += decoder.decode(chunk.value, { stream: true });
      var lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        if (line.indexOf('event: ') === 0) {
          currentEvent = line.slice(7).trim();
        } else if (line.indexOf('data: ') === 0) {
          try {
            var data = JSON.parse(line.slice(6));
            handleEvent(currentEvent, data);
          } catch (e) {}
        }
      }
    }
  } catch (e) {
    showFallback('网络连接异常，请稍后重试');
  } finally {
    btn.disabled = false;
  }
}

function handleEvent(type, data) {
  switch (type) {
    case 'status':
      $('progress-banner').textContent = '\u{1F504} ' + data.message;
      break;
    case 'outline':
      renderOutline(data);
      break;
    case 'chapter':
      appState.chapters.push(data);
      renderChapter(data);
      var nextIdx = data.idx + 1 > data.total ? data.total : data.idx + 1;
      $('progress-footer').textContent = '正在生成第 ' + nextIdx + '/' + data.total + ' 章...';
      break;
    case 'retry':
      $('progress-banner').textContent = '\u{1F504} ' + data.message;
      break;
    case 'done':
      appState.phase = 'done';
      appState.downloadInfo = data;
      showDone(data);
      break;
    case 'fallback':
      appState.phase = 'fallback';
      showFallback(data.message);
      break;
  }
}

function renderOutline(data) {
  var card = $('outline-card');
  var html = '<h2>' + escapeHtml(data.title) + '</h2>';
  if (data.sections && data.sections.length) {
    for (var i = 0; i < data.sections.length; i++) {
      html += '<div class="section-item">' + escapeHtml(data.sections[i].heading) + '</div>';
    }
  }
  card.innerHTML = html;
  card.classList.remove('hidden');
}

function renderChapter(ch) {
  var stream = $('content-stream');
  var div = document.createElement('div');
  div.className = 'chapter-block' + (ch.fallback ? ' fallback' : '');
  div.id = 'chapter-' + ch.idx;

  var headingHtml = '<h3>' + escapeHtml(ch.heading);
  headingHtml += '<span class="chapter-progress">' + ch.idx + '/' + ch.total + '</span>';
  if (ch.fallback) {
    headingHtml += '<span class="fallback-badge">⚠ 需人工补充</span>';
  }
  headingHtml += '</h3>';

  var contentHtml = '<div class="chapter-content">' + simpleMarkdown(ch.content) + '</div>';
  if (ch.fallback) {
    contentHtml += '<div class="fallback-note">※ 本章因服务负载较高，已自动生成精简版本，建议人工补充完善</div>';
  }

  div.innerHTML = headingHtml + contentHtml;
  stream.appendChild(div);
  div.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function showDone(data) {
  $('stage-generating').classList.add('hidden');
  $('stage-done').classList.remove('hidden');

  var card = $('download-card');
  var sizeText = data.size ? formatSize(data.size) : '';
  var wordCount = 0;
  for (var i = 0; i < appState.chapters.length; i++) {
    if (appState.chapters[i].content) wordCount += appState.chapters[i].content.length;
  }

  var html = '<div class="icon">\u{1F4C4}</div>';
  html += '<div class="filename">' + escapeHtml(data.filename || 'document.docx') + '</div>';
  html += '<div class="meta">' + wordCount.toLocaleString() + ' 字';
  if (sizeText) html += ' · ' + sizeText;
  html += '</div>';

  if (data.download_url) {
    html += '<a class="btn-download" href="' + escapeHtml(data.download_url) + '" download>⬇ 下载文档</a>';
  } else {
    html += '<button class="btn-download disabled" disabled>下载暂不可用</button>';
    html += '<div class="fallback-msg">文档渲染暂不可用，请稍后重试</div>';
  }

  if (data.has_fallback) {
    html += '<div class="fallback-msg">※ 部分章节为精简版本，建议人工审核补充</div>';
  }

  card.innerHTML = html;
  card.classList.remove('hidden');
}

function showFallback(message) {
  $('stage-generating').classList.add('hidden');

  if (appState.chapters.length > 0) {
    $('stage-done').classList.remove('hidden');
    var card = $('download-card');
    card.innerHTML = '<div class="icon">⚠️</div>' +
      '<div class="filename">生成未完全成功</div>' +
      '<div class="meta">' + escapeHtml(message) + '</div>' +
      '<div class="fallback-msg">已生成的章节内容仍可在上方查看</div>';
    card.classList.remove('hidden');
  } else {
    $('stage-input').classList.remove('hidden');
    $('progress-banner').textContent = '⚠ ' + message;
    $('stage-generating').classList.remove('hidden');
    $('progress-footer').textContent = '';
  }
}

function escapeHtml(str) {
  var div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function simpleMarkdown(text) {
  if (!text) return '';
  var html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/<\/p><p>/g, '</p><p>');
  html = html.replace(/\n\n/g, '</p><p>');
  html = html.replace(/\n/g, '<br>');
  html = '<p>' + html + '</p>';
  return html;
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

document.addEventListener('DOMContentLoaded', function () {
  $('topic-input').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') startGenerate();
  });
});
