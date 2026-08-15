/* One owner for the battery identity mapping.
 *
 * The two packs are logically A and B in every payload, but the thing
 * written on the physical case is the last two digits of the BLE
 * advertisement name — "V-12V200AH-0533" is the box marked 33. When the
 * dashboard says B is low, the useful question is which box to open, so
 * the pages show both: A(33).
 *
 * Derived from the advertised name rather than configured, so swapping a
 * battery updates every page by itself. Falls back to a bare letter when
 * the name is missing (older rows carry no name), because a wrong number
 * on a battery case is worse than no number.
 */
(function (global) {
  "use strict";

  function battTag(name) {
    if (!name) return null;
    const tail = String(name).split("-").pop();
    if (!tail || tail.length < 2) return null;
    const two = tail.slice(-2);
    return /^\d{2}$/.test(two) ? two : null;
  }

  /* Plain text, for textContent and tooltip strings: "A(33)" or "A". */
  function battLabel(name, letter) {
    const tag = battTag(name);
    return tag ? letter + "(" + tag + ")" : letter;
  }

  /* HTML, for places that can style: the tag renders small and dimmed so
   * it identifies the case without competing with the reading. */
  function battLabelHTML(name, letter) {
    const tag = battTag(name);
    return tag
      ? letter + '<span class="btag" title="marking on the battery case">'
        + tag + "</span>"
      : letter;
  }

  /* Pages whose own payload has no names (the history aggregates) can ask
   * once and reuse it; identities are stable. Never rejects — a failed
   * lookup just leaves the bare letters. */
  function loadBattLabels(url) {
    return fetch(url || "/api/latest")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        return {
          a: battLabel(j && j.name_a, "A"),
          b: battLabel(j && j.name_b, "B"),
          aHTML: battLabelHTML(j && j.name_a, "A"),
          bHTML: battLabelHTML(j && j.name_b, "B"),
        };
      })
      .catch(function () {
        return { a: "A", b: "B", aHTML: "A", bHTML: "B" };
      });
  }

  global.battTag = battTag;
  global.battLabel = battLabel;
  global.battLabelHTML = battLabelHTML;
  global.loadBattLabels = loadBattLabels;
})(this);
