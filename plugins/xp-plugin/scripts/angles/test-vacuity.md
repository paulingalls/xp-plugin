# Angle: checks that cannot fail

A check that cannot fail against the defect it names is worse than no check: it
certifies. Authors reliably cannot do this to their own work, and a vacuous
guard is silent by construction — it reports success forever.

For every guard, gate, assertion, validation and test this diff adds or changes:

- **Name the defect it exists to catch.** Then put that defect back — in your
  head, or in a scratch run — and trace whether the check actually fires.
- **Would it pass unchanged against a do-nothing implementation?** If deleting
  the code under test leaves it green, say so and give the mutation that proves
  it.
- **Does it CONSTRUCT the condition it claims**, or does it observe ambient
  state — grepping for an identifier, asserting some token is present, reading a
  value the fixture itself just set?
- **Does the assertion discriminate?** If a pre-existing failure produces the
  same outcome the test asserts, the test cannot tell the two apart.
- **Does the selector match anything?** A test filter, tag or name that matches
  nothing usually reports success, and a suite that ran zero tests is a green
  that means nothing.
- **Does the check run on the path that matters** — the default path, the error
  path, the path a real caller takes — or only on a path the tests build?

Report the check, the defect it claims to catch, and the concrete mutation that
leaves it green.
