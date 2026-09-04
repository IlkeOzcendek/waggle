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
    server_trouble: "We cannot complete your request right now. Please try again shortly.",
    no_connection: "The panel could not be reached. Check that the server is running, then try again.",
    forgot: "Forgot my password", cancel: "Cancel", remember: "Keep me signed in",
    recovery_eyebrow: "PASSWORD RECOVERY", recovery_title: "Sign in with your recovery code",
    recovery_intro: "Enter the single-use code you generated in settings and choose a new password. The code stops working once it is used.",
    recovery_code: "Recovery code", recovery_new: "New password", recovery_new_confirm: "Confirm new password",
    recovery_submit: "Set password", recovery_no_code: "I do not have a recovery code",
    recovery_terminal: "On the computer running the panel, in the project folder, run:",
    recovery_mismatch: "The new passwords do not match", recovery_failed: "Password could not be reset",
    recovery_done: "Your password has been set. You can sign in now.",
  },
  tr: {
    eyebrow: "EDGE AI KOVAN İZLEME", tagline: "Kovanınızın bir sesi var.<br>Waggle değiştiğinde anlar.",
    learns: "Kovanınızı öğrenir", detects: "Kalıcı değişimi algılar", offline: "Çevrimdışı çalışır",
    ready: "Sistem hazır", welcome: "Tekrar hoş geldiniz", hint: "Kovanlarınızı izlemek için giriş yapın",
    username: "Kullanıcı adı", password: "Parola", signin: "Giriş yap",
    first_time: "Waggle'ı ilk kez mi kuruyorsunuz?", create_owner: "Sistem sahibi hesabı oluştur", signin_error: "Giriş yapılamadı",
    server_trouble: "Şu anda isteğinizi tamamlayamıyoruz. Lütfen kısa bir süre sonra tekrar deneyin.",
    no_connection: "Panele ulaşılamadı. Sunucunun çalıştığını doğrulayıp tekrar deneyin.",
    forgot: "Parolamı unuttum", cancel: "Vazgeç", remember: "Oturumumu açık tut",
    recovery_eyebrow: "PAROLA KURTARMA", recovery_title: "Kurtarma kodunuzla girin",
    recovery_intro: "Ayarlardan aldığınız tek kullanımlık kodu girin ve yeni parolanızı belirleyin. Kod kullanıldıktan sonra geçersiz olur.",
    recovery_code: "Kurtarma kodu", recovery_new: "Yeni parola", recovery_new_confirm: "Yeni parolayı doğrulayın",
    recovery_submit: "Parolayı belirle", recovery_no_code: "Kurtarma kodum yok",
    recovery_terminal: "Panelin çalıştığı bilgisayarda proje klasöründe şu komutu çalıştırın:",
    recovery_mismatch: "Yeni parolalar eşleşmiyor", recovery_failed: "Parola sıfırlanamadı",
    recovery_done: "Parolanız belirlendi. Şimdi giriş yapabilirsiniz.",
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

// The box already carries "Giriş yapılamadı" as its heading, so this line has to add
// something rather than repeat it: what happened, and what to do next.
//
// A 500 answers in plain text rather than JSON, so parsing it first threw a parse error
// that reached the screen — a beekeeper was shown "Unexpected token 'I'" where the panel
// should have said it had failed. The status still matters when something is being
// diagnosed, so it goes to the console, which is where it is looked for.
// The panel answers in Turkish whatever language the screen is in, so an English reader
// was told "Kullanıcı adı veya parola hatalı". These are the three the sign-in form can
// receive; anything else is shown as the server wrote it, which beats showing nothing.
const SERVER_DETAIL_EN = {
  "Kullanıcı adı veya parola hatalı": "Incorrect username or password",
  "Çok fazla başarısız giriş denemesi. Lütfen kısa süre sonra tekrar deneyin.":
    "Too many failed sign-in attempts. Please try again shortly.",
  "Bu hesap devre dışı. Kovanlık sahibine başvurun.":
    "This account is disabled. Contact the apiary owner.",
};

async function failureMessage(response) {
  const body = await response.json().catch(() => null);
  const detail = body && typeof body.detail === "string" ? body.detail.trim() : "";
  if (detail) return language === "en" ? (SERVER_DETAIL_EN[detail] || detail) : detail;
  console.error(`Waggle: /api/login answered HTTP ${response.status}`);
  return loginCopy[language].server_trouble;
}

fetch("/api/setup-status")
  .then((response) => response.json())
  .then((status) => {
    // On a demo server setup is not *required* — the demo account is already there — but
    // the link stays so a real owner account can be registered next to it.
    setupInvitation.hidden = !(status.setup_required || status.setup_available);
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
    // A request that never completes rejects with the browser's own wording ("Failed to
    // fetch"), which reached the screen in English and said nothing a person could act on.
    const response = await fetch("/api/login", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: form.username.value.trim(),
        password: form.password.value,
        remember: document.querySelector("#remember-me").checked,
      }),
    }).catch(() => null);
    if (!response) throw new Error(loginCopy[language].no_connection);
    if (!response.ok) throw new Error(await failureMessage(response));
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
