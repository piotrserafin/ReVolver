var Clay = require('pebble-clay');
var clayConfig = require('./config.json');
var clay = new Clay(clayConfig, null, { autoHandleEvents: false });
var keys = require('message_keys');

// Auth Proxy
var LAMBDA_URL = 'https://tpl5qhrn75bxzps77pdqllhxuy0mckgw.lambda-url.eu-central-1.on.aws/';

// Connected Vehicle API
var VOLVO_API = 'https://api.volvocars.com/connected-vehicle/v2';

// Command registry (must match C COMMANDS[] bit flags)
var COMMANDS = {
  'flash':               { bit: 0x01, success: 'Flashed!' },
  'honk':                { bit: 0x02, success: 'Honked!' },
  'honk-flash':          { bit: 0x04, success: 'Honked!' },
  'lock':                { bit: 0x08, success: 'Locked!' },
  'unlock':              { bit: 0x10, success: 'Unlocked!' },
  'climatization-start': { bit: 0x20, success: 'Climate on!' },
  'climatization-stop':  { bit: 0x40, success: 'Climate off!' },
  'engine-start':        { bit: 0x80, success: 'Started!',
    body: function (p) { return JSON.stringify({ runtimeMinutes: parseInt(p, 10) }); }
  },
  'engine-stop':         { bit: 0x100, success: 'Stopped!' }
};

var STORE = {
  VIN: 'revolver_vin',
  ACCESS_TOKEN: 'revolver_access_token',
  REFRESH_TOKEN: 'revolver_refresh_token',
  EXPIRES_AT: 'revolver_expires_at',
  VCC_API_KEY: 'revolver_vcc_api_key',
  CAR_INFO: 'revolver_car_info',
  AVAILABLE_COMMANDS: 'revolver_commands'
};

// Storage

function get(key) {
  return localStorage.getItem(key) || '';
}

function set(key, val) {
  localStorage.setItem(key, val);
}

function clear(key) {
  localStorage.removeItem(key);
}

// HTTP Helper

function volvoGet(path, cb) {
  var req = new XMLHttpRequest();
  req.open('GET', VOLVO_API + path);
  req.setRequestHeader('Authorization', 'Bearer ' + get(STORE.ACCESS_TOKEN));
  req.setRequestHeader('vcc-api-key', get(STORE.VCC_API_KEY));
  req.onload = function () {
    if (req.status === 200) {
      try {
        cb(JSON.parse(req.responseText));
      } catch (e) {
        cb(null);
      }
    } else {
      cb(null);
    }
  };
  req.onerror = function () {
    cb(null);
  };
  req.send();
}

// Token Refresh

var refreshInFlight = false;
var refreshQueue = [];

function tokenExpired() {
  var token = get(STORE.ACCESS_TOKEN);
  if (!token) return false;
  if (!get(STORE.VCC_API_KEY)) return true;

  var expiresAt = parseInt(get(STORE.EXPIRES_AT), 10);
  if (!expiresAt) return true;

  return expiresAt - Math.floor(Date.now() / 1000) < 60;
}

function refreshToken(cb) {
  if (refreshInFlight) {
    if (cb) refreshQueue.push(cb);
    return;
  }

  var token = get(STORE.REFRESH_TOKEN);
  if (!token) {
    if (cb) cb(false);
    return;
  }

  refreshInFlight = true;
  if (cb) refreshQueue.push(cb);
  console.log('Refreshing with RT: ' + token.substring(0, 8) + '...');

  var req = new XMLHttpRequest();
  req.open('POST', LAMBDA_URL);
  req.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  req.onload = function () {
    refreshInFlight = false;
    var cbs = refreshQueue;
    refreshQueue = [];

    if (req.status === 200) {
      var data = JSON.parse(req.responseText);
      set(STORE.ACCESS_TOKEN, data.access_token);
      if (data.refresh_token) {
        set(STORE.REFRESH_TOKEN, data.refresh_token);
      } else {
        console.log('WARNING: No refresh_token in response!');
      }
      if (data.expires_in)
        set(STORE.EXPIRES_AT, String(Math.floor(Date.now() / 1000) + data.expires_in));
      if (data.vcc_api_key) set(STORE.VCC_API_KEY, data.vcc_api_key);
      console.log('Token refreshed. RT: ' + (data.refresh_token ? data.refresh_token.substring(0, 8) + '...' : 'NONE'));
      cbs.forEach(function (fn) {
        fn(true);
      });
    } else {
      console.log('Refresh failed: ' + req.status + ' ' + req.responseText);
      if (req.status === 400 || req.status === 401) {
        clear(STORE.ACCESS_TOKEN);
        clear(STORE.REFRESH_TOKEN);
        clear(STORE.EXPIRES_AT);
      }
      cbs.forEach(function (fn) {
        fn(false);
      });
    }
  };
  req.onerror = function () {
    refreshInFlight = false;
    var cbs = refreshQueue;
    refreshQueue = [];
    console.log('Refresh network error');
    cbs.forEach(function (fn) {
      fn(false);
    });
  };
  req.send('grant_type=refresh_token&refresh_token=' + encodeURIComponent(token));
}

