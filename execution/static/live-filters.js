// Filtrado instantáneo sin recargar la página, sin frameworks ni build step.
//
// Busca un <form id="dash-filters" data-live-target="id1,id2,...">.
// Al cambiar cualquier campo, hace fetch() de la misma URL con la nueva
// query string, y reemplaza solo los bloques marcados (uno o varios ids,
// separados por coma) con lo que el servidor devolvió — el servidor sigue
// siendo la única fuente de verdad, esto solo evita el reload completo.
// Sirve tanto para la vista operativa (un resumen + una tabla) como para
// el dashboard ejecutivo (varias secciones independientes).
//
// Degradación elegante: si JS falla o está desactivado, el formulario
// sigue funcionando como un GET normal (botón "Filtrar" + recarga).
(function () {
  const form = document.getElementById("dash-filters");
  if (!form) return;

  const targetIds = (form.dataset.liveTarget || "").split(",").map((s) => s.trim()).filter(Boolean);
  const status = document.getElementById("dash-filter-status");

  let debounceTimer = null;

  function currentUrl() {
    const params = new URLSearchParams(new FormData(form));
    // No ensuciar la URL con checkboxes desmarcados/campos vacíos.
    for (const [key, value] of [...params.entries()]) {
      if (!value) params.delete(key);
    }
    const qs = params.toString();
    return window.location.pathname + (qs ? "?" + qs : "");
  }

  async function applyFilters(pushHistory) {
    const url = currentUrl();
    if (status) status.textContent = "Filtrando…";
    try {
      const resp = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const html = await resp.text();
      const doc = new DOMParser().parseFromString(html, "text/html");

      targetIds.forEach(function (id) {
        const fresh = doc.getElementById(id);
        const current = document.getElementById(id);
        if (fresh && current) current.innerHTML = fresh.innerHTML;
      });

      if (pushHistory) history.pushState({ liveFilter: true }, "", url);
      if (status) status.textContent = "";
    } catch (err) {
      // Si algo falla (red caída, etc.), no dejamos la UI muda: se manda
      // el form de verdad, que es el comportamiento sin JS.
      if (status) status.textContent = "";
      form.submit();
    }
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    applyFilters(true);
  });

  form.querySelectorAll("select, input[type=checkbox]").forEach(function (el) {
    el.addEventListener("change", function () {
      applyFilters(true);
    });
  });

  const textInput = form.querySelector("input[type=text]");
  if (textInput) {
    textInput.addEventListener("input", function () {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        applyFilters(true);
      }, 300);
    });
  }

  window.addEventListener("popstate", function () {
    applyFilters(false);
  });

  function syncFormToUrl(href) {
    const params = new URL(href, window.location.origin).searchParams;
    form.querySelectorAll("select, input").forEach(function (el) {
      if (el.type === "checkbox") {
        el.checked = params.get(el.name) === el.value;
      } else {
        el.value = params.get(el.name) || "";
      }
    });
  }

  // Los links "Bloqueados"/"En riesgo"/etc. de las tarjetas KPI también
  // deben sentirse instantáneos. Delegado en `document` (no en los links
  // directamente) porque las secciones se reemplazan por innerHTML en cada
  // filtro — un listener puesto en el nodo viejo se perdería.
  document.addEventListener("click", function (e) {
    const link = e.target.closest("a[data-live-link]");
    if (!link) return;
    e.preventDefault();
    syncFormToUrl(link.href);
    history.pushState({ liveFilter: true }, "", link.href);
    applyFilters(false);
  });
})();
