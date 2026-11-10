let csrf = '';
export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin', ...options,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, ...options.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    const error = new Error(Array.isArray(detail) ? detail.map(item => `${item.field}: ${item.message}`).join('\n') : detail || 'Request failed. Please try again.');
    error.status = response.status;
    throw error;
  }
  if (body.csrf) csrf = body.csrf;
  return body;
}
