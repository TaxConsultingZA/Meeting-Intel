// Process-local guard for synthetic Next acceptance; no shared env or remote fetch.
const fs = require('node:fs');
const read = fs.readFileSync;
fs.readFileSync = function(file, options) {
  if (typeof file === 'string' && /[\\/]\.env(?:\.[^\\/]*)?$/.test(file)) return typeof options === 'string' || options?.encoding ? '' : Buffer.alloc(0);
  return read.apply(this, arguments);
};
const local = value => { const u = new URL(typeof value === 'string' || value instanceof URL ? value : value.url); return ['127.0.0.1','localhost','[::1]'].includes(u.hostname); };
const originalFetch = global.fetch;
global.fetch = function(input, ...rest) { if (!local(input)) throw new Error('External fetch forbidden during synthetic acceptance'); return originalFetch.call(this,input,...rest); };
for (const protocol of ['node:http','node:https']) {
 const api = require(protocol);
 for (const key of ['request','get']) {
   const original = api[key];
   api[key] = function(input,...rest) {
     const host = typeof input === 'string' || input instanceof URL ? new URL(input).hostname : input?.hostname || input?.host || 'localhost';
     if (!['127.0.0.1','localhost','::1'].includes(host)) throw new Error('External HTTP forbidden during synthetic acceptance');
     return original.call(this,input,...rest);
   };
 }
}
