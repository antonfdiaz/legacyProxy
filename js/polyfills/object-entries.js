(function (object) {
  if (object.entries) {
    return;
  }
  object.entries = function (value) {
    var keys = Object.keys(Object(value));
    var entries = [];
    for (var i = 0; i < keys.length; i += 1) {
      if (Object.prototype.hasOwnProperty.call(value, keys[i])) {
        entries.push([keys[i], value[keys[i]]]);
      }
    }
    return entries;
  };
}(Object));
