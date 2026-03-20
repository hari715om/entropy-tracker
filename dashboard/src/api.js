/**
 * API client — fetches data from the Entropy FastAPI backend.
 */

const API_BASE = '/api';

async function fetchJSON(url, options = {}) {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function getRepos() {
  return fetchJSON('/repos');
}

export async function getRepoById(id) {
  return fetchJSON(`/repos/${id}`);
}

export async function getModules(repoId, { top, severity } = {}) {
  const params = new URLSearchParams();
  if (top) params.set('top', top);
  if (severity) params.set('severity', severity);
  const qs = params.toString();
  return fetchJSON(`/repos/${repoId}/modules${qs ? `?${qs}` : ''}`);
}

export async function getModuleDetail(repoId, modulePath) {
  return fetchJSON(`/repos/${repoId}/modules/${modulePath}`);
}

export async function getAlerts(repoId) {
  return fetchJSON(`/repos/${repoId}/alerts`);
}

export async function getTrend(repoId, days = 90) {
  return fetchJSON(`/repos/${repoId}/trend?days=${days}`);
}

export async function triggerScan(repoId) {
  return fetchJSON(`/repos/${repoId}/scan`, { method: 'POST' });
}

export async function healthCheck() {
  return fetchJSON('/health');
}
