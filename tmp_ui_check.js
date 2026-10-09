
const state = { collections: [], documents: [], page: 1, history: [], currentDocument: null };
const $ = id => document.getElementById(id);

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[c]));
}

function updateContextLabel() {
  const release = $('release').value || 'Latest release';
  const source = $('source').value || 'All sources';
  const collection = $('collection').value || 'All collections';
  $('context').textContent = `${release} · ${source} · ${collection}`;
}

function renderCollections() {
  const filter = $('collection-filter').value.toLowerCase();
  const source = $('source').value;
  const visible = state.collections.filter(item =>
    (source === 'All sources' || item.source === source) &&
    (!filter || item.name.toLowerCase().includes(filter))
  );

  $('collections').innerHTML = visible.length
    ? '<strong>Available collections</strong><ul class="collection-list">' + visible.map(item => `<li>${esc(item.name)}<small>${Number(item.document_count || 0).toLocaleString()} documents · ${Number(item.chunk_count || 0).toLocaleString()} chunks</small></li>`).join('') + '</ul>'
    : '<span class="status">No collections match the selected filters.</span>';

  $('collection').innerHTML = '<option value="">All collections</option>' + visible.map(item => `<option value="${esc(item.name)}">${esc(item.name)}</option>`).join('');
  $('control-status').textContent = `${visible.length} collection(s) available`;
  updateContextLabel();
}

function renderResults() {
  const pageSize = 20;
  const start = (state.page - 1) * pageSize;
  const rows = state.documents.slice(start, start + pageSize);

  $('results').innerHTML = rows.length
    ? '<table class="result-table"><thead><tr><th>#</th><th>Document</th><th>Source</th><th>Preview</th></tr></thead><tbody>' + rows.map((doc, index) => `<tr><td>${start + index + 1}</td><td><button class="document-link" type="button" data-id="${esc(doc.document_id)}">${esc(doc.title)}</button></td><td>${esc(doc.document_id)}</td><td>${esc(doc.excerpt.slice(0, 220))}</td></tr>`).join('') + '</tbody></table>'
    : '<span class="status">Search for a Salesforce topic to see documents.</span>';

  const totalPages = Math.max(1, Math.ceil(state.documents.length / pageSize));
  $('page-status').textContent = `Page ${state.page} of ${totalPages}`;
  $('previous').disabled = state.page <= 1;
  $('next').disabled = state.page >= totalPages;

  document.querySelectorAll('.document-link').forEach(button => {
    button.addEventListener('click', async () => {
      await fetchDocument(button.dataset.id);
    });
  });
}

async function fetchDocument(documentId) {
  if (!documentId) return;

  try {
    const body = await request('/api/fetch', {
      method: 'POST',
      body: JSON.stringify({ document_id: documentId })
    });

    const doc = body.document;
    state.currentDocument = doc;

    if (!doc) {
      $('article').innerHTML = '<span class="status">No document content was returned.</span>';
      return;
    }

    $('article').innerHTML = '<h3>' + esc(doc.title) + '</h3><p class="status">' + esc(doc.document_id) + '</p><div class="article-body">' + esc(doc.excerpt || '').replace(/\n/g, '<br>') + '</div>' + (doc.url ? '<p><a href="' + esc(doc.url) + '" target="_blank" rel="noreferrer">Open source</a></p>' : '');
  } catch (error) {
    $('article').innerHTML = '<span class="status">Unable to fetch document: ' + esc(error.message) + '</span>';
  }
}

async function refreshCollections() {
  try {
    const data = await request('/api/collections');
    const collections = Array.isArray(data.collections) ? data.collections : [];
    state.collections = collections;

    const source = $('source');
    const sourceValues = ['All sources', ...new Set(collections.map(item => item.source).filter(Boolean))].sort();
    source.innerHTML = sourceValues.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
    source.value = source.value && sourceValues.includes(source.value) ? source.value : 'All sources';

    renderCollections();
  } catch (error) {
    $('control-status').textContent = 'Could not load collections: ' + error.message;
  }
}

async function searchDocuments() {
  const query = $('query').value.trim();
  const release = $('release').value;
  const collection = $('collection').value || undefined;

  if (!query) {
    $('search-status').textContent = 'Enter a Salesforce topic to search.';
    return;
  }

  try {
    $('search-status').textContent = 'Searching…';
    const body = await request('/api/search', {
      method: 'POST',
      body: JSON.stringify({ query, release, collection })
    });

    state.documents = Array.isArray(body.documents) ? body.documents : [];
    state.page = 1;
    renderResults();
    $('search-status').textContent = `${state.documents.length} result(s) found.`;
    $('article').innerHTML = '<span class="status">Select a document above to fetch its original content.</span>';
  } catch (error) {
    $('search-status').textContent = 'Search failed: ' + error.message;
  }
}

function appendChat(role, text) {
  const chatLog = $('chat-log');
  const item = document.createElement('div');
  item.className = `message ${role}`;
  item.textContent = text;
  chatLog.appendChild(item);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function submitChat(event) {
  event.preventDefault();

  const question = $('chat-input').value.trim();
  if (!question) return;

  appendChat('user', question);
  $('chat-input').value = '';

  const history = state.history.slice(-8).concat([{ role: 'user', content: question }]);

  try {
    const body = await request('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        question,
        release: $('release').value,
        history,
        collection: $('collection').value || undefined
      })
    });

    state.history = history.concat([{ role: 'assistant', content: body.answer }]);
    appendChat('assistant', body.answer);

    const sourcePanel = $('sources');
    sourcePanel.innerHTML = body.sources && body.sources.length
      ? '<strong>Chat sources</strong>' + body.sources.map(item => `<p><a href="${esc(item.url || '#')}" target="_blank" rel="noreferrer">${esc(item.title)}</a></p>`).join('')
      : '<strong>Chat sources</strong><p class="status">No sources were returned.</p>';
  } catch (error) {
    appendChat('assistant', 'I could not answer that right now: ' + error.message);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  $('refresh').addEventListener('click', refreshCollections);
  $('search').addEventListener('click', searchDocuments);
  $('previous').addEventListener('click', () => {
    if (state.page > 1) {
      state.page -= 1;
      renderResults();
    }
  });
  $('next').addEventListener('click', () => {
    const maxPages = Math.max(1, Math.ceil(state.documents.length / 20));
    if (state.page < maxPages) {
      state.page += 1;
      renderResults();
    }
  });
  $('source').addEventListener('change', () => {
    renderCollections();
    updateContextLabel();
  });
  $('collection-filter').addEventListener('input', renderCollections);
  $('release').addEventListener('change', updateContextLabel);
  $('collection').addEventListener('change', updateContextLabel);
  $('chat-form').addEventListener('submit', submitChat);

  refreshCollections();
  updateContextLabel();
});
