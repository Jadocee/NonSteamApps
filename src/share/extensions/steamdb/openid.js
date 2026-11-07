(() => {
  const site = "https://steamdb.info";
  const confirmed = "nonsteamapps-confirmed";
  if (location.pathname.replace(/\/+$/, "") !== "/openid/login") {
    return;
  }
  const origin = (value) => {
    try {
      return new URL(value || "", location.href).origin;
    } catch (error) {
      return "";
    }
  };
  const request = new URLSearchParams(location.search);
  if (request.get("openid.mode") !== "checkid_setup" || origin(request.get("openid.realm")) !== site
      || origin(request.get("openid.return_to")) !== site) {
    return;
  }
  const signedInAs = () => {
    for (const script of document.scripts) {
      const found = script.textContent.match(/\bg_steamID\s*=\s*"(\d{17})"/);
      if (found) {
        return found[1];
      }
    }
    try {
      const info = JSON.parse(document.getElementById("application_config")?.dataset.userinfo || "{}");
      return info.logged_in && /^\d{17}$/.test(String(info.steamid)) ? String(info.steamid) : "";
    } catch (error) {
      return "";
    }
  };
  const posts = (form) => (form.getAttribute("method") || "").toLowerCase() === "post"
    && /\/openid\/login\/?$/.test(new URL(form.getAttribute("action") || location.href, location.href).pathname);
  chrome.storage.local.get("account", ({ account }) => {
    if (!account || signedInAs() !== account || Date.now() - Number(sessionStorage.getItem(confirmed) || 0) < 60000) {
      return;
    }
    const form = document.getElementById("openidForm") || [...document.forms].find(posts);
    const button = document.getElementById("imageLogin")
      || form?.querySelector('input[type="submit"], input[type="image"], button[type="submit"]');
    if (!form || !posts(form) || !button || !form.contains(button)) {
      return;
    }
    sessionStorage.setItem(confirmed, String(Date.now()));
    button.click();
  });
})();
