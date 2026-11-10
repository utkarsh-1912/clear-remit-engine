export async function api(path, options) {
  const response = await fetch(`/api${path}`, options);
  const isJson = response.headers.get('content-type')?.includes('application/json');
  const body = isJson ? await response.json() : await response.text();
  if (response.ok) return body;
  const detail = body?.detail ?? body;
  const message = Array.isArray(detail)
    ? detail.map(({ loc, msg }) => `${loc.slice(1).join('.') || 'Request'} — ${msg}`).join('\n')
    : detail;
  const error = new Error(typeof message === 'string' && message ? message : `Request failed (${response.status}).`);
  error.status = response.status;
  throw error;
}

export function post(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function money(value, currency) {
  return new Intl.NumberFormat(undefined, {
    style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(value);
}

export function timestamp(value) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export function humanize(value) {
  return value.toLowerCase().replaceAll('_', ' ');
}
