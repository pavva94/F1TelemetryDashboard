(() => {
  function route(locationLike = window.location) {
    const requested = new URLSearchParams(locationLike.search).get("view");
    if (requested === "season" || requested === "race") return requested;

    const legacyPath = locationLike.pathname.replace(/\/+$/, "").split("/").pop();
    return legacyPath === "season" ? "season" : "race";
  }

  function url(routeName, params = new URLSearchParams(), locationLike = window.location) {
    const query = new URLSearchParams(params);
    query.set("view", routeName);
    return `${locationLike.pathname}?${query}`;
  }

  function rebase(savedUrl, routeName, locationLike = window.location) {
    if (!savedUrl) return url(routeName, new URLSearchParams(), locationLike);
    try {
      const saved = new URL(savedUrl, locationLike.href);
      return url(routeName, saved.searchParams, locationLike);
    } catch {
      return url(routeName, new URLSearchParams(), locationLike);
    }
  }

  window.FastF1Routing = { route, url, rebase };
})();
