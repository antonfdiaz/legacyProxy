(function (root) {
  if (root.fetch) {
    return;
  }

  function deferred() {
    var state = "pending";
    var value;
    var success = [];
    var failure = [];
    var promise = {
      then: function (onSuccess, onFailure) {
        if (state === "fulfilled") {
          if (onSuccess) {
            onSuccess(value);
          }
        } else if (state === "rejected") {
          if (onFailure) {
            onFailure(value);
          }
        } else {
          success.push(onSuccess);
          failure.push(onFailure);
        }
        return promise;
      }
    };

    return {
      promise: promise,
      resolve: function (result) {
        if (state !== "pending") {
          return;
        }
        state = "fulfilled";
        value = result;
        for (var i = 0; i < success.length; i += 1) {
          if (success[i]) {
            success[i](value);
          }
        }
      },
      reject: function (error) {
        if (state !== "pending") {
          return;
        }
        state = "rejected";
        value = error;
        for (var i = 0; i < failure.length; i += 1) {
          if (failure[i]) {
            failure[i](value);
          }
        }
      }
    };
  }

  function resultPromise(value) {
    if (root.Promise) {
      return root.Promise.resolve(value);
    }
    var result = deferred();
    result.resolve(value);
    return result.promise;
  }

  root.fetch = function (url, options) {
    var xhr = new XMLHttpRequest();
    var request = options || {};
    var result = root.Promise ? null : deferred();
    var promise = root.Promise ? new root.Promise(function (resolve, reject) {
      result = { resolve: resolve, reject: reject };
    }) : result.promise;

    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) {
        return;
      }
      var response = {
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
        statusText: xhr.statusText,
        text: function () {
          return resultPromise(xhr.responseText);
        },
        json: function () {
          return resultPromise(JSON.parse(xhr.responseText));
        }
      };
      result.resolve(response);
    };
    xhr.onerror = function () {
      result.reject(new Error("Network request failed"));
    };
    xhr.open(request.method || "GET", url, true);
    if (request.headers) {
      for (var header in request.headers) {
        if (Object.prototype.hasOwnProperty.call(request.headers, header)) {
          xhr.setRequestHeader(header, request.headers[header]);
        }
      }
    }
    xhr.send(request.body || null);
    return promise;
  };
}(window));
