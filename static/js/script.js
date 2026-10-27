(() => {
  const lines = document.getElementById("sale-lines");
  if (!lines) return;

  const template = document.getElementById("sale-line-template");
  const addButton = document.getElementById("add-sale-line");
  const totalElement = document.getElementById("sale-total");
  const finalTotalElement = document.getElementById("sale-total-final");

  function updateTotals() {
    let total = 0;
    lines.querySelectorAll(".sale-line").forEach((line) => {
      const select = line.querySelector(".product-select");
      const quantity = line.querySelector(".quantity-input");
      const option = select.options[select.selectedIndex];
      const price = Number(option?.dataset.price || 0);
      const stock = Number(option?.dataset.stock || 0);
      const qty = Math.max(0, Number(quantity.value || 0));
      line.querySelector(".subtotal-value").textContent = (price * qty).toFixed(2);
      quantity.max = stock || "";
      quantity.setCustomValidity(qty > stock && stock > 0 ? `Only ${stock} available.` : "");
      total += price * qty;
    });
    totalElement.textContent = `₹${total.toFixed(2)}`;
    finalTotalElement.textContent = `₹${total.toFixed(2)}`;
  }

  addButton?.addEventListener("click", () => {
    lines.append(template.content.cloneNode(true));
    updateTotals();
  });

  lines.addEventListener("input", updateTotals);
  lines.addEventListener("change", updateTotals);
  lines.addEventListener("click", (event) => {
    const button = event.target.closest(".remove-line");
    if (!button) return;
    const allLines = lines.querySelectorAll(".sale-line");
    if (allLines.length > 1) button.closest(".sale-line").remove();
    else {
      const line = button.closest(".sale-line");
      line.querySelector("select").value = "";
      line.querySelector("input").value = 1;
    }
    updateTotals();
  });
  document.getElementById("sale-form")?.addEventListener("submit", (event) => {
    updateTotals();
    if (!event.currentTarget.reportValidity()) event.preventDefault();
  });
  updateTotals();
})();
