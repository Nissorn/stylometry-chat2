function trimTrailingSlash(url) {
  return String(url || '').replace(/\/+$/, '');
}

function detectDefaultHost() {
  if (typeof window === 'undefined') {
    return 'localhost';
  }
  return window.location.hostname || 'localhost';
}

function detectProtocols() {
  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
  return {
    httpProtocol: isHttps ? 'https' : 'http',
    wsProtocol: isHttps ? 'wss' : 'ws'
  };
}

export function getApiBaseUrl() {
  const envValue = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE;
  if (envValue) {
    return trimTrailingSlash(envValue);
  }

  const host = detectDefaultHost();
  const { httpProtocol } = detectProtocols();
  return `${httpProtocol}://${host}:8000`;
}

export function getWsBaseUrl() {
  const envValue = import.meta.env.VITE_WS_BASE_URL || import.meta.env.VITE_WS_BASE;
  if (envValue) {
    return trimTrailingSlash(envValue);
  }

  const host = detectDefaultHost();
  const { wsProtocol } = detectProtocols();
  return `${wsProtocol}://${host}:8000`;
}
