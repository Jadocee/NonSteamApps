(() => {
  if (new URLSearchParams(location.search).get("nonsteamapps") !== "library") {
    return;
  }
  const steamId = decodeURIComponent(location.pathname.split("/")[2] || "");
  const list = "/explore?selectedFilters=restrictToLibrary";
  const known = () => {
    try {
      const users = JSON.parse(localStorage.getItem("masqueradeUsers") || "{}");
      return Boolean(steamId && users && users[steamId]);
    } catch (error) {
      return false;
    }
  };
  if (known()) {
    location.replace(list);
    return;
  }
  const started = Date.now();
  const timer = setInterval(() => {
    if (!location.pathname.startsWith("/dashboard/") || Date.now() - started > 20000) {
      clearInterval(timer);
    } else if (known()) {
      clearInterval(timer);
      location.replace(list);
    }
  }, 250);
})();
