const form = document.querySelector("#login-form");
const errorMessage = document.querySelector("#login-error");
const errorText = document.querySelector("#login-error-text");
const languageButton = document.querySelector("#login-language");
const setupInvitation = document.querySelector("#setup-invitation");
let language = localStorage.getItem("waggle-language") || "tr";
let errorDismissTimer = null;

function clearLoginError() {
  if (errorDismissTimer) clearTimeout(errorDismissTimer);
  errorDismissTimer = null;
  errorMessage.classList.remove("show", "fade-out");
  errorMessage.hidden = true;
  errorText.textContent = "";
  document.querySelector("#login-notice").hidden = true;
}

const loginCopy = {
  en: {
    eyebrow: "EDGE AI HIVE MONITORING", tagline: "Your hive has a voice.<br>Waggle knows when it changes.",
    learns: "Learns your hive", detects: "Detects lasting change", offline: "Works offline",
    ready: "System ready", welcome: "Welcome back", hint: "Sign in to monitor your hives",
    username: "Username", password: "Password", signin: "Sign in",
    first_time: "Setting up Waggle for the first time?", create_owner: "Create owner account", signin_error: "Sign-in failed",
    forgot: "Forgot my password", cancel: "Cancel", remember: "Keep me signed in",
    recovery_eyebrow: "PASSWORD RECOVERY", recovery_title: "Sign in with your recovery code",
    recovery_intro: "Enter the single-use code you generated in settings and choose a new password. The code stops working once it is used.",
    recovery_code: "Recovery code", recovery_new: "New password", recovery_new_confirm: "Confirm new password",
    recovery_submit: "Set password", recovery_no_code: "I do not have a recovery code",
    recovery_terminal: "On the computer running the panel, in the project folder, run:",
    recovery_mismatch: "The new passwords do not match", recovery_failed: "Password could not be reset",
    recovery_done: "Your password has been set. You can sign in now.",
    demo_account: "Demo account",
    demo_account_note: "Signing in with this account opens the panel on the demo channel. Signing in with an account you created opens the real user view.",
  },
  tr: {
    eyebrow: "EDGE AI KOVAN İZLEME", tagline: "Kovanınızın bir sesi var.<br>Waggle değiştiğinde anlar.",
    learns: "Kovanınızı öğrenir", detects: "Kalıcı değişimi algılar", offline: "Çevrimdışı çalışır",
    ready: "Sistem hazır", welcome: "Tekrar hoş geldiniz", hint: "Kovanlarınızı izlemek için giriş yapın",
    username: "Kullanıcı adı", password: "Parola", signin: "Giriş yap",
    first_time: "Waggle'ı ilk kez mi kuruyorsunuz?", create_owner: "Sistem sahibi hesabı oluştur", signin_error: "Giriş yapılamadı",
    forgot: "Parolamı unuttum", cancel: "Vazgeç", remember: "Oturumumu açık tut",
    recovery_eyebrow: "PAROLA KURTARMA", recovery_title: "Kurtarma kodunuzla girin",
    recovery_intro: "Ayarlardan aldığınız tek kullanımlık kodu girin ve yeni parolanızı belirleyin. Kod kullanıldıktan sonra geçersiz olur.",
    recovery_code: "Kurtarma kodu", recovery_new: "Yeni parola", recovery_new_confirm: "Yeni parolayı doğrulayın",
    recovery_submit: "Parolayı belirle", recovery_no_code: "Kurtarma kodum yok",
    recovery_terminal: "Panelin çalıştığı bilgisayarda proje klasöründe şu komutu çalıştırın:",
    recovery_mismatch: "Yeni parolalar eşleşmiyor", recovery_failed: "Parola sıfırlanamadı",
    recovery_done: "Parolanız belirlendi. Şimdi giriş yapabilirsiniz.",
    demo_account: "Demo hesabı",
    demo_account_note: "Bu hesapla girdiğinizde panel demo kanalında açılır. Oluşturduğunuz kendi hesabınızla girerseniz gerçek kullanıcı görünümü açılır.",
  },
};

