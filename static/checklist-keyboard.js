/**
 * Hybrid keyboard navigation for the checklist results grid.
 * - One tab stop into the grid; Up/Down move between rows.
 * - Left/Right or 1-4 set Pass/Fail/Partial/NA for the current row.
 * - Enter opens/focuses Attach for the current row; Escape closes and returns focus.
 */
(function () {
  var gridId = 'checklist-keyboard-grid';

  function getGrid() {
    return document.getElementById(gridId);
  }

  function getRows() {
    var grid = getGrid();
    return grid ? Array.prototype.slice.call(grid.querySelectorAll('.result-row')) : [];
  }

  function getRadios(row) {
    return Array.prototype.slice.call(row.querySelectorAll('input.result-radio'));
  }

  function getSelectedRadio(row) {
    var radios = getRadios(row);
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) return radios[i];
    }
    return radios[0] || null;
  }

  function getAttachLink(row) {
    return row.querySelector('.attach-link');
  }

  function getAttachContainer(row) {
    var cid = row.getAttribute('data-criterion-id');
    return cid ? document.getElementById('attach-field-' + cid) : null;
  }

  function getAttachInput(row) {
    var container = getAttachContainer(row);
    return container ? container.querySelector('.attach-input') : null;
  }

  function isFocusInGrid() {
    var grid = getGrid();
    if (!grid) return false;
    var el = document.activeElement;
    if (!el) return false;
    if (grid.contains(el)) {
      if (el.classList && el.classList.contains('attach-input')) return true;
      if (el.classList && el.classList.contains('result-radio')) return true;
      if (el.classList && el.classList.contains('attach-link')) return true;
    }
    return false;
  }

  function getCurrentRow() {
    var el = document.activeElement;
    if (!el) return null;
    var row = el.closest ? el.closest('.result-row') : (function () {
      var p = el.parentNode;
      while (p && p !== getGrid()) {
        if (p.classList && p.classList.contains('result-row')) return p;
        p = p.parentNode;
      }
      return null;
    })();
    return row;
  }

  function setRovingTabindex(radio) {
    var grid = getGrid();
    if (!grid) return;
    grid.querySelectorAll('input.result-radio').forEach(function (r) {
      r.setAttribute('tabindex', r === radio ? '0' : '-1');
    });
  }

  function focusRow(row) {
    var radio = getSelectedRadio(row);
    if (radio) {
      setRovingTabindex(radio);
      radio.focus();
    }
    updateRowHighlight();
  }

  function updateRowHighlight() {
    var grid = getGrid();
    if (!grid) return;
    var row = getCurrentRow();
    grid.querySelectorAll('.result-row').forEach(function (r) {
      r.classList.toggle('result-row-focused', r === row);
    });
  }

  function clearRowHighlight() {
    var grid = getGrid();
    if (!grid) return;
    grid.querySelectorAll('.result-row').forEach(function (r) {
      r.classList.remove('result-row-focused');
    });
  }

  function initRovingTabindex() {
    var rows = getRows();
    if (rows.length === 0) return;
    var grid = getGrid();
    var allRadios = grid.querySelectorAll('input.result-radio');
    for (var i = 0; i < allRadios.length; i++) {
      allRadios[i].setAttribute('tabindex', '-1');
    }
    // Grid container is the only tab stop; focus moves to first row on first keydown when grid has focus
  }

  function handleGridFocusIn(e) {
    var grid = getGrid();
    if (!grid) return;
    // Never move focus when focus lands on the grid (Tab or click). Let keydown handle
    // "focus first row" when the user actually presses a key after tabbing in. This
    // avoids stealing focus when clicking a label (click often lands focus on grid first).
    updateRowHighlight();
  }

  function handleGridFocusOut(e) {
    var grid = getGrid();
    if (!grid) return;
    if (!grid.contains(e.relatedTarget)) clearRowHighlight();
  }

  function handleKeydown(e) {
    var grid = getGrid();
    if (!grid) return;
    var rows = getRows();
    if (rows.length === 0) return;

    var active = document.activeElement;
    var inAttachInput = active && active.classList && active.classList.contains('attach-input');
    var currentRow = getCurrentRow();
    var rowIndex = currentRow ? rows.indexOf(currentRow) : -1;

    // Only handle when focus is inside the grid (grid container, radio, or attach input)
    if (!grid.contains(active)) return;

    // When focus is on the grid container itself (e.g. just tabbed in), move focus to first row's radio
    // so the rest of the handler can process this key (e.g. ArrowDown moves to second row)
    if (active === grid) {
      focusRow(rows[0]);
      active = document.activeElement;
      currentRow = getCurrentRow();
      rowIndex = currentRow ? rows.indexOf(currentRow) : -1;
    }

    var key = e.key;
    var handled = false;

    if (inAttachInput && currentRow) {
      if (key === 'Escape') {
        var attachContainer = getAttachContainer(currentRow);
        var attachLink = getAttachLink(currentRow);
        if (attachContainer) {
          attachContainer.classList.add('attach-field-hidden');
          if (attachLink) attachLink.setAttribute('aria-expanded', 'false');
        }
        focusRow(currentRow);
        e.preventDefault();
        handled = true;
      } else if (key === 'ArrowDown' && rowIndex < rows.length - 1) {
        focusRow(rows[rowIndex + 1]);
        e.preventDefault();
        handled = true;
      } else if (key === 'ArrowUp' && rowIndex > 0) {
        focusRow(rows[rowIndex - 1]);
        e.preventDefault();
        handled = true;
      }
      if (handled) return;
    }

    // Focus is on a radio or we're not in attach input
    if (!currentRow || rowIndex < 0) return;

    var radios = getRadios(currentRow);
    var radioIndex = radios.indexOf(active);
    if (radioIndex < 0 && !inAttachInput) radioIndex = 0;

    switch (key) {
      case 'ArrowDown':
        if (rowIndex < rows.length - 1) {
          focusRow(rows[rowIndex + 1]);
          handled = true;
        }
        break;
      case 'ArrowUp':
        if (rowIndex > 0) {
          focusRow(rows[rowIndex - 1]);
          handled = true;
        }
        break;
      case 'ArrowLeft':
        if (radios.length) {
          var prev = radioIndex <= 0 ? radios[radios.length - 1] : radios[radioIndex - 1];
          prev.checked = true;
          setRovingTabindex(prev);
          prev.focus();
          handled = true;
        }
        break;
      case 'ArrowRight':
        if (radios.length) {
          var next = radioIndex < 0 || radioIndex >= radios.length - 1 ? radios[0] : radios[radioIndex + 1];
          next.checked = true;
          setRovingTabindex(next);
          next.focus();
          handled = true;
        }
        break;
      case '1':
      case '2':
      case '3':
      case '4':
        var idx = parseInt(key, 10) - 1;
        if (idx >= 0 && idx < radios.length) {
          radios[idx].checked = true;
          setRovingTabindex(radios[idx]);
          radios[idx].focus();
          handled = true;
        }
        break;
      case 'Enter':
        if (!inAttachInput) {
          var container = getAttachContainer(currentRow);
          var link = getAttachLink(currentRow);
          var input = getAttachInput(currentRow);
          if (container && input) {
            container.classList.remove('attach-field-hidden');
            if (link) link.setAttribute('aria-expanded', 'true');
            input.focus();
            handled = true;
          }
        }
        break;
      case 'Escape':
        if (inAttachInput) {
          var c = getAttachContainer(currentRow);
          var l = getAttachLink(currentRow);
          if (c) {
            c.classList.add('attach-field-hidden');
            if (l) l.setAttribute('aria-expanded', 'false');
          }
          focusRow(currentRow);
          handled = true;
        }
        break;
      case 'Home':
        focusRow(rows[0]);
        handled = true;
        break;
      case 'End':
        focusRow(rows[rows.length - 1]);
        handled = true;
        break;
    }

    if (handled) e.preventDefault();
  }

  function init() {
    var grid = getGrid();
    if (!grid) return;
    initRovingTabindex();
    grid.addEventListener('focusin', handleGridFocusIn, true);
    grid.addEventListener('focusout', handleGridFocusOut, true);
    grid.addEventListener('keydown', handleKeydown, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
