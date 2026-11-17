document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.querySelector('.sidebar-toggle');
  toggle?.addEventListener('click', () => {
    const open = document.body.classList.toggle('sidebar-open');
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Navigation schließen' : 'Navigation öffnen');
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
      document.body.classList.remove('sidebar-open');
      toggle?.setAttribute('aria-expanded', 'false');
      toggle?.focus();
    }
  });
  const search = document.getElementById('sectionSearch');
  search?.addEventListener('input', () => {
    let visible = 0;
    document.querySelectorAll('[data-section-name]').forEach(link => {
      link.hidden = !link.dataset.sectionName.includes(search.value.trim().toLowerCase());
      if (!link.hidden) visible++;
    });
    document.querySelectorAll('.workspace-group').forEach(group => {
      group.hidden = !group.querySelector('[data-section-name]:not([hidden])');
    });
    document.getElementById('sectionEmpty').hidden = visible > 0;
  });
  const form = document.querySelector('[data-content-editor]');
  if (form) {
    let dirty = false;
    const state = form.querySelector('[data-save-state]');
    const markDirty = () => {
      dirty = true;
      if (state) { state.textContent = 'Ungespeicherte Änderungen'; state.classList.add('is-dirty'); }
    };
    form.addEventListener('input', markDirty);
    form.addEventListener('change', markDirty);
    form.querySelectorAll('.ql-editor').forEach(editor => new MutationObserver(markDirty).observe(editor, {subtree:true, childList:true, characterData:true}));
    form.addEventListener('submit', () => { dirty = false; });
    window.addEventListener('beforeunload', event => {
      if (dirty) { event.preventDefault(); event.returnValue = ''; }
    });
    const fields = form.querySelector('.editor-fields');
    if (fields) {
      const rail = document.createElement('nav'); rail.className = 'editor-outline'; rail.setAttribute('aria-label', 'Felder im Inhalt');
      const title = document.createElement('strong'); title.textContent = 'IN DIESEM INHALT'; rail.append(title);
      fields.querySelectorAll(':scope > .mb-4 > label, :scope > h5').forEach((label, index) => {
        const block = label.tagName === 'H5' ? label : label.parentElement;
        block.id = 'editor-section-' + index;
        const a = document.createElement('a'); a.href = '#' + block.id; a.textContent = label.textContent.trim().replace(/\s+/g, ' '); rail.append(a);
      });
      fields.before(rail);
    }
  }
  const library = document.getElementById('mediaLibrary');
  if (library) {
    const status = document.getElementById('mediaStatus');
    fetch(library.dataset.url).then(response => { if (!response.ok) throw new Error(); return response.json(); }).then(items => {
      const render = () => {
        const query = document.getElementById('mediaSearch').value.trim().toLowerCase();
        const filtered = items.filter(item => (item.name + ' ' + item.path).toLowerCase().includes(query));
        document.getElementById('mediaCount').textContent = filtered.length + ' von ' + items.length + ' Bildern';
        library.replaceChildren();
        if (!filtered.length) { const empty = document.createElement('p'); empty.className = 'empty-search'; empty.textContent = query ? 'Keine passenden Bilder gefunden.' : 'Noch keine Bilder vorhanden. Lade euer erstes Bild hoch.'; library.append(empty); }
        filtered.forEach(item => {
          const card = document.createElement('article'); card.className = 'media-card';
          const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener'; link.setAttribute('aria-label', item.name + ' öffnen');
          const img = document.createElement('img'); img.src = item.url; img.alt = item.name; img.loading = 'lazy'; link.append(img);
          const text = document.createElement('div'); text.className = 'media-card-body';
          const name = document.createElement('strong'); name.textContent = item.name; name.title = item.name;
          const path = document.createElement('small'); path.textContent = item.path; path.title = item.path;
          const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'btn btn-outline-secondary btn-sm'; copy.textContent = 'Pfad kopieren';
          copy.addEventListener('click', async () => {
            try { await navigator.clipboard.writeText(item.path); status.textContent = 'Bildpfad kopiert: ' + item.path; }
            catch { status.replaceChildren(); const label = document.createElement('label'); label.textContent = 'Bildpfad zum Kopieren'; const input = document.createElement('input'); input.className = 'form-control'; input.value = item.path; input.readOnly = true; label.append(input); status.append(label); input.select(); }
          });
          text.append(name,path,copy); card.append(link,text); library.append(card);
        });
      };
      document.getElementById('mediaSearch').addEventListener('input', render); render();
    }).catch(() => { library.textContent = 'Die Medien konnten nicht geladen werden. Bitte lade die Seite erneut.'; });
  }
});

// Shared picker rendering keeps uploaded filenames as text, including special characters.
window.studioRenderImages = (grid, items) => {
  grid.replaceChildren();
  if (!items.length) {
    const empty = document.createElement('p');
    empty.className = 'text-muted'; empty.textContent = 'Keine passenden Bilder gefunden.';
    grid.append(empty);
  }
  items.forEach(item => {
    const tile = document.createElement('button'); tile.type = 'button'; tile.className = 'image-tile'; tile.dataset.path = item.path;
    const image = document.createElement('img'); image.src = item.url; image.alt = item.name; image.loading = 'lazy';
    const caption = document.createElement('span'); caption.className = 'caption'; caption.title = item.path; caption.textContent = item.name;
    tile.append(image, caption); grid.append(tile);
  });
};
