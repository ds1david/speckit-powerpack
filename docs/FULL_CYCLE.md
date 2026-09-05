# Full Cycle

`speckit-full-cycle` composes the existing Spec Kit and PowerPack primitives for exactly one SPEC. It is orchestration, not a second implementation of the commands it calls.

```text
resolve/create SPEC
  -> clarify
  -> plan
  -> checklist (when applicable)
  -> checklist-converge
  -> tasks
  -> analyze
  -> implement
  -> converge
       -> remaining tasks? implement -> converge
  -> implement-review
       -> findings? implement -> gate -> deep review
  -> DONE
```

The workflow never changes SPEC implicitly. In automatic mode it advances through deterministic phases and selects all review findings, but material ambiguity or a blocked prerequisite still stops the run.

Convergence findings and active implementation-review findings cannot be converted to technical debt to end the cycle.

`DONE` means the current SPEC converges with implementation and the independent deep review approves the current snapshot. It does not approve or merge a GitHub pull request.
