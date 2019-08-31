

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(CACHE_FILES);
    })
  );
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.filter(function(key) {
        return key.indexOf(CACHE_NAME) === -1;
      }).map(function(key) {
        return caches.delete(key);
      }));
    })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(caches.match(event.request).then(function(response) {
    return response || fetch(event.request).then(function(response) {
      if (matchDomain(event.request.url, CACHE_DOMAIN) && (CACHE_DYNAMIC_URLS === true || matchURL(event.request.url, CACHE_DYNAMIC_URLS))) {
        return caches.open(CACHE_NAME).then(function(cache) {
          cache.put(event.request, response.clone());
          return response;
        }).catch(function() {
          return response;
        });
      }
      return response;
    });
  }).catch(function() {
    if (CACHE_OFFLINE_FALLBACK && matchDomain(event.request.url, CACHE_DOMAIN)
        && !matchURL(event.request.url, CACHE_OFFLINE_FALLBACK_IGNORE_PATHS))
    {
      return caches.match(CACHE_OFFLINE_FALLBACK);
    }
  }));
});

function matchDomain(url, domain) {
  return new URL(url).host === domain;
}

function matchURL(url, shouldMatch) {
  var path = new URL(url).pathname;
  for (var i = 0; i < shouldMatch.length; i++) {
    if (shouldMatch[i].indexOf('^') === 0 && path.match(shouldMatch[i])) {
      return true;
    } else if (shouldMatch[i].indexOf('*') === shouldMatch[i].length - 1 && path.indexOf(shouldMatch[i].substr(0, shouldMatch[i].length - 2)) === 0) {
      return true;
    } else if (path.indexOf(shouldMatch[i]) === 0) {
      return true;
    }
  }
  return false;
}
