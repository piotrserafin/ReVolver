'use strict';
// After a command: expected state at once, confirm via one endpoint, invokeStatus failures.

var test = require('node:test');
var assert = require('node:assert');
var h = require('./harness');

var VIN = 'YV1ABCDEFGH123456';

function lockResp(value, ts) {
  return JSON.stringify({ data: { centralLock: { value: value, timestamp: new Date(ts).toISOString() } } });
}

// Car reported UNLOCKED long ago; Volvo keeps returning that until `fresh` is set.
function car(state) {
  return function (x) {
    if (x.method === 'POST') return [200, JSON.stringify({ data: { invokeStatus: state.invoke || 'COMPLETED' } })];
    if (/\/doors$/.test(x.url)) return [200, state.fresh ? lockResp('LOCKED', Date.now()) : lockResp('UNLOCKED', Date.now() - 3600e3)];
    return [200, '{"data":{}}'];
  };
}

function statuses(s) {
  return s.sent.filter(function (m) { return 'CAR_STATUS' in m; }).map(function (m) { return m.CAR_STATUS.split('|')[0]; });
}

function doorGets(s) {
  return s.reqs.filter(function (r) { return /\/doors$/.test(r.url); }).length;
}

function setup(t, state) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: Date.now() });
  var s = h.load({ store: h.loggedIn({ revolver_vin: VIN }), handler: car(state) });
  return s.fire('ready').then(function () { return s; });
}

function advance(t, s, ms) {
  t.mock.timers.tick(ms);
  return s.fire('appmessage', { payload: {} }); // no command: just lets XHR callbacks run
}

test('lock: shows Locked at once, keeps it while Volvo still reports the old state', function (t) {
  var state = {};
  var s;
  return setup(t, state).then(function (x) {
    s = x;
    assert.deepStrictEqual(statuses(s), ['Unlocked']);
    s.sent.length = 0;
    return s.fire('appmessage', { payload: { COMMAND: 'lock' } });
  }).then(function () {
    assert.ok(s.sent.some(function (m) { return m.COMMAND_RESULT === '+Locked!'; }));
    assert.deepStrictEqual(statuses(s), ['Locked']);
    var before = doorGets(s);
    return advance(t, s, 3000).then(function () {
      assert.strictEqual(doorGets(s), before + 1, 'one /doors check at 3 s');
      assert.ok(statuses(s).every(function (v) { return v === 'Locked'; }), statuses(s).join());
    });
  }).then(function () {
    state.fresh = true;
    return advance(t, s, 3000);
  }).then(function () {
    // Confirmed at 6 s → full refresh shows Volvo's value, no more checks
    assert.strictEqual(statuses(s)[statuses(s).length - 1], 'Locked');
    var n = doorGets(s);
    return advance(t, s, 60000).then(function () { assert.strictEqual(doorGets(s), n); });
  });
});

test('a newer report with the old value does not confirm', function (t) {
  var s;
  var state = {};
  return setup(t, state).then(function (x) {
    s = x;
    s.handler = function (req) {
      // The car reports right after the command, doors still unlocked
      if (/\/doors$/.test(req.url)) return [200, lockResp('UNLOCKED', Date.now())];
      return car(state)(req);
    };
    s.sent.length = 0;
    return s.fire('appmessage', { payload: { COMMAND: 'lock' } });
  }).then(function () {
    return advance(t, s, 3000);
  }).then(function () {
    assert.ok(statuses(s).every(function (v) { return v === 'Locked'; }), statuses(s).join());
  });
});

test('no earlier status: full refresh with the expected value', function (t) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: Date.now() });
  // Not logged in at launch → no status loaded; then tokens arrive and a command is sent
  var s = h.load({ store: { revolver_vin: VIN }, handler: car({}) });
  return s.fire('ready').then(function () {
    Object.assign(s.store, h.loggedIn({ revolver_vin: VIN }));
    s.sent.length = 0;
    return s.fire('appmessage', { payload: { COMMAND: 'lock' } });
  }).then(function () {
    assert.deepStrictEqual(statuses(s), ['Locked']);
  });
});

test('never confirmed: gives up after 60 s and shows what Volvo reports', function (t) {
  var s;
  return setup(t, {}).then(function (x) {
    s = x;
    return s.fire('appmessage', { payload: { COMMAND: 'lock' } });
  }).then(function () {
    var p = Promise.resolve();
    [3000, 3000, 4000, 5000, 10000, 15000, 20000].forEach(function (ms) {
      p = p.then(function () { return advance(t, s, ms); });
    });
    return p;
  }).then(function () {
    assert.strictEqual(statuses(s)[statuses(s).length - 1], 'Unlocked');
    // 7 checks + 1 final refresh + 1 at launch
    assert.strictEqual(doorGets(s), 9);
  });
});

test('HTTP 200 with a failed invokeStatus is an error, not "Locked!"', function (t) {
  var s;
  return setup(t, { invoke: 'UNABLE_TO_LOCK_DOOR_OPEN' }).then(function (x) {
    s = x;
    s.sent.length = 0;
    return s.fire('appmessage', { payload: { COMMAND: 'lock' } });
  }).then(function () {
    assert.ok(s.sent.some(function (m) { return m.COMMAND_RESULT === '-Door open'; }), JSON.stringify(s.sent));
    assert.ok(statuses(s).every(function (v) { return v === 'Unlocked'; }), statuses(s).join());
  });
});

test('flash: no expected state, one normal refresh', function (t) {
  var s;
  return setup(t, {}).then(function (x) {
    s = x;
    var n = doorGets(s);
    return s.fire('appmessage', { payload: { COMMAND: 'flash' } }).then(function () {
      assert.strictEqual(doorGets(s), n + 1);
      return advance(t, s, 60000);
    }).then(function () {
      assert.strictEqual(doorGets(s), n + 1);
    });
  });
});