// Message Queue

var msgQueue = [];
var msgSending = false;

function send(msg) {
  msgQueue.push(msg);
  pump();
}

function pump() {
  if (msgSending || msgQueue.length === 0) return;
  msgSending = true;
  var msg = msgQueue.shift();

  Pebble.sendAppMessage(
    msg,
    function () {
      msgSending = false;
      pump();
    },
    function () {
      msgSending = false;
      msgQueue.unshift(msg);
      setTimeout(pump, 200);
    }
  );
}

function sendStatus() {
  var vin = get(STORE.VIN);
  var token = get(STORE.ACCESS_TOKEN);

  var status = 'Open settings';
  if (vin && token) status = 'Ready';
  else if (token) status = 'Set VIN';
  else if (vin) status = 'Login needed';

  send({ VIN: vin || 'Not set', STATUS_MSG: status });

  // Send cached data
  var info = get(STORE.CAR_INFO);
  if (info) send({ CAR_INFO: info });

  var cachedCmds = get(STORE.AVAILABLE_COMMANDS);
  if (cachedCmds) {
    try {
      var mask = 0;
      JSON.parse(cachedCmds).forEach(function (cmd) {
        if (cmd in COMMANDS) mask |= COMMANDS[cmd].bit;
      });
      send({ AVAILABLE_CMDS: mask });
    } catch (e) {}
  }

  // Fetch live data if authenticated
  if (vin && token && get(STORE.VCC_API_KEY)) {
    fetchCommandAccessibility();
    if (!cachedCmds) fetchAvailableCommands();
    if (!info) fetchVehicleDetails();
    fetchCarStatus();
  }
}

function sendResult(text, ok) {
  send({ COMMAND_RESULT: (ok ? '+' : '-') + text });
}

// Data Fetchers

function fetchVehicleDetails() {
  var vin = get(STORE.VIN);
  volvoGet('/vehicles/' + vin, function (resp) {
    if (!resp) return;
    var data = resp.data || resp;
    var parts = [];
    if (data.descriptions && data.descriptions.model) parts.push(data.descriptions.model);
    if (data.modelYear) parts.push(String(data.modelYear));
    if (parts.length) {
      var str = parts.join(' ');
      set(STORE.CAR_INFO, str);
      send({ CAR_INFO: str });
    }
  });
}

function fetchAvailableCommands() {
  var vin = get(STORE.VIN);
  volvoGet('/vehicles/' + vin + '/commands', function (resp) {
    if (!resp) return;
    var cmds = (resp.data || []).map(function (c) {
      return c.command.toLowerCase().replace(/_/g, '-').replace('and-', '');
    });
    set(STORE.AVAILABLE_COMMANDS, JSON.stringify(cmds));
    console.log('Available commands: ' + cmds.join(', '));

    var mask = 0;
    cmds.forEach(function (cmd) {
      if (cmd in COMMANDS) mask |= COMMANDS[cmd].bit;
    });
    send({ AVAILABLE_CMDS: mask });
  });
}

function fetchCommandAccessibility() {
  var vin = get(STORE.VIN);
  volvoGet('/vehicles/' + vin + '/command-accessibility', function (resp) {
    if (!resp) {
      send({ STATUS_MSG: 'Ready' });
      return;
    }
    var status = (resp.data && resp.data.availabilityStatus) || resp.availabilityStatus;
    if (status && status.value) {
      console.log('Command accessibility: ' + status.value);
      var msg = 'Ready';
      if (status.value === 'AVAILABLE') msg = 'Ready';
      else if (status.value === 'UNAVAILABLE') msg = 'Driving';
      else if (status.value === 'UNSPECIFIED') msg = 'Ready';
      else msg = status.value;
      send({ STATUS_MSG: msg });
    } else {
      send({ STATUS_MSG: 'Ready' });
    }
  });
}

