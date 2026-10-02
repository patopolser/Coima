// Motion tokens. Mirror of the --dur-* / --ease-* custom properties in
// src/styles/tokens.css; keep both in sync.

export const DUR = {
  page: 260,
  list: 180,
  stagger: 24,      // per-item delay inside a list
  staggerMax: 120,  // cap so long lists never feel slow
  section: 70,      // delay between reading-order steps (data-reveal 1..n)
  modalIn: 240,
  modalOut: 160,
  hover: 160,
  value: 180,
  shine: 220,
}

export const EASE = {
  in: 'cubic-bezier(0.16, 1, 0.3, 1)',
  out: 'cubic-bezier(0.4, 0, 1, 1)',
  hover: 'cubic-bezier(0.2, 0, 0.2, 1)',
}
