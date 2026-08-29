import { auth } from "../firebase";

const BROKER_URL = import.meta.env.VITE_BROKER_URL as string;

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/**
 * The only place that talks to the broker (plan Key Decision #6 /
 * web/src/api/queries.ts contract). Attaches the current user's Firebase ID
 * token and retries exactly once on a 401 with a force-refreshed token --
 * covers the case where the cached token expired between renders but the
 * user is still signed in, without masking a genuine auth failure behind
 * infinite retries.
 */
export async function authedFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const doFetch = async (forceRefresh: boolean): Promise<Response> => {
    const user = auth?.currentUser;
    if (!user) {
      throw new ApiError(401, null, "not signed in");
    }
    const token = await user.getIdToken(forceRefresh);
    return fetch(`${BROKER_URL}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
        Authorization: `Bearer ${token}`,
      },
    });
  };

  let response = await doFetch(false);
  if (response.status === 401) {
    response = await doFetch(true);
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      (body && typeof body === "object" && "error" in body && String((body as { error: unknown }).error)) ||
      `request failed with status ${response.status}`;
    throw new ApiError(response.status, body, message);
  }
  return body;
}
