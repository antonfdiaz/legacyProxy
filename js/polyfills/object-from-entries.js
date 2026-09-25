(function (object) {
  if (object.fromEntries) {
    return;
  }
  object.fromEntries = function (entries) {
    var result = {};
    for (var i = 0; i < entries.length; i += 1) {
      result[entries[i][0]] = entries[i][1];
    }
    return result;
  };
}(Object));
