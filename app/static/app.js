const form = document.querySelector("#verify-form");
const button = form.querySelector("button");
const results = document.querySelector("#results");
const resultList = document.querySelector("#result-list");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const emails = document.querySelector("#emails").value
    .split(/[\n,]+/)
    .filter((email) => email.trim());

  button.disabled = true;
  button.textContent = "Checking…";
  resultList.replaceChildren();

  try {
    const response = await fetch("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ emails }),
    });
    if (!response.ok) throw new Error("The request could not be completed.");

    const data = await response.json();
    for (const item of data) {
      const row = document.createElement("div");
      row.className = `result ${item.valid ? "valid" : "invalid"}`;

      const address = document.createElement("strong");
      address.textContent = item.email || "(empty address)";
      const detail = document.createElement("span");
      detail.textContent = item.valid ? "Valid format" : item.reason;
      row.append(address);
      if (item.original_email !== item.email) {
        const original = document.createElement("span");
        original.textContent = `Submitted: ${item.original_email}`;
        row.append(original);
      }
      row.append(detail);
      resultList.append(row);
    }
    results.hidden = false;
  } catch (error) {
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = error.message;
    resultList.append(message);
    results.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "Check addresses";
  }
});
