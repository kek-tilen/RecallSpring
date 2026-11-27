/**
 * Passkeys in the browser (docs/08 -> Passkeys): navigator.credentials directly, no extra package. The server sends
 * WebAuthn options as JSON (base64url for binary fields) and checks the answer; nothing here is trusted by it.
 */

type Json = Record<string, unknown>;

export function b64urlToBytes(text: string): ArrayBuffer {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4);
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

export function bytesToB64url(buf: ArrayBuffer | ArrayBufferView): string {
  const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  let raw = "";
  for (const b of bytes) raw += String.fromCharCode(b);
  return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Whether this browser can use passkeys at all. */
export function passkeysSupported(): boolean {
  return typeof window !== "undefined" && typeof window.PublicKeyCredential === "function" && !!navigator.credentials;
}

/** Passkeys never work on an IP address (WebAuthn needs a name such as localhost). */
export function onIpAddress(host = window.location.hostname): boolean {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.includes(":") || host.startsWith("[");
}

/** Whether passkeys work at this address: localhost (or <name>.localhost), or the remote address. */
export function passkeyAddress(remoteHost: string | null, host = window.location.hostname): boolean {
  const h = host.toLowerCase();
  return h === "localhost" || h.endsWith(".localhost") || (!!remoteHost && h === remoteHost.toLowerCase());
}

/** The same page at localhost, for the note on 127.0.0.1. */
export function localhostUrl(loc: Location = window.location): string {
  return `${loc.protocol}//localhost${loc.port ? `:${loc.port}` : ""}${loc.pathname}${loc.search}`;
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(list)) return undefined;
  return list.map((d: Json) => ({ ...(d as object), id: b64urlToBytes(String(d.id)) }) as PublicKeyCredentialDescriptor);
}

export function creationOptions(o: Json): PublicKeyCredentialCreationOptions {
  const user = o.user as Json;
  return {
    ...(o as object),
    challenge: b64urlToBytes(String(o.challenge)),
    user: { ...(user as object), id: b64urlToBytes(String(user.id)) },
    excludeCredentials: descriptors(o.excludeCredentials),
  } as PublicKeyCredentialCreationOptions;
}

export function requestOptions(o: Json): PublicKeyCredentialRequestOptions {
  return {
    ...(o as object),
    challenge: b64urlToBytes(String(o.challenge)),
    allowCredentials: descriptors(o.allowCredentials),
  } as PublicKeyCredentialRequestOptions;
}

/** The credential as the JSON the server expects (what PublicKeyCredential.toJSON() gives in newer browsers). */
export function credentialJson(cred: PublicKeyCredential): Json {
  const r = cred.response as AuthenticatorAttestationResponse & AuthenticatorAssertionResponse;
  const response: Json = { clientDataJSON: bytesToB64url(r.clientDataJSON) };
  if ("attestationObject" in r && r.attestationObject) {
    response.attestationObject = bytesToB64url(r.attestationObject);
    response.transports = typeof r.getTransports === "function" ? r.getTransports() : [];
  } else {
    response.authenticatorData = bytesToB64url(r.authenticatorData);
    response.signature = bytesToB64url(r.signature);
    if (r.userHandle) response.userHandle = bytesToB64url(r.userHandle);
  }
  return {
    id: cred.id,
    rawId: bytesToB64url(cred.rawId),
    type: cred.type,
    response,
    authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
    clientExtensionResults: cred.getClientExtensionResults?.() ?? {},
  };
}

export async function createPasskey(options: Json): Promise<Json> {
  const cred = (await navigator.credentials.create({ publicKey: creationOptions(options) })) as PublicKeyCredential | null;
  if (!cred) throw new DOMException("No passkey was made.", "NotAllowedError");
  return credentialJson(cred);
}

export async function getPasskey(options: Json, conditional?: AbortSignal): Promise<Json> {
  const cred = (await navigator.credentials.get({
    publicKey: requestOptions(options),
    ...(conditional ? { mediation: "conditional" as CredentialMediationRequirement, signal: conditional } : {}),
  })) as PublicKeyCredential | null;
  if (!cred) throw new DOMException("No passkey was chosen.", "NotAllowedError");
  return credentialJson(cred);
}

export async function autofillAvailable(): Promise<boolean> {
  const pkc = window.PublicKeyCredential as unknown as { isConditionalMediationAvailable?: () => Promise<boolean> };
  try {
    return passkeysSupported() && typeof pkc.isConditionalMediationAvailable === "function" && (await pkc.isConditionalMediationAvailable());
  } catch {
    return false;
  }
}

/** One plain line for a browser-side failure (the server's own errors carry their message). */
export function browserError(e: unknown): Error {
  if (e instanceof DOMException) {
    if (e.name === "NotAllowedError" || e.name === "AbortError") return new Error("The passkey prompt was cancelled or timed out.");
    if (e.name === "InvalidStateError") return new Error("This device already has a passkey for RecallSpring at this address.");
    if (e.name === "SecurityError") return new Error("Passkeys do not work at this address.");
    return new Error("The browser could not use a passkey here.");
  }
  return e instanceof Error ? e : new Error("Something went wrong.");
}
