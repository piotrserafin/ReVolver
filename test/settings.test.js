'use strict';
// Clay settings → localStorage and watch messages; cached command bitmask.

var test = require('node:test');
var assert = require('node:assert');
var h = require('./harness');

var K = h.MESSAGE_KEYS;

function closeSettings(s, settings) {
  s.setSettings(settings);
  s.sent.length = 0;
  return s.fire('webviewclosed', { response: encodeURIComponent('x') }, 6);
}

test('VIN from numeric key with {value}; VIN change clears car cache', function () {
  var s = h.load({ store: h.loggedIn({ revolver_car_info: 'XC60' }) });
  var settings = {};
  settings[K.VIN] = { value: 'VIN2' };
  return closeSettings(s, settings).then(function () {
    assert.strictEqual(s.store.revolver_vin, 'VIN2');
    assert.ok(!('revolver_car_info' in s.store));
  });
});

test('no VIN in settings keeps the stored VIN', function () {
  var s = h.load({ store: h.loggedIn() });
  return closeSettings(s, { VIBRATE: true }).then(function () {
    assert.strictEqual(s.store.revolver_vin, 'VIN1');
  });
});

test('vibrate: wrapped false → 0, plain true → 1', function () {
  var s = h.load({ store: h.loggedIn() });
  var off = {};
  off[K.VIBRATE] = { value: false };
  return closeSettings(s, off).then(function () {
    assert.ok(s.sent.some(function (m) { return m.VIBRATE === 0; }), JSON.stringify(s.sent));
    return closeSettings(s, { VIBRATE: true });
  }).then(function () {
    assert.ok(s.sent.some(function (m) { return m.VIBRATE === 1; }), JSON.stringify(s.sent));
  });
});

test('quick action and exit flag sent to the watch', function () {
  var s = h.load({ store: h.loggedIn() });
  return closeSettings(s, { QUICK_ACTION: { value: 'lock' }, QUICK_EXIT: { value: true } }).then(function () {
    assert.ok(s.sent.some(function (m) { return m.QUICK_ACTION === 'lock' && m.QUICK_EXIT === 1; }), JSON.stringify(s.sent));
  });
});

test('cached commands → bitmask, unknown names ignored', function () {
  var s = h.load({ store: h.loggedIn({ revolver_commands: JSON.stringify(['flash', 'lock', 'lock-reduced-guard', 'engine-start', 'unknown']) }) });
  return s.fire('ready', undefined, 6).then(function () {
    assert.ok(s.sent.some(function (m) { return m.AVAILABLE_CMDS === (0x01 | 0x08 | 0x80 | 0x200); }),
      JSON.stringify(s.sent.filter(function (m) { return 'AVAILABLE_CMDS' in m; })));
  });
});