function translateLogin() {
  document.documentElement.lang = language;
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.innerHTML = loginCopy[language][element.dataset.i18n];
  });
  languageButton.textContent = language === "tr" ? "EN" : "TR";
  document.title = language === "tr" ? "Waggle | Giriş" : "Waggle | Sign in";
}

languageButton.addEventListener("click", () => {
  language = language === "tr" ? "en" : "tr";
  localStorage.setItem("waggle-language", language);
  translateLogin();
});

document.querySelector(".password-toggle").addEventListener("click", (event) => {
  const password = document.querySelector("#password");
  password.type = password.type === "password" ? "text" : "password";
  event.currentTarget.setAttribute("aria-label", password.type === "password" ? "Parolayı göster" : "Parolayı gizle");
});

fetch("/api/setup-status")
  .then((response) => response.json())
  .then((status) => {
    // On a demo server setup is not *required* — the demo account is already there — but
    // the link stays so a real owner account can be registered next to it.
    setupInvitation.hidden = !(status.setup_required || status.setup_available);
    const demoHint = document.querySelector("#demo-account-hint");
    demoHint.hidden = !status.demo_mode;
    if (status.demo_username) document.querySelector("#demo-account-username").textContent = status.demo_username;
  })
  .catch(() => { setupInvitation.hidden = true; });

const recoveryDialog = document.querySelector("#recovery-dialog");
const recoveryMessage = document.querySelector("#recovery-message");

function setRecoveryMessage(text, isError = false) {
  recoveryMessage.textContent = text;
  recoveryMessage.classList.toggle("is-error", Boolean(text) && isError);
}

document.querySelector("#forgot-password").addEventListener("click", () => {
  setRecoveryMessage("");
  document.querySelector("#recovery-form").reset();
  document.querySelector("#recovery-username").value = document.querySelector("#username").value.trim();
  recoveryDialog.showModal();
});
document.querySelector("#recovery-cancel").addEventListener("click", () => recoveryDialog.close());

document.querySelector("#recovery-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const next = document.querySelector("#recovery-new-password").value;
  if (next !== document.querySelector("#recovery-new-password-confirm").value) {
    setRecoveryMessage(loginCopy[language].recovery_mismatch, true);
    return;
  }
  const button = document.querySelector("#recovery-submit");
  button.disabled = true;
  try {
    const response = await fetch("/api/password-recovery", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: document.querySelector("#recovery-username").value.trim(),
        recovery_code: document.querySelector("#recovery-code").value,
        new_password: next,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || loginCopy[language].recovery_failed);
    }
    // The password is set, so the sign-in form is one step away: prefill it and say so.
    recoveryDialog.close();
    form.username.value = document.querySelector("#recovery-username").value.trim();
    form.password.value = "";
    form.password.focus();
    const notice = document.querySelector("#login-notice");
    notice.textContent = loginCopy[language].recovery_done;
    notice.hidden = false;
  } catch (error) {
    setRecoveryMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearLoginError();
  form.querySelectorAll(".input-shell").forEach(field => field.classList.remove("input-error"));
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = language === "tr" ? "Giriş yapılıyor…" : "Signing in…";
  try {
    const response = await fetch("/api/login", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: form.username.value.trim(),
        password: form.password.value,
        remember: document.querySelector("#remember-me").checked,
      }),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.detail || (language === "tr" ? "Giriş yapılamadı" : "Sign-in failed"));
    }
    window.location.replace("/");
  } catch (error) {
    errorText.textContent = error.message;
    errorMessage.hidden = false;
    errorMessage.classList.remove("show");
    void errorMessage.offsetWidth;
    errorMessage.classList.add("show");
    form.querySelectorAll(".input-shell").forEach(field => field.classList.add("input-error"));
    errorDismissTimer = setTimeout(() => {
      errorMessage.classList.add("fade-out");
      errorMessage.addEventListener("animationend", clearLoginError, {once: true});
    }, 4200);
    button.disabled = false;
    button.textContent = loginCopy[language].signin;
  }
});

form.querySelectorAll("input").forEach(input => input.addEventListener("input", () => {
  clearLoginError();
  input.closest(".input-shell")?.classList.remove("input-error");
}));

translateLogin();
