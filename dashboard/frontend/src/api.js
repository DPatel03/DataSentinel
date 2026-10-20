const API_BASE = import.meta.env.VITE_API_URL || "/api";
const TOKEN_KEY = "ds_dashboard_token";

function currentToken() {
  return (
    localStorage.getItem(TOKEN_KEY) ||
    import.meta.env.VITE_DASHBOARD_TOKEN ||
    ""
  );
}

export function setAuthToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function fetchApi(path, options = {}) {
  const token = currentToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    const err = new Error("Unauthorized");
    err.status = 401;
    throw err;
  }
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  if (res.status === 204) return null;
  return res.json();
}
