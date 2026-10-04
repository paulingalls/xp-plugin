# Angle: state and lifecycle

For every value this diff stores (a flag, a cache, a token, a row, a file, a
field), answer four questions and report where the answers disagree:

- **Who writes it**, on which paths, including the failure path? A value recorded
  before the step that makes it true is a lie the next reader believes.
- **Who reads it**, and does the reader trust it more than the writer earned?
- **Who clears it**, and what happens on the day nothing does?
- **Can writer and reader drift?** Copies that disagree, a caller bypassing the
  update contract, a snapshot overwriting merged truth, a default meaning both
  "unset" and "empty".

Follow each value across files: the write and the contradicting read usually
live apart. Report the state, the writer, the missing reader or clearer, and
what a user sees when it bites. A loud error means this angle found nothing.
