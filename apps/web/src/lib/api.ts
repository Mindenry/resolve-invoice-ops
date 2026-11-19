export const API_BASE = "/api/v1";

let accessToken: string | null = null;
let organizationId: string | null = localStorage.getItem("resolve-org");
let refreshPromise: Promise<boolean> | null = null;

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export function setOrganization(id: string | null) {
  organizationId = id;
  if (id) localStorage.setItem("resolve-org", id);
  else localStorage.removeItem("resolve-org");
}

export function getOrganization() {
  return organizationId;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  formData?: FormData;
  skipAuth?: boolean;
}

async function rawRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (accessToken && !options.skipAuth) headers.set("Authorization", `Bearer ${accessToken}`);
  if (organizationId) headers.set("X-Organization-Id", organizationId);
  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData;
  } else if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    body,
    credentials: "include",
  });
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
        });
        if (!response.ok) return false;
        const data = (await response.json()) as { access_token: string; organization: { id: string } };
        accessToken = data.access_token;
        if (data.organization?.id) setOrganization(data.organization.id);
        return true;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    if (!response.ok) throw new ApiError(response.status, "http_error", response.statusText);
    return (await response.text()) as unknown as T;
  }
  const payload = await response.json();
  if (!response.ok) {
    const error = payload?.error ?? {};
    throw new ApiError(
      response.status,
      error.code ?? "http_error",
      error.message ?? "The request failed.",
      error.details,
    );
  }
  return payload as T;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}, retried = false): Promise<T> {
  const response = await rawRequest(path, options);
  if (response.status === 401 && !retried && !options.skipAuth) {
    const refreshed = await tryRefresh();
    if (refreshed) return apiRequest<T>(path, options, true);
  }
  return parse<T>(response);
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => apiRequest<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(path: string, options?: RequestOptions) => apiRequest<T>(path, { ...options, method: "DELETE" }),
  upload: <T>(path: string, formData: FormData) =>
    apiRequest<T>(path, { method: "POST", formData }),
  refresh: tryRefresh,
};

export async function fetchBlob(path: string): Promise<Blob> {
  const response = await rawRequest(path, { method: "GET" });
  if (!response.ok) {
    let message = "Download failed";
    try {
      const payload = await response.json();
      message = payload?.error?.message ?? message;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, "download_failed", message);
  }
  return response.blob();
}

export function buildQuery(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "" || value === false) return;
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, String(item)));
    } else {
      search.append(key, String(value));
    }
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}
