const form = document.querySelector("#login-form");
const errorMessage = document.querySelector("#login-error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorMessage.textContent = "";
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "Giriş yapılıyor…";
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: form.username.value.trim(),
        password: form.password.value,
      }),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.detail || "Giriş yapılamadı");
    }
    window.location.replace("/");
  } catch (error) {
    errorMessage.textContent = error.message;
    button.disabled = false;
    button.textContent = "Giriş yap";
  }
});
