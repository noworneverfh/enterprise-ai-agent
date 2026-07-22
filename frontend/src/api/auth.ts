import { requestJson, setAuthToken } from '../api';
import type { CurrentUser, LoginResponse } from '../types';

export function login(username: string, password: string): Promise<LoginResponse> {
  return requestJson<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function register(
  username: string,
  password: string,
): Promise<CurrentUser> {
  return requestJson<CurrentUser>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function fetchCurrentUser(): Promise<CurrentUser> {
  return requestJson<CurrentUser>('/auth/me');
}

export async function loginAndStoreToken(
  username: string,
  password: string,
): Promise<CurrentUser> {
  const token = await login(username, password);
  setAuthToken(token.access_token);
  return fetchCurrentUser();
}
