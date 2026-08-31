const form = document.querySelector("#verify-form");
const button = form.querySelector("button");
const results = document.querySelector("#results");
const resultList = document.querySelector("#result-list");
const resultSummary = document.querySelector("#result-summary");

const smtpLabels = {
  recipient_accepted: "Mailbox accepted",
  catch_all: "Catch-all domain",
  mailbox_not_found: "Mailbox not found",
  recipient_inconclusive: "Mailbox inconclusive",
  dns_inconclusive: "DNS inconclusive",
  not_configured: "Not configured",
};

function addDetail(container, label, value) {
  const detail = document.createElement("div");
  detail.className = "result-detail";
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value;
  detail.append(term, description);
  container.append(detail);
}

function renderResult(item) {
  const row = document.createElement("article");
  row.className = `result ${item.valid ? "valid" : "invalid"}`;

  const heading = document.createElement("div");
  heading.className = "result-heading";
  const address = document.createElement("h3");
  address.textContent = item.email || "(empty address)";
  const badge = document.createElement("span");
  badge.className = "status-badge";
  badge.textContent = item.valid ? "Valid" : "Invalid";
  heading.append(address, badge);
  row.append(heading);

  const message = document.createElement("p");
  message.className = "result-message";
  message.textContent = item.reason || "The address passed all configured checks.";
  row.append(message);

  const details = document.createElement("dl");
  details.className = "result-details";
  if (item.original_email !== item.email) {
    addDetail(details, "Submitted", item.original_email || "(empty address)");
  }
  if (item.provider) addDetail(details, "Mail provider", item.provider);
  if (item.smtp_status) {
    addDetail(
      details,
      "SMTP check",
      smtpLabels[item.smtp_status] || item.smtp_status.replaceAll("_", " "),
    );
  }
  if (details.childElementCount) row.append(details);
  return row;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const emails = document.querySelector("#emails").value
    .split(/[\n,]+/)
    .filter((email) => email.trim());
  const apiKey = document.querySelector("#api-key").value;

  button.disabled = true;
  button.textContent = "Checking…";
  resultList.replaceChildren();
  resultSummary.textContent = "";
  results.hidden = true;

  try {
    const response = await fetch("/api/verify", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify({ emails }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "The request could not be completed.");
    }

    const data = await response.json();
    const validCount = data.filter((item) => item.valid).length;
    const invalidCount = data.length - validCount;
    resultSummary.textContent = `${data.length} checked · ${validCount} valid · ${invalidCount} invalid`;
    resultList.append(...data.map(renderResult));
    results.hidden = false;
  } catch (error) {
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = error.message;
    resultList.append(message);
    resultSummary.textContent = "Check failed";
    results.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "Check addresses";
  }
});
