(function (object) {
  if (object.values) {
    return;
  }
  object.values = function (value) {
    var keys = Object.keys(Object(value));
    var values = [];
    for (var i = 0; i < keys.length; i += 1) {
      if (Object.prototype.hasOwnProperty.call(value, keys[i])) {
        values.push(value[keys[i]]);
      }
    }
    return values;
  };
}(Object));