function fetchCarStatus() {
  var vin = get(STORE.VIN);
  var results = { lock: '?', engine: '?', fuel: '?', range: '?', windows: '?' };
  var pending = 5;

  function finish() {
    if (--pending > 0) return;
    // Format: "lock|engine|fuel|range|windows"
    var str = results.lock + '|' + results.engine + '|' + results.fuel + '|' +
              results.range + '|' + results.windows;
    send({ CAR_STATUS: str });
  }

  volvoGet('/vehicles/' + vin + '/doors', function (resp) {
    if (resp) {
      var lock = (resp.data && resp.data.centralLock) || resp.centralLock;
      if (lock && lock.value) {
        results.lock = lock.value === 'LOCKED' ? 'Locked' : 'Unlocked';
      }
    }
    finish();
  });

  volvoGet('/vehicles/' + vin + '/engine-status', function (resp) {
    if (resp) {
      var es = (resp.data && resp.data.engineStatus) || resp.engineStatus;
      if (es && es.value) {
        results.engine = es.value === 'RUNNING' ? 'Running' : 'Off';
      }
    }
    finish();
  });

  volvoGet('/vehicles/' + vin + '/fuel', function (resp) {
    if (resp) {
      var fuel = (resp.data && resp.data.fuelAmount) || resp.fuelAmount;
      if (fuel && fuel.value !== undefined) {
        results.fuel = Math.round(fuel.value) + 'L';
      }
    }
    finish();
  });

  volvoGet('/vehicles/' + vin + '/statistics', function (resp) {
    if (resp) {
      var data = resp.data || resp;
      var dte = data.distanceToEmptyTank || data.distanceToEmpty;
      if (dte && dte.value !== undefined) {
        results.range = Math.round(dte.value) + 'km';
      }
    }
    finish();
  });

  volvoGet('/vehicles/' + vin + '/windows', function (resp) {
    if (resp) {
      var data = resp.data || resp;
      var open = [];
      if (data.frontLeftWindow && data.frontLeftWindow.value === 'OPEN') open.push('FL');
      if (data.frontRightWindow && data.frontRightWindow.value === 'OPEN') open.push('FR');
      if (data.rearLeftWindow && data.rearLeftWindow.value === 'OPEN') open.push('BL');
      if (data.rearRightWindow && data.rearRightWindow.value === 'OPEN') open.push('BR');
      if (data.sunroof && data.sunroof.value === 'OPEN') open.push('RT');
      results.windows = open.length > 0 ? open.join(' ') : 'OK';
    }
    finish();
  });
}

// Command Execution

function isCommandAvailable(command) {
  var stored = get(STORE.AVAILABLE_COMMANDS);
  if (!stored) return true;
  try {
    var cmds = JSON.parse(stored);
    var check = command.indexOf(':') !== -1 ? command.split(':')[0] : command;
    return cmds.indexOf(check) !== -1;
  } catch (e) {
    return true;
  }
}

function executeCommand(command) {
  if (command === 'refresh') {
    var _rt = get(STORE.REFRESH_TOKEN);
    var _exp = parseInt(get(STORE.EXPIRES_AT), 10);
    var _now = Math.floor(Date.now() / 1000);
    var _remaining = isNaN(_exp) ? NaN : _exp - _now;
    var _needed = isNaN(_remaining) || _remaining < 60;
    console.log('Manual refresh. RT: ' + (_rt ? _rt.substring(0, 8) + '...' : 'NONE') +
      ' | Token ' + (isNaN(_remaining) ? 'N/A' : (_remaining > 0 ? 'valid (' + _remaining + 's left)' : 'EXPIRED (' + (-_remaining) + 's ago)')) +
      ' | Refresh ' + (_needed ? 'NEEDED' : 'not needed'));
    if (_needed && _rt) {
      refreshToken(function (ok) {
        if (ok) {
          fetchCommandAccessibility();
          fetchCarStatus();
        } else {
          send({ STATUS_MSG: 'Re-login needed' });
        }
      });
    } else {
      fetchCommandAccessibility();
      fetchCarStatus();
    }
    return;
  }

  var vin = get(STORE.VIN);
  if (!vin) {
    sendResult('No VIN set', false);
    return;
  }
  if (!get(STORE.ACCESS_TOKEN)) {
    sendResult('Not logged in', false);
    return;
  }
  if (!get(STORE.VCC_API_KEY)) {
    sendResult('No API key', false);
    return;
  }
  if (!isCommandAvailable(command)) {
    sendResult('Not supported', false);
    return;
  }

  if (tokenExpired()) {
    refreshToken(function (ok) {
      if (ok) callApi(command, false);
      else sendResult('Re-login needed', false);
    });
  } else {
    callApi(command, false);
  }
}

