# Angle: checks that cannot fail

A check that cannot fail against the defect it names certifies a falsehood. For
every guard, assertion, validation and test this diff adds or changes:

- **Name the defect it catches**, put that defect back, and trace whether the
  check fires.
- **Would it pass against a do-nothing implementation?** Give the mutation.
- **Does it construct the condition it claims**, or observe ambient state: a grep
  for an identifier, a value the fixture itself just set?
- **Does the assertion discriminate?** A pre-existing failure that produces the
  same outcome makes the test unable to tell the two apart.
- **Does the selector match anything?** A filter that matches nothing reports
  success; a suite that ran zero tests is a green that means nothing.
- **Does it run on the path that matters**: the default path, the error path,
  the path a real caller takes?

Report the check, the defect it claims to catch, and the mutation that leaves it
green.
