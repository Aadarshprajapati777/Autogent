const baseUrl =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/**
 * Server-side api helper. Uses the Clerk session token from the request
 * to authenticate against the backend.
 */
export async function apiServer<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Request failed: ${response.status}`);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

/**
 * Client-side api helper. Reads the JWT from localStorage (set after login
 * or Clerk bootstrap). For Clerk flows, the token is stored by the
 * auth-provider after calling /auth/bootstrap.
 */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token =
    typeof window !== "undefined"
      ? window.localStorage.getItem("autogent_token")
      : null;
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Request failed: ${response.status}`);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export { baseUrl };
