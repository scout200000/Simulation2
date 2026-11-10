const AUTH_KEY = "simulation2.auth";

function readSession(store) {
  try {
    const raw = store.getItem(AUTH_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function getAuthSession() {
  return readSession(localStorage) || readSession(sessionStorage);
}

export function isAuthenticated() {
  return Boolean(getAuthSession()?.account);
}

export function signIn(account, remember = false) {
  const session = {
    account: account.trim(),
    signedInAt: new Date().toISOString()
  };

  localStorage.removeItem(AUTH_KEY);
  sessionStorage.removeItem(AUTH_KEY);
  const store = remember ? localStorage : sessionStorage;
  store.setItem(AUTH_KEY, JSON.stringify(session));
  return session;
}

export function signOut() {
  localStorage.removeItem(AUTH_KEY);
  sessionStorage.removeItem(AUTH_KEY);
}