function callApi(command, isRetry) {
  // Parse "path:param" format for commands with body
  var apiPath = command;
  var body = '{}';
  var colonIdx = command.indexOf(':');
  if (colonIdx !== -1) {
    apiPath = command.substring(0, colonIdx);
    var param = command.substring(colonIdx + 1);
    if (COMMANDS[apiPath] && COMMANDS[apiPath].body) {
      body = COMMANDS[apiPath].body(param);
    }
  }

  var url = VOLVO_API + '/vehicles/' + get(STORE.VIN) + '/commands/' + apiPath;
  console.log('API: POST ' + url + ' body: ' + body);

  var req = new XMLHttpRequest();
  req.open('POST', url);
  req.setRequestHeader('Content-Type', 'application/json');
  req.setRequestHeader('Authorization', 'Bearer ' + get(STORE.ACCESS_TOKEN));
  req.setRequestHeader('vcc-api-key', get(STORE.VCC_API_KEY));
  req.onload = function () {
    console.log('API ' + req.status + ': ' + req.responseText);
    if (req.status >= 200 && req.status < 300) {
      var msg = (COMMANDS[apiPath] && COMMANDS[apiPath].success) || 'Done';
      sendResult(msg, true);
      fetchCarStatus();
    } else if (req.status === 401 && !isRetry) {
      refreshToken(function (ok) {
        if (ok) callApi(command, true);
        else sendResult('Re-login needed', false);
      });
    } else if (req.status === 404) {
      sendResult('Not supported', false);
    } else if (req.status === 409) {
      sendResult('Already done', false);
    } else if (req.status === 422) {
      sendResult('Car busy, try later', false);
    } else if (req.status === 403) {
      sendResult('Not authorized', false);
    } else if (req.status >= 500) {
      sendResult('Volvo server error', false);
    } else {
      sendResult('Error: ' + req.status, false);
    }
  };
  req.onerror = function () {
    sendResult('Network error', false);
  };
  req.send(body);
}

// Event Handlers

Pebble.addEventListener('ready', function () {
  console.log('ReVolver ready');

  // Send cached data immediately (no delay)
  var vin = get(STORE.VIN);
  if (vin) send({ VIN: vin });
  var info = get(STORE.CAR_INFO);
  if (info) send({ CAR_INFO: info });

  if (tokenExpired()) {
    var _rt = get(STORE.REFRESH_TOKEN);
    var _exp = parseInt(get(STORE.EXPIRES_AT), 10);
    var _now = Math.floor(Date.now() / 1000);
    console.log('Token expired on launch. RT: ' + (_rt ? _rt.substring(0, 8) + '...' : 'NONE'));
    console.log('Expires: ' + (isNaN(_exp) ? 'N/A' : new Date(_exp * 1000).toISOString()) + ' (remaining: ' + (_exp - _now) + 's)');
    send({ STATUS_MSG: 'Refreshing...' });
    refreshToken(function () {
      sendStatus();
    });
  } else {
    sendStatus();
  }
});

Pebble.addEventListener('appmessage', function (e) {
  var cmd = e.payload.COMMAND || e.payload[String(keys.COMMAND)];
  if (cmd) {
    console.log('Command: ' + cmd);
    executeCommand(cmd);
  }
});

Pebble.addEventListener('showConfiguration', function () {
  Pebble.openURL(clay.generateUrl());
});

Pebble.addEventListener('webviewclosed', function (e) {
  if (!e || !e.response) return;
  console.log('webviewclosed payload: ' + decodeURIComponent(e.response).substring(0, 200));

  // Auth response (from ReVolverAuth)
  try {
    var data = JSON.parse(decodeURIComponent(e.response));
    if (data && !Array.isArray(data) && data.ACCESS_TOKEN) {
      console.log('Auth payload keys: ' + Object.keys(data).join(', '));
      console.log('VCC_API_KEY present: ' + (data.VCC_API_KEY ? 'yes (' + data.VCC_API_KEY.substring(0, 8) + '...)' : 'NO'));
      set(STORE.ACCESS_TOKEN, data.ACCESS_TOKEN);
      if (data.REFRESH_TOKEN) set(STORE.REFRESH_TOKEN, data.REFRESH_TOKEN);
      if (data.EXPIRES_IN)
        set(
          STORE.EXPIRES_AT,
          String(Math.floor(Date.now() / 1000) + parseInt(data.EXPIRES_IN, 10))
        );
      if (data.VCC_API_KEY) set(STORE.VCC_API_KEY, data.VCC_API_KEY);
      sendStatus();
      return;
    }
  } catch (ex) {}

  // Clay settings response
  try {
    var dict = clay.getSettings(e.response);
    var vin = dict.VIN || dict[String(keys.VIN)];
    if (vin) {
      if (typeof vin === 'object') vin = vin.value;
      if (vin) {
        var oldVin = get(STORE.VIN);
        set(STORE.VIN, String(vin));
        // Clear cached car data if VIN changed
        if (oldVin && oldVin !== String(vin)) {
          clear(STORE.CAR_INFO);
          clear(STORE.AVAILABLE_COMMANDS);
        }
      }
    }
    var vibrate = dict.VIBRATE !== undefined ? dict.VIBRATE : dict[String(keys.VIBRATE)];
    if (vibrate !== undefined) {
      var val = typeof vibrate === 'object' ? vibrate.value : vibrate;
      send({ VIBRATE: val ? 1 : 0 });
    }
    sendStatus();
  } catch (ex) {
    console.log('Settings parse error: ' + ex);
  }
});
