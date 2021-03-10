

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CACHE_FILES))
  );
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(keys
        .filter((key) => !key.includes(CACHE_NAME))
        .map((key) => caches.delete(key))
      );
    })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(caches.match(event.request).then((response) => {
    return response || fetch(event.request).then((response) => {
      if (matchDomain(event.request.url, CACHE_DOMAINS) && (CACHE_DYNAMIC_URLS === true || matchURL(event.request.url, CACHE_DYNAMIC_URLS))) {
        return caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, response.clone());
          return response;
        }).catch(() => response);
      }
      return response;
    });
  }).catch(() => {
    if (CACHE_OFFLINE_FALLBACK && matchDomain(event.request.url, CACHE_DOMAINS)
        && !matchURL(event.request.url, CACHE_OFFLINE_FALLBACK_IGNORE_PATHS))
    {
      return caches.match(CACHE_OFFLINE_FALLBACK);
    }
  }));
});

function matchDomain(url, domains) {
  for (let domain of domains) {
    if (new URL(url).host === domain) {
      return true;
    }
  }
  return false;
}

function matchURL(url, shouldMatch) {
  const path = new URL(url).pathname;
  for (let pattern of shouldMatch) {
    if (pattern.indexOf('^') === 0 && path.match(pattern)) {
      return true;
    } else if (pattern.indexOf('*') === pattern.length - 1 && path.indexOf(pattern.substr(0, pattern.length - 2)) === 0) {
      return true;
    } else if (path.indexOf(pattern) === 0) {
      return true;
    }
  }
  return false;
}
