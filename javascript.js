() => {
    // Expand all price accordions
    document.querySelectorAll('button[data-accordion-target]').forEach(btn => {
        const targetId = btn.getAttribute('data-accordion-target');
        const target = document.querySelector(targetId);
        if (target) {
            target.classList.remove('hidden');
            btn.setAttribute('aria-expanded', 'true');
        }
    });

    // Remove guest prices
    document.querySelectorAll('dt.price-gaeste').forEach(el => {
        el.closest('div')?.remove();
    });

    // Remove allergen info
    document.querySelectorAll('small.zusatzsstoffe').forEach(el => {
        if ((el.textContent || "").includes("enthält Allergene")) {
            el.remove();
        }
    });

    // Remove accordion headers
    document.querySelectorAll('h4[id^="accordion-collapse-heading-"]').forEach(h4 => {
        h4.remove();
    });

    // Reorder prices: Beschäftigte (Mitarbeiter) first, then Studierende
    document.querySelectorAll(".bg-lighter-cyan").forEach(menuItem => {
        const priceContainer = menuItem.querySelector("dl");
        if (!priceContainer) return;

        const mitarbeiter = priceContainer.querySelector("dt.price-mitarbeiter")?.closest("div");
        const studierende = priceContainer.querySelector("dt.price-studierende")?.closest("div");

        if (mitarbeiter && studierende && studierende.previousSibling !== mitarbeiter) {
            priceContainer.insertBefore(mitarbeiter, studierende);
        }
    });
}
