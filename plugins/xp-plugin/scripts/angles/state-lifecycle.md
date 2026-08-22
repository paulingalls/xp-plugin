# Angle: state and lifecycle

For every value this diff stores — a marker, a flag, a cache, a token, a row, a
file on disk, a field on an object — answer four questions, and report where the
answers disagree:

- **Who WRITES it**, and on which paths? Including the failure path: a value
  recorded before the step that makes it true is a lie the next reader believes.
- **Who READS it**, and does the reader trust it more than the writer earned?
- **Who CLEARS it**, and what happens on the day nothing does?
- **Can writer and reader DRIFT?** A gate that advances its own state. Two
  copies of one value where only one is updated. A snapshot written back over
  something merged since. A default that means both "unset" and "empty".

Follow each value across the whole diff, not within one file: the write and the
read that contradict it are usually in different files, which is why nobody
holding the whole change sees them together.

Report the lifecycle hole itself — the state, the writer, the missing reader or
clearer, and what a user sees on the run where it bites. Silence is the tell: if
the wrong value produces a loud error, this angle has not found anything.
