/* Shared UI helpers for standalone pages (POS, Cuestionario) that don't
   extend base.html. Defines window.toast and window.askConfirm, injecting
   their own DOM. Idempotent: won't redefine if already present. */
(function () {
  if (!window.toast) {
    window.toast = function (msg, ok) {
      var host = document.getElementById("uiToastHost");
      if (!host) {
        host = document.createElement("div");
        host.id = "uiToastHost";
        host.style.cssText = "position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:100000;display:flex;flex-direction:column;gap:10px;align-items:center;pointer-events:none;";
        document.body.appendChild(host);
      }
      var t = document.createElement("div");
      t.textContent = msg;
      t.style.cssText = "pointer-events:auto;padding:14px 22px;border-radius:12px;font-size:18px;font-weight:800;color:#fff;box-shadow:0 10px 30px rgba(0,0,0,.4);opacity:0;transform:translateY(-10px);transition:opacity .2s,transform .2s;background:" + ((ok === false) ? "#c62828" : "#2e7d32") + ";";
      host.appendChild(t);
      requestAnimationFrame(function () { t.style.opacity = "1"; t.style.transform = "translateY(0)"; });
      setTimeout(function () { t.style.opacity = "0"; t.style.transform = "translateY(-10px)"; setTimeout(function () { t.remove(); }, 250); }, 2600);
    };
  }

  if (!window.askConfirm) {
    window.askConfirm = function (msg, opts) {
      opts = opts || {};
      return new Promise(function (resolve) {
        var ov = document.getElementById("uiConfirmOverlay");
        if (!ov) {
          ov = document.createElement("div");
          ov.id = "uiConfirmOverlay";
          ov.style.cssText = "display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:100001;align-items:center;justify-content:center;padding:20px;";
          ov.innerHTML =
            '<div style="background:#0f1115;border:1px solid #3a4150;border-radius:20px;padding:26px;width:100%;max-width:400px;text-align:center;box-shadow:0 20px 50px rgba(0,0,0,.5);">'
            + '<div id="uiConfirmMsg" style="font-size:24px;font-weight:800;margin-bottom:20px;color:#fff;"></div>'
            + '<div style="display:flex;gap:12px;">'
            + '<button id="uiConfirmNo" style="flex:1;min-height:60px;border:none;border-radius:14px;font-size:20px;font-weight:800;cursor:pointer;background:#2a2f3a;color:#fff;">No</button>'
            + '<button id="uiConfirmYes" style="flex:1;min-height:60px;border:none;border-radius:14px;font-size:20px;font-weight:800;cursor:pointer;background:#e45b5b;color:#fff;">Sí</button>'
            + '</div></div>';
          document.body.appendChild(ov);
        }
        document.getElementById("uiConfirmMsg").textContent = msg;
        var yes = document.getElementById("uiConfirmYes");
        var no = document.getElementById("uiConfirmNo");
        yes.textContent = opts.yes || "Sí";
        no.textContent = opts.no || "No";
        ov.style.display = "flex";
        function done(v) {
          ov.style.display = "none";
          yes.removeEventListener("click", oy);
          no.removeEventListener("click", on);
          ov.removeEventListener("click", ob);
          resolve(v);
        }
        function oy() { done(true); }
        function on() { done(false); }
        function ob(e) { if (e.target === ov) done(false); }
        yes.addEventListener("click", oy);
        no.addEventListener("click", on);
        ov.addEventListener("click", ob);
      });
    };
  }
})();
