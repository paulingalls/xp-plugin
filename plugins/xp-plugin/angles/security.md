# Angle: what this made reachable

What can now be reached that could not be reached before? Many changes have no
such surface; reporting nothing is a correct result. Report what you can trace
to a caller, never a category.

- **Untrusted input reaching an interpreter**: a shell, a query, a template, a
  deserializer, a path join, an eval, a regex built from input.
- **Write-then-execute**: anything the actor can write that something later
  executes or trusts: a config, a hook, a dependency pin, a generated script.
- **Deny-lists where an allow-list was meant**, and exemptions that wave through
  the file that enforces the rule.
- **Secrets**: newly logged, written to disk or committed, issued with no expiry,
  or compared with `==`.
- **Authorization on one path and not its sibling**, or enforced only by the
  caller, so a second caller inherits nothing.
- **Moved trust boundaries**: validation moved further in, a server limit moved
  to the client, identity supplied by the requester.

For each: the entry point, the path it travels, and what an actor gains.
