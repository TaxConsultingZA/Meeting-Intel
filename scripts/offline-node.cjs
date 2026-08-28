/* Test/build preload only. Never use this for the deployed application.
 * Inherited through NODE_OPTIONS by Node build workers. Local IPC is allowed;
 * TCP, TLS, DNS, UDP and unmocked fetch are rejected before any connection.
 */
const net = require('node:net');
const tls = require('node:tls');
const dns = require('node:dns');
const dgram = require('node:dgram');

function deny() {
  throw new Error('Offline validation prohibits real network access; mock the transport');
}

const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const first = Array.isArray(args[0]) ? args[0][0] : args[0];
  const pipe = (typeof first === 'object' && first !== null && first.path && !first.port)
    || (typeof first === 'string' && !/^\d+$/.test(first));
  if (pipe) return connect.apply(this, args);
  return deny();
};
tls.connect = deny;
dgram.Socket.prototype.send = deny;
dgram.Socket.prototype.connect = deny;
for (const target of [dns, dns.promises]) {
  for (const name of Object.keys(target)) {
    if (/^(lookup|resolve|reverse)/.test(name) && typeof target[name] === 'function') target[name] = deny;
  }
}
globalThis.fetch = deny;
require('node:module').syncBuiltinESMExports();

Object.assign(process.env, {
  NEXT_TELEMETRY_DISABLED: '1',
  DATABASE_URL: 'postgresql://offline:offline@127.0.0.1:1/offline_tests',
  AUTH_SECRET: 'offline-build-placeholder-not-a-real-secret',
  AUTH_MICROSOFT_ENTRA_ID_ID: 'offline-client',
  AUTH_MICROSOFT_ENTRA_ID_SECRET: 'offline-secret',
  AUTH_MICROSOFT_ENTRA_ID_TENANT_ID: 'offline-tenant',
  AUTH_MICROSOFT_ENTRA_ID_API_ID: 'offline-api',
  AUTH_URL: 'http://localhost:3000',
  NEXT_PUBLIC_API_URL: 'http://127.0.0.1:1',
  EMAILS_ENABLED: 'false',
  ENABLE_AUTO_RECONCILE: 'false',
  GEMINI_ENABLED: 'false',
  GEMINI_API_KEY: '',
  ASSEMBLYAI_API_KEY: '',
});
