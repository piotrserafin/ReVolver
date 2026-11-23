'use strict';
// 401 handling for status GETs: refresh once, retry once, share one refresh.

var test = require('node:test');
var assert = require('node:assert');
var h = require('./harness');

function lambdaOk() {
  return [200, JSON.stringify({ access_token: 'NEW', refresh_token: 'RT2', expires_in: 300, vcc_api_key: 'K' })];
}

function getsByUrl(s) {
  var by = {};
  s.reqs.filter(function (r) { return r.method === 'GET'; }).forEach(function (r) {
    (by[r.url] = by[r.url] || []).push(r.auth);
  });
  return by;
}

// Old token rejected, new token accepted.
function rejectOld(s) {
  return function (x) {
    if (x.method === 'POST') return lambdaOk();
    var mine = s.reqs.filter(function (r) { return r.url === x.url; });
    return mine[mine.length - 1].auth === 'Bearer OLD' ? [401, '{}'] : [200, '{"data":{}}'];
  };
}

test('401 → refresh, then retry with the new token', function () {
  var s = h.load({ store: h.loggedIn() });
  s.handler = rejectOld(s);
  return s.fire('ready').then(function () {
    var by = getsByUrl(s);
    // GETs started after the refresh use the new token right away.
    var rejected = Object.keys(by).filter(function (u) { return by[u][0] === 'Bearer OLD'; });
    assert.ok(rejected.length > 0, 'no GET hit the old token');
    rejected.forEach(function (u) { assert.deepStrictEqual(by[u], ['Bearer OLD', 'Bearer NEW'], u); });
    Object.keys(by).forEach(function (u) { assert.strictEqual(by[u][by[u].length - 1], 'Bearer NEW', u); });
  });
});

test('parallel 401s share one refresh', function () {
  var s = h.load({ store: h.loggedIn() });
  s.handler = rejectOld(s);
  return s.fire('ready').then(function () {
    var posts = s.reqs.filter(function (r) { return r.method === 'POST'; });
    assert.strictEqual(posts.length, 1);
  });
});

test('still 401 after refresh → no endless retry', function () {
  var s = h.load({
    store: h.loggedIn(),
    handler: function (x) { return x.method === 'POST' ? lambdaOk() : [401, '{}']; }
  });
  return s.fire('ready').then(function () {
    var by = getsByUrl(s);
    Object.keys(by).forEach(function (u) { assert.ok(by[u].length <= 2, u + ' ' + by[u].length); });
  });
});

test('failed refresh → no retry', function () {
  var s = h.load({
    store: h.loggedIn(),
    handler: function (x) { return x.method === 'POST' ? [400, '{}'] : [401, '{}']; }
  });
  return s.fire('ready').then(function () {
    var by = getsByUrl(s);
    Object.keys(by).forEach(function (u) { assert.strictEqual(by[u].length, 1, u); });
  });
});
