(() => {
  const store = chrome.storage.local;
  const tried = "nonsteamapps-sign-in";
  const given = location.hash.match(/^#nonsteamapps=(\d{17})$/);
  if (given) {
    store.set({ account: given[1] });
    history.replaceState(history.state, "", location.pathname + location.search);
  }
  if (location.pathname.startsWith("/signout")) {
    store.set({ signedIn: false });
    return;
  }
  const check = () => {
    const header = document.querySelector(".header-user");
    if (!header) {
      return;
    }
    const signIn = header.querySelector('a.header-login[href^="/login/"]');
    if (!signIn) {
      store.set({ signedIn: true });
      return;
    }
    store.get(["account", "signedIn"], ({ account, signedIn }) => {
      if (account && signedIn && !sessionStorage.getItem(tried)) {
        sessionStorage.setItem(tried, "1");
        location.assign(signIn.href);
      }
    });
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", check, { once: true });
  } else {
    check();
  }
})();
