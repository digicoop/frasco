'use strict';

angular.module('frasco', []).provider('frascoServiceFactory', function() {
  var forEach = angular.forEach;
  var baseUrl = '';
  var globalErrorHandlers = [];
  var defaultHttpOptions = {};

  this.setBaseUrl = function(url) {
    baseUrl = url;
  };

  this.$get = ['$http', function($http) {
    return {
      setBaseUrl: function(url) {
        baseUrl = url;
      },
      registerGlobalErrorHandler: function(callback) {
        globalErrorHandlers.push(callback);
      },
      setDefaultHttpOptions: function(options) {
        defaultHttpOptions = options;
      },
      makeEndpoint: function(name, route, args) {
        var view_args = [];
        var re = /:([a-z0-9_]+)/ig, m;
        while ((m = re.exec(route)) !== null) {
          view_args.push(m[1]);
        }

        var functionArgsToData = function(func_args) {
          var data = {};
          for (var i in args) {
            data[args[i]] = func_args[i];
          }
          return data;
        };

        var buildUrl = function(data) {
          var url = baseUrl + route;
          var leftover = {};
          forEach(data, function(value, key) {
            if (view_args.indexOf(key) > -1) {
              url = url.replace(":" + key, value);
            } else {
              leftover[key] = value;
            }
          })
          return {url: url, data: leftover};
        };

        var makeExecuter = function(url, data) {
          return {
            execute: function(options, successCallback, errorCallback) {
              options['url'] = url;
              var r = $http(angular.extend({}, defaultHttpOptions, options));
              if (successCallback) {
                r.then(function(resp) {
                  return successCallback(resp.data, resp);
                });
              }
              var errorQ = r;
              if (errorCallback) {
                errorQ = r.catch(errorCallback);
              }
              forEach(globalErrorHandlers, function(callback) {
                errorQ = errorQ.catch(callback);
              });
              return r;
            },
            get: function(successCallback, errorCallback, options) {
              if (typeof(errorCallback) !== 'function') {
                options = errorCallback;
                errorCallback = null;
              }
              return this.execute(angular.extend({method: 'GET', params: data}, options || {}),
                successCallback, errorCallback);
            },
            post: function(successCallback, errorCallback, options) {
              if (typeof(errorCallback) !== 'function') {
                options = errorCallback;
                errorCallback = null;
              }
              return this.execute(angular.extend({method: 'POST', data: data}, options || {}),
                successCallback, errorCallback);
            },
            put: function(successCallback, errorCallback, options) {
              if (typeof(errorCallback) !== 'function') {
                options = errorCallback;
                errorCallback = null;
              }
              return this.execute(angular.extend({method: 'PUT', data: data}, options || {}),
                successCallback, errorCallback);
            },
            delete: function(successCallback, errorCallback, options) {
              if (typeof(errorCallback) !== 'function') {
                options = errorCallback;
                errorCallback = null;
              }
              return this.execute(angular.extend({method: 'DELETE', params: data}, options || {}),
                successCallback, errorCallback);
            }
          };
        };

        var endpoint = function() {
          var spec = buildUrl(functionArgsToData(arguments));
          return makeExecuter(spec.url, spec.data);
        };
        endpoint.__name__ = name;
        endpoint.url = function(data) {
          return buildUrl(data).url;
        };
        endpoint.$http = function(url_args, options) {
          options['url'] = endpoint.url(url_args);
          return $http(angular.extend({}, defaultHttpOptions, options));
        };
        endpoint.prepare = function(data) {
          var spec = buildUrl(data);
          return makeExecuter(spec.url, spec.data);
        };
        return endpoint;
      },
      make: function(service_name, base_url, args, actions) {
        var o = {'__name__': service_name};
        var self = this;
        forEach(actions, function(spec, name) {
          o[name] = self.makeEndpoint(service_name + "." + name,
            base_url + spec[0], args.concat(spec[1]));
        });
        return o;
      }
    };
  }];
});
