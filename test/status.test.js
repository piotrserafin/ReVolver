'use strict';
// Car status sent to the watch on launch.

var test = require('node:test');
var assert = require('node:assert');
var h = require('./harness');

var FUEL = { data: { fuelAmount: { value: '28', unit: 'l' } } };

function launch(statistics) {
  var s = h.load({
    store: h.loggedIn({ revolver_energy_capable: 'false', revolver_commands: '["flash"]', revolver_car_info: 'XC60' }),
    handler: function (x) {
      if (/\/statistics$/.test(x.url)) return [200, JSON.stringify(statistics)];
      if (/\/fuel$/.test(x.url)) return [200, JSON.stringify(FUEL)];
      return [200, '{"data":{}}'];
    }
  });
  return s.fire('ready').then(function () {
    var msgs = s.sent.filter(function (m) { return m.CAR_STATUS; });
    return msgs.length ? msgs[msgs.length - 1].CAR_STATUS : '';
  });
}

test('fuel range from distanceToEmptyTank (current API)', function () {
  // Real /statistics response, 2026-11-18.
  return launch({ data: {
    averageFuelConsumption: { unit: 'l/100km', value: 11.8 },
    distanceToEmptyTank: { timestamp: '2026-11-18T15:48:06.046Z', unit: 'km', value: 240 },
    tripMeterManual: { unit: 'km', value: 3630 }
  } }).then(function (status) {
    assert.match(status, /\|28L\|240km\|/);
  });
});

test('fuel range from distanceToEmpty (published spec)', function () {
  return launch({ data: { distanceToEmpty: { unit: 'km', value: '512' } } }).then(function (status) {
    assert.match(status, /\|28L\|512km\|/);
  });
});

test('missing range shows ?', function () {
  return launch({ data: { averageSpeed: { value: 3 } } }).then(function (status) {
    assert.match(status, /\|28L\|\?\|/);
  });
});
